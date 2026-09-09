"""``ingestion_store`` Lambda handler.

Writes the complete image metadata record to the DynamoDB images table and
emits the ``IngestionSuccess`` CloudWatch metric. This is the final step of
the Step Functions ingestion workflow.
"""

from typing import Any

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.metrics import Metrics, MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

from ingestion import config

logger = Logger()
metrics = Metrics(namespace="ImageNetOGRedux", service="ingestion")

# Module-level resource (reused across warm invocations, per project standards).
_dynamodb = boto3.resource("dynamodb")
_images_table = _dynamodb.Table(config.IMAGES_TABLE)


@metrics.log_metrics
def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    """Persist the image metadata record and emit the success metric.

    Args:
        event: The Step Functions event. Required keys are ``collection_name``,
            ``image_key``, ``s3_bucket``, ``s3vector_bucket``, ``date_added``,
            and ``date_added_epoch``. The optional ``description`` key is
            stored as-is (may be ``None``).
        context: The Lambda context object (unused).

    Returns:
        The input ``event`` unchanged.
    """
    collection_name = event["collection_name"]
    image_key = event["image_key"]

    item: dict[str, Any] = {
        "collection_name": collection_name,
        "image_key": image_key,
        "date_added": event["date_added"],
        "date_added_epoch": int(event["date_added_epoch"]),
        "description": event.get("description"),
        "s3_bucket": event["s3_bucket"],
        "s3vector_bucket": event["s3vector_bucket"],
    }

    _images_table.put_item(Item=item)

    metrics.add_metric(name="IngestionSuccess", unit=MetricUnit.Count, value=1)
    logger.info(
        "Image metadata stored",
        collection_name=collection_name,
        image_key=image_key,
    )

    return event
