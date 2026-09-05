---
inclusion: auto
name: python-standards
description: Python coding standards, tooling, architecture patterns, type hints, docstrings, and testing conventions for the ImageNetOG Redux project
---

# Python Standards — ImageNetOG Redux

Applies to all Python source files under `src/` and `tests/`.

---

## Tooling

### Required tools (all pinned in `pyproject.toml`)

| Tool | Purpose | Invocation |
|---|---|---|
| `ruff` | Linting + formatting (replaces flake8, isort, black) | `ruff check src/ tests/` / `ruff format src/ tests/` |
| `mypy` | Static type checking | `mypy src/` |
| `bandit` | Security static analysis | `bandit -r src/ -ll` |
| `pytest` | Test runner | `pytest tests/unit tests/property` |
| `pytest-cov` | Coverage reporting | `pytest --cov=src --cov-report=term-missing` |
| `hypothesis` | Property-based testing | Used via `@given` decorator in `tests/property/` |
| `moto[all]` | AWS service mocking | Used in unit and property tests |

### Ruff configuration (in `pyproject.toml`)

```toml
[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "S", "B", "C4", "PTH"]
ignore = ["S101"]  # allow assert in tests

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = false
```

### Hypothesis profile (in `pyproject.toml` or `conftest.py`)

```toml
[tool.hypothesis]
deriving = "best"
max_examples = 100
```

All property tests run a minimum of 100 examples. Do not suppress `HealthCheck` warnings without a documented reason.

---

## Runtime Version Guard

Every Lambda entry-point module must include the following guard at import time (not inside the handler function):

```python
import sys

if sys.version_info[:2] != (3, 12):
    raise RuntimeError(
        f"Unsupported Python runtime: {sys.version}. Required: 3.12.x"
    )
```

Place this in `src/api_handler/__init__.py` and `src/ingestion/__init__.py` so it fires on cold start before any handler is invoked.

---

## Architecture Patterns

### Service layer separation

Lambda handlers are thin. They do two things only: parse input from the event, and call a service-layer function. All business logic lives in the service layer.

```python
# CORRECT — thin handler
def handler(event: dict, context: object) -> dict:
    params = parse_pagination(event)
    return list_collections_service(params)

# WRONG — logic in handler
def handler(event: dict, context: object) -> dict:
    limit = int(event.get("queryStringParameters", {}).get("limit", 20))
    items = dynamodb.scan(...)
    ...
```

Source layout:
```
src/api_handler/
    lambda_function.py   ← entry point, handler() only
    app.py               ← Powertools router registration
    routes/
        collections.py   ← thin route functions
        images.py
    services/
        collections.py   ← business logic
        images.py
    params.py            ← query parameter parsing/validation
    exceptions.py        ← exception classes
    responses.py         ← response builder helpers
    config.py            ← all env var access
    middleware.py        ← error handler middleware
```

### Configuration module

All `os.environ` access is centralised in `src/api_handler/config.py`. No other file reads environment variables directly.

```python
# src/api_handler/config.py
import os

COLLECTIONS_TABLE: str = os.environ["COLLECTIONS_TABLE"]
IMAGES_TABLE: str = os.environ["IMAGES_TABLE"]
EMBED_MODEL_ID: str = os.environ.get("EMBED_MODEL_ID", "amazon.titan-embed-image-v1")
PRESIGNED_URL_TTL_SECONDS: int = int(os.environ.get("PRESIGNED_URL_TTL_SECONDS", "300"))
```

Import config values by name: `from api_handler.config import COLLECTIONS_TABLE`.

### boto3 client initialisation

boto3 clients are initialised **once at module load time**, outside any function or class. Never create a client inside a handler or service function — this re-creates the connection on every invocation and defeats Lambda's execution context reuse.

