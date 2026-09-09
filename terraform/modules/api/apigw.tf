# ---------------------------------------------------------------------------
# API Gateway REST API (task 6.3)
#
# A regional REST API fronting the api_handler Lambda via AWS_PROXY integration.
# All four read routes are Cognito-authorized (COGNITO_USER_POOLS). Gateway
# Responses for UNAUTHORIZED (401) and THROTTLED (429) return structured JSON
# matching the API's error contract.
#
# Route tree:
#   /v1
#     /collections                                 GET
#       /{collection_name}                         GET
#         /images                                  GET
#           /{image_key}                           GET
#
# `local.name_prefix`, the region data source, and the account-id data source
# are declared in iam.tf and shared across the module.
# ---------------------------------------------------------------------------

resource "aws_api_gateway_rest_api" "api" {
  name        = "${local.name_prefix}-api"
  description = "ImageNetOG Redux read API (${var.env})"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = merge(var.tags, { Component = "api" })
}

# ---------------------------------------------------------------------------
# Cognito User Pools authorizer (300s result cache).
# ---------------------------------------------------------------------------
resource "aws_api_gateway_authorizer" "cognito" {
  name                             = "${local.name_prefix}-cognito-authorizer"
  rest_api_id                      = aws_api_gateway_rest_api.api.id
  type                             = "COGNITO_USER_POOLS"
  provider_arns                    = [var.cognito_user_pool_arn]
  identity_source                  = "method.request.header.Authorization"
  authorizer_result_ttl_in_seconds = 300
}

# ---------------------------------------------------------------------------
# Resource tree
# ---------------------------------------------------------------------------
resource "aws_api_gateway_resource" "v1" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "v1"
}

resource "aws_api_gateway_resource" "collections" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.v1.id
  path_part   = "collections"
}

resource "aws_api_gateway_resource" "collection" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.collections.id
  path_part   = "{collection_name}"
}

resource "aws_api_gateway_resource" "images" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.collection.id
  path_part   = "images"
}

resource "aws_api_gateway_resource" "image" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.images.id
  path_part   = "{image_key}"
}

# ---------------------------------------------------------------------------
# Methods + integrations for each route.
#
# Each of the four routes is a Cognito-authorized GET wired to the api_handler
# Lambda through an AWS_PROXY integration. Defined via for_each over the four
# resource IDs to keep the four near-identical route definitions DRY.
# ---------------------------------------------------------------------------
locals {
  api_routes = {
    collections = aws_api_gateway_resource.collections.id
    collection  = aws_api_gateway_resource.collection.id
    images      = aws_api_gateway_resource.images.id
    image       = aws_api_gateway_resource.image.id
  }
}

resource "aws_api_gateway_method" "get" {
  for_each = local.api_routes

  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = each.value
  http_method   = "GET"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "get" {
  for_each = local.api_routes

  rest_api_id = aws_api_gateway_rest_api.api.id
  resource_id = each.value
  http_method = aws_api_gateway_method.get[each.key].http_method

  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = aws_lambda_function.api_handler.invoke_arn
}

# ---------------------------------------------------------------------------
# Lambda invoke permission for API Gateway.
# ---------------------------------------------------------------------------
resource "aws_lambda_permission" "apigw_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_handler.function_name
  principal     = "apigateway.amazonaws.com"

  # Restrict to this REST API (any method/resource under it).
  source_arn = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# Deployment + stage.
#
# The deployment is recreated whenever the API configuration changes, tracked
# via a redeployment trigger hashing the route/integration/authorizer config.
# ---------------------------------------------------------------------------
resource "aws_api_gateway_deployment" "api" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_authorizer.cognito.id,
      [for k in sort(keys(local.api_routes)) : local.api_routes[k]],
      [for k in sort(keys(local.api_routes)) : aws_api_gateway_method.get[k].id],
      [for k in sort(keys(local.api_routes)) : aws_api_gateway_integration.get[k].id],
      aws_api_gateway_gateway_response.unauthorized.id,
      aws_api_gateway_gateway_response.throttled.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.get,
    aws_api_gateway_gateway_response.unauthorized,
    aws_api_gateway_gateway_response.throttled,
  ]
}

resource "aws_api_gateway_stage" "api" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  deployment_id = aws_api_gateway_deployment.api.id
  stage_name    = var.api_stage_name

  tags = merge(var.tags, { Component = "api" })
}

# ---------------------------------------------------------------------------
# Gateway Responses — structured JSON for auth + throttle failures so callers
# receive the same {"error": ..., "message": ...} contract the Lambda emits.
# ---------------------------------------------------------------------------
resource "aws_api_gateway_gateway_response" "unauthorized" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  response_type = "UNAUTHORIZED"
  status_code   = "401"

  response_parameters = {
    "gatewayresponse.header.Content-Type" = "'application/json'"
  }

  response_templates = {
    "application/json" = jsonencode({
      error   = "auth.unauthorized"
      message = "Authentication is required to access this resource."
    })
  }
}

resource "aws_api_gateway_gateway_response" "throttled" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  response_type = "THROTTLED"
  status_code   = "429"

  response_parameters = {
    "gatewayresponse.header.Content-Type" = "'application/json'"
  }

  response_templates = {
    "application/json" = jsonencode({
      error   = "rate_limit.exceeded"
      message = "Request rate limit exceeded. Please retry later."
    })
  }
}
