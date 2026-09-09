data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  region      = data.aws_region.current.name
  name_prefix = "${var.env}-imagenetog"
}

# ---------------------------------------------------------------------------
# API Lambda execution role
# ---------------------------------------------------------------------------
resource "aws_iam_role" "api_lambda_role" {
  name = "${local.name_prefix}-api-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = merge(var.tags, { Component = "api" })
}

# Basic Lambda execution — CloudWatch Logs.
resource "aws_iam_role_policy_attachment" "api_lambda_basic" {
  role       = aws_iam_role.api_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ---------------------------------------------------------------------------
# DynamoDB read — collections + images tables and their indexes only.
# ---------------------------------------------------------------------------
resource "aws_iam_policy" "api_dynamodb_read" {
  name        = "${local.name_prefix}-api-dynamodb-read"
  description = "Allow the API Lambda to read collection and image metadata"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadMetadataTables"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan",
        ]
        Resource = [
          var.collections_table_arn,
          "${var.collections_table_arn}/index/*",
          var.images_table_arn,
          "${var.images_table_arn}/index/*",
        ]
      }
    ]
  })

  tags = merge(var.tags, { Component = "api" })
}

resource "aws_iam_role_policy_attachment" "api_dynamodb_read" {
  role       = aws_iam_role.api_lambda_role.name
  policy_arn = aws_iam_policy.api_dynamodb_read.arn
}

# ---------------------------------------------------------------------------
# S3 read — presigned URL generation for collection image buckets only.
# ---------------------------------------------------------------------------
resource "aws_iam_policy" "api_s3_read" {
  name        = "${local.name_prefix}-api-s3-read"
  description = "Allow the API Lambda to read image objects for presigned URL generation"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadImageBuckets"
        Effect = "Allow"
        Action = ["s3:GetObject"]
        Resource = [
          "arn:aws:s3:::${local.name_prefix}-*-images/*",
        ]
      }
    ]
  })

  tags = merge(var.tags, { Component = "api" })
}

resource "aws_iam_role_policy_attachment" "api_s3_read" {
  role       = aws_iam_role.api_lambda_role.name
  policy_arn = aws_iam_policy.api_s3_read.arn
}

# ---------------------------------------------------------------------------
# Bedrock InvokeModel — Titan Embed only (for description vector search).
# ---------------------------------------------------------------------------
resource "aws_iam_policy" "api_bedrock" {
  name        = "${local.name_prefix}-api-bedrock"
  description = "Allow the API Lambda to invoke Titan Embed for description search"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokeEmbedModel"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = ["arn:aws:bedrock:${local.region}::foundation-model/${var.embed_model_id}"]
      }
    ]
  })

  tags = merge(var.tags, { Component = "api" })
}

resource "aws_iam_role_policy_attachment" "api_bedrock" {
  role       = aws_iam_role.api_lambda_role.name
  policy_arn = aws_iam_policy.api_bedrock.arn
}

# ---------------------------------------------------------------------------
# S3 Vectors read — query and fetch vectors from collection vector buckets.
# S3 Vectors scopes at the vector-bucket resource; we restrict to the
# {env}-imagenetog-*-vectors naming pattern for this environment.
# ---------------------------------------------------------------------------
resource "aws_iam_policy" "api_s3vectors_read" {
  name        = "${local.name_prefix}-api-s3vectors-read"
  description = "Allow the API Lambda to query and fetch vectors from collection vector buckets"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "QueryCollectionVectors"
        Effect = "Allow"
        Action = [
          "s3vectors:QueryVectors",
          "s3vectors:GetVectors",
        ]
        Resource = [
          "arn:aws:s3vectors:${local.region}:${local.account_id}:bucket/${local.name_prefix}-*-vectors",
          "arn:aws:s3vectors:${local.region}:${local.account_id}:bucket/${local.name_prefix}-*-vectors/index/*",
        ]
      }
    ]
  })

  tags = merge(var.tags, { Component = "api" })
}

resource "aws_iam_role_policy_attachment" "api_s3vectors_read" {
  role       = aws_iam_role.api_lambda_role.name
  policy_arn = aws_iam_policy.api_s3vectors_read.arn
}
