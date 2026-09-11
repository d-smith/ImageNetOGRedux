# Implementation Plan: ImageNetOG Redux — AWS Deployment

## Overview

Implement the ImageNetOG Redux read-only REST API and its supporting AWS infrastructure. The work is organized in six epics: project scaffolding, Terraform infrastructure, shared API library code (routing, auth plumbing, pagination, error handling), the four `api_handler` route handlers, the three ingestion Lambda functions, and the administrative collection script. Property-based tests (Hypothesis) are included as optional sub-tasks alongside each implementation unit; integration tests are optional sub-tasks in the final epic.

All Python code targets **Python 3.12+**. Infrastructure is written in **Terraform (HCL)**. The test framework is `pytest` + `Hypothesis` + `moto`.

---

## Tasks

- [x] 1. Project scaffolding and repository structure
  - Create top-level directory layout: `src/api_handler/`, `src/ingestion/`, `src/scripts/`, `tests/unit/`, `tests/property/`, `tests/integration/`, `terraform/`
  - Add `pyproject.toml` (or `requirements*.txt`) pinning `aws-lambda-powertools`, `boto3`, `hypothesis`, `moto[all]`, `pytest`, `pytest-cov`
  - Add a `pytest.ini` (or `pyproject.toml` `[tool.pytest.ini_options]`) section configuring `testpaths`, `hypothesis` profile, and coverage reporting
  - Add a runtime version guard in `src/api_handler/__init__.py` that imports `sys` and raises `RuntimeError` if `sys.version_info < (3, 12)` — satisfies the Lambda start-up check in Requirement 1.3
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Terraform foundation — remote state, provider pins, and shared variables
  - [x] 2.1 Create `terraform/versions.tf` pinning `hashicorp/aws ~> 5.0` and Terraform `>= 1.7`
  - [x] 2.2 Create `terraform/backend.tf` configuring the S3 remote backend with per-environment key (`${env}/terraform.tfstate`) and DynamoDB lock table `imagenetog-tfstate-locks`
  - [x] 2.3 Create `terraform/environments/{dev,staging,prod}/variables.tf` declaring `env`, `aws_region` (default `us-east-1`), and per-environment tunable variables (Lambda memory, rate-limit burst/rate)
  - [x] 2.4 Create `terraform/environments/{dev,staging,prod}/terraform.tfvars` with per-environment values
  - _Requirements: 13.2, 13.3, 13.4, 13.5_

- [x] 3. Terraform module — `auth` (Cognito)
  - [x] 3.1 Write `terraform/modules/auth/main.tf` defining `aws_cognito_user_pool` and `aws_cognito_user_pool_client`; expose `user_pool_id` and `app_client_id` as outputs
  - [x]* 3.2 Verify `terraform validate` passes for the `auth` module
  - _Requirements: 3.1, 3.2, 13.1_

- [x] 4. Terraform module — `storage` (DynamoDB)
  - [x] 4.1 Write `terraform/modules/storage/main.tf` defining `aws_dynamodb_table` for `{env}-imagenetog-collections` (PK `collection_name`; GSI `created_epoch-index`) and `{env}-imagenetog-images` (PK `collection_name` + SK `image_key`; LSI `date_added_epoch-index`)
  - [x]* 4.2 Verify `terraform validate` passes for the `storage` module
  - _Requirements: 13.1_

