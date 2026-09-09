# ---------------------------------------------------------------------------
# Step Functions state machine — ingestion orchestration
#
# Flow (see design.md "Ingestion Flow"):
#   1. ParallelEmbedAndDescribe
#        ├── EmbedBranch:    ingestion_embed    (Retry 2x, Catch → FailIngestion)
#        └── DescribeBranch: ingestion_describe (Retry 2x, Catch → FailIngestion)
#   2. StoreMetadata: ingestion_store           (Retry 2x, Catch → FailIngestion)
#
# The Parallel state emits an array [embedResult, describeResult]. A small
# result selector merges the original input with the description before the
# store step so ingestion_store receives a single flat object.
# ---------------------------------------------------------------------------

# Standard exponential-backoff retry applied to every task state.
locals {
  sfn_retry = [
    {
      ErrorEquals     = ["States.ALL"]
      IntervalSeconds = 2
      MaxAttempts     = 2
      BackoffRate     = 2.0
    }
  ]

  ingestion_definition = jsonencode({
    Comment = "ImageNetOG Redux image ingestion workflow"
    StartAt = "ParallelEmbedAndDescribe"
    States = {
      ParallelEmbedAndDescribe = {
        Type = "Parallel"
        # Merge the describe branch's description into the original input and
        # pass the flattened object to the store step.
        ResultSelector = {
          "collection_name.$"  = "$[0].collection_name"
          "image_key.$"        = "$[0].image_key"
          "s3_bucket.$"        = "$[0].s3_bucket"
          "s3vector_bucket.$"  = "$[0].s3vector_bucket"
          "date_added.$"       = "$[0].date_added"
          "date_added_epoch.$" = "$[0].date_added_epoch"
          "description.$"      = "$[1].description"
        }
        Branches = [
          {
            StartAt = "EmbedImage"
            States = {
              EmbedImage = {
                Type     = "Task"
                Resource = aws_lambda_function.ingestion["embed"].arn
                Retry    = local.sfn_retry
                Catch    = [{ ErrorEquals = ["States.ALL"], Next = "FailIngestion" }]
                End      = true
              }
              FailIngestion = { Type = "Fail", Error = "IngestionError", Cause = "Embed branch failed" }
            }
          },
          {
            StartAt = "DescribeImage"
            States = {
              DescribeImage = {
                Type     = "Task"
                Resource = aws_lambda_function.ingestion["describe"].arn
                Retry    = local.sfn_retry
                Catch    = [{ ErrorEquals = ["States.ALL"], Next = "FailIngestion" }]
                End      = true
              }
              FailIngestion = { Type = "Fail", Error = "IngestionError", Cause = "Describe branch failed" }
            }
          }
        ]
        Next  = "StoreMetadata"
        Catch = [{ ErrorEquals = ["States.ALL"], Next = "FailWorkflow" }]
      }
      StoreMetadata = {
        Type     = "Task"
        Resource = aws_lambda_function.ingestion["store"].arn
        Retry    = local.sfn_retry
        Catch    = [{ ErrorEquals = ["States.ALL"], Next = "FailWorkflow" }]
        End      = true
      }
      FailWorkflow = {
        Type  = "Fail"
        Error = "IngestionError"
        Cause = "Ingestion workflow failed"
      }
    }
  })
}

# ---------------------------------------------------------------------------
# Step Functions execution role — may invoke the three ingestion Lambdas only.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "ingestion_sfn_role" {
  name = "${local.name_prefix}-ingestion-sfn-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "states.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = merge(var.tags, { Component = "ingestion" })
}

resource "aws_iam_policy" "ingestion_sfn_invoke" {
  name        = "${local.name_prefix}-ingestion-sfn-invoke"
  description = "Allow the ingestion state machine to invoke the ingestion Lambda functions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokeIngestionLambdas"
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [for fn in aws_lambda_function.ingestion : fn.arn]
      }
    ]
  })

  tags = merge(var.tags, { Component = "ingestion" })
}

resource "aws_iam_role_policy_attachment" "ingestion_sfn_invoke" {
  role       = aws_iam_role.ingestion_sfn_role.name
  policy_arn = aws_iam_policy.ingestion_sfn_invoke.arn
}

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
resource "aws_sfn_state_machine" "ingestion" {
  name     = "${local.name_prefix}-ingestion"
  role_arn = aws_iam_role.ingestion_sfn_role.arn

  definition = local.ingestion_definition

  tags = merge(var.tags, { Component = "ingestion" })
}
