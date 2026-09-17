# ---------------------------------------------------------------------------
# API Gateway logging
#
# API Gateway requires an *account-level* IAM role to push execution and access
# logs to CloudWatch Logs (`aws_api_gateway_account.cloudwatch_role_arn`). This
# is a single account-wide setting; we manage a dedicated role for it here
# rather than relying on a role owned by another stack.
#
# NOTE: `aws_api_gateway_account` is an account-level singleton per region. In
# an account shared with other API Gateway stacks, applying this sets the shared
# CloudWatch role. That is intentional here (the previously-set role belonged to
# an unrelated stack); the AWS-managed push policy is functionally identical.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "apigw_cloudwatch" {
  name = "${local.name_prefix}-apigw-cloudwatch"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "apigateway.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = merge(var.tags, { Component = "api" })
}

# AWS-managed policy granting API Gateway the CloudWatch Logs actions it needs.
resource "aws_iam_role_policy_attachment" "apigw_cloudwatch" {
  role       = aws_iam_role.apigw_cloudwatch.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_account" "this" {
  cloudwatch_role_arn = aws_iam_role.apigw_cloudwatch.arn

  depends_on = [aws_iam_role_policy_attachment.apigw_cloudwatch]
}

# Access-log group for the stage (execution logs use the API-Gateway-managed
# `API-Gateway-Execution-Logs_<api-id>/<stage>` group automatically).
resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${local.name_prefix}-api/${local.stage_name}"
  retention_in_days = var.log_retention_days

  tags = merge(var.tags, { Component = "api" })
}