- [ ] 5. Terraform module — `ingestion` (Step Functions + Lambda ingestion functions + EventBridge)
  - [ ] 5.1 Write `terraform/modules/ingestion/iam.tf` defining `aws_iam_role.ingestion_lambda_role` with `s3:GetObject` on image buckets, `bedrock:InvokeModel` on Titan Embed and Nova Lite, `s3vectors:PutVectors`/`CreateIndex`, and `dynamodb:PutItem` on the images table
  - [x] 5.2 Write `terraform/modules/ingestion/lambdas.tf` defining three `aws_lambda_function` resources (`ingestion_embed`, `ingestion_describe`, `ingestion_store`) with Python 3.12 runtime, environment variables (`IMAGES_TABLE`, `EMBED_MODEL_ID`, `DESCRIBE_MODEL_ID`), and the ingestion IAM role
  - [x] 5.3 Write `terraform/modules/ingestion/sfn.tf` defining `aws_sfn_state_machine` with the parallel embed/describe branch and sequential store step; include `Retry` (2 attempts, exponential backoff) and `Catch` blocks on each state
  - [x] 5.4 Write `terraform/modules/ingestion/eventbridge.tf` defining the `aws_cloudwatch_event_rule` for `s3:ObjectCreated` and the `aws_cloudwatch_event_target` wiring it to the Step Functions state machine
  - [ ]* 5.5 Verify `terraform validate` passes for the `ingestion` module
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 13.1_

- [ ] 6. Terraform module — `api` (API Gateway + `api_handler` Lambda + IAM + usage plan)
  - [x] 6.1 Write `terraform/modules/api/iam.tf` defining `aws_iam_role.api_lambda_role` with `dynamodb:GetItem`, `dynamodb:Query`, `dynamodb:Scan` on both DynamoDB tables; `s3:GetObject` for presigned URL generation; `bedrock:InvokeModel` on Titan Embed; `s3vectors:QueryVectors` and `s3vectors:GetVectors`
  - [x] 6.2 Write `terraform/modules/api/lambda.tf` defining `aws_lambda_function.api_handler` (Python 3.12, proxy integration, environment variables `COLLECTIONS_TABLE`, `IMAGES_TABLE`, `COGNITO_USER_POOL_ID`, `EMBED_MODEL_ID`, `PRESIGNED_URL_TTL_SECONDS`)
  - [x] 6.3 Write `terraform/modules/api/apigw.tf` defining `aws_api_gateway_rest_api`, Cognito JWT `aws_api_gateway_authorizer` (300 s cache TTL), `aws_api_gateway_resource` and `aws_api_gateway_method` for all four route paths, `aws_api_gateway_integration` (Lambda proxy), Gateway Responses for `UNAUTHORIZED` and `THROTTLED` in structured JSON format
  - [x] 6.4 Write `terraform/modules/api/usage_plan.tf` defining `aws_api_gateway_usage_plan` with configurable burst and rate limits, wired to the API stage
  - [ ]* 6.5 Verify `terraform validate` passes for the `api` module
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 9.1, 9.2, 10.4, 13.1_

- [ ] 7. Terraform root modules — wire all modules into environments
  - [x] 7.1 Write `terraform/environments/dev/main.tf` calling all four modules (`auth`, `storage`, `ingestion`, `api`) with dev-appropriate variable values; also add `aws_iam_role.admin_role` with the permissions described in the design
  - [ ] 7.2 Replicate the same root module structure for `staging` and `prod` environments
  - [ ]* 7.3 Run `terraform validate` and `terraform plan -detailed-exitcode` (with a mocked/stub backend) for each environment; confirm plan exit code 2 (changes pending, no errors)
  - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

- [ ] 8. Shared API library — exceptions, error handler, and response helpers
  - [x] 8.1 Create `src/api_handler/exceptions.py` defining `CollectionNotFoundError`, `ImageNotFoundError`, `InvalidParameterError`, `MethodNotAllowedError` (all subclassing a base `APIError` with `http_status` and `error_token` attributes)
  - [x] 8.2 Create `src/api_handler/responses.py` with helpers `ok(body)`, `error_response(status, token, message)` that always set `Content-Type: application/json`; the error helper must produce `{"error": "<token>", "message": "<msg>"}` with no stack trace
  - [ ] 8.3 Create `src/api_handler/middleware.py` with a Powertools middleware (or exception handler decorator) that catches each exception class and calls `error_response` with the mapped status and token; the catch-all for bare `Exception` logs the full traceback to CloudWatch and returns a 500 with `server.error`
  - [x]* 8.4 Write unit tests in `tests/unit/test_error_handler.py`: verify correct JSON shape, correct token, no traceback in 500 body, correct `Content-Type` header
  - [x]* 8.5 Write property test `tests/property/test_error_properties.py` — Property 17 (arbitrary error conditions produce `error` + `message` JSON matching `^[a-z_]+\.[a-z_]+$`); Property 18 (requests with invalid parameters produce a 400 body naming each invalid param)
  - _Requirements: 10.3, 10.5, 10.6_

