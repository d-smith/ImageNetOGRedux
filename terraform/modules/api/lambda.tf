# ---------------------------------------------------------------------------
# API handler Lambda function (task 6.2)
#
# A single Python 3.12 function fronted by API Gateway (see apigw.tf) using the
# AWS_PROXY integration. Business logic lives in src/api_handler; this function
# is the sole compute for all four read routes.
#
# `local.name_prefix`, the region data source, and the account-id data source
# are declared in iam.tf and shared across the module.
# ---------------------------------------------------------------------------

# Package the API handler source directory. path.root-relative to match the
# ingestion module packaging convention.
data "archive_file" "api_handler" {
  type        = "zip"
  source_dir  = "${path.root}/../../src/api_handler"
  output_path = "${path.root}/../../.build/api_handler.zip"
}

resource "aws_lambda_function" "api_handler" {
  function_name = "${local.name_prefix}-api-handler"
  role          = aws_iam_role.api_lambda_role.arn

  filename         = data.archive_file.api_handler.output_path
  source_code_hash = data.archive_file.api_handler.output_base64sha256

  runtime     = "python3.12"
  handler     = "lambda_function.handler"
  memory_size = var.lambda_memory_mb
  timeout     = var.lambda_timeout_seconds

  environment {
    # Names only — configuration, never credentials (per security-patterns).
    variables = {
      COLLECTIONS_TABLE         = var.collections_table_name
      IMAGES_TABLE              = var.images_table_name
      COGNITO_USER_POOL_ID      = var.cognito_user_pool_id
      EMBED_MODEL_ID            = var.embed_model_id
      PRESIGNED_URL_TTL_SECONDS = tostring(var.presigned_url_ttl_seconds)
      POWERTOOLS_SERVICE_NAME   = "${local.name_prefix}-api-handler"
    }
  }

  tags = merge(var.tags, { Component = "api" })

  # Ensure the log group exists before the function so Lambda does not race to
  # auto-create it (which would prevent our explicit retention/tags settings).
  depends_on = [aws_cloudwatch_log_group.api_handler]
}

# ---------------------------------------------------------------------------
# CloudWatch log group — explicitly provisioned for retention + tags.
# Naming matches the Lambda auto-created convention: /aws/lambda/<function>.
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "api_handler" {
  name              = "/aws/lambda/${local.name_prefix}-api-handler"
  retention_in_days = var.log_retention_days

  tags = merge(var.tags, { Component = "api" })
}
