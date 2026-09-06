variable "env" {
  type        = string
  description = "Deployment environment (dev, staging, prod)"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.env)
    error_message = "env must be one of: dev, staging, prod"
  }
}

variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region for all resources"
}

variable "lambda_memory_mb" {
  type        = number
  default     = 1024
  description = "Memory allocated to each Lambda function in MB"
}

variable "api_gateway_rate_limit" {
  type        = number
  default     = 500
  description = "Steady-state requests per second for the API Gateway usage plan"
}

variable "api_gateway_burst_limit" {
  type        = number
  default     = 1000
  description = "Maximum burst requests for the API Gateway usage plan"
}

variable "log_retention_days" {
  type        = number
  default     = 90
  description = "CloudWatch log group retention in days"
}
