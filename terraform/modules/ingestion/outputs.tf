output "ingestion_lambda_role_arn" {
  description = "ARN of the ingestion Lambda IAM execution role"
  value       = aws_iam_role.ingestion_lambda_role.arn
}

output "ingestion_lambda_role_name" {
  description = "Name of the ingestion Lambda IAM execution role"
  value       = aws_iam_role.ingestion_lambda_role.name
}
