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

variable "billing_mode" {
  type        = string
  default     = "PAY_PER_REQUEST"
  description = "DynamoDB billing mode: PAY_PER_REQUEST or PROVISIONED"
  validation {
    condition     = contains(["PAY_PER_REQUEST", "PROVISIONED"], var.billing_mode)
    error_message = "billing_mode must be PAY_PER_REQUEST or PROVISIONED"
  }
}