```python
# CORRECT — module-level client
import boto3
_dynamodb = boto3.resource("dynamodb")
_s3 = boto3.client("s3")

# WRONG — client inside function
def get_collection(name: str) -> dict:
    dynamodb = boto3.resource("dynamodb")  # ← never do this
    ...
```

The module-level client pattern also makes moto patching straightforward: mock before import, or use `@mock_aws` decorator on the test.

### Error token constants

Error tokens are string constants defined in `src/api_handler/exceptions.py`. Never use inline string literals for error tokens elsewhere in the codebase.

```python
# exceptions.py
class APIError(Exception):
    http_status: int
    error_token: str

class CollectionNotFoundError(APIError):
    http_status = 404
    error_token = "resource.not_found"

class ImageNotFoundError(APIError):
    http_status = 404
    error_token = "resource.not_found"

class InvalidParameterError(APIError):
    http_status = 400
    error_token = "param.invalid"

class MethodNotAllowedError(APIError):
    http_status = 405
    error_token = "method.not_allowed"
```

---

## Type Hints

All public functions and methods require full type annotations. Use Python 3.12 syntax throughout — no `from __future__ import annotations` needed.

```python
# CORRECT
def parse_pagination(event: dict[str, object]) -> tuple[int, int]:
    ...

def list_collections(params: PaginationParams) -> CollectionListResponse:
    ...

# WRONG — no annotations
def parse_pagination(event):
    ...
```

Use `X | None` instead of `Optional[X]`. Use `list[str]` instead of `List[str]`. Use `dict[str, str]` instead of `Dict[str, str]`.

Define typed data structures with `dataclasses` or `TypedDict` for internal request/response objects. Do not pass raw `dict` objects between the service layer and route handlers.

---

## Docstrings

Use Google style. Required on all public functions, classes, and modules. Not required on private helpers (prefixed with `_`) unless the logic is non-obvious.

```python
def parse_date(value: str, param_name: str) -> date:
    """Parse an ISO 8601 date string, raising InvalidParameterError on failure.

    Args:
        value: The raw string value from the query parameter.
        param_name: The query parameter name, used in the error message.

    Returns:
        A `datetime.date` object.

    Raises:
        InvalidParameterError: If `value` is not a valid ISO 8601 date (YYYY-MM-DD).
    """
```

---

## Logging

Use **AWS Lambda Powertools Logger** for all log output. Never use `print()` or `logging.getLogger()` directly.

```python
from aws_lambda_powertools import Logger
logger = Logger()  # reads SERVICE_NAME from env, structured JSON output

# CORRECT
logger.info("Collection not found", collection_name=name)
logger.exception("Unexpected error during ingestion")  # includes traceback

# WRONG
print(f"Collection not found: {name}")
import logging; logging.info(...)
```

For 500 errors: log the full exception with `logger.exception(...)` **before** returning the sanitised response. The traceback goes to CloudWatch Logs, never to the response body.

---

## Testing Conventions

### File naming

| Test type | Location | Naming |
|---|---|---|
| Unit | `tests/unit/` | `test_{module}.py` |
| Property | `tests/property/` | `test_{concern}_properties.py` |
| Integration | `tests/integration/` | `test_{concern}_integration.py` |

### Property test tagging

Every property test function includes a comment on the first line of the function body identifying the property it validates:

```python
@given(st.integers())
def test_limit_bounds(limit: int) -> None:
    # Feature: aws-deployment-feature, Property 6: Limit bounds enforcement
    ...
```

### moto usage

Use the `@mock_aws` decorator (moto v4+) on test classes or functions. Do not use the context manager form in new tests — the decorator is cleaner with Hypothesis.

```python
from moto import mock_aws

@mock_aws
@given(...)
def test_collection_filter(...) -> None:
    ...
```

### No live AWS calls in unit or property tests

Unit and property tests must never make real AWS API calls. If a test requires a boto3 client, it must be wrapped with `@mock_aws` or the client must be injected as a dependency and replaced with a mock in the test.
