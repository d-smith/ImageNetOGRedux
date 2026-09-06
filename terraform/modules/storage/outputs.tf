output "collections_table_name" {
  description = "Name of the DynamoDB collections table"
  value       = aws_dynamodb_table.collections.name
}

output "collections_table_arn" {
  description = "ARN of the DynamoDB collections table"
  value       = aws_dynamodb_table.collections.arn
}

output "images_table_name" {
  description = "Name of the DynamoDB images table"
  value       = aws_dynamodb_table.images.name
}

output "images_table_arn" {
  description = "ARN of the DynamoDB images table"
  value       = aws_dynamodb_table.images.arn
}
