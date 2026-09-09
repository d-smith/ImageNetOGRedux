"""Administrative CLI to provision a new ImageNetOG Redux collection.

Given a collection name and target environment, this script creates:

1. The S3 image bucket ``{env}-imagenetog-{collection_name}-images``.
2. The S3 Vector bucket ``{env}-imagenetog-{collection_name}-vectors``.
3. The S3 Vectors index ``images`` (cosine distance, 1024-dim, float32) within
   the vector bucket, with all metadata keys filterable.
4. The DynamoDB item in ``{env}-imagenetog-collections`` describing the
   collection.

All resources are created in ``us-east-1`` (the project's fixed region).

Usage::

    python -m scripts.create_collection --collection-name nature-2024 --env dev
"""

import argparse
import re
import sys
from datetime import UTC, datetime

import boto3
from aws_lambda_powertools import Logger

logger = Logger(service="create_collection")

# Region is fixed for this project (see terraform-conventions steering).
REGION = "us-east-1"

# Fixed S3 Vectors index configuration shared by every collection.
VECTOR_INDEX_NAME = "images"
VECTOR_DIMENSION = 1024
VECTOR_DATA_TYPE = "float32"
VECTOR_DISTANCE_METRIC = "cosine"

# Collection name: lowercase alphanumeric + hyphens, 3-48 characters, must
# start and end with an alphanumeric character.
COLLECTION_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,46}[a-z0-9]$")

VALID_ENVS = ("dev", "staging", "prod")


def validate_collection_name(collection_name: str) -> None:
    """Validate a collection name against the project naming rules.

    Args:
        collection_name: The candidate collection name.

    Raises:
        ValueError: If the name is not 3-48 characters of lowercase
            alphanumerics and hyphens, starting and ending with an
            alphanumeric character.
    """
    if not COLLECTION_NAME_PATTERN.match(collection_name):
        raise ValueError(
            f"Invalid collection name '{collection_name}': must be 3-48 characters, "
            "lowercase alphanumeric and hyphens only, and must start and end with "
            "an alphanumeric character (pattern: ^[a-z0-9][a-z0-9-]{1,46}[a-z0-9]$)."
        )


def create_image_bucket(s3_client: object, bucket_name: str) -> None:
    """Create the S3 image bucket for a collection in ``us-east-1``.

    Args:
        s3_client: A boto3 S3 client.
        bucket_name: The image bucket name to create.
    """
    # us-east-1 must not supply a LocationConstraint (AWS API requirement).
    s3_client.create_bucket(Bucket=bucket_name)  # type: ignore[attr-defined]
    logger.info("Created S3 image bucket", bucket=bucket_name)


def create_vector_bucket_and_index(s3vectors_client: object, bucket_name: str) -> None:
    """Create the S3 Vector bucket and its ``images`` index for a collection.

    Args:
        s3vectors_client: A boto3 ``s3vectors`` client.
        bucket_name: The vector bucket name to create.
    """
    s3vectors_client.create_vector_bucket(vectorBucketName=bucket_name)  # type: ignore[attr-defined]
    logger.info("Created S3 Vector bucket", bucket=bucket_name)

    s3vectors_client.create_index(  # type: ignore[attr-defined]
        vectorBucketName=bucket_name,
        indexName=VECTOR_INDEX_NAME,
        dataType=VECTOR_DATA_TYPE,
        dimension=VECTOR_DIMENSION,
        distanceMetric=VECTOR_DISTANCE_METRIC,
        # Empty list => no metadata keys are non-filterable, i.e. all keys are
        # filterable by default.
        metadataConfiguration={"nonFilterableMetadataKeys": []},
    )
    logger.info(
        "Created S3 Vectors index",
        bucket=bucket_name,
        index=VECTOR_INDEX_NAME,
        dimension=VECTOR_DIMENSION,
    )


def write_collection_record(
    dynamodb_resource: object,
    table_name: str,
    collection_name: str,
    s3_bucket: str,
    s3vector_bucket: str,
) -> None:
    """Write the collection metadata item to the collections table.

    Args:
        dynamodb_resource: A boto3 DynamoDB resource.
        table_name: The collections table name.
        collection_name: The collection identifier (also the partition key).
        s3_bucket: The image bucket name (internal field).
        s3vector_bucket: The vector bucket name (internal field).
    """
    now = datetime.now(UTC)
    created = now.date().isoformat()
    created_epoch = int(now.timestamp())

    table = dynamodb_resource.Table(table_name)  # type: ignore[attr-defined]
    table.put_item(
        Item={
            "collection_name": collection_name,
            "created": created,
            "created_epoch": created_epoch,
            "_type": "COLLECTION",
            "s3_bucket": s3_bucket,
            "s3vector_bucket": s3vector_bucket,
        }
    )
    logger.info(
        "Wrote collection record",
        table=table_name,
        collection_name=collection_name,
        created=created,
    )


def create_collection(collection_name: str, env: str) -> None:
    """Provision all AWS resources for a new collection.

    Args:
        collection_name: The collection identifier.
        env: The deployment environment (``dev``, ``staging``, or ``prod``).

    Raises:
        ValueError: If ``collection_name`` fails validation.
    """
    validate_collection_name(collection_name)

    image_bucket = f"{env}-imagenetog-{collection_name}-images"
    vector_bucket = f"{env}-imagenetog-{collection_name}-vectors"
    collections_table = f"{env}-imagenetog-collections"

    s3_client = boto3.client("s3", region_name=REGION)
    s3vectors_client = boto3.client("s3vectors", region_name=REGION)
    dynamodb_resource = boto3.resource("dynamodb", region_name=REGION)

    logger.info(
        "Creating collection",
        collection_name=collection_name,
        env=env,
    )

    create_image_bucket(s3_client, image_bucket)
    create_vector_bucket_and_index(s3vectors_client, vector_bucket)
    write_collection_record(
        dynamodb_resource,
        collections_table,
        collection_name,
        image_bucket,
        vector_bucket,
    )

    logger.info("Collection created successfully", collection_name=collection_name)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        The parsed argument namespace with ``collection_name`` and ``env``.
    """
    parser = argparse.ArgumentParser(
        description="Provision a new ImageNetOG Redux collection.",
    )
    parser.add_argument(
        "--collection-name",
        required=True,
        help="Collection name (lowercase alphanumeric and hyphens, 3-48 chars).",
    )
    parser.add_argument(
        "--env",
        required=True,
        choices=VALID_ENVS,
        help="Deployment environment.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code: ``0`` on success, ``2`` on validation error.
    """
    args = parse_args(argv)
    try:
        create_collection(args.collection_name, args.env)
    except ValueError as exc:
        logger.error("Validation failed", reason=str(exc))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
