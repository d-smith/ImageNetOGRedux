output "user_pool_id" {
  description = "The ID of the Cognito User Pool"
  value       = aws_cognito_user_pool.main.id
}

output "user_pool_arn" {
  description = "The ARN of the Cognito User Pool"
  value       = aws_cognito_user_pool.main.arn
}

output "user_pool_endpoint" {
  description = "The endpoint URL of the Cognito User Pool (issuer URL for JWT validation)"
  value       = aws_cognito_user_pool.main.endpoint
}

output "app_client_id" {
  description = "The app client ID for the API consumer"
  value       = aws_cognito_user_pool_client.api.id
}
