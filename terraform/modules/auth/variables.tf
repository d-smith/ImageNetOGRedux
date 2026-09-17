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

variable "hosted_ui_domain_suffix" {
  type        = string
  default     = "auth"
  description = "Suffix appended to the {env}-imagenetog Cognito hosted-UI domain prefix. The full prefix ({env}-imagenetog-{suffix}) must be globally unique within the region."
}

variable "enable_user_password_auth" {
  type        = bool
  default     = false
  description = "Enable the ALLOW_USER_PASSWORD_AUTH flow on the app client. Convenient for dev/test token minting via `aws cognito-idp initiate-auth`, but weaker than SRP (the password transits to the service). Keep false in production."
}
