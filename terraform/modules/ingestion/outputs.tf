output "ingestion_lambda_role_arn" {
  description = "ARN of the ingestion Lambda IAM execution role"
  value       = aws_iam_role.ingestion_lambda_role.arn
}

output "ingestion_lambda_role_name" {
  description = "Name of the ingestion Lambda IAM execution role"
  value       = aws_iam_role.ingestion_lambda_role.name
}

output "state_machine_arn" {
  description = "ARN of the ingestion Step Functions state machine"
  value       = aws_sfn_state_machine.ingestion.arn
}

output "state_machine_name" {
  description = "Name of the ingestion Step Functions state machine"
  value       = aws_sfn_state_machine.ingestion.name
}

output "ingestion_function_arns" {
  description = "Map of ingestion Lambda function keys to their ARNs"
  value       = { for k, fn in aws_lambda_function.ingestion : k => fn.arn }
}

output "event_rule_name" {
  description = "Name of the EventBridge rule that triggers ingestion"
  value       = aws_cloudwatch_event_rule.ingestion_object_created.name
}
