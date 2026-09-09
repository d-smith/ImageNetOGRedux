"""``ingestion_describe`` Lambda handler.

Generates a short natural-language description of an image using Amazon Nova
Lite (via Bedrock). This is a best-effort enrichment step: a description
failure must not fail the whole ingestion workflow, so the handler falls back
to ``description=None`` and logs the exception rather than raising.
"""

import base64
import json
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

from ingestion import config

logger = Logger()

# Module-level clients (reused across warm invocations, per project standards).
_s3 = boto3.client("s3")
_bedrock_runtime = boto3.client("bedrock-runtime")

# Prompt sent alongside the image to Nova Lite.
_DESCRIBE_PROMPT = "Describe this image concisely in 1-3 sentences."


def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    """Generate an image description and enrich the event with it.

    A description failure is caught and logged; the event is still returned
    with ``description`` set to ``None`` so the downstream store step can
    proceed.

    Args:
        event: The Step Functions event. Required keys are ``s3_bucket`` and
            ``image_key`` (other keys are passed through untouched).
        context: The Lambda context object (unused).

    Returns:
        The input ``event`` enriched with a ``description`` key (``str`` or
        ``None``).
    """
    image_key = event["image_key"]
    s3_bucket = event["s3_bucket"]

    description: str | None
    try:
        image_b64 = _fetch_image_base64(s3_bucket, image_key)
        image_format = _detect_format(image_key)
        description = _invoke_description_model(image_b64, image_format)
        logger.info("Description generated", image_key=image_key)
    except Exception:
        # Best-effort step: never fail the workflow on a description error.
        logger.exception("Description generation failed; falling back to null")
        description = None

    return {**event, "description": description}


def _fetch_image_base64(bucket: str, key: str) -> str:
    """Fetch an image from S3 and return its base64-encoded contents.

    Args:
        bucket: The S3 bucket holding the raw image.
        key: The S3 object key of the image.

    Returns:
        The base64-encoded image bytes as an ASCII string.
    """
    response = _s3.get_object(Bucket=bucket, Key=key)
    raw_bytes: bytes = response["Body"].read()
    return base64.b64encode(raw_bytes).decode("ascii")


def _detect_format(image_key: str) -> str:
    """Infer the Bedrock image format from an object key extension.

    Args:
        image_key: The S3 object key of the image.

    Returns:
        ``"png"`` for keys ending in ``.png`` (case-insensitive), otherwise
        ``"jpeg"``.
    """
    if image_key.lower().endswith(".png"):
        return "png"
    return "jpeg"


def _invoke_description_model(image_b64: str, image_format: str) -> str:
    """Invoke Nova Lite and extract the description text from the response.

    Args:
        image_b64: The base64-encoded image to describe.
        image_format: The Bedrock image format (``"png"`` or ``"jpeg"``).

    Returns:
        The generated description string.
    """
    body = json.dumps(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "image": {
                                "format": image_format,
                                "source": {"bytes": image_b64},
                            }
                        },
                        {"text": _DESCRIBE_PROMPT},
                    ],
                }
            ]
        }
    )
    response = _bedrock_runtime.invoke_model(modelId=config.DESCRIBE_MODEL_ID, body=body)
    payload = json.loads(response["body"].read())
    return _extract_description(payload)


def _extract_description(payload: dict[str, Any]) -> str:
    """Extract the description text from a Nova Lite response payload.

    Args:
        payload: The parsed JSON response body from the model invocation.

    Returns:
        The concatenated text content of the model's message.
    """
    content = payload["output"]["message"]["content"]
    texts = [block["text"] for block in content if "text" in block]
    return " ".join(texts).strip()
