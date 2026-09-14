"""Administrative CLI to tear down an ImageNetOG Redux collection.

Deletes the per-collection resources that ``create_collection`` provisions
outside of Terraform (Terraform does not manage them, so ``terraform destroy``
leaves them behind):

1. The DynamoDB item in ``{env}-imagenetog-collections``.
2. The S3 Vectors index ``images`` and the vector bucket
   ``{env}-imagenetog-{collection_name}-vectors``.
3. The S3 image bucket ``{env}-imagenetog-{collection_name}-images`` (emptied
   first, including all object versions).

The operation is **idempotent**: resources that are already absent are skipped.
It is **destructive**, so it requires an explicit ``--yes`` flag (or an
interactive confirmation) before deleting anything.

Usage::

    python -m scripts.delete_collection --collection-name nature-2024 --env dev --yes
"""

import argparse
import sys

import boto3
from aws_lambda_powertools import Logger
from botocore.exceptions import ClientError

logger = Logger(service="delete_collection")

REGION = "us-east-1"
VECTOR_INDEX_NAME = "images"
VALID_ENVS = ("dev", "staging", "prod")


def _empty_and_delete_image_bucket(s3_client: object, bucket_name: str) -> None:
    """Empty (all versions) and delete the S3 image bucket, if it exists.

    Args:
        s3_client: A boto3 S3 client.
        bucket_name: The image bucket name to remove.
    """
    try:
        s3_client.head_bucket(Bucket=bucket_name)  # type: ignore[attr-defined]
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket", "NotFound"):
            logger.info("Image bucket already absent, skipping", bucket=bucket_name)
            return
        raise

    # Delete all object versions and delete markers, then the bucket itself.
    paginator = s3_client.get_paginator("list_object_versions")  # type: ignore[attr-defined]
    for page in paginator.paginate(Bucket=bucket_name):
        to_delete = [
            {"Key": obj["Key"], "VersionId": obj["VersionId"]}
            for group in ("Versions", "DeleteMarkers")
            for obj in page.get(group, [])
        ]
        if to_delete:
            s3_client.delete_objects(  # type: ignore[attr-defined]
                Bucket=bucket_name, Delete={"Objects": to_delete}
            )

    s3_client.delete_bucket(Bucket=bucket_name)  # type: ignore[attr-defined]
    logger.info("Deleted S3 image bucket", bucket=bucket_name)


def _delete_vector_bucket_and_index(s3vectors_client: object, bucket_name: str) -> None:
    """Delete the S3 Vectors index and vector bucket, if present.

    Args:
        s3vectors_client: A boto3 ``s3vectors`` client.
        bucket_name: The vector bucket name to remove.
    """
    # Delete the index first (a bucket with indexes cannot be removed).
    try:
        s3vectors_client.delete_index(  # type: ignore[attr-defined]
            vectorBucketName=bucket_name, indexName=VECTOR_INDEX_NAME
        )
        logger.info("Deleted S3 Vectors index", bucket=bucket_name, index=VECTOR_INDEX_NAME)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NotFoundException", "ConflictException"):
            logger.info("S3 Vectors index already absent, skipping", bucket=bucket_name)
        else:
            raise

    try:
        s3vectors_client.delete_vector_bucket(vectorBucketName=bucket_name)  # type: ignore[attr-defined]
        logger.info("Deleted S3 Vector bucket", bucket=bucket_name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NotFoundException":
            logger.info("S3 Vector bucket already absent, skipping", bucket=bucket_name)
        else:
            raise


def _delete_collection_record(
    dynamodb_resource: object, table_name: str, collection_name: str
) -> None:
    """Delete the DynamoDB collection record, if present (idempotent).

    Args:
        dynamodb_resource: A boto3 DynamoDB resource.
        table_name: The collections table name.
        collection_name: The collection identifier / partition key.
    """
    table = dynamodb_resource.Table(table_name)  # type: ignore[attr-defined]
    table.delete_item(Key={"collection_name": collection_name})
    logger.info(
        "Deleted collection record",
        table=table_name,
        collection_name=collection_name,
    )


def delete_collection(collection_name: str, env: str) -> None:
    """Delete all AWS resources for a collection (idempotent).

    Args:
        collection_name: The collection identifier.
        env: The deployment environment (``dev``, ``staging``, or ``prod``).
    """
    image_bucket = f"{env}-imagenetog-{collection_name}-images"
    vector_bucket = f"{env}-imagenetog-{collection_name}-vectors"
    collections_table = f"{env}-imagenetog-collections"

    s3_client = boto3.client("s3", region_name=REGION)
    s3vectors_client = boto3.client("s3vectors", region_name=REGION)
    dynamodb_resource = boto3.resource("dynamodb", region_name=REGION)

    logger.info("Deleting collection", collection_name=collection_name, env=env)

    # Order: DynamoDB record first (so a partially-deleted collection no longer
    # appears in listings), then vector resources, then the image bucket.
    _delete_collection_record(dynamodb_resource, collections_table, collection_name)
    _delete_vector_bucket_and_index(s3vectors_client, vector_bucket)
    _empty_and_delete_image_bucket(s3_client, image_bucket)

    logger.info("Collection deleted", collection_name=collection_name)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        The parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Delete an ImageNetOG Redux collection and its AWS resources.",
    )
    parser.add_argument("--collection-name", required=True, help="Collection name to delete.")
    parser.add_argument("--env", required=True, choices=VALID_ENVS, help="Deployment environment.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt (required for non-interactive use).",
    )
    return parser.parse_args(argv)


def _confirmed(collection_name: str, env: str, assume_yes: bool) -> bool:
    """Return True if the destructive delete is confirmed."""
    if assume_yes:
        return True
    prompt = (
        f"This will permanently delete collection '{collection_name}' in '{env}' "
        f"(image bucket, vector bucket + index, and DynamoDB record). Type the "
        f"collection name to confirm: "
    )
    try:
        return input(prompt).strip() == collection_name
    except (EOFError, OSError):
        # No readable stdin (non-interactive / captured) -> treat as not confirmed.
        return False


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code: ``0`` on success, ``1`` if not confirmed.
    """
    args = parse_args(argv)
    if not _confirmed(args.collection_name, args.env, args.yes):
        logger.warning("Deletion not confirmed; aborting", collection_name=args.collection_name)
        return 1
    delete_collection(args.collection_name, args.env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
