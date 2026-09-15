# Implementation Plan: OpenAPI Spec + Bruno Collection

## Overview

Deliver an OpenAPI 3.1 spec describing the deployed ImageNetOG Redux read API, a
Bruno collection for lightweight manual exploratory testing (with a
browser-assisted Cognito token flow), and a small Terraform addition provisioning
the Cognito hosted-UI domain the token flow depends on. Scope is limited to the
four existing `GET` routes under `/v1`; no application behavior changes.

Artifacts: `openapi/openapi.yaml`, `bruno/imagenetog-redux/`, a hosted-UI domain
in `terraform/modules/auth/`, and a README section wiring it all together.

---

## Tasks

- [x] 1. Provision the Cognito hosted-UI domain (Terraform)
  - Add `aws_cognito_user_pool_domain` to `terraform/modules/auth/main.tf`, named
    from `var.env` (`{env}-imagenetog-*`), attached to the existing User Pool
  - Add a `hosted_ui_domain_suffix` variable to `terraform/modules/auth/variables.tf`
  - Add `hosted_ui_domain`, `hosted_ui_base_url`, `hosted_ui_login_url` outputs to
    `terraform/modules/auth/outputs.tf`; re-export `hosted_ui_domain` and
    `hosted_ui_login_url` from `terraform/environments/dev/outputs.tf`
  - Verify with `terraform fmt -check -recursive terraform/`, `terraform validate`
    (dev), and `terraform plan` (expect exit code 2). Do NOT run `terraform apply`.
    - **Done:** Added a `data "aws_region" "current"` source + the
      `aws_cognito_user_pool_domain.hosted_ui` resource and the three outputs;
      re-exported `hosted_ui_domain`/`hosted_ui_login_url` from the dev root.
      `terraform fmt -check -recursive` and `terraform validate` (dev, via
      `init -backend=false`) both pass. `terraform plan` was **not** run — it
      requires live AWS credentials and the S3 remote backend (same environment
      constraint documented for `aws-deployment-feature` task 7.3). The dev
      infra is already deployed, so the new domain becomes live only after a
      user-run `terraform apply` (documented in the README).
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 2. Author the OpenAPI 3.1 skeleton with servers + security scheme
  - Create `openapi/openapi.yaml` with `openapi: 3.1.0`, `info`, a templated
    `servers` URL matching the deployed stage, an OAuth2 `authorizationCode`
    security scheme (scopes `openid email profile`), and global `security`
  - Document that the token is sent as the raw `Authorization` header
  - Verify: lint with `@redocly/cli` or `openapi-spec-validator` (zero errors)
    - **Done:** `python3 -m openapi_spec_validator openapi/openapi.yaml` → `OK`.
  - _Requirements: 1.1, 1.6, 1.7_

- [x] 3. Add reusable components — schemas, parameters, error responses
  - Define schemas `Collection`, `CollectionList`, `Image`, `ImageList`,
    `PresignedUrl`, `Error` matching exact service-layer shapes (`dateAdded`
    camelCase, nullable `description`)
  - Define shared parameters (`limit`, `offset`, `sort`, `order`, date-range
    params, `name`, `description`, `collection_name` pattern, `image_key`
    maxLength)
  - Define reusable responses for 400/401/404/405/429/500 using `Error` and the
    documented tokens
  - Verify: linter passes; `$ref`s resolve; field names cross-checked against
    `services/collections.py` and `services/images.py`
    - **Done:** validator passes; a structural check confirmed all 25 internal
      `$ref`s resolve. Field names cross-checked against `PublicCollection` and
      `PublicImage` in the service layer.
  - _Requirements: 1.3, 1.4, 1.5_