- [ ] 9. Shared API library — query parameter parsing and validation
  - [ ] 9.1 Create `src/api_handler/params.py` with `parse_pagination(event)` returning validated `(limit: int, offset: int)` (defaults 20/0; raises `InvalidParameterError` if `limit > 100` or non-integer); `parse_sort(event, allowed_fields)` raising `InvalidParameterError` for unknown sort fields; `parse_date(value, param_name)` raising `InvalidParameterError` for non-ISO 8601 strings; `parse_date_range(after, before)` raising `InvalidParameterError` when after > before
  - [x]* 9.2 Write unit tests in `tests/unit/test_param_validation.py`: boundary values (limit=1, 100, 101), invalid sort fields, invalid date strings, inverted date ranges
  - [x]* 9.3 Write property tests in `tests/property/test_pagination_properties.py` — Property 4 (slice size = `min(limit, max(0, N-offset))`); Property 5 (total/limit/offset fields accurate); Property 6 (`limit > 100` → 400, `limit` in `[1,100]` → accepted); Property 7 (non-valid sort fields → 400)
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

- [ ] 10. Shared API library — router setup and method/version enforcement
  - [ ] 10.1 Create `src/api_handler/app.py` initialising `APIGatewayRestResolver` from AWS Lambda Powertools; register the router; add a before-request hook that raises `MethodNotAllowedError` for any non-GET method reaching a registered path; add a path-prefix guard that returns 404 for paths not starting with `/v1/`
  - [x] 10.2 Create `src/api_handler/lambda_function.py` as the Lambda entry-point; import the runtime version guard from `__init__.py`, wire the Powertools app, and expose `handler(event, context)`
  - [x]* 10.3 Write unit tests in `tests/unit/test_router.py`: verify 405 for POST/PUT/DELETE/PATCH on each route; verify 404 for `/v2/`, `/`, `/collections`
  - [x]* 10.4 Write property tests in `tests/property/test_router_properties.py` — Property 1 (arbitrary non-GET method on any registered path → 405); Property 2 (arbitrary path not starting with `/v1/` → 404)
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2_

- [ ] 11. Checkpoint — core library complete
  - Ensure all unit tests and property tests for epics 8–10 pass (`pytest tests/unit tests/property -k "error or param or router"`). Ask the user if questions arise.

- [ ] 12. Route handler — `GET /v1/collections`
  - [x] 12.1 Create `src/api_handler/routes/collections.py`; implement `list_collections(event)`:
    - Call `parse_pagination` and `parse_sort(allowed=["name","created"])` and date-range params from `params.py`
    - Perform DynamoDB `scan` on `COLLECTIONS_TABLE` with field projection (exclude `s3_bucket`, `s3vector_bucket`)
    - Apply `name` prefix filter (case-insensitive) and `created_epoch` range filter in-Lambda
    - Apply offset/limit slice and build paginated envelope `{"items": [...], "total": N, "limit": L, "offset": O}`
  - [x]* 12.2 Write property tests in `tests/property/test_collection_properties.py` — Property 8 (every collection item has `name` + `created`, never `s3_bucket`/`s3vector_bucket`); Property 9 (`name` prefix filter returns exactly matching collections); Property 10 (date-range filter correctness + inverted-range rejection)
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [ ] 13. Route handler — `GET /v1/collections/{collection_name}`
  - [x] 13.1 Implement `get_collection(collection_name)` in `src/api_handler/routes/collections.py`:
    - DynamoDB `get_item` on `COLLECTIONS_TABLE` by `collection_name`
    - Raise `CollectionNotFoundError` if item is absent
    - Return `{"name": ..., "created": ...}` (exclude internal fields)
  - _Requirements: 6.1, 6.5, 10.1_

