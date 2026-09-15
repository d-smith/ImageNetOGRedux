"""Unit tests for ``ingestion.event_utils.enrich_event`` (Failure 2 fix).

The EventBridge rule delivers only ``s3_bucket`` + ``image_key``; the embed
step enriches the event with the derived collection/date fields before the rest
of the workflow runs. These tests pin that derivation.
"""

import re

import pytest

from ingestion.event_utils import enrich_event

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def test_derives_collection_and_vector_bucket_from_image_bucket() -> None:
    event = {
        "s3_bucket": "dev-imagenetog-my-collection-images",
        "image_key": "uploads/cat.jpg",
    }
    enriched = enrich_event(event)

    assert enriched["collection_name"] == "my-collection"
    assert enriched["s3vector_bucket"] == "dev-imagenetog-my-collection-vectors"
    assert enriched["s3_bucket"] == "dev-imagenetog-my-collection-images"
    assert enriched["image_key"] == "uploads/cat.jpg"


def test_derives_date_fields() -> None:
    enriched = enrich_event({"s3_bucket": "prod-imagenetog-nature-images", "image_key": "a.png"})
    assert _ISO_DATE_RE.match(enriched["date_added"])
    assert isinstance(enriched["date_added_epoch"], int)
    assert enriched["date_added_epoch"] > 0


def test_handles_collection_name_with_hyphens() -> None:
    enriched = enrich_event({"s3_bucket": "staging-imagenetog-a-b-c-images", "image_key": "k.jpg"})
    assert enriched["collection_name"] == "a-b-c"
    assert enriched["s3vector_bucket"] == "staging-imagenetog-a-b-c-vectors"


def test_preserves_already_present_fields() -> None:
    # A fully-populated event (e.g. manual SFN start) passes through unchanged.
    event = {
        "s3_bucket": "dev-imagenetog-my-collection-images",
        "image_key": "k.jpg",
        "collection_name": "override",
        "s3vector_bucket": "custom-vectors",
        "date_added": "2020-01-01",
        "date_added_epoch": 1577836800,
    }
    enriched = enrich_event(event)
    assert enriched["collection_name"] == "override"
    assert enriched["s3vector_bucket"] == "custom-vectors"
    assert enriched["date_added"] == "2020-01-01"
    assert enriched["date_added_epoch"] == 1577836800


def test_invalid_bucket_name_raises() -> None:
    with pytest.raises(ValueError, match="Cannot derive collection"):
        enrich_event({"s3_bucket": "not-a-valid-bucket", "image_key": "k.jpg"})


def test_missing_required_keys_raise() -> None:
    with pytest.raises(KeyError):
        enrich_event({"image_key": "k.jpg"})  # no s3_bucket
    with pytest.raises(KeyError):
        enrich_event({"s3_bucket": "dev-imagenetog-x-images"})  # no image_key