- [x] 4. Define the four paths wired to shared components
  - Add `get` operations for `/collections`, `/collections/{collection_name}`,
    `/collections/{collection_name}/images`,
    `/collections/{collection_name}/images/{image_key}`, each referencing shared
    parameters, a 200 schema, and the shared error responses
  - Include 405 semantics and the description/date-range behavior notes for images
  - Verify: full-spec lint passes; all four paths + operationIds present
    - **Done:** structural check confirmed the four paths and operationIds
      `listCollections`/`getCollection`/`listImages`/`getImageUrl`.
  - _Requirements: 1.2, 1.3, 1.4, 1.5_

- [x] 5. Scaffold the Bruno collection with environment + collection-level auth
  - Create `bruno/imagenetog-redux/bruno.json`, `environments/dev.bru` with
    placeholder vars (`baseUrl`, `hostedUiDomain`, `appClientId`, `redirectUri`,
    `authCode`, `authToken`, `testCollection`, `testImageKey`), and a
    collection-level `Authorization: {{authToken}}` header
  - Add any Bruno secret/local files to `.gitignore` if introduced
  - Verify: `.bru`/`bruno.json` parse; no real credentials committed
    - **Done:** all `.bru` files parse via `@usebruno/lang` (`bruToJsonV2`,
      `bruToEnvJsonV2`, `collectionBruToJson`). Added `bruno/**/.env` and
      `bruno/**/environments/*.local.bru` to `.gitignore`. Secret scan clean —
      `authCode`/`authToken` are empty placeholders.
  - _Requirements: 3.4, 5.1, 5.2_

- [x] 6. Add the Get Token request (code-for-token exchange)
  - Add `Auth/Get Token.bru`: POST `application/x-www-form-urlencoded` to
    `https://{{hostedUiDomain}}/oauth2/token` with `grant_type`, `client_id`,
    `code`, `redirect_uri` (no client secret); post-response script sets
    `authToken` from `id_token`
  - Document the browser step (authorize URL → login → copy `code` into `authCode`)
  - Verify: manual — valid code returns 200 and sets `authToken`; invalid code
    returns 400 (confirms wiring)
    - **Done (structure):** parsed body confirms `body:formUrlEncoded`,
      `auth:none`, and the four form fields; post-response script sets
      `authToken`. End-to-end token exchange is a manual step (requires a real
      browser login against deployed dev).
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 7. Add requests covering every API endpoint
  - Add one request per route plus representative variants (collections: default,
    paged, name-prefix, date-range, sorted; images: date listing, search,
    combined, paged; get-image URL) and negative paths (not-found, unauthenticated)
  - Each sends `Authorization: {{authToken}}`, uses env vars for identifiers, and
    includes lightweight assertions on status + key fields
  - Verify: manual run against dev — happy paths 200 with documented shapes;
    not-found 404 `resource.not_found`; unauthenticated 401 `auth.unauthorized`
    - **Done (structure):** 14 endpoint requests authored and parsed OK, each
      with `tests { ... }` assertions on status + key fields. Live execution
      against deployed dev is a manual step (needs a valid token).
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 8. Document the workflow in the README
  - Add an "API spec & Bruno collection" section: pointer to
    `openapi/openapi.yaml`; AWS CLI user-bootstrap (`admin-create-user` +
    `admin-set-user-password`); reading `terraform output` for the hosted-UI
    domain/login URL and app client id; the browser → code → Get-Token → requests
    flow; and the list of Bruno env vars to populate
  - Ensure the OpenAPI `servers`/hosted-UI URLs and Bruno placeholders reference
    the same Terraform-derived coordinates
  - Verify: end-to-end walkthrough against dev; `terraform fmt -check` / `validate`
    still pass
  - _Requirements: 6.1, 6.2, 6.3_

---

## Safety / Scope Notes

- Task 1 adds infrastructure but execution runs only `terraform fmt`, `validate`,
  and `plan` — never `apply` (touches the live dev account), and does not create
  the Cognito test user; those are user-approved actions.
- No committed file may contain real tokens or credentials; placeholders only.
- Follow project steering: python-standards, terraform-conventions,
  security-patterns.
