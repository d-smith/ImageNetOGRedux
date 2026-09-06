locals {
  name_prefix = "${var.env}-imagenetog"
}

# ---------------------------------------------------------------------------
# Collections table
#
# Schema:
#   PK  collection_name (S)   — unique collection identifier
#       created         (S)   — ISO 8601 date string (YYYY-MM-DD)
#       created_epoch   (N)   — Unix timestamp (seconds); used for range queries
#       s3_bucket       (S)   — internal; never returned by API
#       s3vector_bucket (S)   — internal; never returned by API
#
# GSI `created_epoch-index`:
#   Hash  = _type (S) — constant "COLLECTION"; single-partition, ordered range scan
#   Range = created_epoch (N)
# ---------------------------------------------------------------------------
resource "aws_dynamodb_table" "collections" {
  name         = "${local.name_prefix}-collections"
  billing_mode = var.billing_mode
  hash_key     = "collection_name"

  attribute {
    name = "collection_name"
    type = "S"
  }

  attribute {
    name = "_type"
    type = "S"
  }

  attribute {
    name = "created_epoch"
    type = "N"
  }

  global_secondary_index {
    name            = "created_epoch-index"
    hash_key        = "_type"
    range_key       = "created_epoch"
    projection_type = "ALL"
  }

  # Point-in-time recovery enabled in all environments
  point_in_time_recovery {
    enabled = true
  }

  # Encryption at rest with AWS-managed key
  server_side_encryption {
    enabled = true
  }

  tags = merge(var.tags, { Component = "storage" })
}

# ---------------------------------------------------------------------------
# Images table
#
# Schema:
#   PK  collection_name  (S)  — parent collection identifier
#   SK  image_key        (S)  — S3 object key (unique within collection)
#       date_added       (S)  — ISO 8601 date string (YYYY-MM-DD)
#       date_added_epoch (N)  — Unix timestamp (seconds); used for range queries
#       description      (S)  — nullable natural-language description
#       s3_bucket        (S)  — internal; never returned by API
#       s3vector_bucket  (S)  — internal; never returned by API
#
# LSI `date_added_epoch-index`:
#   Hash  = collection_name (S)   — same as table PK
#   Range = date_added_epoch (N)  — enables efficient date-range filtering per collection
# ---------------------------------------------------------------------------
resource "aws_dynamodb_table" "images" {
  name         = "${local.name_prefix}-images"
  billing_mode = var.billing_mode
  hash_key     = "collection_name"
  range_key    = "image_key"

  attribute {
    name = "collection_name"
    type = "S"
  }

  attribute {
    name = "image_key"
    type = "S"
  }

  attribute {
    name = "date_added_epoch"
    type = "N"
  }

  local_secondary_index {
    name            = "date_added_epoch-index"
    range_key       = "date_added_epoch"
    projection_type = "ALL"
  }

  # Point-in-time recovery enabled in all environments
  point_in_time_recovery {
    enabled = true
  }

  # Encryption at rest with AWS-managed key
  server_side_encryption {
    enabled = true
  }

  tags = merge(var.tags, { Component = "storage" })
}
