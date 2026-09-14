"""Administrative CLI to list ImageNetOG Redux collections and find orphans.

Read-only. Reports, for a given environment:

* Collections registered in the ``{env}-imagenetog-collections`` DynamoDB table.
* Per-collection S3 image buckets (``{env}-imagenetog-*-images``) and S3 Vectors
  buckets (``{env}-imagenetog-*-vectors``) that exist in the account.
* **Orphans** — buckets that exist but have no matching DynamoDB record. These
  are the resources left behind after ``terraform destroy`` (which removes the
  collections table but not the per-collection buckets) or after a partial
  ``create_collection`` failure. Use ``delete_collection.py`` to reclaim them.

Usage::

    python -m scripts.list_collections --env dev

Note: if the collections table has been destroyed (e.g. after
``terraform destroy``), the DynamoDB lookup is reported as unavailable and every
discovered bucket is treated as an orphan.
"""

import argparse
import re
import sys

import boto3
from aws_lambda_powertools import Logger
from botocore.exceptions import ClientError

logger = Logger(service="list_collections")

REGION = "us-east-1"
VALID_ENVS = ("dev", "staging", "prod")


def _registered_collections(dynamodb_resource: object, table_name: str) -> set[str] | None:
    """Return the set of collection names in the table, or None if unavailable.

    Args:
        dynamodb_resource: A boto3 DynamoDB resource.
        table_name: The collections table name.

    Returns:
        A set of collection names, or ``None`` if the table does not exist
        (e.g. after ``terraform destroy``).
    """
    table = dynamodb_resource.Table(table_name)  # type: ignore[attr-defined]
    names: set[str] = set()
    try:
        scan_kwargs: dict[str, object] = {"ProjectionExpression": "collection_name"}
        while True:
            response = table.scan(**scan_kwargs)
            names.update(str(item["collection_name"]) for item in response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if last_key is None:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            return None
        raise
    return names


def _bucket_collections(s3_client: object, env: str) -> dict[str, set[str]]:
    """Discover collection names implied by existing per-collection buckets.

    Args:
        s3_client: A boto3 S3 client.
        env: The deployment environment.

    Returns:
        A mapping ``{"images": {names...}, "vectors": {names...}}`` of the
        collection names extracted from bucket names for each bucket kind.
    """
    images_re = re.compile(rf"^{re.escape(env)}-imagenetog-(?P<name>.+)-images$")
    vectors_re = re.compile(rf"^{re.escape(env)}-imagenetog-(?P<name>.+)-vectors$")

    found: dict[str, set[str]] = {"images": set(), "vectors": set()}
    for bucket in s3_client.list_buckets().get("Buckets", []):  # type: ignore[attr-defined]
        name = bucket["Name"]
        if m := images_re.match(name):
            found["images"].add(m.group("name"))
        elif m := vectors_re.match(name):
            found["vectors"].add(m.group("name"))
    return found


def list_collections(env: str) -> int:
    """Print a report of collections and orphaned buckets for ``env``.

    Args:
        env: The deployment environment.

    Returns:
        The number of orphaned bucket-implied collections found (``0`` when the
        environment is clean).
    """
    collections_table = f"{env}-imagenetog-collections"
    s3_client = boto3.client("s3", region_name=REGION)
    dynamodb_resource = boto3.resource("dynamodb", region_name=REGION)

    registered = _registered_collections(dynamodb_resource, collections_table)
    buckets = _bucket_collections(s3_client, env)
    bucket_names = buckets["images"] | buckets["vectors"]

    if registered is None:
        logger.warning(
            "Collections table not found; treating all discovered buckets as orphans",
            table=collections_table,
        )
        registered = set()

    orphans = sorted(bucket_names - registered)

    logger.info(
        "Collection report",
        env=env,
        registered=sorted(registered),
        image_buckets=sorted(buckets["images"]),
        vector_buckets=sorted(buckets["vectors"]),
        orphans=orphans,
    )

    if orphans:
        logger.warning(
            "Orphaned buckets found (exist without a DynamoDB record); "
            "reclaim with delete_collection.py",
            orphans=orphans,
        )
    return len(orphans)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        The parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="List ImageNetOG Redux collections and find orphaned buckets.",
    )
    parser.add_argument("--env", required=True, choices=VALID_ENVS, help="Deployment environment.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code ``0`` (the report always succeeds; orphan count is
        logged, not returned as a failure code).
    """
    args = parse_args(argv)
    list_collections(args.env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
