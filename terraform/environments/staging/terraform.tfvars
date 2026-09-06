# terraform.tfvars — staging environment

env                     = "staging"
aws_region              = "us-east-1"
lambda_memory_mb        = 512
api_gateway_rate_limit  = 100
api_gateway_burst_limit = 200
log_retention_days      = 30
