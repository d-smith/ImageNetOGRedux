# ImageNetOG Redux

Before there was ImageNet, there was [ImageNet](https://ieeexplore.ieee.org/document/244984).

TODO: Text blurb setting the context for the original ImageNet PACS... context then, and how we'd reimagine building something its ilk today.

## Development

All Python tooling is pinned in `pyproject.toml` and installed into the project
virtualenv at `.venv/`. Activate it to drop the `.venv/bin/` prefix from the
commands below:

```bash
source .venv/bin/activate
```

The commands below assume you are in the repository root and show the explicit
`.venv/bin/` prefix so they work whether or not the virtualenv is activated.

### Running tests

Test configuration lives in `pyproject.toml` (`[tool.pytest.ini_options]`):
`testpaths` is set to `tests/unit` and `tests/property`, and coverage reporting
is enabled by default. Required Lambda environment variables and the
`src/` import path are set automatically by `tests/conftest.py`, so no manual
setup is needed.

Run the full suite:

```bash
.venv/bin/pytest
```

The property-based tests (under `tests/property/`) run 100 Hypothesis examples
each and take a couple of minutes. For fast iteration, run the unit tests only
and skip coverage:

```bash
.venv/bin/pytest tests/unit --no-cov -q
```

Run a single file or a single test:

```bash
.venv/bin/pytest tests/unit/test_error_handler.py --no-cov -q
.venv/bin/pytest tests/unit/test_router.py::TestMethodEnforcement --no-cov
```

Filter tests by keyword with `-k`:

```bash
.venv/bin/pytest tests/unit tests/property -k "error or param or router"
```

### Linting and formatting

Linting and formatting use [`ruff`](https://docs.astral.sh/ruff/):

```bash
.venv/bin/ruff check src/ tests/          # lint
.venv/bin/ruff format --check src/ tests/ # verify formatting (no changes written)
```

To apply fixes and formatting in place:

```bash
.venv/bin/ruff check --fix src/ tests/
.venv/bin/ruff format src/ tests/
```

### Type checking

Static type checking uses [`mypy`](https://mypy.readthedocs.io/) in strict mode:

```bash
.venv/bin/mypy --explicit-package-bases src/
```

> **Note:** `--explicit-package-bases` is required. Because `pyproject.toml`
> sets `mypy_path = "src"`, running a bare `mypy src/` makes each module
> resolvable under two names (e.g. `api_handler.foo` and `src.api_handler.foo`)
> and mypy aborts with a "source file found twice" error. The flag disambiguates
> the package root.



## Deployment

Infrastructure is defined in Terraform under `terraform/`. Each environment
(`dev`, `staging`, `prod`) is a separate Terraform root under
`terraform/environments/<env>/` with its own S3 remote backend configured via
`backend.config`.

### Prerequisites

- Terraform `>= 1.7, < 2.0` and the AWS provider `~> 5.0` (pinned in
  `terraform/versions.tf` and each environment root).
- AWS credentials in scope. This project uses AWS SSO — log in with your
  designated profile before running any Terraform or integration commands:

  ```bash
  aws sso login --profile terraform
  export AWS_PROFILE=terraform
  export AWS_REGION=us-east-1
  ```

- A boto3/botocore new enough to include the S3 Vectors (`s3vectors`) service.
  The project pins a compatible version in `pyproject.toml`; the deployed Lambda
  packages pin the same in `src/api_handler/requirements.txt`.

### Bootstrap the Terraform backend (one time per account)

The S3 remote backend and its DynamoDB lock table are **not** managed by
Terraform (Terraform cannot manage the backend it depends on). Create them once,
manually, before the first `terraform init`. The names must match those in
`terraform/environments/<env>/backend.config` (the defaults are shown below).

```bash
# DynamoDB state-lock table. The primary key MUST be named `LockID` (string) —
# this is required by Terraform's S3 backend.
aws dynamodb create-table \
  --table-name imagenetog-tfstate-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1 --profile terraform

# S3 state bucket (versioning strongly recommended so state is recoverable).
# The bucket name must be globally unique; if the default is taken, choose an
# account-scoped name and update every backend.config to match.
aws s3api create-bucket \
  --bucket imagenetog-redux-tfstate \
  --region us-east-1 --profile terraform
aws s3api put-bucket-versioning \
  --bucket imagenetog-redux-tfstate \
  --versioning-configuration Status=Enabled --profile terraform
```

> **Notes:**
> - In `us-east-1` do **not** pass `--create-bucket-configuration` /
>   `LocationConstraint`; that is only for other regions.
> - The lock table and state bucket are shared across all three environments —
>   each environment uses a distinct state **key** (`dev/`, `staging/`, `prod/`),
>   not a distinct table or bucket. You bootstrap these once, not per environment.
> - Symptom if the lock table is missing: `terraform plan` fails with
>   `Error acquiring the state lock ... ResourceNotFoundException`.

### Provision an environment

Run these from the environment root you want to deploy (example uses `dev`):

```bash
cd terraform/environments/dev

# Initialise the S3 backend (values come from backend.config).
terraform init -backend-config=backend.config

# Review the plan. Exit code 2 means "changes pending" and is expected.
terraform plan

# Apply. (Never auto-apply prod on merge — prod apply requires manual approval.)
terraform apply
```

Useful outputs after apply:

```bash
terraform output api_invoke_url   # base URL of the deployed API Gateway stage
terraform output user_pool_id     # Cognito User Pool ID (for obtaining tokens)
terraform output rest_api_id
terraform output admin_role_arn
```

### Create a collection

S3 image/vector buckets and the collection's DynamoDB record are provisioned at
runtime by the admin script, not by Terraform:

```bash
.venv/bin/python -m scripts.create_collection --collection-name my-collection --env dev
```

This creates `dev-imagenetog-my-collection-images`,
`dev-imagenetog-my-collection-vectors` (with the `images` vector index), and the
collection record in `dev-imagenetog-collections`. Uploading an image to the
image bucket then triggers the ingestion workflow automatically.

`create_collection.py` is **idempotent** — re-running it for an existing
collection skips resources that already exist (so a partially-failed run can be
safely re-run to completion).

### List and delete collections

Per-collection buckets, the vector index, and the DynamoDB record are created
outside Terraform, so **`terraform destroy` does not remove them** — you must
clean them up with the admin scripts.

List collections and find orphaned buckets (read-only):

```bash
.venv/bin/python -m scripts.list_collections --env dev
```

This reports the collections registered in DynamoDB, the per-collection image
buckets that exist, and any **orphans** (buckets with no matching DynamoDB
record — e.g. left behind after `terraform destroy` or a partial create).

Delete a collection and all its resources (destructive; empties + deletes the
image bucket, deletes the vector index + vector bucket, and removes the
DynamoDB record). Idempotent — absent resources are skipped:

```bash
# Interactive: prompts you to type the collection name to confirm.
.venv/bin/python -m scripts.delete_collection --collection-name my-collection --env dev

# Non-interactive (CI / scripted): skip the prompt with --yes.
.venv/bin/python -m scripts.delete_collection --collection-name my-collection --env dev --yes
```

> **Note:** `list_collections` discovers *image* buckets via `s3:ListBuckets`,
> but S3 Vectors buckets are **not** standard S3 buckets and do not appear in
> that listing — so the orphan scan covers image buckets. Run
> `delete_collection` (which deletes the vector bucket + index directly by name)
> to fully reclaim a collection, and tear down collections **before**
> `terraform destroy` so their names are still known.

## Integration tests

The tests under `tests/integration/` run against a **deployed** environment
(real AWS, not `moto`). They are excluded from the default `pytest` run and are
selected explicitly with `-m integration`. Each test **skips** (rather than
fails) when the environment variables it needs are not set, so it is safe to
invoke them without a deployment.

### Setup

1. Deploy an environment and create a test collection (see **Deployment**).
2. Log in to AWS SSO and export the deployment coordinates:

   ```bash
   aws sso login --profile terraform
   export AWS_PROFILE=terraform
   export AWS_REGION=us-east-1
   export IMAGENETOG_ENV=dev

   # From `terraform output api_invoke_url`:
   export IMAGENETOG_API_BASE_URL="https://<rest-api-id>.execute-api.us-east-1.amazonaws.com/v1"

   # An existing collection created via create_collection.py:
   export IMAGENETOG_TEST_COLLECTION=my-collection
   ```

3. Optional variables:

   ```bash
   # Only needed for the rate-limit test (throttling is applied after auth,
   # so it needs a valid Cognito Bearer token — access or ID token):
   export IMAGENETOG_JWT="<a-valid-cognito-token>"

   # Override derived defaults if your naming differs:
   export IMAGENETOG_IMAGES_TABLE=dev-imagenetog-images
   export IMAGENETOG_TEST_IMAGE_BUCKET=dev-imagenetog-my-collection-images
   ```

### Run

```bash
.venv/bin/pytest -m integration tests/integration --no-cov -v
```

What each test needs and does:

| Test | Requires | Behaviour |
|---|---|---|
| `test_auth_integration.py` | `IMAGENETOG_API_BASE_URL` | Asserts the deployed API returns `401` + structured JSON for missing / invalid / non-Bearer tokens. |
| `test_rate_limit.py` | `IMAGENETOG_API_BASE_URL`, `IMAGENETOG_JWT` | Bursts authorized requests above the usage plan and asserts a `429` with `rate_limit.exceeded`. |
| `test_ingestion_e2e.py` | `IMAGENETOG_TEST_COLLECTION` (+ AWS creds) | Uploads a test image to the collection bucket and polls DynamoDB (up to 180s) until the metadata record appears with all required fields. |
| `test_presigned_url_expiry.py` | `IMAGENETOG_TEST_COLLECTION` (+ AWS creds) | Generates a 5-second presigned URL, waits past expiry, and asserts S3 returns `403`. |

Any test whose required variables are unset is reported as **skipped**. To run a
single integration test:

```bash
.venv/bin/pytest -m integration tests/integration/test_auth_integration.py --no-cov -v
```

> **Note on the rate-limit test:** it is timing- and account-sensitive. The dev
> usage plan is intentionally small (`api_gateway_rate_limit` / `burst` in
> `terraform/environments/dev/terraform.tfvars`). If your deployed limits are
> larger, increase `_BURST` in `test_rate_limit.py`.
