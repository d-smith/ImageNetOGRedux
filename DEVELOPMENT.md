

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
terraform output app_client_id    # Cognito App Client ID (for obtaining tokens)
terraform output rest_api_id
terraform output admin_role_arn
```

> **Lambda dependency layer (build artifact).** The shared Lambda layer
> (`aws-lambda-powertools` + `boto3`) is built during `terraform apply`: a
> `null_resource` runs `pip install` into `.build/layer-<env>/python/` and zips
> it to `.build/layer-<env>.zip`, which the `aws_lambda_layer_version` uploads.
> This requires `pip` and network access on the machine running `apply`. The
> build re-runs only when `terraform/modules/layer/requirements.txt` changes.
>
> The built zip under `.build/` must persist across applies. If you delete
> `.build/` after the layer has been applied, a normal `terraform apply` will
> **not** rebuild it automatically (a `null_resource` provisioner only runs on
> create/replace, and its trigger — the requirements hash — is unchanged), so
> the apply fails with `reading ZIP file ... no such file or directory`. Force
> a rebuild with:
>
> ```bash
> terraform apply -replace='module.layer.null_resource.layer_build'
> ```
>
> (This is why the teardown step lists `.build` removal as *optional* — if you
> clean it, use the `-replace` form on the next apply.)

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

### Recreate a collection from scratch

To reset a collection (e.g. for a clean integration-test run), delete it, then
recreate it. `delete_collection` is idempotent, so this is safe even if a
previous create only partially succeeded:

```bash
# 1. Tear down (add --yes to skip the confirmation prompt).
.venv/bin/python -m scripts.delete_collection --collection-name my-collection --env dev --yes

# 2. Recreate.
.venv/bin/python -m scripts.create_collection --collection-name my-collection --env dev
```

### Tear down an environment

Order matters. Per-collection buckets, the vector index, and the collection's
DynamoDB record are created **outside** Terraform, so `terraform destroy` will
not remove them. Delete collections **first** (while their names are still
known), then destroy the Terraform-managed infrastructure — otherwise the
buckets become orphans that must be cleaned up by hand.

```bash
export AWS_PROFILE=terraform
export AWS_REGION=us-east-1

# 1. Delete every collection first (repeat for each; --yes skips the prompt).
.venv/bin/python -m scripts.delete_collection --collection-name my-collection --env dev --yes

# 2. Confirm nothing is left (want: registered [], orphans []).
.venv/bin/python -m scripts.list_collections --env dev

# 3. Destroy the Terraform-managed infrastructure.
cd terraform/environments/dev
terraform init -backend-config=backend.config   # re-init if needed
terraform destroy

# 4. (Optional) remove local build artifacts (rebuilt on the next apply).
cd ../../.. && rm -rf .build
```

> **Do NOT tear down the Terraform backend** (the S3 state bucket
> `imagenetog-redux-tfstate` and the DynamoDB lock table
> `imagenetog-tfstate-locks`). These are account-level, shared across all
> environments, and created once by the bootstrap step. Leave them in place —
> after `terraform destroy` the state file simply becomes an empty state.

To redeploy from scratch afterwards, follow **Provision an environment** →
**Create a collection** → **Integration tests** again. Note that a fresh
`terraform apply` creates a **new** API Gateway with a different
`api_invoke_url` — always re-read it from `terraform output api_invoke_url`
rather than reusing a previous URL. Also allow 1–2 minutes after
`create_collection` for S3→EventBridge notifications to propagate before the
first ingestion run.

## Integration tests

The tests under `tests/integration/` run against a **deployed** environment
(real AWS, not `moto`). They are excluded from the default `pytest` run and are
selected explicitly with `-m integration`. Each test **skips** (rather than
fails) when the environment variables it needs are not set, so it is safe to
invoke them without a deployment.

### Quick start (run everything)

Copy-paste this from the **repo root** to configure and run the full suite
against `dev`. Edit only the three values in step 2; everything else is read
from Terraform.

```bash
# 1. Auth + region
aws sso login --profile terraform
export AWS_PROFILE=terraform
export AWS_REGION=us-east-1
export IMAGENETOG_ENV=dev

