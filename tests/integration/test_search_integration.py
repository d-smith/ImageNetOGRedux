"""Integration tests: description (vector) search path end-to-end.

These exercise the parts of the API that unit/property tests cannot: the real
``s3vectors:QueryVectors`` call (with ``returnDistance``), ``BatchGetItem``
hydration, Bedrock embedding, the distance-threshold filter, the ``score``
field, and the ``maxDistance`` override.

The primary test is **self-contained**: it uploads a committed synthetic image
(a distinctive red-house landscape), waits for the async ingestion workflow to
index it, then searches for it — so it does not depend on pre-existing data. It
skips cleanly when the deployment coordinates / collection are unavailable.

Two fast tests need only a token: ``maxDistance`` validation (400s) and the
date-listing response shape (no ``score``).

_Requirements: 6.1, 6.2, 6.3, 7.1, 7.2, 7.3_
"""

import contextlib
import time
import uuid
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.integration

_TIMEOUT = 15
_POLL_TIMEOUT_SECONDS = 180
_POLL_INTERVAL_SECONDS = 5


def _wait_for_ingestion(
    dynamodb_resource: object,
    images_table_name: str,
    collection: str,
    image_key: str,
) -> dict:
    """Poll the images table until the ingestion record for ``image_key`` exists."""
    table = dynamodb_resource.Table(images_table_name)  # type: ignore[attr-defined]
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        item = table.get_item(Key={"collection_name": collection, "image_key": image_key}).get(
            "Item"
        )
        if item is not None:
            return item
        time.sleep(_POLL_INTERVAL_SECONDS)
    pytest.fail(
        f"ingestion record for {image_key!r} did not appear within {_POLL_TIMEOUT_SECONDS}s"
    )


def test_description_search_finds_ingested_image(
    api_base_url: str,
    id_token: str,
    s3_client: object,
    dynamodb_resource: object,
    test_collection: str,
    test_image_bucket: str,
    images_table_name: str,
    search_image_path: str,
    search_match_term: str,
) -> None:
    """Upload the synthetic image, wait for ingestion, then search for it.

    Asserts the search returns 200, includes the uploaded image, and that each
    result carries a numeric ``score`` (the relevance distance) without leaking
    internal fields.
    """
    image_key = f"integration-tests/search-{uuid.uuid4().hex}.png"
    with Path(search_image_path).open("rb") as fh:
        body = fh.read()

    s3_client.put_object(  # type: ignore[attr-defined]
        Bucket=test_image_bucket, Key=image_key, Body=body, ContentType="image/png"
    )
    _wait_for_ingestion(dynamodb_resource, images_table_name, test_collection, image_key)

    try:
        # A generous maxDistance so the match is returned regardless of minor
        # embedding variation; the point is that the pipeline works end-to-end.
        resp = requests.get(
            f"{api_base_url}/collections/{test_collection}/images",
            headers={"Authorization": id_token},
            params={"description": search_match_term, "maxDistance": "0.7", "limit": "20"},
            timeout=_TIMEOUT,
        )
        assert resp.status_code == 200, f"search failed: {resp.status_code} {resp.text[:300]}"
        assert "IncompleteSignatureException" not in resp.text
        body_json = resp.json()

        keys = {item["key"] for item in body_json["items"]}
        assert image_key in keys, (
            f"uploaded image {image_key!r} not returned for query {search_match_term!r}; "
            f"got {keys}"
        )
        for item in body_json["items"]:
            assert isinstance(
                item.get("score"), int | float
            ), f"search result missing numeric 'score': {item}"
            assert "s3_bucket" not in item and "s3vector_bucket" not in item
    finally:
        # Clean up both the object and its metadata record (best effort).
        with contextlib.suppress(Exception):
            s3_client.delete_object(Bucket=test_image_bucket, Key=image_key)  # type: ignore[attr-defined]
            dynamodb_resource.Table(images_table_name).delete_item(  # type: ignore[attr-defined]
                Key={"collection_name": test_collection, "image_key": image_key}
            )


def test_max_distance_override_widens_results(
    api_base_url: str,
    id_token: str,
    test_collection: str,
) -> None:
    """A tiny maxDistance returns no more results than a large one (filter works)."""
    base = f"{api_base_url}/collections/{test_collection}/images"
    common = {"description": "a red house in a green field", "limit": "20"}

    strict = requests.get(
        base,
        headers={"Authorization": id_token},
        params={**common, "maxDistance": "0.01"},
        timeout=_TIMEOUT,
    )
    loose = requests.get(
        base,
        headers={"Authorization": id_token},
        params={**common, "maxDistance": "2.0"},
        timeout=_TIMEOUT,
    )
    assert strict.status_code == 200 and loose.status_code == 200
    # A near-zero threshold cannot return MORE than an all-inclusive one.
    assert strict.json()["total"] <= loose.json()["total"]


def test_max_distance_invalid_values_rejected(
    api_base_url: str,
    id_token: str,
    test_collection: str,
) -> None:
    """Malformed / out-of-range maxDistance returns 400 param.invalid."""
    base = f"{api_base_url}/collections/{test_collection}/images"
    for bad in ("abc", "5", "-1"):
        resp = requests.get(
            base,
            headers={"Authorization": id_token},
            params={"description": "anything", "maxDistance": bad},
            timeout=_TIMEOUT,
        )
        assert resp.status_code == 400, f"maxDistance={bad!r} should be 400, got {resp.status_code}"
        assert resp.json().get("error") == "param.invalid"


def test_date_listing_has_no_score(
    api_base_url: str,
    id_token: str,
    test_collection: str,
) -> None:
    """Plain date listing (no description) returns items WITHOUT a score field."""
    resp = requests.get(
        f"{api_base_url}/collections/{test_collection}/images",
        headers={"Authorization": id_token},
        params={"limit": "20"},
        timeout=_TIMEOUT,
    )
    assert resp.status_code == 200, f"{resp.status_code}: {resp.text[:200]}"
    for item in resp.json()["items"]:
        assert "score" not in item, f"date-listing item unexpectedly has a score: {item}"
        assert set(item.keys()) <= {"key", "dateAdded", "description"}
