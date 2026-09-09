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

variable "collections_table_arn" {
  type        = string
  description = "ARN of the DynamoDB collections table (from storage module)"
}

variable "images_table_arn" {
  type        = string
  description = "ARN of the DynamoDB images table (from storage module)"
}

variable "embed_model_id" {
  type        = string
  default     = "amazon.titan-embed-image-v1"
  description = "Bedrock model ID for text embedding (used to scope the InvokeModel IAM policy)"
}