# 2. FILL THESE IN (Terraform can't derive them):
export IMAGENETOG_TEST_COLLECTION="my-collection"        # an existing collection
export IMAGENETOG_TEST_USERNAME="tester@example.com"     # a confirmed Cognito user
export IMAGENETOG_TEST_PASSWORD="REPLACE_WITH_PASSWORD"  # that user's permanent password

# 3. (Optional) create/confirm the test user with the password above:
USER_POOL_ID="$(terraform -chdir=terraform/environments/dev output -raw user_pool_id)"
aws cognito-idp admin-create-user --user-pool-id "$USER_POOL_ID" \
  --username "$IMAGENETOG_TEST_USERNAME" --message-action SUPPRESS 2>/dev/null || true
aws cognito-idp admin-set-user-password --user-pool-id "$USER_POOL_ID" \
  --username "$IMAGENETOG_TEST_USERNAME" --password "$IMAGENETOG_TEST_PASSWORD" --permanent

# 4. Auto-derived from Terraform outputs:
export IMAGENETOG_API_BASE_URL="$(terraform -chdir=terraform/environments/dev output -raw api_invoke_url)"
export IMAGENETOG_APP_CLIENT_ID="$(terraform -chdir=terraform/environments/dev output -raw app_client_id)"
export IMAGENETOG_REST_API_ID="$(terraform -chdir=terraform/environments/dev output -raw rest_api_id)"

