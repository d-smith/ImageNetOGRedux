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
# values. The state bucket and DynamoDB lock table named in those files must be
# created once, out-of-band, before the first `terraform init` (Terraform cannot
# manage the backend it depends on). See the "Bootstrap the Terraform backend"
# section in README.md. If the default bucket name (`imagenetog-redux-tfstate`) is
# not globally unique in your account, choose an account-scoped name and update
# every backend.config to match.

terraform {
  backend "s3" {
    region  = "us-east-1"
    encrypt = true
  }
}
