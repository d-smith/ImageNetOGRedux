# ---------------------------------------------------------------------------
# Dev environment outputs (task 7.1)
# ---------------------------------------------------------------------------

output "api_invoke_url" {
  description = "Invoke URL of the deployed API Gateway stage"
  value       = module.api.api_invoke_url
}

output "rest_api_id" {
  description = "ID of the API Gateway REST API"
  value       = module.api.rest_api_id
}

output "user_pool_id" {
  description = "ID of the Cognito User Pool"
  value       = module.auth.user_pool_id
}

output "admin_role_arn" {
  description = "ARN of the admin IAM role"
  value       = aws_iam_role.admin_role.arn
}
