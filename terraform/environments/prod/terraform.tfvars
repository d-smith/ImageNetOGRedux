# terraform.tfvars — prod environment

env                     = "prod"
aws_region              = "us-east-1"
lambda_memory_mb        = 1024
api_gateway_rate_limit  = 10
api_gateway_burst_limit = 20
log_retention_days      = 7
