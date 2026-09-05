---
inclusion: auto
name: security-patterns
description: Security patterns, input validation rules, IAM constraints, and data privacy rules for the ImageNetOG Redux project
---

# Security Patterns — ImageNetOG Redux

Applies to all Python source files under `src/` and all Terraform files under `terraform/`. Pay particular attention when working on `src/api_handler/routes/images.py`, `src/api_handler/routes/collections.py`, `src/ingestion/`, and any IAM or S3 Terraform resources.

---

## Input Validation

**Validate all query parameters before any AWS call.** The `params.py` module is the single validation gate. No service function or route handler calls a boto3 client with unvalidated input.

Validation order in every route handler:
1. Parse and validate all query parameters (raises `InvalidParameterError` on failure)
2. Validate path parameters (collection name format, image key length)
3. Only then call service functions that touch AWS

```python
# CORRECT — validate first, AWS second
def list_images(collection_name: str, event: dict) -> dict:
    params = parse_pagination(event)          # raises on invalid input
    date_range = parse_date_range(event)      # raises on invalid input
    validate_collection_name(collection_name) # raises on invalid format
    return images_service.list(collection_name, params, date_range)

# WRONG — AWS call before validation
def list_images(collection_name: str, event: dict) -> dict:
    items = dynamodb.query(...)               # ← called before validating input
    limit = int(event.get("limit", 20))
```

### Collection name validation

Collection names must match `^[a-z0-9][a-z0-9-]{1,46}[a-z0-9]$` before being used in any DynamoDB key, S3 bucket name, or S3 Vectors bucket name. Reject anything that does not match with `InvalidParameterError`.

### Image key validation

Image keys (S3 object keys) must not contain `..` path traversal sequences. Reject keys containing `..` before generating a presigned URL or looking up DynamoDB records.

```python
def validate_image_key(key: str) -> None:
    if ".." in key:
        raise InvalidParameterError("image_key", "Path traversal sequences are not permitted")
    if len(key) > 1024:
        raise InvalidParameterError("image_key", "Key exceeds maximum length of 1024 characters")
```

### Description query sanitisation

The `description` vector search parameter is passed to Bedrock as a text string. It must be:
- Stripped of leading/trailing whitespace
- Truncated to 500 characters maximum before embedding
- Never interpolated into a DynamoDB expression or S3 key

```python
description = description.strip()[:500]
```

---

## Secrets and Credentials

**No secrets in source code or environment variables beyond what Lambda injects.**

Acceptable env vars (set by Terraform, contain no credentials):
- Table names, model IDs, TTL values, User Pool IDs — these are configuration, not secrets.

Not acceptable:
- API keys, passwords, access keys, or tokens in any env var, source file, or Terraform `.tfvars` file committed to the repository.

AWS credentials for Lambda execution come exclusively from the IAM execution role attached to the function. Never call `boto3.Session(aws_access_key_id=..., aws_secret_access_key=...)` in application code.

If a secret is needed (e.g., a third-party API key), it must be stored in AWS Secrets Manager and retrieved at runtime via `boto3.client("secretsmanager").get_secret_value(...)`. The secret value must not be logged.

---

## Presigned URL Security

The presigned URL endpoint is a security boundary. Follow these rules exactly:

1. **Always verify the collection exists** (DynamoDB `get_item` on collections table) before generating a URL. Do not generate a URL for a bucket that cannot be confirmed to exist in the system.
2. **Always verify the image key exists** (DynamoDB `get_item` on images table) before generating a URL. A presigned URL for a non-existent key leaks the bucket name and key path to the caller.
3. **Use `ExpiresIn=300` exactly.** Do not allow callers to specify TTL. The TTL value comes from `config.PRESIGNED_URL_TTL_SECONDS` which defaults to `300` and is set by Terraform — it is not a query parameter.
4. **Use the S3 bucket name from DynamoDB**, not from caller input. Never construct a bucket name from the `collection_name` path parameter without first confirming the collection record exists.

