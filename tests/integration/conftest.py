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
    IMAGENETOG_APP_CLIENT_ID  Cognito app client id (from `terraform output app_client_id`),
                              used to mint an ID token for happy-path API tests.
    IMAGENETOG_TEST_USERNAME  Cognito test user (email) for token minting.
    IMAGENETOG_TEST_PASSWORD  Password for that user (USER_PASSWORD_AUTH; dev/staging only).
    IMAGENETOG_REST_API_ID    API Gateway REST API id (from `terraform output rest_api_id`),
                              used by the stage/path structural checks.
"""

import os
from collections.abc import Iterator
from pathlib import Path

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
def app_client_id() -> str:
    """Cognito app client id used to mint tokens (from terraform output)."""
    return _require("IMAGENETOG_APP_CLIENT_ID")


@pytest.fixture(scope="session")
def rest_api_id() -> str:
    """API Gateway REST API id (from terraform output rest_api_id)."""
    return _require("IMAGENETOG_REST_API_ID")


@pytest.fixture(scope="session")
def search_image_path() -> str:
    """Path to the committed synthetic test image (a red house landscape).

    Distinctive enough that a text query like "a red house" embeds close to it
    (~0.5 cosine distance) while unrelated queries stay well above the default
    threshold — see the search integration test.
    """
    return str(Path(__file__).parent / "assets" / "red_house_landscape.png")


@pytest.fixture(scope="session")
def search_match_term() -> str:
    """A text query known to match the committed test image."""
    return os.environ.get("IMAGENETOG_TEST_SEARCH_TERM", "a red house in a green field")


@pytest.fixture(scope="session")
def id_token(app_client_id: str, boto_session: "boto3.Session") -> str:
    """Mint a Cognito ID token via USER_PASSWORD_AUTH for happy-path tests.

    Requires ``IMAGENETOG_APP_CLIENT_ID``, ``IMAGENETOG_TEST_USERNAME`` and
    ``IMAGENETOG_TEST_PASSWORD`` (and the app client to have
    ``ALLOW_USER_PASSWORD_AUTH`` enabled — true for dev/staging). Skips cleanly
    when any of these is unavailable, so the suite stays safe to run without a
    token-capable environment.
    """
    username = _require("IMAGENETOG_TEST_USERNAME")
    password = _require("IMAGENETOG_TEST_PASSWORD")
    client = boto_session.client("cognito-idp")
    try:
        resp = client.initiate_auth(
            AuthFlow="USER_PASSWORD_AUTH",
            ClientId=app_client_id,
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )
    except Exception as exc:  # noqa: BLE001 — surface as skip, not error
        pytest.skip(f"could not mint an ID token via USER_PASSWORD_AUTH: {exc}")
    token = resp.get("AuthenticationResult", {}).get("IdToken")
    if not token:
        pytest.skip("initiate-auth returned no IdToken (challenge required?)")
    return str(token)


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


@pytest.fixture
def s3_client(boto_session: boto3.Session) -> object:
    return boto_session.client("s3")


@pytest.fixture
def dynamodb_resource(boto_session: boto3.Session) -> Iterator[object]:
    yield boto_session.resource("dynamodb")


@pytest.fixture
def apigateway_client(boto_session: boto3.Session) -> object:
    """API Gateway (v1/REST) management client for structural assertions."""
    return boto_session.client("apigateway")
