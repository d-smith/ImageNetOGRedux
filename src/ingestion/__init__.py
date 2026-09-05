"""Ingestion Lambda package.

Raises RuntimeError at import time if the Python runtime is not 3.12.x,
satisfying the Lambda cold-start version check (Requirement 1.3).
"""

import sys

if sys.version_info[:2] != (3, 12):
    raise RuntimeError(f"Unsupported Python runtime: {sys.version}. Required: 3.12.x")
