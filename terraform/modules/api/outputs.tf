output "api_lambda_role_arn" {
  description = "ARN of the API Lambda IAM execution role"
  value       = aws_iam_role.api_lambda_role.arn
}

output "api_lambda_role_name" {
  description = "Name of the API Lambda IAM execution role"
  value       = aws_iam_role.api_lambda_role.name
}

output "api_handler_function_name" {
  description = "Name of the API handler Lambda function"
  value       = aws_lambda_function.api_handler.function_name
}

output "api_handler_function_arn" {
  description = "ARN of the API handler Lambda function"
  value       = aws_lambda_function.api_handler.arn
}

output "rest_api_id" {
  description = "ID of the API Gateway REST API"
  value       = aws_api_gateway_rest_api.api.id
}

output "api_invoke_url" {
  description = "Invoke URL of the deployed API Gateway stage"
  value       = aws_api_gateway_stage.api.invoke_url
}

output "authorizer_id" {
  description = "ID of the Cognito User Pools API Gateway authorizer"
  value       = aws_api_gateway_authorizer.cognito.id
}
