"""Event enrichment for the ingestion workflow.

The EventBridge rule that triggers ingestion only forwards the minimal S3
``Object Created`` fields — the image bucket name and object key. The
downstream steps, however, need the full set of collection/date fields
(``collection_name``, ``s3vector_bucket``, ``date_added``,
``date_added_epoch``). Rather than push all of that into the EventBridge input
transformer (which cannot compute dates or parse names), the first workflow
step (``embed``) derives them here and passes the enriched event forward.

Naming contract (must match ``scripts.create_collection`` and the
terraform-conventions naming rules):

    image bucket   : {env}-imagenetog-{collection_name}-images
    vector bucket  : {env}-imagenetog-{collection_name}-vectors
"""

import re
from datetime import UTC, datetime
from typing import Any

# Extract {env} and {collection_name} from an image bucket name of the form
# ``{env}-imagenetog-{collection_name}-images``. ``env`` is a fixed enum and
# collection names never contain "-imagenetog-", so this is unambiguous.
_IMAGE_BUCKET_RE = re.compile(r"^(?P<env>dev|staging|prod)-imagenetog-(?P<name>.+)-images$")


def enrich_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``event`` with all downstream ingestion fields present.

    Missing fields are derived from ``s3_bucket`` and the current UTC date.
    Fields already present on the event are preserved (so a fully-populated
    event — e.g. from a test harness or a manual Step Functions start — passes
    through unchanged).

    Args:
        event: The ingestion event. Must contain at least ``s3_bucket`` and
            ``image_key`` (as delivered by the EventBridge input transformer).

    Returns:
        A new event dict containing ``s3_bucket``, ``image_key``,
        ``collection_name``, ``s3vector_bucket``, ``date_added``, and
        ``date_added_epoch``.

    Raises:
        KeyError: If ``s3_bucket`` or ``image_key`` is absent.
        ValueError: If ``s3_bucket`` does not match the expected
            ``{env}-imagenetog-{collection_name}-images`` naming pattern and
            ``collection_name`` / ``s3vector_bucket`` cannot be derived.
    """
    s3_bucket = event["s3_bucket"]
    image_key = event["image_key"]

    enriched: dict[str, Any] = dict(event)

    if "collection_name" not in enriched or "s3vector_bucket" not in enriched:
        env, collection_name = _parse_image_bucket(s3_bucket)
        enriched.setdefault("collection_name", collection_name)
        enriched.setdefault("s3vector_bucket", f"{env}-imagenetog-{collection_name}-vectors")

    if "date_added" not in enriched or "date_added_epoch" not in enriched:
        now = datetime.now(UTC)
        enriched.setdefault("date_added", now.date().isoformat())
        enriched.setdefault("date_added_epoch", int(now.timestamp()))

    enriched["image_key"] = image_key  # normalise/ensure present
    return enriched


def _parse_image_bucket(s3_bucket: str) -> tuple[str, str]:
    """Parse an image bucket name into ``(env, collection_name)``.

    Args:
        s3_bucket: The image bucket name.

    Returns:
        A ``(env, collection_name)`` tuple.

    Raises:
        ValueError: If the bucket name does not match the expected pattern.
    """
    match = _IMAGE_BUCKET_RE.match(s3_bucket)
    if match is None:
        raise ValueError(
            f"Cannot derive collection from bucket name '{s3_bucket}': "
            "expected '{env}-imagenetog-{collection_name}-images'."
        )
    return match.group("env"), match.group("name")
