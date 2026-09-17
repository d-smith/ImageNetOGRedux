# Requirements Document

## Introduction

The ImageNetOG Redux read API is deployed and functional, but it has no
machine-readable description and no lightweight way to exercise it manually
against a deployed environment. This feature delivers two artifacts and one
small infrastructure addition:

1. An **OpenAPI 3.1 specification** describing the full public API surface —
   every endpoint, path/query parameter, response schema, and error contract.
2. A **Bruno collection** for lightweight manual exploratory testing, including
   the ability to obtain a Cognito token via the browser hosted-UI flow and
   requests that cover every API endpoint.
3. A **Cognito hosted-UI domain** (a small Terraform addition to the `auth`
   module) so the browser login page the token flow depends on actually exists.

Scope is limited to the four existing read-only `GET` routes under `/v1`. No
application behavior changes: the Lambda handlers, service layer, and API
contract are described as-is, not modified.

---

## Glossary

- **API**: The deployed ImageNetOG Redux read-only HTTP interface exposed via
  AWS API Gateway under the `/v1/` path prefix.
- **OpenAPI_Spec**: The OpenAPI 3.1 document (`openapi/openapi.yaml`) describing
  all API endpoints, parameters, response schemas, and error contracts.
- **Bruno_Collection**: The Bruno API-client collection
  (`bruno/imagenetog-redux/`) containing an environment, a token-exchange
  request, and one request per API endpoint.
- **Cognito_JWT**: A JSON Web Token issued by AWS Cognito, presented to the API
  in the raw `Authorization` header. The API Gateway Cognito authorizer accepts
  the ID or access token (no `authorization_scopes` are configured).
- **Hosted_UI**: The Cognito-hosted login page, reachable only once a Cognito
  User Pool domain is provisioned.
- **Hosted_UI_Domain**: The `aws_cognito_user_pool_domain` resource that gives
  the Hosted_UI a resolvable URL.
- **Authorization_Code_Flow**: The OAuth2 flow (already enabled on the app
  client via `allowed_oauth_flows = ["code"]`) in which the browser receives a
  `code` at the redirect URI, which is then exchanged at the `/oauth2/token`
  endpoint for tokens.
- **Auth_Token**: The Bruno environment variable (`authToken`) holding the
  Cognito_JWT that every API request sends in its `Authorization` header.
- **App_Client**: The public Cognito User Pool app client
  (`generate_secret = false`) used to obtain tokens.
- **Error_Contract**: The `{"error": "<token>", "message": "<text>"}` JSON body
  returned by the API for all error responses.

---

## Requirements

### Requirement 1: OpenAPI Specification of the Full API Surface

**User Story:** As an API consumer, I want a complete OpenAPI 3.1 specification,
so that I can understand every endpoint, parameter, response schema, and error
contract without reading the Lambda source code.

#### Acceptance Criteria

1. THE OpenAPI_Spec SHALL be a valid OpenAPI 3.1.0 document that passes a
   standard OpenAPI linter/validator with zero errors.
2. THE OpenAPI_Spec SHALL describe all four read endpoints: `GET /collections`,
   `GET /collections/{collection_name}`,
   `GET /collections/{collection_name}/images`, and
   `GET /collections/{collection_name}/images/{image_key}`.
3. THE OpenAPI_Spec SHALL document, for each endpoint, all supported query and
   path parameters with their types, defaults, permitted values, and validation
   constraints (e.g. `limit` 1–100 default 20, `offset` >= 0, `sort`/`order`
   enums, ISO-8601 date-range params, the collection-name pattern, and the
   image-key length/traversal constraints).
4. THE OpenAPI_Spec SHALL define response schemas matching the exact public
   field shapes returned by the service layer, including the camelCase
   `dateAdded` field and the nullable `description` field on images.
5. THE OpenAPI_Spec SHALL enumerate the Error_Contract responses with their
   correct status codes and error tokens: `400 param.invalid`,
   `401 auth.unauthorized`, `404 resource.not_found`,
   `405 method.not_allowed`, `429 rate_limit.exceeded`, and
   `500 server.error`.
6. THE OpenAPI_Spec SHALL define a security scheme representing the Cognito
   authentication (OAuth2 Authorization_Code_Flow, scopes `openid email
   profile`) and apply it globally, and SHALL document that the token is sent as
   the raw `Authorization` header.
