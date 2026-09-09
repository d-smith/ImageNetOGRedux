"""Centralised configuration for the ingestion Lambda functions.

All ``os.environ`` access for the ingestion pipeline lives here. No other
ingestion module reads environment variables directly (per the project Python
standards). Import the values by name::

    from ingestion.config import IMAGES_TABLE

Required variables (set by Terraform, contain no credentials):
    IMAGES_TABLE

Optional variables (have safe defaults):
    EMBED_MODEL_ID, DESCRIBE_MODEL_ID
"""

import os

# --- Required configuration (raises KeyError at import if unset) ---
IMAGES_TABLE: str = os.environ["IMAGES_TABLE"]

# --- Optional configuration (Terraform overrides; defaults are safe) ---
EMBED_MODEL_ID: str = os.environ.get("EMBED_MODEL_ID", "amazon.titan-embed-image-v1")
DESCRIBE_MODEL_ID: str = os.environ.get("DESCRIBE_MODEL_ID", "amazon.nova-lite-v1:0")
