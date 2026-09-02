# Requirements Document

## Introduction

ImageNetOG Redux is a read-only RESTful API service hosted on AWS that exposes collections of images and their associated metadata to authenticated end users. Each collection groups images stored in S3, with vector embeddings stored in S3 Vector buckets and metadata stored in DynamoDB. The API supports listing collections, listing and searching images within a collection (including description-based vector similarity search), and retrieving time-limited presigned URLs for individual images. Image ingestion and collection creation are handled by separate administrative tooling and are out of scope for the API itself.

---

## Glossary

- **System**: The ImageNetOG Redux API service as a whole (Lambda functions + API Gateway + supporting AWS infrastructure).
- **API**: The RESTful HTTP interface exposed to end users via AWS API Gateway.
- **Collection**: A named grouping of images, consisting of an S3 bucket, a corresponding S3 Vector bucket, and a DynamoDB metadata entry recording the collection name, creation date, S3 bucket location, and S3 Vector bucket location.
- **Image**: A single image file stored in a Collection's S3 bucket, identified by a unique key, with associated metadata (key, date added, description) stored in DynamoDB and a vector embedding stored in the Collection's S3 Vector bucket.
- **Image_Key**: The unique string identifier for an Image within a Collection.
- **Presigned_URL**: A time-limited, cryptographically signed URL that grants temporary read access to a specific Image in S3.
- **Description**: A natural-language string describing the content of an Image, generated during ingestion and stored in DynamoDB; also used as a query input for vector similarity search.
- **Vector_Embedding**: A high-dimensional numeric representation of an Image generated during ingestion by a pre-trained Bedrock model and stored in an S3 Vector bucket.
- **Vector_Search**: A similarity-based search that ranks Images by the cosine (or equivalent) distance between their Vector_Embeddings and the embedding of a user-supplied Description.
- **Cognito_JWT**: A JSON Web Token issued by AWS Cognito and presented by clients as a Bearer token in the Authorization header.
- **Lambda**: An AWS Lambda function serving as the compute layer for API request handling.
- **DynamoDB**: The AWS DynamoDB table(s) used to store Collection and Image metadata.
- **S3**: AWS Simple Storage Service; the raw image storage layer.
- **S3_Vector**: AWS S3 Vectors; the vector embedding storage layer.
- **Step_Functions**: AWS Step Functions used to orchestrate the image ingestion workflow.
- **Bedrock**: AWS Bedrock; the managed AI service used to generate Vector_Embeddings and Descriptions during ingestion.
- **API_Gateway**: AWS API Gateway; the ingress layer that routes requests to Lambda and enforces authentication.
- **Authorizer**: The AWS Cognito JWT Authorizer attached to API_Gateway that validates Cognito_JWTs on every request.
- **Rate_Limiter**: The API Gateway usage-plan mechanism that enforces per-client request rate limits.
- **Ingestion_Workflow**: The Step_Functions state machine triggered on S3 upload that generates embeddings and descriptions and writes metadata to DynamoDB.
- **Admin_Role**: The dedicated IAM role assigned to administrators performing collection management and image upload operations.
- **Collection_Script**: The administrative script that takes a collection name as input, creates the S3 bucket, S3 Vector bucket, and DynamoDB metadata entry following the standard naming convention.
- **OpenAPI_Spec**: The OpenAPI (Swagger) specification document describing all API endpoints, request/response schemas, and example usage.

---

## Requirements

### Requirement 1: Platform and Runtime

**User Story:** As a platform engineer, I want the service to run on Python 3.12+ on AWS Lambda, so that the team can use a modern, well-supported runtime with a consistent deployment target.

#### Acceptance Criteria

1. THE System SHALL be implemented in Python such that it executes without syntax errors or runtime import failures on Python 3.12.x patch releases.
2. THE Lambda SHALL execute API request handlers using the Python 3.12 runtime environment.
3. IF the deployment environment provides a Python runtime version outside the 3.12.x series, THEN the Lambda SHALL fail to start and produce an error indicating an unsupported runtime version.

---

### Requirement 2: RESTful Read-Only API

**User Story:** As an end user, I want a well-structured read-only RESTful API, so that I can discover and retrieve images without risking accidental modification of data.

