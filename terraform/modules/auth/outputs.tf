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

output "hosted_ui_domain" {
  description = "The Cognito hosted-UI domain prefix"
  value       = aws_cognito_user_pool_domain.hosted_ui.domain
}

output "hosted_ui_base_url" {
  description = "Base URL of the Cognito hosted UI (https://<domain>.auth.<region>.amazoncognito.com)"
  value       = "https://${aws_cognito_user_pool_domain.hosted_ui.domain}.auth.${data.aws_region.current.name}.amazoncognito.com"
}

output "hosted_ui_login_url" {
  description = "Ready-to-open hosted-UI authorize URL (authorization-code flow) for obtaining a token"
  value = join("", [
    "https://${aws_cognito_user_pool_domain.hosted_ui.domain}.auth.${data.aws_region.current.name}.amazoncognito.com/oauth2/authorize",
    "?client_id=${aws_cognito_user_pool_client.api.id}",
    "&response_type=code",
    "&scope=openid+email+profile",
    "&redirect_uri=https%3A%2F%2Flocalhost%3A3000%2Fcallback",
  ])
}
