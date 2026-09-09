"""Property tests for the collections service (task 12.2).

* Property 8: every returned item has ``name`` + ``created`` and never
  ``s3_bucket`` / ``s3vector_bucket``.
* Property 9: the ``name`` prefix filter (case-insensitive) returns exactly the
  matching collections.
* Property 10: the date-range filter returns only in-range collections; an
  inverted range is rejected at the parameter layer.

_Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

Implementation note: the service binds its DynamoDB resource at import time. We
activate moto once for the whole module (via an autouse fixture), reload the
service inside that mock so its module-level table points at the mocked
backend, and clear the table between examples. This avoids re-entering moto and
reloading per Hypothesis example (which blew the default deadline).
"""

import importlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import boto3
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from api_handler import config
from api_handler.params import DateRangeParams, PaginationParams

_COLLECTION_NAME = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
    min_size=3,
    max_size=20,
).filter(lambda s: s[0] != "-" and s[-1] != "-")

_ISO_DATE = st.dates(min_value=date(2000, 1, 1), max_value=date(2030, 12, 31))

# Populated by the module fixture: the live service module (reloaded under moto)
# and the mocked DynamoDB table resource.
_svc: Any = None
_table: Any = None


@pytest.fixture(autouse=True, scope="module")
def _mocked_service() -> Iterator[None]:
    """Start moto for the module, create the table, reload the service once."""
    global _svc, _table
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _table = dynamodb.create_table(
            TableName=config.COLLECTIONS_TABLE,
            KeySchema=[{"AttributeName": "collection_name", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "collection_name", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        _table.wait_until_exists()

        from api_handler.services import collections as svc

        _svc = importlib.reload(svc)  # rebind module-level table to the mock
        yield


def _clear_table() -> None:
    """Delete every item so each example starts from an empty table."""
    scanned = _table.scan().get("Items", [])
    with _table.batch_writer() as batch:
        for item in scanned:
            batch.delete_item(Key={"collection_name": item["collection_name"]})


def _epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())


def _put(name: str, created: date) -> None:
    _table.put_item(
        Item={
            "collection_name": name,
            "created": created.isoformat(),
            "created_epoch": _epoch(created),
            "_type": "COLLECTION",
            "s3_bucket": f"dev-imagenetog-{name}-images",
            "s3vector_bucket": f"dev-imagenetog-{name}-vectors",
        }
    )


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    names=st.lists(_COLLECTION_NAME, min_size=1, max_size=8, unique=True),
    created=_ISO_DATE,
)
def test_field_completeness_and_privacy(names: list[str], created: date) -> None:
    # Feature: aws-deployment-feature, Property 8: field completeness and privacy
    _clear_table()
    for n in names:
        _put(n, created)

    result = _svc.list_collections(
        pagination=PaginationParams(limit=100, offset=0),
        sort_field="name",
        order="asc",
        date_range=DateRangeParams(after=None, before=None),
        name_prefix=None,
    )

    assert result["total"] == len(names)
    for item in result["items"]:
        assert set(item.keys()) == {"name", "created"}


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    names=st.lists(_COLLECTION_NAME, min_size=1, max_size=10, unique=True),
    prefix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=3),
)
def test_name_prefix_filter(names: list[str], prefix: str) -> None:
    # Feature: aws-deployment-feature, Property 9: collection name filter correctness
    _clear_table()
    for n in names:
        _put(n, date(2024, 1, 1))

    result = _svc.list_collections(
        pagination=PaginationParams(limit=100, offset=0),
        sort_field="name",
        order="asc",
        date_range=DateRangeParams(after=None, before=None),
        name_prefix=prefix,
    )

    returned = {item["name"] for item in result["items"]}
    expected = {n for n in names if n.lower().startswith(prefix.lower())}
    assert returned == expected


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(dates=st.lists(_ISO_DATE, min_size=1, max_size=10), lo=_ISO_DATE, hi=_ISO_DATE)
def test_date_range_filter(dates: list[date], lo: date, hi: date) -> None:
    # Feature: aws-deployment-feature, Property 10: collection date-range filter correctness
    _clear_table()
    after, before = (lo, hi) if lo <= hi else (hi, lo)
    names = []
    for idx, d in enumerate(dates):
        name = f"col-{idx}"
        names.append((name, d))
        _put(name, d)

    result = _svc.list_collections(
        pagination=PaginationParams(limit=100, offset=0),
        sort_field="created",
        order="asc",
        date_range=DateRangeParams(after=after, before=before),
        name_prefix=None,
    )

    returned = {item["name"] for item in result["items"]}
    expected = {name for name, d in names if after <= d <= before}
    assert returned == expected
