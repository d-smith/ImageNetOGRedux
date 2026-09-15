# Design Document: OpenAPI Spec + Bruno Collection

## Overview

This feature adds two documentation/tooling artifacts and one small
infrastructure resource to the existing ImageNetOG Redux project:

1. `openapi/openapi.yaml` — an OpenAPI 3.1 description of the deployed read API.
2. `bruno/imagenetog-redux/` — a Bruno collection for manual exploratory
   testing, including a browser-assisted Cognito token flow.
3. An `aws_cognito_user_pool_domain` in the `auth` Terraform module so the
   Cognito hosted UI has a resolvable login URL.

No application code changes. The OpenAPI spec and Bruno collection describe the
API exactly as implemented in `src/api_handler/`.

---

## Investigated Facts (source of truth)

The API contract below was read directly from source and infrastructure:

### Endpoints (`src/api_handler/routes/*.py`, `terraform/modules/api/apigw.tf`)

| Method | Path | Handler |
|---|---|---|
| GET | `/v1/collections` | `list_collections` |
| GET | `/v1/collections/{collection_name}` | `get_collection` |
| GET | `/v1/collections/{collection_name}/images` | `list_images` |
| GET | `/v1/collections/{collection_name}/images/{image_key}` | `get_image` |

All methods are `COGNITO_USER_POOLS`-authorized with no `authorization_scopes`.

### Query/path parameters (`src/api_handler/params.py`)

- `limit`: integer, 1–100, default 20 (`param.invalid` otherwise).
- `offset`: integer, >= 0, default 0.
- `sort`: collections → `name|created` (default `name`); images → `dateAdded`.
- `order`: `asc|desc`, default `asc`.
- `name`: case-insensitive prefix filter (collections).
- `createdAfter` / `createdBefore`: ISO-8601 `YYYY-MM-DD` (collections).
- `addedAfter` / `addedBefore`: ISO-8601 `YYYY-MM-DD` (images).
- `description`: free-text vector-search query (images), truncated to 500 chars.
- `collection_name` (path): pattern `^[a-z0-9][a-z0-9-]{1,46}[a-z0-9]$`, 3–48
  chars.
- `image_key` (path): rejects `..`, max length 1024.

Images list behavior: `description` triggers vector search (offset ignored,
`total` = ranked top-K); date-only uses the LSI; combined pushes a date filter
into the vector query.

### Response shapes (`src/api_handler/services/*.py`)

- `PublicCollection` = `{ "name": string, "created": string }`.
- Collection list envelope = `{ "items": [PublicCollection], "total": int,
  "limit": int, "offset": int }`.
- `PublicImage` = `{ "key": string, "dateAdded": string, "description":
  string|null }` (note camelCase `dateAdded`).
- Image list envelope = `{ "items": [PublicImage], "total": int, "limit": int,
  "offset": int }`.
- Presigned URL = `{ "key": string, "url": string }`.

### Error contract (`responses.py`, `exceptions.py`, `apigw.tf`)

Body is always `{ "error": <token>, "message": <text> }`.

| Status | Token | Source |
|---|---|---|
| 400 | `param.invalid` | Lambda (`InvalidParameterError`) |
| 401 | `auth.unauthorized` | API Gateway `UNAUTHORIZED` gateway response |
| 404 | `resource.not_found` | Lambda (not-found + version-prefix miss) |
| 405 | `method.not_allowed` | Lambda (`MethodNotAllowedError`) |
| 429 | `rate_limit.exceeded` | API Gateway `THROTTLED` gateway response |
| 500 | `server.error` | Lambda catch-all middleware |

### Auth (`terraform/modules/auth/main.tf`, `apigw.tf`)

- App client: public (`generate_secret = false`),
  `allowed_oauth_flows = ["code"]`, scopes `openid email profile`, callback
  `https://localhost:3000/callback`, token validity 1h.
- Authorizer: `COGNITO_USER_POOLS`,
  `identity_source = method.request.header.Authorization`, no scopes → accepts
  the raw ID/access token (no `Bearer` prefix required).
