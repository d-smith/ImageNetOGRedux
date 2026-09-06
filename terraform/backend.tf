# Partial backend configuration — bucket, key, and dynamodb_table are intentionally
# omitted here because the S3 backend does not support variable interpolation, and
# each environment uses a distinct state key.
#
# Supply the remaining values at init time using a per-environment backend config:
#
#   terraform -chdir=environments/dev init \
#     -backend-config=backend.config
#
# See terraform/environments/{dev,staging,prod}/backend.config for the per-environment
# values.  The config files use the placeholder "REPLACE_WITH_ACCOUNT_ID" for the
# bucket name — substitute your AWS account ID before running terraform init.

terraform {
  backend "s3" {
    region  = "us-east-1"
    encrypt = true
  }
}