# 5. Run the full suite
.venv/bin/pytest -m integration tests/integration --no-cov -v
```

The per-variable detail and what each test does are documented below.

### Setup

1. Deploy an environment and create a test collection (see **Deployment**).
2. Log in to AWS SSO and export the deployment coordinates:

   ```bash
   aws sso login --profile terraform
   export AWS_PROFILE=terraform
   export AWS_REGION=us-east-1
   export IMAGENETOG_ENV=dev

   # Read the base URL straight from Terraform (already includes /dev/v1):
   export IMAGENETOG_API_BASE_URL="$(terraform -chdir=terraform/environments/dev output -raw api_invoke_url)"

   # An existing collection created via create_collection.py:
   export IMAGENETOG_TEST_COLLECTION=my-collection
   ```

3. Optional variables:

   ```bash
   # Override derived defaults if your naming differs:
   export IMAGENETOG_IMAGES_TABLE=dev-imagenetog-images
   export IMAGENETOG_TEST_IMAGE_BUCKET=dev-imagenetog-my-collection-images

   # Override the query used by the description-search test to match the
   # committed test image (defaults to "a red house in a green field"):
   export IMAGENETOG_TEST_SEARCH_TERM="a red house in a green field"
   ```

4. For the authenticated tests (happy-path, description-search, and
   stage-routing), also export the app client id, a test user, and the REST API
   id:

   ```bash
   export IMAGENETOG_APP_CLIENT_ID="$(terraform -chdir=terraform/environments/dev output -raw app_client_id)"
   export IMAGENETOG_REST_API_ID="$(terraform -chdir=terraform/environments/dev output -raw rest_api_id)"
   export IMAGENETOG_TEST_USERNAME=tester@example.com
   export IMAGENETOG_TEST_PASSWORD="$TEST_USER_PASSWORD"   # dev/staging: USER_PASSWORD_AUTH is enabled
   ```

### Run

```bash
.venv/bin/pytest -m integration tests/integration --no-cov -v
```

What each test needs and does:

| Test | Requires | Behaviour |
|---|---|---|
| `test_auth_integration.py` | `IMAGENETOG_API_BASE_URL` | Asserts the deployed API returns `401` + structured JSON for missing / invalid / non-Bearer tokens, **and** that a rejection is never an IAM/SigV4 `IncompleteSignatureException` (which would indicate a stage/path misconfiguration). |
| `test_api_happy_path.py` | `IMAGENETOG_API_BASE_URL`, `IMAGENETOG_APP_CLIENT_ID`, `IMAGENETOG_TEST_USERNAME`, `IMAGENETOG_TEST_PASSWORD` | Mints a real ID token and asserts an authenticated `GET /collections` returns `200` with the documented envelope — the positive counterpart that catches a misrouted/broken API a rejection-only test would miss. |
| `test_stage_routing.py` | `IMAGENETOG_REST_API_ID` (+ AWS creds) | Structural check: asserts the API Gateway stage name does not collide with a top-level resource path segment (e.g. a stage named `v1` vs the `/v1` prefix), which would make routes unreachable. |
| `test_rate_limit.py` | `IMAGENETOG_API_BASE_URL` (+ AWS creds) | Verifies the rate-limiting **configuration**: the usage plan exists with positive rate/burst throttle settings, is attached to the API stage, and the `THROTTLED` gateway response returns the `rate_limit.exceeded` JSON contract. |
| `test_ingestion_e2e.py` | `IMAGENETOG_TEST_COLLECTION` (+ AWS creds) | Uploads a test image to the collection bucket and polls DynamoDB (up to 180s) until the metadata record appears with all required fields. |
| `test_search_integration.py` | `IMAGENETOG_API_BASE_URL`, `IMAGENETOG_APP_CLIENT_ID`, `IMAGENETOG_TEST_USERNAME`, `IMAGENETOG_TEST_PASSWORD`, `IMAGENETOG_TEST_COLLECTION` (+ AWS creds) | Exercises the description (vector) search path end-to-end: uploads a committed synthetic image (`tests/integration/assets/red_house_landscape.png`), waits for ingestion, then searches for it and asserts a `200` with the image returned and a numeric `score`. Also checks `maxDistance` override behaviour, `maxDistance` validation (`400 param.invalid`), and that plain date listings carry no `score`. Takes ~30–90s (polls ingestion). |
| `test_presigned_url_expiry.py` | `IMAGENETOG_TEST_COLLECTION` (+ AWS creds) | Generates a 5-second presigned URL, waits past expiry, and asserts S3 returns `403`. |

Any test whose required variables are unset is reported as **skipped**. To run a
single integration test:

```bash
.venv/bin/pytest -m integration tests/integration/test_auth_integration.py --no-cov -v
```

> **Note on the rate-limit test:** it verifies the throttling **configuration**
> (usage plan + stage attachment + `THROTTLED` response contract) rather than
> generating a request burst. This is deterministic and needs no Cognito token:
> a behavioural burst test is timing- and account-sensitive, and throttling is
> applied only after authorization. The dev throttle values live in
> `api_gateway_rate_limit` / `api_gateway_burst_limit` in
> `terraform/environments/dev/terraform.tfvars`.


## Architecture diagram

An editable AWS architecture diagram lives at
[`docs/architecture.drawio`](docs/architecture.drawio) — open or edit it with
[draw.io / diagrams.net](https://app.diagrams.net) (web, desktop, or the VS Code
"Draw.io Integration" extension). It covers both the read path (Client → Cognito
→ API Gateway → api-handler Lambda → DynamoDB / S3 / Bedrock / S3 Vectors) and
the event-driven ingestion pipeline (S3 upload → EventBridge → Step Functions →
embed/describe/store Lambdas).

The diagram is generated from a declarative model (not parsed from Terraform).
To regenerate it after the topology changes, edit the `NODES` / `EDGES` /
`GROUPS` tables in `src/scripts/generate_architecture_diagram.py` and re-run:

```bash
.venv/bin/python -m scripts.generate_architecture_diagram
# custom output path:
.venv/bin/python -m scripts.generate_architecture_diagram --output docs/architecture.drawio
```


## API spec & Bruno collection

The read API is described by an OpenAPI 3.1 spec, and a
[Bruno](https://www.usebruno.com/) collection is provided for lightweight manual
exploratory testing (including obtaining a Cognito token via the browser).

### OpenAPI specification

The spec lives at [`openapi/openapi.yaml`](openapi/openapi.yaml). It describes
all four read endpoints, their query/path parameters, response schemas, the
error contract (`param.invalid`, `auth.unauthorized`, `resource.not_found`,
`method.not_allowed`, `rate_limit.exceeded`, `server.error`), and the Cognito
OAuth2 security scheme.

Validate or preview it:

```bash
# Validate (Python; matches the validator used in this repo)
python3 -m openapi_spec_validator openapi/openapi.yaml

