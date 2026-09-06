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

variable "token_validity_hours" {
  type        = number
  default     = 1
  description = "Access token validity in hours"
}

variable "refresh_token_validity_days" {
  type        = number
  default     = 30
  description = "Refresh token validity in days"
}
