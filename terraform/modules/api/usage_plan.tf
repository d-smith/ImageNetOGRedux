# ---------------------------------------------------------------------------
# API Gateway usage plan (task 6.4)
#
# Account-level throttling for the deployed API stage. No API keys are attached
# — this plan enforces steady-state rate and burst limits across all callers.
# The THROTTLED (429) gateway response that surfaces limit breaches to clients
# is defined in apigw.tf.
# ---------------------------------------------------------------------------

resource "aws_api_gateway_usage_plan" "api" {
  name = "${local.name_prefix}-usage-plan"

  api_stages {
    api_id = aws_api_gateway_rest_api.api.id
    stage  = aws_api_gateway_stage.api.stage_name
  }

  throttle_settings {
    rate_limit  = var.api_gateway_rate_limit
    burst_limit = var.api_gateway_burst_limit
  }

  tags = merge(var.tags, { Component = "api" })
}