# Or lint / preview with Redocly (Node)
npx @redocly/cli lint openapi/openapi.yaml
npx @redocly/cli preview-docs openapi/openapi.yaml
```

The `servers` URL is templated (`restApiId`, `region`, `stage`); fill
`restApiId` from `terraform output rest_api_id`. The `authorizationUrl` /
`tokenUrl` in the security scheme use a `HOSTED_UI_DOMAIN` placeholder — replace
it with your hosted-UI domain (below) when importing the spec into a tool that
drives the OAuth flow.

### Bruno collection

The collection lives at [`bruno/imagenetog-redux/`](bruno/imagenetog-redux/).
Open the `bruno/imagenetog-redux` folder in Bruno and select the **dev**
environment. Every request inherits an `Authorization: {{authToken}}` header;
you obtain that token through the browser and the **Get Token** request.

#### Prerequisite: the Cognito hosted-UI domain

The browser login page requires a Cognito hosted-UI domain
(`aws_cognito_user_pool_domain`). It is defined in the `auth` module but is a
**new** addition — if your deployed environment predates it, apply it first:

```bash
cd terraform/environments/dev
terraform init -backend-config=backend.config
terraform apply   # creates {env}-imagenetog-auth hosted-UI domain + outputs
```

> The domain prefix (`{env}-imagenetog-auth`) must be globally unique within the
> region. If `apply` fails with a domain-already-exists error, override
> `hosted_ui_domain_suffix` in the `auth` module call.

#### Prerequisite: a Cognito user to log in with

The pool has no seeded user. Create and confirm a dev test user with the AWS CLI
(sign-up + email verification also works, but admin creation is fastest):

```bash
export AWS_PROFILE=terraform
export AWS_REGION=us-east-1
USER_POOL_ID="$(terraform -chdir=terraform/environments/dev output -raw user_pool_id)"

# Create the user (email is the username).
aws cognito-idp admin-create-user \
  --user-pool-id "$USER_POOL_ID" \
  --username "tester@example.com" \
  --message-action SUPPRESS

# Set a permanent password so the account is immediately usable
# (must satisfy the pool policy: >=12 chars, upper/lower/number/symbol).
# Choose your own value; do not commit it anywhere.
aws cognito-idp admin-set-user-password \
  --user-pool-id "$USER_POOL_ID" \
  --username "tester@example.com" \
  --password "$TEST_USER_PASSWORD" \
  --permanent
```

> Set `TEST_USER_PASSWORD` in your shell first (e.g.
> `export TEST_USER_PASSWORD='...'`) with a value satisfying the pool policy.
> It is a throwaway credential for a **dev** pool — never reuse it or commit it
> anywhere.

#### Read the deployment coordinates

```bash
cd terraform/environments/dev
terraform output api_invoke_url        # -> baseUrl (already includes /{env}/v1)
terraform output rest_api_id           # -> baseUrl host (if building the URL by hand)
terraform output app_client_id         # -> appClientId
terraform output hosted_ui_domain      # -> hostedUiDomain prefix
terraform output hosted_ui_login_url   # -> open this in a browser (browser flow)
```

> **URL convention.** The API Gateway **stage name equals the environment name**
> (`dev`, `staging`, `prod`), and the API version lives in the resource path
> (`/v1`). So the invoke URL is
> `https://<rest_api_id>.execute-api.us-east-1.amazonaws.com/<env>/v1` — for dev,
> `.../dev/v1`. Only the host varies between environments; the `/v1/...` path is
> identical everywhere. The stage name must never be `v1` (it would collide with
> the `/v1` path prefix); a Terraform validation enforces this.