- Gap: no `aws_cognito_user_pool_domain` exists yet.

---

## Component 1: Cognito Hosted-UI Domain (Terraform)

Add to `terraform/modules/auth/main.tf`:

```hcl
resource "aws_cognito_user_pool_domain" "hosted_ui" {
  domain       = "${local.name_prefix}-${var.hosted_ui_domain_suffix}"
  user_pool_id = aws_cognito_user_pool.main.id
}
```

- `local.name_prefix` is already `"${var.env}-imagenetog"`.
- A `hosted_ui_domain_suffix` variable (default e.g. `"auth"`) is added to
  `variables.tf` so the Cognito domain prefix is configurable and can be made
  globally unique per account if needed.
- Cognito prefix domains resolve to
  `https://<domain>.auth.<region>.amazoncognito.com`. The region comes from a
  `data "aws_region" "current"` source (no hardcoded region), consistent with
  terraform-conventions.

New `auth` module outputs (`outputs.tf`):

- `hosted_ui_domain` — the domain prefix string.
- `hosted_ui_base_url` — `https://<domain>.auth.<region>.amazoncognito.com`.
- `hosted_ui_login_url` — a ready-to-click authorize URL including
  `client_id`, `response_type=code`, `scope=openid+email+profile`, and
  `redirect_uri` (the existing localhost callback).

The `dev` environment root (`terraform/environments/dev/outputs.tf`) re-exports
`hosted_ui_domain` and `hosted_ui_login_url`.

Verification is limited to `terraform fmt -check -recursive`, `terraform
validate`, and `terraform plan` (no `apply`; applying is a user action).

---

## Component 2: OpenAPI 3.1 Specification

File: `openapi/openapi.yaml`.

Structure:

- `openapi: 3.1.0`, `info` (title, version `v1`, description).
- `servers`: templated URL
  `https://{restApiId}.execute-api.{region}.amazonaws.com/{stage}` with
  variables defaulting to the dev coordinates (region `us-east-1`, stage `v1`).
- `security`: global reference to the Cognito scheme.
- `components.securitySchemes.cognitoAuth`: `type: oauth2` with an
  `authorizationCode` flow (authorization URL `.../oauth2/authorize`, token URL
  `.../oauth2/token`, scopes `openid`, `email`, `profile`), plus a description
  noting the token is sent as the raw `Authorization` header.
- `components.schemas`: `Collection`, `CollectionList`, `Image`, `ImageList`,
  `PresignedUrl`, `Error` — mirroring the investigated response shapes exactly
  (`dateAdded` camelCase; `description` nullable via `type: [string, "null"]`).
- `components.parameters`: `limitParam`, `offsetParam`, `sortParam`
  (per-endpoint enum via separate params where the allowed set differs),
  `orderParam`, `createdAfterParam`, `createdBeforeParam`, `addedAfterParam`,
  `addedBeforeParam`, `nameParam`, `descriptionParam`, `collectionNameParam`
  (path, with pattern), `imageKeyParam` (path, with maxLength).
- `components.responses`: `BadRequest` (400), `Unauthorized` (401),
  `NotFound` (404), `MethodNotAllowed` (405), `TooManyRequests` (429),
  `ServerError` (500) — each using the `Error` schema and documenting the token.
- `paths`: the four `get` operations, each with `operationId`, referenced
  parameters, a `200` response using the matching list/object schema, and the
  shared error responses.

Validation: `npx @redocly/cli lint` (preferred) or
`python -m openapi_spec_validator`. The spec must lint clean.

---

## Component 3: Bruno Collection

Directory layout:

