# ---------------------------------------------------------------------------
# Dev environment root module (task 7.1)
#
# Wires the four infrastructure modules — auth, storage, ingestion, api — and
# provisions the admin IAM role used for bucket/vector-bucket provisioning and
# collection registration.
#
# environments/dev is its own Terraform root (distinct from terraform/), so it
# declares its own terraform block, provider, and S3 backend. Backend values
# are supplied at init time via -backend-config=backend.config.
# ---------------------------------------------------------------------------

terraform {
  required_version = ">= 1.7, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  backend "s3" {}
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name

  common_tags = {
    Project     = "imagenetog-redux"
    Environment = var.env
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------
module "auth" {
  source = "../../modules/auth"

  env  = var.env
  tags = local.common_tags
}

module "storage" {
  source = "../../modules/storage"

  env  = var.env
  tags = local.common_tags
}

module "ingestion" {
  source = "../../modules/ingestion"

  env                = var.env
  tags               = local.common_tags
  images_table_arn   = module.storage.images_table_arn
  images_table_name  = module.storage.images_table_name
  lambda_memory_mb   = var.lambda_memory_mb
  log_retention_days = var.log_retention_days
}

module "api" {
  source = "../../modules/api"

  env                     = var.env
  tags                    = local.common_tags
  collections_table_arn   = module.storage.collections_table_arn
  images_table_arn        = module.storage.images_table_arn
  collections_table_name  = module.storage.collections_table_name
  images_table_name       = module.storage.images_table_name
  cognito_user_pool_id    = module.auth.user_pool_id
  cognito_user_pool_arn   = module.auth.user_pool_arn
  lambda_memory_mb        = var.lambda_memory_mb
  log_retention_days      = var.log_retention_days
  api_gateway_rate_limit  = var.api_gateway_rate_limit
  api_gateway_burst_limit = var.api_gateway_burst_limit
}

# ---------------------------------------------------------------------------
# Admin role
#
# Assumable by principals in this AWS account. Grants the narrow set of
# provisioning permissions required to create per-collection image buckets,
# create vector buckets/indexes, and register collections in DynamoDB.
# Scoped to the {env}-imagenetog-* naming pattern per security-patterns.md.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "admin_role" {
  name = "${var.env}-imagenetog-admin-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_policy" "admin" {
  name        = "${var.env}-imagenetog-admin"
  description = "Provisioning permissions for image buckets, vector buckets, and collection registration"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ProvisionImageBuckets"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket",
          "s3:PutObject",
        ]
        Resource = [
          "arn:aws:s3:::${var.env}-imagenetog-*-images",
          "arn:aws:s3:::${var.env}-imagenetog-*-images/*",
        ]
      },
      {
        Sid    = "ProvisionVectorBuckets"
        Effect = "Allow"
        Action = [
          "s3vectors:CreateVectorBucket",
          "s3vectors:CreateIndex",
        ]
        Resource = [
          "arn:aws:s3vectors:${local.region}:${local.account_id}:bucket/${var.env}-imagenetog-*-vectors",
          "arn:aws:s3vectors:${local.region}:${local.account_id}:bucket/${var.env}-imagenetog-*-vectors/index/*",
        ]
      },
      {
        Sid      = "RegisterCollections"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = [module.storage.collections_table_arn]
      },
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "admin" {
  role       = aws_iam_role.admin_role.name
  policy_arn = aws_iam_policy.admin.arn
}