```python
# CORRECT — bucket name comes from confirmed DynamoDB record
collection = get_collection_or_raise(collection_name)
image = get_image_or_raise(collection_name, image_key)
url = s3.generate_presigned_url(
    "get_object",
    Params={"Bucket": collection["s3_bucket"], "Key": image_key},
    ExpiresIn=config.PRESIGNED_URL_TTL_SECONDS,
)

# WRONG — bucket name constructed from user input
bucket = f"prod-imagenetog-{collection_name}-images"  # ← never do this
url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, ...})
```

---

## IAM Least Privilege

When writing Terraform IAM policies, scope every permission to the minimum necessary resource ARN. Never use `"Resource": "*"` unless the AWS service genuinely does not support resource-level permissions (document this with a comment if so).

```hcl
# CORRECT — scoped to specific table ARNs
resource "aws_iam_policy" "api_dynamodb" {
  policy = jsonencode({
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"]
      Resource = [
        aws_dynamodb_table.collections.arn,
        aws_dynamodb_table.images.arn,
        "${aws_dynamodb_table.images.arn}/index/*",
      ]
    }]
  })
}

# WRONG — wildcard resource
Resource = ["*"]
```

IAM role boundaries by function — do not expand these without a documented reason:

| Role | Permitted actions | Permitted resources |
|---|---|---|
| `api_lambda_role` | `dynamodb:GetItem`, `Query`, `Scan` | collections + images tables and their indexes |
| `api_lambda_role` | `s3:GetObject` | `*-imagenetog-*-images` buckets only |
| `api_lambda_role` | `bedrock:InvokeModel` | `amazon.titan-embed-image-v1` ARN only |
| `api_lambda_role` | `s3vectors:QueryVectors`, `GetVectors` | `*-imagenetog-*-vectors` buckets only |
| `ingestion_lambda_role` | `s3:GetObject` | `*-imagenetog-*-images` buckets only |
| `ingestion_lambda_role` | `bedrock:InvokeModel` | Titan Embed + Nova Lite ARNs only |
| `ingestion_lambda_role` | `s3vectors:PutVectors`, `CreateIndex` | `*-imagenetog-*-vectors` buckets only |
| `ingestion_lambda_role` | `dynamodb:PutItem` | images table only |
| `admin_role` | `s3:PutObject`, `CreateBucket` | `*-imagenetog-*-images` pattern only |

---

## S3 Bucket Security

All S3 buckets storing image files must be provisioned with:

```hcl
resource "aws_s3_bucket_public_access_block" "images" {
  bucket                  = aws_s3_bucket.images.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

No bucket policy may grant `s3:GetObject` to `"Principal": "*"`. Image access is exclusively via presigned URLs generated by the `api_lambda_role`.

---

## Data Privacy — Internal Field Filtering

The `s3_bucket` and `s3vector_bucket` fields stored in DynamoDB are internal infrastructure details. They must never appear in any API response body. This is enforced in the response-building layer, not by DynamoDB projection alone (projection is defence-in-depth).

```python
INTERNAL_FIELDS = frozenset({"s3_bucket", "s3vector_bucket"})

def to_public_collection(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in INTERNAL_FIELDS}
```

Apply `to_public_collection` / `to_public_image` transformations in the service layer before returning data to the route handler. Never return a raw DynamoDB item dict to the response builder.

---

## Error Response Safety

500 responses must never include:
- Python tracebacks
- Internal table names, bucket names, or ARNs
- Raw exception messages from boto3 (which often contain resource names)

The error middleware catches all bare `Exception` instances, logs the full traceback with `logger.exception(...)`, and returns only:

```json
{ "error": "server.error", "message": "An internal error occurred." }
```

Do not re-raise or propagate boto3 `ClientError` exceptions to the response layer without first mapping them to a domain `APIError` subclass.

```python
# CORRECT — map boto3 errors to domain errors
try:
    response = dynamodb_table.get_item(Key={"collection_name": name})
except ClientError as exc:
    logger.exception("DynamoDB get_item failed", collection_name=name)
    raise  # let the catch-all middleware return 500

if "Item" not in response:
    raise CollectionNotFoundError(name)

# WRONG — leaking boto3 error detail
except ClientError as exc:
    return {"error": str(exc)}  # ← may contain ARNs, table names, account IDs
```