- [ ] 14. Route handler — `GET /v1/collections/{collection_name}/images`
  - [x] 14.1 Create `src/api_handler/routes/images.py`; implement `list_images(collection_name, event)`:
    - Validate collection exists (reuse `get_collection`); raise `CollectionNotFoundError` otherwise
    - Parse pagination, sort, `addedAfter`/`addedBefore`, and `description` params
    - **Date-only path:** Query `date_added_epoch-index` LSI with `KeyConditionExpression` and optional `FilterExpression`; apply offset/limit; project out internal fields
    - **Description-only path:** Call Bedrock `invoke_model(amazon.titan-embed-image-v1, inputText=description)`; call `s3vectors.query_vectors(topK=limit, queryVector=vec)`; `batch_get_item` from `IMAGES_TABLE`; project out internal fields
    - **Combined path:** Same as description path but pass `filter={"date_added_epoch": {"$gte": ..., "$lte": ...}}` to `query_vectors`
    - Build and return paginated envelope; for vector search `total` = len(S3V result)
  - [x]* 14.2 Write property tests in `tests/property/test_image_properties.py` — Property 11 (every image item has `key` + `dateAdded` + `description`, never `s3_bucket`/`s3vector_bucket`); Property 12 (date filter correctness + error on invalid/inverted range); Property 13 (all returned image keys exist in the collection); Property 14 (combined search respects date filter)
    - **Resolved (2026-09-11):** All four properties are DONE. Properties 11 & 12 (date-only path) run under `@mock_aws`. Because `moto` (5.1.22) does **not** implement `s3vectors:QueryVectors`, Properties 13 & 14 stub the service's module-level `_s3vectors` client with a fake `query_vectors` that mirrors the real contract (returns a ranked key subset and honours the `date_added_epoch` `$gte`/`$lte` filter) and stub `_embed_description`; DynamoDB stays under moto so `batch_get_item` hydration and the containment check are real. The earlier coverage pragmas on `_search_by_description` were removed — the vector-search path is now measured (`services/images.py` ~91%). Re-check newer `moto` releases for native `query_vectors` support to replace the stub.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [ ] 15. Route handler — `GET /v1/collections/{collection_name}/images/{image_key}`
  - [x] 15.1 Implement `get_image(collection_name, image_key)` in `src/api_handler/routes/images.py`:
    - `get_item` on `COLLECTIONS_TABLE` to retrieve `s3_bucket`; raise `CollectionNotFoundError` if absent
    - `get_item` on `IMAGES_TABLE` by `(collection_name, image_key)`; raise `ImageNotFoundError` if absent
    - Call `boto3.client('s3').generate_presigned_url('get_object', Params={'Bucket': s3_bucket, 'Key': image_key}, ExpiresIn=int(os.environ['PRESIGNED_URL_TTL_SECONDS']))` (default 300)
    - Return `{"key": image_key, "url": presigned_url}`
  - [x]* 15.2 Write unit tests in `tests/unit/test_presigned_url.py`: verify `ExpiresIn=300` passed to boto3 mock; verify 404 for missing collection; verify 404 for missing image key
  - [x]* 15.3 Write property tests in `tests/property/test_presigned_properties.py` — Property 15 (valid collection + valid image_key → 200 with non-empty URL); Property 16 (any valid image lookup → `ExpiresIn=300` in mock boto3 call)
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 10.1, 10.2_