#### Acceptance Criteria

1. THE API SHALL expose endpoints for Collections and Images using only the HTTP GET method; IF a non-GET HTTP method is used on any API endpoint, THEN THE API SHALL return an HTTP 405 Method Not Allowed response.
2. THE API SHALL version all endpoints under the `/v1/` path prefix; IF a request is made to a path that does not begin with a valid version prefix, THEN THE API SHALL return an HTTP 404 response.
3. THE API SHALL return HTTP status codes that conform to RESTful conventions: 200 for success, 400 for malformed requests, 401 for unauthenticated requests, 403 for unauthorized requests, 404 for resources not found, 405 for method not allowed, and 429 for rate-limit violations.
4. THE System SHALL restrict all write, update, and delete operations on Collections and Images to administrative tooling; the API SHALL NOT expose endpoints for creating, modifying, or deleting Collections or Images.
5. THE API SHALL respond to any successful GET request within 2000 milliseconds under normal operating conditions.

---

### Requirement 3: Authentication

**User Story:** As a security engineer, I want every API request to require a valid Cognito JWT, so that unauthenticated clients cannot access any data.

#### Acceptance Criteria

1. WHEN an inbound request is received, THE Authorizer SHALL validate the Cognito JWT presented in the `Authorization: Bearer` header by verifying the cryptographic signature against the Cognito JWKS endpoint, confirming the token has not expired, and confirming the issuer and audience claims match the configured Cognito User Pool, before the request reaches a Lambda handler.
2. IF a request is received with a missing `Authorization` header, a non-Bearer authorization scheme, a JWT with an invalid cryptographic signature, an expired JWT, or a JWT whose issuer or audience claims do not match the configured Cognito User Pool, THEN THE Authorizer SHALL reject the request with an HTTP 401 response and SHALL NOT invoke any Lambda handler.

---

### Requirement 4: API Documentation

**User Story:** As an API consumer, I want a complete OpenAPI specification, so that I can understand all available endpoints, request parameters, response schemas, and example payloads without reading source code.

#### Acceptance Criteria

1. THE System SHALL publish an OpenAPI 3.0 specification accessible at a dedicated documentation endpoint, that documents every API endpoint, including path, HTTP method, query parameters, request headers, response schemas, and at least one example request and response per endpoint.
2. THE OpenAPI_Spec SHALL document all error response schemas defined in Requirement 10.
3. WHEN the API changes, THE System SHALL update the OpenAPI specification such that every documented endpoint path, method, parameter, and response schema matches the behavior of the deployed API.

---

### Requirement 5: Pagination, Filtering, and Sorting for List Endpoints

**User Story:** As an end user, I want to page through, filter, and sort large lists of collections and images, so that I can efficiently find what I am looking for.

#### Acceptance Criteria

1. THE API SHALL support pagination on all list endpoints via `limit` and `offset` query parameters, where `offset` is a non-negative integer indicating the number of items to skip.
2. THE API SHALL default to a page size of 20 items when no `limit` parameter is supplied.
3. THE API SHALL include pagination metadata in every list response, containing the total count of matching items, the applied `limit`, and the applied `offset`.
4. THE API SHALL accept a `limit` query parameter with a maximum value of 100; IF a `limit` value greater than 100 is supplied, THEN THE API SHALL return a 400 error indicating that the limit exceeds the maximum allowed value.
5. THE API SHALL allow Collections to be sorted by `name` or `created` via a `sort` query parameter, and by sort direction via an `order` query parameter accepting `asc` or `desc`, defaulting to `asc`.
6. THE API SHALL allow Images to be sorted by `dateAdded` via a `sort` query parameter, and by sort direction via an `order` query parameter accepting `asc` or `desc`, defaulting to `asc`.
7. IF a `sort` query parameter value is supplied that is not a supported sort field for the requested resource, THEN THE API SHALL return a 400 error indicating which field name was invalid.

---

### Requirement 6: List Collections

**User Story:** As an end user, I want to list available collections with their names and creation dates, so that I can discover what image groups exist.

#### Acceptance Criteria

