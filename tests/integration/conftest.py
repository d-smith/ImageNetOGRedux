"""Fixtures and configuration for the deployed-environment integration tests.

These tests run against a **real, deployed** ImageNetOG Redux environment — not
moto. They are excluded from the default ``pytest`` run (``testpaths`` in
``pyproject.toml`` covers only ``tests/unit`` and ``tests/property``) and are
selected explicitly with ``-m integration`` pointed at ``tests/integration``.

All deployment coordinates come from environment variables so nothing about a
specific account or stack is hard-coded. When a required variable is missing,
the dependent test/fixture **skips** rather than fails — so running the suite
without a deployed stack is safe and produces skips, never errors.

Required / optional environment variables (see the README "Integration tests"
section):

    IMAGENETOG_API_BASE_URL   Base invoke URL of the deployed API Gateway stage,
                              e.g. https://abc123.execute-api.us-east-1.amazonaws.com/v1
    AWS_PROFILE               AWS profile to use (e.g. the SSO 'terraform' profile).
    AWS_REGION                Region of the deployment (default us-east-1).
    IMAGENETOG_ENV            Deployment environment name (dev/staging/prod; default dev).
    IMAGENETOG_IMAGES_TABLE   DynamoDB images table name (default {env}-imagenetog-images).
    IMAGENETOG_TEST_COLLECTION        An existing collection name to exercise ingestion against.
    IMAGENETOG_TEST_IMAGE_BUCKET      Image S3 bucket for that collection
                              (default {env}-imagenetog-{collection}-images).
    IMAGENETOG_JWT            A valid Cognito access/ID token (Bearer) for authorized
                              calls (rate-limit test). Optional; tests needing it skip
                              when unset.
"""

import os
from collections.abc import Iterator

import boto3
import pytest


def _require(var: str) -> str:
    """Return the env var value, or skip the test when it is not set."""
    value = os.environ.get(var)
    if not value:
        pytest.skip(f"integration test requires ${var} to be set (see README)")
    return value


@pytest.fixture(scope="session")
def region() -> str:
    return os.environ.get("AWS_REGION", "us-east-1")


@pytest.fixture(scope="session")
def env_name() -> str:
    return os.environ.get("IMAGENETOG_ENV", "dev")


@pytest.fixture(scope="session")
def api_base_url() -> str:
    """Deployed API Gateway stage base URL (without a trailing slash)."""
    return _require("IMAGENETOG_API_BASE_URL").rstrip("/")


@pytest.fixture(scope="session")
def boto_session(region: str) -> boto3.Session:
    """A boto3 session honouring AWS_PROFILE / SSO credentials in scope."""
    profile = os.environ.get("AWS_PROFILE")
    return boto3.Session(profile_name=profile, region_name=region)


@pytest.fixture(scope="session")
def images_table_name(env_name: str) -> str:
    return os.environ.get("IMAGENETOG_IMAGES_TABLE", f"{env_name}-imagenetog-images")


@pytest.fixture(scope="session")
def test_collection() -> str:
    """An existing collection name to exercise (created via create_collection)."""
    return _require("IMAGENETOG_TEST_COLLECTION")


@pytest.fixture(scope="session")
def test_image_bucket(env_name: str, test_collection: str) -> str:
    return os.environ.get(
        "IMAGENETOG_TEST_IMAGE_BUCKET",
        f"{env_name}-imagenetog-{test_collection}-images",
    )


@pytest.fixture(scope="session")
def jwt_token() -> str:
    """A valid Bearer token for authorized calls; skips the test when absent."""
    return _require("IMAGENETOG_JWT")


@pytest.fixture
def s3_client(boto_session: boto3.Session) -> object:
    return boto_session.client("s3")


@pytest.fixture
def dynamodb_resource(boto_session: boto3.Session) -> Iterator[object]:
    yield boto_session.resource("dynamodb")