- [ ] 16. Checkpoint — all API route handlers complete
  - Ensure all unit tests and property tests pass for epics 8–15 (`pytest tests/unit tests/property`). Ask the user if questions arise.

- [ ] 17. Ingestion Lambda — `ingestion_embed`
  - [x] 17.1 Create `src/ingestion/embed.py` implementing `handler(event, context)`:
    - Read `collection_name`, `image_key`, `s3_bucket`, `s3vector_bucket`, `date_added_epoch` from the Step Functions event
    - `s3.get_object` → raw bytes → base64-encode
    - `bedrock_runtime.invoke_model(modelId=EMBED_MODEL_ID, body={"inputImage": b64, "embeddingConfig": {"outputEmbeddingLength": 1024}})`
    - `s3vectors.put_vectors(vectorBucketName=s3vector_bucket, indexName="images", vectors=[{key, data: {float32: embedding}, metadata: {date_added_epoch, image_key}}])`
    - Return the input event unchanged (pass-through for Step Functions)
  - _Requirements: 12.1, 12.2_

- [ ] 18. Ingestion Lambda — `ingestion_describe`
  - [x] 18.1 Create `src/ingestion/describe.py` implementing `handler(event, context)`:
    - Read fields from event; `s3.get_object` → raw bytes → base64-encode
    - Detect image format from the `image_key` extension (`jpeg`/`png` fallback to `jpeg`)
    - `bedrock_runtime.invoke_model(modelId=DESCRIBE_MODEL_ID, body={"messages": [{role: "user", content: [{image: {format, source: {bytes: b64}}}, {text: "Describe this image concisely in 1-3 sentences."}]}]})`
    - Extract description string from response; return event enriched with `{"description": "..."}` for Step Functions
  - _Requirements: 12.3_

- [ ] 19. Ingestion Lambda — `ingestion_store`
  - [x] 19.1 Create `src/ingestion/store.py` implementing `handler(event, context)`:
    - Read all required fields from event (`collection_name`, `image_key`, `s3_bucket`, `s3vector_bucket`, `date_added`, `date_added_epoch`, `description`)
    - `dynamodb.put_item(TableName=IMAGES_TABLE, Item={...})` with all required fields; `description` stored as-is (may be null)
    - Emit CloudWatch metric `IngestionSuccess` on completion
  - [x]* 19.2 Write property test `tests/property/test_ingestion_properties.py` — Property 19 (for any generated `(collection, image)` pair, after mocked ingestion workflow execution the DynamoDB record contains all required non-null fields: `collection_name`, `image_key`, `date_added`, `date_added_epoch`, `s3_bucket`, `s3vector_bucket`)
  - _Requirements: 12.3, 12.4_

- [ ] 20. Checkpoint — ingestion Lambdas complete
  - Ensure all unit and property tests pass for epics 17–19 (`pytest tests/unit tests/property`). Ask the user if questions arise.

- [ ] 21. Administrative collection script
  - [x] 21.1 Create `src/scripts/create_collection.py` implementing CLI via `argparse` with `--collection-name` and `--env` arguments:
    - Validate collection name against `^[a-z0-9][a-z0-9-]{1,46}[a-z0-9]$` (3–48 chars, lowercase alphanumeric + hyphens); raise `ValueError` with descriptive message on failure
    - Create S3 image bucket: `{env}-imagenetog-{collection_name}-images` in `us-east-1`
    - Create S3 Vector bucket: `{env}-imagenetog-{collection_name}-vectors`
    - Create S3 Vectors index `images` (cosine, 1024-dim, float32, all metadata keys filterable) within the vector bucket
    - `dynamodb.put_item` on `{env}-imagenetog-collections` with `collection_name`, `created` (ISO 8601 today), `created_epoch`, `s3_bucket`, `s3vector_bucket`
  - [x]* 21.2 Write unit tests in `tests/unit/test_create_collection.py`: verify naming validation rejects invalid names (too short, too long, uppercase, special chars) and accepts valid names; verify correct bucket/index/DynamoDB calls using `moto`
  - _Requirements: 11.1, 11.2, 11.3_

