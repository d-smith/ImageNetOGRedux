---
inclusion: auto
name: terraform-conventions
description: Terraform conventions, module structure, naming rules, tagging, and state management for the ImageNetOG Redux project
---

# Terraform Conventions — ImageNetOG Redux

Applies to all files under `terraform/`.

---

## Version Pins

All provider and Terraform versions are pinned in `terraform/versions.tf`. Never use open-ended version constraints.

```hcl
terraform {
  required_version = ">= 1.7, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}
```

Modules inherit the provider from the root; do not declare `required_providers` inside modules.

---

## Directory Structure

```
terraform/
├── modules/
│   ├── api/          # API Gateway, api_handler Lambda, IAM, usage plan
│   ├── auth/         # Cognito User Pool + App Client
│   ├── ingestion/    # Step Functions, ingestion Lambdas, EventBridge
│   └── storage/      # DynamoDB tables
├── environments/
│   ├── dev/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── terraform.tfvars
│   ├── staging/
│   │   └── ...
│   └── prod/
│       └── ...
├── backend.tf
└── versions.tf
```

Each module directory contains only: `main.tf`, `variables.tf`, `outputs.tf`, and optionally named sub-files (e.g., `iam.tf`, `lambdas.tf`). No module contains a `backend.tf` or `versions.tf` — those live in the root only.

---

## Remote State

State is stored remotely. Local state (`terraform.tfstate` files in the repository) is never committed. Add `**/.terraform/` and `*.tfstate*` to `.gitignore`.

Backend configuration (`terraform/backend.tf`):

```hcl
terraform {
  backend "s3" {
    bucket         = "{account-id}-imagenetog-tfstate"
    key            = "${var.env}/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "imagenetog-tfstate-locks"
    encrypt        = true
  }
}
```

Each environment uses a distinct key (`dev/terraform.tfstate`, `staging/terraform.tfstate`, `prod/terraform.tfstate`). State files for different environments are never shared.

---

## Naming Convention

All resource names follow the pattern `{env}-imagenetog-{resource-descriptor}`, where `{env}` is one of `dev`, `staging`, `prod` and is passed in as the `var.env` variable.

| Resource | Name pattern |
|---|---|
| DynamoDB collections table | `{env}-imagenetog-collections` |
| DynamoDB images table | `{env}-imagenetog-images` |
| S3 image bucket (per collection) | `{env}-imagenetog-{collection_name}-images` |
| S3 Vector bucket (per collection) | `{env}-imagenetog-{collection_name}-vectors` |
| Lambda: API handler | `{env}-imagenetog-api-handler` |
| Lambda: ingestion embed | `{env}-imagenetog-ingestion-embed` |
| Lambda: ingestion describe | `{env}-imagenetog-ingestion-describe` |
| Lambda: ingestion store | `{env}-imagenetog-ingestion-store` |
| Step Functions state machine | `{env}-imagenetog-ingestion` |
| Cognito User Pool | `{env}-imagenetog-userpool` |
| IAM role: API Lambda | `{env}-imagenetog-api-lambda-role` |
| IAM role: ingestion Lambda | `{env}-imagenetog-ingestion-lambda-role` |
| IAM role: admin | `{env}-imagenetog-admin-role` |
| API Gateway REST API | `{env}-imagenetog-api` |
| CloudWatch log group | `/aws/lambda/{env}-imagenetog-{function-name}` |

Use `var.env` to construct names. Never hardcode environment strings inside module files.

```hcl
# CORRECT
resource "aws_dynamodb_table" "collections" {
  name = "${var.env}-imagenetog-collections"
}

# WRONG — hardcoded env
resource "aws_dynamodb_table" "collections" {
  name = "prod-imagenetog-collections"
}
```

---

## Required Tags

Every taggable AWS resource must include these tags:

```hcl
tags = {
  Project     = "imagenetog-redux"
  Environment = var.env
  ManagedBy   = "terraform"
}
```

Add a `local.common_tags` map at the root of each environment's `main.tf` and merge it into every resource's `tags` argument:

