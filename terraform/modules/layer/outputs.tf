output "layer_arn" {
  description = "ARN (with version) of the shared dependencies Lambda layer"
  value       = aws_lambda_layer_version.deps.arn
}
