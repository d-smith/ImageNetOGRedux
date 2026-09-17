"""Centralised configuration for the api_handler Lambda.

All ``os.environ`` access for the API handler lives here. No other module reads
environment variables directly (per the project Python standards). Import the
values by name::

    from api_handler.config import COLLECTIONS_TABLE

Required variables (set by Terraform, contain no credentials):
    COLLECTIONS_TABLE, IMAGES_TABLE, COGNITO_USER_POOL_ID

Optional variables (have safe defaults):
    EMBED_MODEL_ID, PRESIGNED_URL_TTL_SECONDS, SEARCH_MAX_DISTANCE
"""

import os

# --- Required configuration (raises KeyError at import if unset) ---
COLLECTIONS_TABLE: str = os.environ["COLLECTIONS_TABLE"]
IMAGES_TABLE: str = os.environ["IMAGES_TABLE"]
COGNITO_USER_POOL_ID: str = os.environ["COGNITO_USER_POOL_ID"]

# --- Optional configuration (Terraform overrides; defaults are safe) ---
EMBED_MODEL_ID: str = os.environ.get("EMBED_MODEL_ID", "amazon.titan-embed-image-v1")
PRESIGNED_URL_TTL_SECONDS: int = int(os.environ.get("PRESIGNED_URL_TTL_SECONDS", "300"))

# Maximum cosine distance for a description vector-search result to be
# considered a match. Results with a distance strictly greater than this are
# filtered out, so an irrelevant query returns few or no results instead of the
# full ranked top-K. Cosine distance ranges 0.0 (identical) .. 2.0 (opposite);
# ~0.6 empirically separates real matches from noise for Titan multimodal
# embeddings. Tune per environment via the SEARCH_MAX_DISTANCE env var.
SEARCH_MAX_DISTANCE: float = float(os.environ.get("SEARCH_MAX_DISTANCE", "0.6"))