```hcl
locals {
  common_tags = {
    Project     = "imagenetog-redux"
    Environment = var.env
    ManagedBy   = "terraform"
  }
}
```

Module resources accept a `tags` variable and merge caller-supplied tags with their own:

```hcl
# In module variables.tf
variable "tags" {
  type    = map(string)
  default = {}
}

# In module main.tf
tags = merge(var.tags, { Component = "api" })
```

---

## No Hardcoded Account IDs or Regions

Never hardcode AWS account IDs or region strings in resource definitions. Use data sources:

```hcl
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Then reference as:
data.aws_caller_identity.current.account_id
data.aws_region.current.name
```

The region is always `us-east-1` for this project, enforced by the `aws` provider configuration in each environment's `main.tf`:

```hcl
provider "aws" {
  region = "us-east-1"
}
```

---

## Variable Definitions

Every module exposes an `env` variable and a `tags` variable at minimum.

```hcl
# modules/*/variables.tf
variable "env" {
  type        = string
  description = "Deployment environment (dev, staging, prod)"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.env)
    error_message = "env must be one of: dev, staging, prod"
  }
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Additional tags to merge onto all resources in this module"
}
```

Per-environment tunable values (Lambda memory, usage plan rate/burst) are declared in `environments/{env}/variables.tf` and set in `environments/{env}/terraform.tfvars`. They are passed explicitly to modules — modules do not read environment variables or use `locals` to derive env-specific defaults.

---

## IAM Policy Style

Write IAM policies using `jsonencode` in HCL, not as inline JSON strings or separate JSON files. This keeps policies readable and diff-friendly.

```hcl
# CORRECT
resource "aws_iam_policy" "api_dynamodb" {
  name   = "${var.env}-imagenetog-api-dynamodb"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"]
        Resource = [
          aws_dynamodb_table.collections.arn,
          aws_dynamodb_table.images.arn,
        ]
      }
    ]
  })
  tags = merge(var.tags, { Component = "api" })
}

# WRONG — JSON string
policy = "{\"Version\": \"2012-10-17\", ...}"
```

Attach policies to roles with `aws_iam_role_policy_attachment`, not inline `aws_iam_role_policy`. This keeps policies individually reusable and visible in the IAM console.

---

## Lambda Packaging

Lambda function source code is referenced via a `data "archive_file"` resource that zips the relevant `src/` subdirectory. The zip file is written to a `.build/` directory (gitignored).

```hcl
data "archive_file" "api_handler" {
  type        = "zip"
  source_dir  = "${path.root}/../../src/api_handler"
  output_path = "${path.root}/../../.build/api_handler.zip"
}

resource "aws_lambda_function" "api_handler" {
  filename         = data.archive_file.api_handler.output_path
  source_code_hash = data.archive_file.api_handler.output_base64sha256
  runtime          = "python3.12"
  handler          = "lambda_function.handler"
  ...
}
```

Always set `source_code_hash` so Terraform detects code changes and triggers redeployment.

---

## CloudWatch Log Groups

Explicitly provision `aws_cloudwatch_log_group` resources for every Lambda function. Do not rely on Lambda auto-creating log groups — explicit provisioning allows setting retention and tags.

```hcl
resource "aws_cloudwatch_log_group" "api_handler" {
  name              = "/aws/lambda/${aws_lambda_function.api_handler.function_name}"
  retention_in_days = 30
  tags              = merge(var.tags, { Component = "api" })
}
```

Set `retention_in_days = 30` for dev and staging; use a variable for prod (default 90).

---

## CI/CD Checks

The following must pass in CI for every pull request touching `terraform/`:

```bash
terraform fmt -check -recursive terraform/
terraform validate   # run per environment directory
```

`terraform plan` output is captured and attached to the PR as a comment. A plan exit code of `1` (error) blocks merge. A plan exit code of `2` (changes pending) is expected and does not block merge.

Never run `terraform apply` automatically on merge to main for the `prod` environment. Apply to `prod` requires manual approval.