7. THE OpenAPI_Spec SHALL declare a `servers` entry whose URL matches the
   deployed API Gateway stage URL pattern
   (`https://<rest-api-id>.execute-api.us-east-1.amazonaws.com/v1`).

---

### Requirement 2: Cognito Hosted-UI Domain

**User Story:** As a developer, I want a Cognito hosted-UI domain provisioned,
so that a browser login page exists for obtaining a token.

#### Acceptance Criteria

1. THE `auth` Terraform module SHALL define an `aws_cognito_user_pool_domain`
   resource attached to the existing User Pool, named following the
   `{env}-imagenetog-*` convention and constructed from `var.env` (no hardcoded
   environment string).
2. THE `auth` module SHALL expose the hosted-UI domain and a derived login URL
   as module outputs, and the `dev` environment root SHALL re-export them.
3. THE Terraform changes SHALL pass `terraform fmt -check -recursive` and
   `terraform validate`, and a `terraform plan` for the `dev` environment SHALL
   show only the new domain resource plus the new outputs.
4. THE existing app-client OAuth configuration (authorization-code flow,
   scopes, callback URL) SHALL remain unchanged.

---

### Requirement 3: Browser-Based Token Retrieval in Bruno

**User Story:** As a developer doing lightweight manual exploratory testing, I
want to log in through the browser and have Bruno exchange the resulting code
for a token, so that I can authenticate API requests without implementing SRP or
storing credentials in the collection.

#### Acceptance Criteria

1. THE Bruno_Collection SHALL provide a "Get Token" request that POSTs an
   `application/x-www-form-urlencoded` body to the Cognito `/oauth2/token`
   endpoint with `grant_type=authorization_code`, `client_id`, `code`, and
   `redirect_uri`, and SHALL NOT include a client secret (the App_Client is a
   public client).
2. WHEN the "Get Token" request receives a successful token response, THE Bruno
   post-response script SHALL extract the ID token and store it in the
   `authToken` environment variable.
3. THE Bruno_Collection SHALL document the browser step: visit the Hosted_UI
   authorize URL, log in, and copy the returned `code` from the redirect into
   the Bruno `authCode` variable.
4. THE Bruno_Collection SHALL send `Authorization: {{authToken}}` on every API
   request via a collection-level configuration.

---

### Requirement 4: Bruno Requests Covering Every Endpoint

**User Story:** As a developer, I want Bruno requests that cover the entire API,
so that I can manually exercise and explore every endpoint quickly.

#### Acceptance Criteria

1. THE Bruno_Collection SHALL include at least one request for each of the four
   API endpoints.
2. THE Bruno_Collection SHALL include representative variants exercising the
   documented query parameters: pagination, sorting, name-prefix and date-range
   filtering for collections; date listing, description vector search, combined
   search, and pagination for images.
3. THE Bruno_Collection SHALL include negative-path requests demonstrating the
   Error_Contract: a not-found resource (`404 resource.not_found`) and an
   unauthenticated request (`401 auth.unauthorized`).
4. THE Bruno_Collection SHALL reference collection and image identifiers via
   environment variables rather than hardcoded values, and SHALL include
   lightweight assertions on status code and key response fields where useful.

---

### Requirement 5: No Committed Secrets

**User Story:** As a security-conscious maintainer, I want the committed
artifacts to contain no real credentials or tokens, so that the repository stays
safe to share.

#### Acceptance Criteria

1. THE Bruno_Collection environment file SHALL contain only placeholder values
   for `authCode`, `authToken`, and any identifier variables — never real
   tokens, codes, or credentials.
2. IF any Bruno secret/local-override files are introduced, THEN they SHALL be
   added to `.gitignore` so they are not committed.

---

### Requirement 6: Documentation and Consistency

**User Story:** As a new contributor, I want the workflow documented in the
README, so that I can go from a clean checkout to a valid token and green
requests without guesswork.

#### Acceptance Criteria

1. THE README SHALL add a section that points to the OpenAPI_Spec, documents the
   AWS CLI user-bootstrap step (`admin-create-user` + `admin-set-user-password`)
   for seeding a dev test user, explains obtaining the hosted-UI domain and app
   client id from `terraform output`, and walks through the browser-login →
   copy-code → Get-Token → run-requests flow.
2. THE README section SHALL list the Bruno environment variables that must be
   populated.
3. THE OpenAPI_Spec `servers`/hosted-UI URLs and the Bruno environment
   placeholders SHALL reference the same Terraform-derived coordinates so the
   two artifacts remain consistent.
