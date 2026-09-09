"""``ingestion_embed`` Lambda handler.

Reads an image from S3, generates a 1,024-dimension float32 embedding using
the Bedrock Titan multimodal embedding model, and writes the vector (plus
filterable metadata) to the collection's S3 Vectors index.

This is the first step of the Step Functions ingestion workflow. The handler
returns the input event unchanged so that Step Functions can pass it to the
downstream states.
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

# The ``s3vectors`` client is created lazily: the pinned boto3 (1.34.x) predates
# the S3 Vectors service, so an eager module-level ``boto3.client("s3vectors")``
# raises UnknownServiceError at import (which would crash the Lambda cold start).
# The Lambda runtime ships a newer boto3 where the service is available.
_s3vectors_client: Any = None


def _s3vectors() -> Any:
    """Return the module-cached ``s3vectors`` client, creating it on first use."""
    global _s3vectors_client
    if _s3vectors_client is None:
        _s3vectors_client = boto3.client("s3vectors")  # type: ignore[call-overload]
    return _s3vectors_client


# The S3 Vectors index name is fixed for every collection (see design.md).
_VECTOR_INDEX_NAME = "images"

# Titan multimodal embedding dimension used across the project.
_EMBEDDING_LENGTH = 1024


def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    """Generate an image embedding and store it in S3 Vectors.

    Args:
        event: The Step Functions event. Required keys are ``collection_name``,
            ``image_key``, ``s3_bucket``, ``s3vector_bucket``, and
            ``date_added_epoch``.
        context: The Lambda context object (unused).

    Returns:
        The input ``event`` unchanged, so Step Functions can pass it to the
        next state.
    """
    collection_name = event["collection_name"]
    image_key = event["image_key"]
    s3_bucket = event["s3_bucket"]
    s3vector_bucket = event["s3vector_bucket"]
    date_added_epoch = int(event["date_added_epoch"])

    logger.info(
        "Generating embedding",
        collection_name=collection_name,
        image_key=image_key,
    )

    image_b64 = _fetch_image_base64(s3_bucket, image_key)
    embedding = _invoke_embedding_model(image_b64)

    _s3vectors().put_vectors(
        vectorBucketName=s3vector_bucket,
        indexName=_VECTOR_INDEX_NAME,
        vectors=[
            {
                "key": image_key,
                "data": {"float32": embedding},
                "metadata": {
                    "date_added_epoch": date_added_epoch,
                    "image_key": image_key,
                },
            }
        ],
    )

    logger.info(
        "Embedding stored",
        collection_name=collection_name,
        image_key=image_key,
    )

    # Pass-through: Step Functions forwards this to the next state unchanged.
    return event


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


def _invoke_embedding_model(image_b64: str) -> list[float]:
    """Invoke the Bedrock embedding model and parse the resulting vector.

    Args:
        image_b64: The base64-encoded image to embed.

    Returns:
        The embedding as a list of ``float`` values.
    """
    body = json.dumps(
        {
            "inputImage": image_b64,
            "embeddingConfig": {"outputEmbeddingLength": _EMBEDDING_LENGTH},
        }
    )
    response = _bedrock_runtime.invoke_model(modelId=config.EMBED_MODEL_ID, body=body)
    payload = json.loads(response["body"].read())
    embedding: list[float] = payload["embedding"]
    return embedding
