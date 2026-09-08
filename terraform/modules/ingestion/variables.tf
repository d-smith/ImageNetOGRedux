variable "env" {
  type        = string
  description = "Deployment environment (dev, staging, prod)"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.env)
    error_message = "env must be one of: dev, staging, prod"
  }
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Additional tags to merge onto all resources in this module"
}

variable "images_table_arn" {
  type        = string
  description = "ARN of the DynamoDB images table (from storage module)"
}

variable "images_table_name" {
  type        = string
  description = "Name of the DynamoDB images table (from storage module)"
}

variable "lambda_memory_mb" {
  type        = number
  default     = 512
  description = "Memory allocated to each ingestion Lambda function in MB"
}

variable "lambda_timeout_seconds" {
  type        = number
  default     = 300
  description = "Timeout in seconds for each ingestion Lambda function"
}

variable "log_retention_days" {
  type        = number
  default     = 30
  description = "CloudWatch log group retention in days"
}

variable "embed_model_id" {
  type        = string
  default     = "amazon.titan-embed-image-v1"
  description = "Bedrock model ID for image embedding (used to scope the InvokeModel IAM policy)"
}

variable "describe_model_id" {
  type        = string
  default     = "amazon.nova-lite-v1:0"
  description = "Bedrock model ID for image description (used to scope the InvokeModel IAM policy)"
}
