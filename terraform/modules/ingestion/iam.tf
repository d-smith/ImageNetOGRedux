data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  region      = data.aws_region.current.name
  name_prefix = "${var.env}-imagenetog"
}

# ---------------------------------------------------------------------------
# Ingestion Lambda execution role
# ---------------------------------------------------------------------------
resource "aws_iam_role" "ingestion_lambda_role" {
  name = "${local.name_prefix}-ingestion-lambda-role"

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

  tags = merge(var.tags, { Component = "ingestion" })
}

# ---------------------------------------------------------------------------
# Basic Lambda execution — CloudWatch Logs
# Attach AWS managed policy so Lambda can write logs.
# ---------------------------------------------------------------------------
resource "aws_iam_role_policy_attachment" "ingestion_lambda_basic" {
  role       = aws_iam_role.ingestion_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ---------------------------------------------------------------------------
# S3 read — image buckets only
# Pattern: {env}-imagenetog-*-images  (any collection name)
# ---------------------------------------------------------------------------
resource "aws_iam_policy" "ingestion_s3_read" {
  name        = "${local.name_prefix}-ingestion-s3-read"
  description = "Allow ingestion Lambdas to read raw images from collection S3 buckets"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadImageBuckets"
        Effect = "Allow"
        Action = ["s3:GetObject"]
        Resource = [
          # Objects inside any collection image bucket for this environment
          "arn:aws:s3:::${local.name_prefix}-*-images/*",
        ]
      }
    ]
  })

  tags = merge(var.tags, { Component = "ingestion" })
}

resource "aws_iam_role_policy_attachment" "ingestion_s3_read" {
  role       = aws_iam_role.ingestion_lambda_role.name
  policy_arn = aws_iam_policy.ingestion_s3_read.arn
}

# ---------------------------------------------------------------------------
# Bedrock InvokeModel — Titan Embed + Nova Lite only
# ---------------------------------------------------------------------------
resource "aws_iam_policy" "ingestion_bedrock" {
  name        = "${local.name_prefix}-ingestion-bedrock"
  description = "Allow ingestion Lambdas to invoke Titan Embed and Nova Lite via Bedrock"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "InvokeEmbedAndDescribeModels"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = [
          # Amazon Titan Multimodal Embeddings G1 (embedding model)
          "arn:aws:bedrock:${local.region}::foundation-model/amazon.titan-embed-image-v1",
          # Amazon Nova Lite (description model)
          "arn:aws:bedrock:${local.region}::foundation-model/amazon.nova-lite-v1:0",
        ]
      }
    ]
  })

  tags = merge(var.tags, { Component = "ingestion" })
}

resource "aws_iam_role_policy_attachment" "ingestion_bedrock" {
  role       = aws_iam_role.ingestion_lambda_role.name
  policy_arn = aws_iam_policy.ingestion_bedrock.arn
}

# ---------------------------------------------------------------------------
# S3 Vectors — write vectors to collection vector buckets only
# S3 Vectors does not support resource-level ARN scoping for PutVectors /
# CreateIndex at the individual index level; the resource is the vector bucket.
# We scope to the naming pattern for this environment.
# ---------------------------------------------------------------------------
resource "aws_iam_policy" "ingestion_s3vectors_write" {
  name        = "${local.name_prefix}-ingestion-s3vectors-write"
  description = "Allow ingestion Lambdas to put vectors and create indexes in collection vector buckets"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "WriteCollectionVectors"
        Effect = "Allow"
        Action = [
          "s3vectors:PutVectors",
          "s3vectors:CreateIndex",
        ]
        # S3 Vectors ARN format: arn:aws:s3vectors:{region}:{account}:bucket/{bucket-name}
        Resource = [
          "arn:aws:s3vectors:${local.region}:${local.account_id}:bucket/${local.name_prefix}-*-vectors",
          "arn:aws:s3vectors:${local.region}:${local.account_id}:bucket/${local.name_prefix}-*-vectors/index/*",
        ]
      }
    ]
  })

  tags = merge(var.tags, { Component = "ingestion" })
}

resource "aws_iam_role_policy_attachment" "ingestion_s3vectors_write" {
  role       = aws_iam_role.ingestion_lambda_role.name
  policy_arn = aws_iam_policy.ingestion_s3vectors_write.arn
}

# ---------------------------------------------------------------------------
# DynamoDB — write image records to the images table only
# ---------------------------------------------------------------------------
resource "aws_iam_policy" "ingestion_dynamodb_write" {
  name        = "${local.name_prefix}-ingestion-dynamodb-write"
  description = "Allow ingestion Lambdas to write image metadata records to the images table"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "WriteImagesTable"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = [var.images_table_arn]
      }
    ]
  })

  tags = merge(var.tags, { Component = "ingestion" })
}

resource "aws_iam_role_policy_attachment" "ingestion_dynamodb_write" {
  role       = aws_iam_role.ingestion_lambda_role.name
  policy_arn = aws_iam_policy.ingestion_dynamodb_write.arn
}
