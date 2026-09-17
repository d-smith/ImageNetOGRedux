# ---------------------------------------------------------------------------
# Prod environment outputs (task 7.2)
# ---------------------------------------------------------------------------

output "api_invoke_url" {
  description = "Invoke URL of the deployed API Gateway stage"
  value       = module.api.api_invoke_url
}

output "rest_api_id" {
  description = "ID of the API Gateway REST API"
  value       = module.api.rest_api_id
}

output "api_execution_log_group" {
  description = "CloudWatch Logs group for API Gateway execution logs (per-request authorizer decisions)"
  value       = module.api.api_execution_log_group
}

output "api_access_log_group" {
  description = "CloudWatch Logs group for API Gateway access logs"
  value       = module.api.api_access_log_group
}

output "user_pool_id" {
  description = "ID of the Cognito User Pool"
  value       = module.auth.user_pool_id
}

output "admin_role_arn" {
  description = "ARN of the admin IAM role"
  value       = aws_iam_role.admin_role.arn
}

output "app_client_id" {
  description = "Cognito User Pool App Client ID (for obtaining tokens)"
  value       = module.auth.app_client_id
}

output "hosted_ui_domain" {
  description = "Cognito hosted-UI domain prefix"
  value       = module.auth.hosted_ui_domain
}

output "hosted_ui_login_url" {
  description = "Ready-to-open Cognito hosted-UI authorize URL (authorization-code flow) for obtaining a token"
  value       = module.auth.hosted_ui_login_url
}