1. WHEN a GET request is made to the collections list endpoint, THE API SHALL return a paginated list of Collections, each entry containing the Collection `name` and `created` date, with a default page size of 20 and a maximum page size of 100 items per page.
2. IF a `name` filter query parameter is provided, THEN THE API SHALL return only Collections whose `name` exactly matches or begins with the provided value, using case-insensitive comparison.
3. IF a `createdAfter` and/or `createdBefore` query parameter is provided, THEN THE API SHALL return only Collections whose `created` date falls within the specified range, where each parameter value must be an ISO 8601 date string (YYYY-MM-DD).
4. IF both `createdAfter` and `createdBefore` are provided and `createdAfter` is later than `createdBefore`, THEN THE API SHALL return an error response indicating the date range is invalid and return no Collection results.
5. THE API SHALL NOT include internal storage fields (S3 bucket location or S3 Vector bucket location) in the collections list response.

---

### Requirement 7: List and Search Images in a Collection

**User Story:** As an end user, I want to list and search images within a collection, so that I can find images by date or by a natural-language description.

#### Acceptance Criteria

1. WHEN a GET request is made to the images list endpoint for a Collection, THE API SHALL return a paginated list of Images belonging to that Collection, each entry containing the Image `key`, `dateAdded`, and `description` (which may be null if no description was provided at upload time).
2. THE API SHALL allow the images list to be filtered by `dateAdded` using `addedAfter` and/or `addedBefore` query parameters, each accepting a date value in ISO 8601 format (YYYY-MM-DD); IF either parameter is not a valid ISO 8601 date, or if `addedBefore` is earlier than `addedAfter`, THEN THE API SHALL return an error response indicating the invalid filter parameter without returning any Image results.
3. WHERE a `description` query parameter is supplied, THE API SHALL perform a Vector_Search against the Collection's S3_Vector bucket using the Vector_Embedding of the supplied description to rank Images by similarity, returning an empty list when no Images exist in the Collection.
4. WHEN a GET request is made to the images list endpoint with both a `dateAdded` filter and a `description` query parameter, THE API SHALL first narrow the candidate Image set using the `dateAdded` filter, then rank the narrowed set by Vector_Search similarity, returning the top results up to the `limit` query parameter value, where `limit` defaults to 20 and is capped at 100; IF `limit` is supplied and is not a positive integer within the range 1 to 100, THEN THE API SHALL return an error response indicating the invalid limit parameter.
5. THE API SHALL NOT include the S3 bucket location or S3 Vector bucket location fields in the images list response.
6. IF a GET request is made to the images list endpoint for a Collection that does not exist, THEN THE API SHALL return an error response indicating that the Collection was not found.

---

### Requirement 8: Retrieve a Presigned Image URL

**User Story:** As an end user, I want to retrieve a temporary secure URL for a specific image, so that I can download it directly from S3 for a limited time.

#### Acceptance Criteria

1. WHEN a GET request is made to the single-image endpoint with a Collection name and Image_Key that both exist, THE API SHALL return an HTTP 200 response containing a Presigned_URL that grants temporary read access to the Image file in S3.
2. WHEN a Presigned_URL is generated, THE URL SHALL be valid for exactly 5 minutes from the time of generation.
3. IF a GET request is made to the single-image endpoint with a Collection name that does not exist, THEN THE API SHALL return an HTTP 404 response identifying the missing Collection.
4. IF a GET request is made to the single-image endpoint with a valid Collection name but an Image_Key that does not exist within that Collection, THEN THE API SHALL return an HTTP 404 response identifying the missing Image.
5. WHEN a Presigned_URL has expired, attempts to access the Image using that URL SHALL be rejected by S3, which enforces signature expiry.
6. THE API SHALL ensure that Images in S3 are not accessible without a valid unexpired Presigned_URL or equivalent authorization mechanism; direct unauthenticated access to S3 image objects SHALL be denied.

---

### Requirement 9: Rate Limiting

**User Story:** As a platform engineer, I want API request rate limiting enforced at the gateway level, so that abusive or runaway clients cannot degrade the service for other users.

#### Acceptance Criteria

1. THE Rate_Limiter SHALL enforce per-client request rate limits on all API endpoints via API_Gateway usage plans.
2. IF a client exceeds the configured rate limit, THEN THE API_Gateway SHALL return an HTTP 429 response to that client.

