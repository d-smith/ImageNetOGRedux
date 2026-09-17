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
  description = "Base invoke URL of the deployed API, including the /v1 path prefix (e.g. https://<id>.execute-api.<region>.amazonaws.com/<stage>/v1). Append resource paths like /collections directly."
  value       = "${aws_api_gateway_stage.api.invoke_url}/v1"
}

output "authorizer_id" {
  description = "ID of the Cognito User Pools API Gateway authorizer"
  value       = aws_api_gateway_authorizer.cognito.id
}

output "api_execution_log_group" {
  description = "CloudWatch Logs group for API Gateway execution logs (per-request authorizer decisions)"
  value       = "API-Gateway-Execution-Logs_${aws_api_gateway_rest_api.api.id}/${local.stage_name}"
}

output "api_access_log_group" {
  description = "CloudWatch Logs group for API Gateway access logs"
  value       = aws_cloudwatch_log_group.api_access.name
}
