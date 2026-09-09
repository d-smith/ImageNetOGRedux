"""Shared pytest configuration and fixtures for the ImageNetOG Redux test suite.

Responsibilities:
* Ensure ``src/`` is importable as the package root so tests can
  ``import api_handler`` without an editable install.
* Register and load a Hypothesis settings profile enforcing the project
  convention of a minimum of 100 examples per property test.
* Provide required Lambda environment variables so that importing
  ``api_handler`` modules (which read config at import time) does not fail.
"""

import os
import sys
from pathlib import Path

from hypothesis import HealthCheck, settings

# ---------------------------------------------------------------------------
# Path setup — make ``src/`` the import root for ``api_handler`` / ``ingestion``
# ---------------------------------------------------------------------------
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# ---------------------------------------------------------------------------
# Environment defaults — config modules read these at import time.
# These are configuration names, never real credentials.
# ---------------------------------------------------------------------------
os.environ.setdefault("COLLECTIONS_TABLE", "test-imagenetog-collections")
os.environ.setdefault("IMAGES_TABLE", "test-imagenetog-images")
os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("EMBED_MODEL_ID", "amazon.titan-embed-image-v1")
os.environ.setdefault("PRESIGNED_URL_TTL_SECONDS", "300")

# ---------------------------------------------------------------------------
# Hypothesis profile — minimum 100 examples per project standard.
# ---------------------------------------------------------------------------
settings.register_profile(
    "imagenetog",
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
settings.load_profile("imagenetog")