---

### Requirement 10: Error Handling

**User Story:** As an API consumer, I want structured, informative error responses for all failure conditions, so that I can diagnose problems without inspecting server logs.

#### Acceptance Criteria

1. IF a request references a Collection name that does not exist, THEN THE API SHALL return an HTTP 404 response with a structured JSON error body identifying the missing resource.
2. IF a request references an Image_Key that does not exist within the specified Collection, THEN THE API SHALL return an HTTP 404 response with a structured JSON error body identifying the missing resource.
3. IF a request contains a malformed, invalid, or out-of-range filter or sort parameter, THEN THE API SHALL return an HTTP 400 response with a structured JSON error body that identifies each invalid parameter by name and states the reason it was rejected.
4. IF a request is unauthenticated or carries an invalid Cognito_JWT, THEN THE Authorizer SHALL return an HTTP 401 response with a structured JSON error body.
5. THE structured JSON error body SHALL include a machine-readable `error` field containing a dot-separated string token (e.g., `resource.not_found`, `param.invalid`) and a `message` field containing a plain-text description of the failure, and THE API SHALL return all error responses with a `Content-Type` of `application/json`.
6. IF a request fails due to an internal server error, THEN THE API SHALL return an HTTP 500 response with a structured JSON error body containing an `error` token and a `message` field, and SHALL NOT include internal stack traces or system details in the response body.

---

### Requirement 11: Collection Administration (Out of Scope for API)

**User Story:** As an administrator, I want a script to create new collections following a standard naming convention, so that collections are provisioned consistently without manual steps.

#### Acceptance Criteria

1. THE Collection_Script SHALL accept a collection name as input and create an S3 bucket, an S3_Vector bucket, and a DynamoDB metadata entry for the new Collection.
2. THE Collection_Script SHALL enforce a standard naming convention for bucket names and DynamoDB entries to ensure consistency across environments.
3. THE Collection_Script SHALL create all resources in the `us-east-1` AWS region.
4. THE Admin_Role SHALL be granted IAM permissions to invoke the Collection_Script and to create S3 buckets, S3 Vector buckets, and DynamoDB entries.

---

### Requirement 12: Image Ingestion Workflow (Out of Scope for API)

**User Story:** As an administrator, I want image uploads to S3 to automatically trigger metadata generation and storage, so that newly uploaded images become searchable without manual steps.

#### Acceptance Criteria

1. WHEN an image file is uploaded to a Collection's S3 bucket, THE Ingestion_Workflow SHALL be triggered automatically.
2. THE Ingestion_Workflow SHALL generate a Vector_Embedding for the uploaded Image using a pre-trained Bedrock model and store the embedding in the Collection's S3_Vector bucket, along with metadata fields required to support date and other filter operations.
3. THE Ingestion_Workflow SHALL generate a Description for the uploaded Image using a pre-trained Bedrock model and store the Description in DynamoDB as part of the Image metadata record.
4. THE Ingestion_Workflow SHALL store the Image metadata record in DynamoDB, including the Image_Key, `dateAdded`, Description, S3 bucket location, and S3_Vector bucket location.
5. THE Admin_Role SHALL be granted IAM permissions to upload images to a Collection's S3 bucket using the AWS CLI or AWS Management Console.

---

### Requirement 13: Infrastructure as Code

**User Story:** As a platform engineer, I want all AWS infrastructure to be defined in Terraform, so that environments can be provisioned reproducibly across development, staging, and production.

#### Acceptance Criteria

1. THE System SHALL provision all AWS resources (API_Gateway, Lambda, DynamoDB, S3, S3_Vector, Step_Functions, Cognito, IAM roles, and usage plans) using Terraform.
2. THE System SHALL support deployment to at minimum three named environments: development, staging, and production, where each environment's Terraform state SHALL be isolated from other environments.
3. THE System SHALL deploy all resources to the `us-east-1` AWS region.
4. THE System SHALL store Terraform state in a remote backend with per-environment state files, preventing local state from being used in CI/CD pipelines.
5. THE System SHALL define per-environment variable values in dedicated Terraform variable definition files (e.g., `terraform.tfvars` or equivalent), one file per environment.
