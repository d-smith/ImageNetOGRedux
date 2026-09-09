# ---------------------------------------------------------------------------
# EventBridge — S3 ObjectCreated → Step Functions ingestion workflow
#
# When an image is uploaded to any collection image bucket
# ({env}-imagenetog-*-images), EventBridge starts an execution of the ingestion
# state machine.
#
# Prerequisite: each collection image bucket must have EventBridge
# notifications enabled (`aws_s3_bucket_notification { eventbridge = true }`).
# Buckets are provisioned per-collection by the admin script (task 21), which
# is responsible for enabling that setting. This module only defines the rule
# and target.
#
# Input mapping note: an S3 ObjectCreated event carries the bucket name and
# object key, but NOT the derived fields the state machine needs
# (s3vector_bucket, date_added, date_added_epoch). The input transformer below
# supplies bucket + key + collection_name (parsed from the bucket name); the
# derived fields are computed by the embed/describe/store Lambdas at runtime
# from the event and the current date. See design.md "Ingestion Flow".
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "ingestion_object_created" {
  name        = "${local.name_prefix}-ingestion-object-created"
  description = "Trigger the ingestion workflow when an image is uploaded to a collection bucket"

  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created"]
    detail = {
      bucket = {
        # Match any collection image bucket for this environment.
        name = [{ prefix = "${local.name_prefix}-" }]
      }
      object = {
        key = [{ suffix = ".jpg" }, { suffix = ".jpeg" }, { suffix = ".png" }]
      }
    }
  })

  tags = merge(var.tags, { Component = "ingestion" })
}

# ---------------------------------------------------------------------------
# EventBridge execution role — may start executions of the ingestion machine.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "ingestion_events_role" {
  name = "${local.name_prefix}-ingestion-events-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "events.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = merge(var.tags, { Component = "ingestion" })
}

resource "aws_iam_policy" "ingestion_events_start" {
  name        = "${local.name_prefix}-ingestion-events-start"
  description = "Allow EventBridge to start executions of the ingestion state machine"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "StartIngestionExecution"
        Effect   = "Allow"
        Action   = ["states:StartExecution"]
        Resource = [aws_sfn_state_machine.ingestion.arn]
      }
    ]
  })

  tags = merge(var.tags, { Component = "ingestion" })
}

resource "aws_iam_role_policy_attachment" "ingestion_events_start" {
  role       = aws_iam_role.ingestion_events_role.name
  policy_arn = aws_iam_policy.ingestion_events_start.arn
}

# ---------------------------------------------------------------------------
# Target — wire the rule to the state machine with an input transformer that
# extracts bucket and object key from the S3 event.
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_event_target" "ingestion_sfn" {
  rule     = aws_cloudwatch_event_rule.ingestion_object_created.name
  arn      = aws_sfn_state_machine.ingestion.arn
  role_arn = aws_iam_role.ingestion_events_role.arn

  input_transformer {
    input_paths = {
      bucket = "$.detail.bucket.name"
      key    = "$.detail.object.key"
    }
    # The Lambdas derive collection_name from the bucket name, and compute the
    # s3vector_bucket and date fields at runtime.
    input_template = <<-EOT
      {
        "s3_bucket": "<bucket>",
        "image_key": "<key>"
      }
    EOT
  }
}
