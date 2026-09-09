output "api_lambda_role_arn" {
  description = "ARN of the API Lambda IAM execution role"
  value       = aws_iam_role.api_lambda_role.arn
}

output "api_lambda_role_name" {
  description = "Name of the API Lambda IAM execution role"
  value       = aws_iam_role.api_lambda_role.name
}
