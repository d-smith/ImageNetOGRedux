locals {
  name_prefix = "${var.env}-imagenetog"
}

# ---------------------------------------------------------------------------
# Cognito User Pool
# ---------------------------------------------------------------------------
resource "aws_cognito_user_pool" "main" {
  name = "${local.name_prefix}-userpool"

  # Require email verification on sign-up
  auto_verified_attributes = ["email"]

  # Username is the email address
  username_attributes = ["email"]

  # Strong password policy
  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  # Account recovery by verified email only
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # MFA is optional at the pool level; enforced per-app-client via lambda trigger if needed
  mfa_configuration = "OFF"

  # Schema attributes — email is required by default; we add no custom attributes for now
  schema {
    attribute_data_type      = "String"
    name                     = "email"
    required                 = true
    mutable                  = true
    developer_only_attribute = false
    string_attribute_constraints {
      min_length = 3
      max_length = 254
    }
  }

  tags = merge(var.tags, { Component = "auth" })
}

# ---------------------------------------------------------------------------
# Cognito User Pool App Client
# Clients cannot read back the client secret; this is a public client used
# by API consumers obtaining tokens via the hosted UI or SDK flows.
# ---------------------------------------------------------------------------
resource "aws_cognito_user_pool_client" "api" {
  name         = "${local.name_prefix}-api-client"
  user_pool_id = aws_cognito_user_pool.main.id

  # No client secret — public client
  generate_secret = false

  # Allowed OAuth flows — authorization_code only; implicit flow is disabled for security
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  # Callback / logout URLs — override per-environment if needed via tfvars
  # Placeholders acceptable here; they are updated by the environment root module
  callback_urls = ["https://localhost:3000/callback"]
  logout_urls   = ["https://localhost:3000/logout"]

  # Token validity
  access_token_validity  = var.token_validity_hours
  id_token_validity      = var.token_validity_hours
  refresh_token_validity = var.refresh_token_validity_days

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  # Prevent user existence errors from leaking during auth
  prevent_user_existence_errors = "ENABLED"

  # Read/write attributes — grant access to standard Cognito email attributes
  read_attributes  = ["email", "email_verified"]
  write_attributes = ["email"]

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]
}