- [ ] 22. Wire routes into Powertools app and finalize Lambda package
  - [x] 22.1 Update `src/api_handler/app.py` to import and register all four route handlers from `routes/collections.py` and `routes/images.py` using the Powertools `Router` pattern
  - [x] 22.2 Update `src/api_handler/lambda_function.py` to include the version guard import and confirm the Powertools `handler` export matches the Terraform `handler` config (`lambda_function.handler`)
  - [x] 22.3 Add `src/api_handler/requirements.txt` (Lambda layer / package deps) listing pinned versions of `aws-lambda-powertools` and `boto3`
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2_

- [ ] 23. Auth property tests and sort property tests
  - [ ]* 23.1 Write property tests in `tests/property/test_auth_properties.py` — Property 3 (generate valid/invalid JWT structures against a mock JWKS; assert allow/reject behavior)
  - [ ]* 23.2 Write property tests in `tests/property/test_sort_properties.py` — Property 7 (generate arbitrary strings as `sort` parameter; assert non-valid sort fields return 400 for both collections and images endpoints)
  - _Requirements: 3.1, 3.2, 5.7_

- [ ] 24. Final checkpoint — full test suite
  - Run `pytest tests/unit tests/property --tb=short` and confirm all tests pass. Ask the user if questions arise.

- [ ] 25. Integration tests (optional)
  - [ ]* 25.1 Write `tests/integration/test_auth_integration.py`: verify deployed API Gateway returns 401 on missing/invalid JWT; verify structured JSON error body
  - [ ]* 25.2 Write `tests/integration/test_rate_limit.py`: burst above configured usage plan and assert 429 with structured JSON body
  - [ ]* 25.3 Write `tests/integration/test_ingestion_e2e.py`: upload a test image to the dev S3 bucket; poll DynamoDB until the record appears (or timeout); assert all required fields are present
  - [ ]* 25.4 Write `tests/integration/test_presigned_url_expiry.py`: generate a presigned URL with TTL=5 s (test-only override); wait 6 s; assert S3 rejects the expired URL
  - _Requirements: 3.2, 8.5, 9.2, 12.1_

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP path.
- Every task that references properties from the design document is annotated with the property number(s) it validates.
- Terraform modules are written and validated before any Python Lambda code so that the IAM surface is understood before implementation.
- `moto` is used for all AWS service mocking in unit and property tests; no live AWS account is required to run the test suite.
- Integration tests (epic 25) require a deployed dev environment and live AWS credentials.
- The `terraform validate` sub-tasks (3.2, 4.2, 5.5, 6.5, 7.3) are marked optional because they require a configured Terraform CLI; run them in CI or locally when Terraform is available.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1", "2.2", "2.3", "2.4"] },
    { "id": 1, "tasks": ["3.1", "4.1", "8.1", "8.2"] },
    { "id": 2, "tasks": ["3.2", "4.2", "5.1", "8.3", "9.1", "10.1"] },
    { "id": 3, "tasks": ["5.2", "5.3", "5.4", "8.4", "8.5", "9.2", "9.3", "10.2", "10.3", "10.4"] },
    { "id": 4, "tasks": ["5.5", "6.1", "12.1", "13.1"] },
    { "id": 5, "tasks": ["6.2", "6.3", "14.1", "15.1", "17.1", "18.1", "19.1", "21.1"] },
    { "id": 6, "tasks": ["6.4", "6.5", "7.1", "12.2", "14.2", "15.2", "15.3", "19.2", "21.2", "22.1", "22.2", "22.3"] },
    { "id": 7, "tasks": ["7.2", "7.3", "23.1", "23.2"] },
    { "id": 8, "tasks": ["25.1", "25.2", "25.3", "25.4"] }
  ]
}
```