#### Populate the Bruno `dev` environment

Set these variables in the Bruno **dev** environment (they ship with
placeholders — no real values are committed):

| Variable | Value |
|---|---|
| `baseUrl` | `https://<rest_api_id>.execute-api.us-east-1.amazonaws.com/dev/v1` (from `terraform output api_invoke_url`) |
| `hostedUiDomain` | `<hosted_ui_domain>.auth.us-east-1.amazoncognito.com` |
| `appClientId` | `terraform output app_client_id` |
| `redirectUri` | `https://localhost:3000/callback` (matches the app client) |
| `authCode` | *(empty — pasted after browser login)* |
| `authToken` | *(empty — set automatically by Get Token)* |
| `testCollection` | an existing collection name (e.g. `my-collection`) |
| `testImageKey` | an existing image key in that collection |

#### Obtain an ID token for Bruno

You need a Cognito **ID token** in the Bruno `authToken` variable. Send it as
the **raw** `Authorization` header value — **no `Bearer` prefix** (that is how
the API Gateway Cognito authorizer expects it). There are two ways to get one.

##### Option A — AWS CLI (fastest; recommended for quick testing)

The app client enables `ALLOW_USER_PASSWORD_AUTH`, so you can mint an ID token
directly with `initiate-auth` — no browser needed. Use the test user created
above:

```bash
export AWS_PROFILE=terraform
export AWS_REGION=us-east-1
cd terraform/environments/dev

CLIENT_ID="$(terraform output -raw app_client_id)"

ID_TOKEN="$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id "$CLIENT_ID" \
  --auth-parameters USERNAME=tester@example.com,PASSWORD="$TEST_USER_PASSWORD" \
  --query 'AuthenticationResult.IdToken' --output text)"

echo "$ID_TOKEN"   # copy this value into the Bruno `authToken` variable
```

Paste the `ID_TOKEN` value into the Bruno **dev** environment's `authToken`
variable, then run any request under **Collections** or **Images**. You can also
sanity-check the token straight from curl before using Bruno:

```bash
BASE_URL="$(terraform output -raw api_invoke_url)"   # -> https://<id>.execute-api.us-east-1.amazonaws.com/dev/v1
curl -i -H "Authorization: $ID_TOKEN" "$BASE_URL/collections"   # -> 200 + JSON
```

ID tokens expire after ~1 hour — re-run `initiate-auth` to get a fresh one.

> Do **not** paste real tokens into the committed `environments/dev.bru`
> (Bruno persists edited values back to that file). Keep real values in a
> git-ignored `environments/dev.local.bru` instead — `bruno/**/environments/*.local.bru`
> is already git-ignored.

##### Option B — browser (Cognito hosted UI)

1. Open the `hosted_ui_login_url` value in a browser and log in with the test
   user.
2. Cognito redirects to `https://localhost:3000/callback?code=<CODE>`. Nothing
   runs on `localhost:3000` — just copy the `code` value out of the address bar.
3. Paste it into the Bruno `authCode` variable.
4. Run **Auth → Get Token**. Its post-response script stores the ID token in
   `authToken`, so all other requests authenticate automatically.
5. Run any request under **Collections** or **Images**. Repeat steps 1–4 to
   refresh when the token expires.

The collection includes happy-path and negative-path requests (not-found → 404
`resource.not_found`; cleared token → 401 `auth.unauthorized`; traversal key →
400 `param.invalid`) with lightweight assertions on status and key fields.

> **No secrets are committed.** The Bruno environment ships with only
> placeholders; real tokens and codes stay local. `bruno/**/.env` and
> `bruno/**/environments/*.local.bru` are git-ignored.
