# ---------------------------------------------------------------------------
# Ingestion Lambda functions
#
# Three functions orchestrated by the Step Functions state machine (see sfn.tf):
#   * ingestion_embed    — image → 1024-dim embedding → S3 Vectors
#   * ingestion_describe — image → natural-language description via Nova Lite
#   * ingestion_store    — write the assembled metadata record to DynamoDB
#
# All three share the single ingestion execution role (see iam.tf) and the same
# Python 3.12 source package (src/ingestion). The Step Functions state passes
# the target handler per function via the `handler` argument.
#
# `local.name_prefix`, the region data source, and the account-id data source
# are declared in iam.tf and shared across the module.
# ---------------------------------------------------------------------------

# Package the shared ingestion source directory once. Each function selects its
# entry point via its own `handler` attribute (embed.handler, etc.).
# Package the ``ingestion`` package so the zip contains a top-level
# ``ingestion/`` directory. The handlers import ``from ingestion import ...``,
# so the package (not its flattened contents) must be importable at runtime.
# We zip ``src/`` and exclude the other packages / build noise, then reference
# handlers by their dotted package path (e.g. ``ingestion.embed.handler``).
data "archive_file" "ingestion" {
  type        = "zip"
  source_dir  = "${path.module}/../../../src"
  output_path = "${path.module}/../../../.build/ingestion.zip"

  excludes = [
    "__init__.py",
    "api_handler",
    "scripts",
    "imagenetog_redux.egg-info",
  ]
}

locals {
  # Environment variables common to all ingestion functions. Names only — these
  # are configuration, never credentials (per security-patterns steering).
  ingestion_env = {
    IMAGES_TABLE            = var.images_table_name
    EMBED_MODEL_ID          = var.embed_model_id
    DESCRIBE_MODEL_ID       = var.describe_model_id
    POWERTOOLS_SERVICE_NAME = "${local.name_prefix}-ingestion"
  }

  # Function definitions: logical key → handler entry point.
  ingestion_functions = {
    embed = {
      name_suffix = "ingestion-embed"
      handler     = "ingestion.embed.handler"
    }
    describe = {
      name_suffix = "ingestion-describe"
      handler     = "ingestion.describe.handler"
    }
    store = {
      name_suffix = "ingestion-store"
      handler     = "ingestion.store.handler"
    }
  }
}

resource "aws_lambda_function" "ingestion" {
  for_each = local.ingestion_functions

  function_name = "${local.name_prefix}-${each.value.name_suffix}"
  role          = aws_iam_role.ingestion_lambda_role.arn

  filename         = data.archive_file.ingestion.output_path
  source_code_hash = data.archive_file.ingestion.output_base64sha256

  runtime     = "python3.12"
  handler     = each.value.handler
  memory_size = var.lambda_memory_mb
  timeout     = var.lambda_timeout_seconds
  layers      = [var.layer_arn]

  environment {
    variables = local.ingestion_env
  }

  tags = merge(var.tags, {
    Component = "ingestion"
    Function  = each.value.name_suffix
  })

  # Ensure the log group exists before the function so Lambda does not race to
  # auto-create it (which would prevent our explicit retention/tags settings).
  depends_on = [aws_cloudwatch_log_group.ingestion]
}

# ---------------------------------------------------------------------------
# CloudWatch log groups — explicitly provisioned for retention + tags.
# Naming matches the Lambda auto-created convention: /aws/lambda/<function>.
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "ingestion" {
  for_each = local.ingestion_functions

  name              = "/aws/lambda/${local.name_prefix}-${each.value.name_suffix}"
  retention_in_days = var.log_retention_days

  tags = merge(var.tags, {
    Component = "ingestion"
    Function  = each.value.name_suffix
  })
}