```
bruno/imagenetog-redux/
  bruno.json                     # collection manifest + collection-level auth
  collection.bru                 # collection-level headers/auth (if applicable)
  environments/
    dev.bru                      # placeholder env vars
  Auth/
    Get Token.bru                # code -> token exchange, sets authToken
  Collections/
    List Collections.bru
    List Collections (paged).bru
    List Collections (by name).bru
    List Collections (date range).bru
    Get Collection.bru
    Get Collection (not found).bru
    List Collections (unauthenticated).bru
  Images/
    List Images.bru
    List Images (search).bru
    List Images (search + date).bru
    List Images (paged).bru
    Get Image URL.bru
    Get Image URL (not found).bru
    Get Image URL (invalid key).bru
```

### Environment variables (`environments/dev.bru`, placeholders only)

- `baseUrl` — e.g. `https://REST_API_ID.execute-api.us-east-1.amazonaws.com/v1`.
- `hostedUiDomain` — e.g. `dev-imagenetog-auth.auth.us-east-1.amazoncognito.com`.
- `appClientId` — from `terraform output app_client_id`.
- `redirectUri` — `https://localhost:3000/callback`.
- `authCode` — empty placeholder; pasted after browser login.
- `authToken` — empty placeholder; set by the Get Token post-response script.
- `testCollection` — a collection name to exercise.
- `testImageKey` — an image key to exercise.

### Collection-level auth

`bruno.json`/collection settings apply `Authorization: {{authToken}}` to every
request so individual requests do not repeat the header. The negative-path
"unauthenticated" request overrides this with no/blank auth.

### Get Token request

- `POST https://{{hostedUiDomain}}/oauth2/token`
- Header `Content-Type: application/x-www-form-urlencoded`.
- Body (form-urlencoded): `grant_type=authorization_code`,
  `client_id={{appClientId}}`, `code={{authCode}}`,
  `redirect_uri={{redirectUri}}`. No client secret.
- Post-response script: on 200, parse JSON, set `bru.setEnvVar("authToken",
  body.id_token)` and store `refresh_token`.
- This request overrides the collection auth (no `Authorization` header needed
  for the token exchange).

### Endpoint requests

Each request under `Collections/` and `Images/` targets `{{baseUrl}}/...`, uses
`{{testCollection}}` / `{{testImageKey}}` where needed, and carries the
collection-level `Authorization: {{authToken}}`. Lightweight `assert` blocks
check `res.status` and key fields (e.g. `res.body.items` is an array,
`res.body.url` present).

---

## Component 4: README Documentation

Add an "API spec & Bruno collection" section covering:

1. Pointer to `openapi/openapi.yaml` and how to lint/preview it.
2. Seeding a dev test user with the AWS CLI:
   `aws cognito-idp admin-create-user` + `admin-set-user-password`
   (referencing `terraform output user_pool_id`).
3. Reading `terraform output` for `app_client_id`, `api_invoke_url`, and the new
   `hosted_ui_login_url`.
4. The browser flow: open `hosted_ui_login_url`, log in, copy `code` from the
   `https://localhost:3000/callback?code=...` redirect into Bruno `authCode`,
   run "Get Token", then run the endpoint requests.
5. The list of Bruno environment variables to populate.

---

## Testing Strategy

- **Terraform**: `terraform fmt -check -recursive terraform/`, `terraform
  validate` (dev), `terraform plan` (expect exit code 2, only the new
  domain/outputs). No `apply`.
- **OpenAPI**: lint with `@redocly/cli` or `openapi-spec-validator`; a small
  check that all four paths and operationIds are present.
- **Bruno**: confirm `.bru` files and `bruno.json` are structurally valid
  (parse / open in Bruno). End-to-end request execution against dev is a manual
  step performed by the user with a real token.
- **Secrets**: confirm no committed file contains a real token/code/credential.

---

## Security Considerations

- The App_Client is public (no secret), so the token exchange is safe to encode
  in a committed request; only placeholders for `code`/`token` are committed.
- The hosted-UI domain change does not alter the app client's OAuth flows,
  scopes, or callback — it only exposes the login page.
- `terraform apply` and Cognito user creation are deliberately excluded from
  automated execution; they are user-approved actions against the live dev
  account.
