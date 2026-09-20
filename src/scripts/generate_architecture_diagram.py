"""Generate the ImageNetOG Redux AWS architecture diagram as a draw.io file.

Emits a ``.drawio`` (draw.io / diagrams.net) XML document describing the
project's per-environment AWS topology. The output opens and edits natively in
draw.io — every node uses an AWS4 shape style, so the diagram is fully editable
node-by-node after generation.

The architecture is declared here as a **single source of truth** (the module
level ``NODES``, ``EDGES``, and ``GROUPS`` tables) rather than parsed from
Terraform. This keeps the model readable and stable: when the infrastructure
changes, update the tables below and re-run this script. The topology mirrors
the Terraform under ``terraform/modules/{auth,storage,api,ingestion}``:

Read path
    Client -> Cognito (token) -> API Gateway (Cognito authorizer, /v1/*) ->
    api-handler Lambda -> {DynamoDB, S3 image buckets (presigned),
    Bedrock Titan Embed, S3 Vectors (query)}.

Ingestion path (event-driven)
    S3 image upload -> EventBridge (Object Created) -> Step Functions ->
    parallel {embed Lambda -> Bedrock Titan Embed + S3 Vectors PutVectors;
    describe Lambda -> Bedrock Nova Lite} -> store Lambda -> DynamoDB images.

Usage::

    python -m scripts.generate_architecture_diagram
    python -m scripts.generate_architecture_diagram --output docs/architecture.drawio

The generated XML is validated (parsed back) before being written, so a
malformed document is never emitted.
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from aws_lambda_powertools import Logger

logger = Logger(service="generate_architecture_diagram")

DEFAULT_OUTPUT = "docs/architecture.drawio"

# AWS4 resource-icon fill colours (draw.io shape library palette), by service
# category, so related services share a colour.
_COMPUTE = "#ED7100"  # Lambda (orange)
_APP_INTEGRATION = "#E7157B"  # API Gateway, EventBridge, Step Functions (pink)
_DATABASE = "#4D72F3"  # DynamoDB (blue)
_STORAGE = "#7AA116"  # S3 / S3 Vectors (green)
_ML = "#01A88D"  # Bedrock (teal)
_SECURITY = "#DD344C"  # Cognito (red)
_GENERAL = "#232F3E"  # user / generic (dark slate)


@dataclass(frozen=True)
class Node:
    """A single diagram shape (AWS resource icon or actor).

    Attributes:
        node_id: Unique cell id, referenced by edges.
        label: Human-readable label (``\\n`` for line breaks).
        res_icon: AWS4 ``resIcon`` shape name (e.g. ``mxgraph.aws4.lambda``).
        fill: Icon fill colour hex.
        x: Left coordinate on the page.
        y: Top coordinate on the page.
        width: Shape width.
        height: Shape height.
    """

    node_id: str
    label: str
    res_icon: str
    fill: str
    x: int
    y: int
    width: int = 78
    height: int = 78


@dataclass(frozen=True)
class Edge:
    """A directed connector between two nodes.

    Attributes:
        source: Source node id.
        target: Target node id.
        label: Optional edge label.
        dashed: Whether the connector is drawn dashed.
    """

    source: str
    target: str
    label: str = ""
    dashed: bool = False


@dataclass(frozen=True)
class Group:
    """A labelled container boundary (e.g. the AWS Cloud / ingestion boundary).

    Attributes:
        group_id: Unique cell id.
        label: Boundary label.
        x: Left coordinate.
        y: Top coordinate.
        width: Boundary width.
        height: Boundary height.
        stroke: Border colour hex.
        dashed: Whether the border is dashed.
    """

    group_id: str
    label: str
    x: int
    y: int
    width: int
    height: int
    stroke: str = "#232F3E"
    dashed: bool = False


# ---------------------------------------------------------------------------
# Architecture model — the single source of truth. Update these tables when the
# Terraform topology changes, then re-run the script.
# ---------------------------------------------------------------------------
GROUPS: list[Group] = [
    Group("cloud", "AWS Cloud — us-east-1", 180, 70, 1360, 880, stroke="#232F3E"),
    Group(
        "ingestion-group",
        "Ingestion pipeline (event-driven)",
        220,
        640,
        1080,
        280,
        stroke="#5A6C86",
        dashed=True,
    ),
]

NODES: list[Node] = [
    # Actor
    Node("client", "API Client\n(Bruno / SDK / curl)", "mxgraph.aws4.user", _GENERAL, 40, 200),
    # Auth
    Node(
        "cognito",
        "Cognito User Pool\n+ App Client + Hosted UI\n(env-imagenetog-userpool)",
        "mxgraph.aws4.cognito",
        _SECURITY,
        240,
        120,
    ),
    # Edge / API
    Node(
        "apigw",
        "API Gateway (REST, Regional)\nstage = env, path /v1/*\nCognito authorizer + usage plan",
        "mxgraph.aws4.api_gateway",
        _APP_INTEGRATION,
        240,
        300,
    ),
    Node(
        "apihandler",
        "api-handler Lambda\n(Python 3.12)\n4 read routes",
        "mxgraph.aws4.lambda",
        _COMPUTE,
        440,
        300,
    ),
    # Read-path backends
    Node(
        "ddb-read",
        "DynamoDB\ncollections + images tables\n(GetItem/Query/Scan)",
        "mxgraph.aws4.dynamodb",
        _DATABASE,
        700,
        140,
    ),
    Node(
        "s3-read",
        "S3 image buckets\nenv-imagenetog-*-images\n(presigned GetObject)",
        "mxgraph.aws4.s3",
        _STORAGE,
        700,
        270,
    ),
    Node(
        "bedrock-embed-read",
        "Bedrock Titan Embed\n(query embedding)",
        "mxgraph.aws4.bedrock",
        _ML,
        700,
        400,
    ),
    Node(
        "s3vectors-read",
        "S3 Vectors buckets\nenv-imagenetog-*-vectors\n(QueryVectors/GetVectors)",
        "mxgraph.aws4.s3",
        _STORAGE,
        700,
        530,
    ),
    # Ingestion pipeline
    Node(
        "s3-upload",
        "S3 image bucket\n(image upload)\nEventBridge notifications on",
        "mxgraph.aws4.s3",
        _STORAGE,
        250,
        720,
    ),
    Node(
        "eventbridge",
        "EventBridge rule\nObject Created\n(.jpg/.jpeg/.png)",
        "mxgraph.aws4.eventbridge",
        _APP_INTEGRATION,
        400,
        720,
    ),
    Node(
        "sfn",
        "Step Functions\ningestion state machine",
        "mxgraph.aws4.step_functions",
        _APP_INTEGRATION,
        550,
        720,
    ),
    Node(
        "lambda-embed",
        "embed Lambda\nTitan Embed -> S3 Vectors",
        "mxgraph.aws4.lambda",
        _COMPUTE,
        720,
        660,
        width=70,
        height=70,
    ),
    Node(
        "lambda-describe",
        "describe Lambda\nNova Lite",
        "mxgraph.aws4.lambda",
        _COMPUTE,
        720,
        800,
        width=70,
        height=70,
    ),
    Node(
        "lambda-store",
        "store Lambda\nPutItem",
        "mxgraph.aws4.lambda",
        _COMPUTE,
        900,
        730,
        width=70,
        height=70,
    ),
    Node(
        "bedrock-ing",
        "Bedrock\nTitan Embed + Nova Lite",
        "mxgraph.aws4.bedrock",
        _ML,
        1050,
        660,
        width=70,
        height=70,
    ),
    Node(
        "s3vectors-write",
        "S3 Vectors\nPutVectors",
        "mxgraph.aws4.s3",
        _STORAGE,
        1050,
        780,
        width=70,
        height=70,
    ),
    Node(
        "ddb-write",
        "DynamoDB\nimages table (PutItem)",
        "mxgraph.aws4.dynamodb",
        _DATABASE,
        1050,
        900,
        width=70,
        height=70,
    ),
    # Observability
    Node(
        "logs",
        "CloudWatch Logs\n(all Lambdas + API GW access/exec logs, 30d)",
        "mxgraph.aws4.cloudwatch",
        _APP_INTEGRATION,
        1360,
        300,
        width=70,
        height=70,
    ),
]

EDGES: list[Edge] = [
    # Read path
    Edge("client", "cognito", "1. get ID token"),
    Edge("client", "apigw", "2. GET /v1/... (Authorization: token)"),
    Edge("apigw", "cognito", "validate token", dashed=True),
    Edge("apigw", "apihandler", "AWS_PROXY"),
    Edge("apihandler", "ddb-read", "read metadata"),
    Edge("apihandler", "s3-read", "presign GetObject"),
    Edge("apihandler", "bedrock-embed-read", "embed query"),
    Edge("apihandler", "s3vectors-read", "vector search"),
    # Ingestion path
    Edge("s3-upload", "eventbridge", "Object Created"),
    Edge("eventbridge", "sfn", "StartExecution"),
    Edge("sfn", "lambda-embed", "parallel"),
    Edge("sfn", "lambda-describe", "parallel"),
    Edge("sfn", "lambda-store", "then StoreMetadata"),
    Edge("lambda-embed", "bedrock-ing"),
    Edge("lambda-describe", "bedrock-ing", dashed=True),
    Edge("lambda-embed", "s3vectors-write", "PutVectors"),
    Edge("lambda-store", "ddb-write", "PutItem"),
]

TITLE = "ImageNetOG Redux — AWS Architecture (per-environment: dev / staging / prod)"

# draw.io group container style with a cloud-like outline.
_GROUP_STYLE = (
    "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],"
    "[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];"
    "outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;"
    "container=1;pointerEvents=0;collapsible=0;recursiveResize=0;"
    "shape=mxgraph.aws4.group;grStroke=1;strokeColor={stroke};fillColor=none;"
    "verticalAlign=top;fontColor={stroke};align=left;spacingLeft=30;dashed={dashed};"
)

_NODE_STYLE = (
    "sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor={fill};"
    "strokeColor=none;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;"
    "align=center;html=1;fontSize=11;aspect=fixed;"
    "shape=mxgraph.aws4.resourceIcon;resIcon={res_icon};"
)

_EDGE_STYLE = "endArrow=classic;html=1;fontSize=10;rounded=0;dashed={dashed};"


def _add_geometry(cell: ET.Element, x: int, y: int, width: int, height: int) -> None:
    """Attach an ``mxGeometry`` child to a cell element.

    Args:
        cell: The parent ``mxCell`` element.
        x: Left coordinate.
        y: Top coordinate.
        width: Cell width.
        height: Cell height.
    """
    geom = ET.SubElement(cell, "mxGeometry")
    geom.set("x", str(x))
    geom.set("y", str(y))
    geom.set("width", str(width))
    geom.set("height", str(height))
    geom.set("as", "geometry")


def build_diagram_xml() -> str:
    """Build the complete draw.io XML document from the architecture model.

    Returns:
        A pretty-printed, well-formed ``.drawio`` XML string.
    """
    mxfile = ET.Element("mxfile", {"host": "app.diagrams.net", "agent": "Kiro"})
    diagram = ET.SubElement(
        mxfile, "diagram", {"id": "imagenetog-redux-arch", "name": "ImageNetOG Redux Architecture"}
    )
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1400",
            "dy": "900",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "1600",
            "pageHeight": "1000",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")

    # Mandatory base layers.
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    # Title.
    title = ET.SubElement(
        root,
        "mxCell",
        {
            "id": "title",
            "value": TITLE,
            "style": (
                "text;html=1;strokeColor=none;fillColor=none;align=center;"
                "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=18;fontStyle=1;"
            ),
            "vertex": "1",
            "parent": "1",
        },
    )
    _add_geometry(title, 360, 16, 880, 30)

    # Group boundaries.
    for group in GROUPS:
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": group.group_id,
                "value": group.label,
                "style": _GROUP_STYLE.format(
                    stroke=group.stroke, dashed="1" if group.dashed else "0"
                ),
                "vertex": "1",
                "parent": "1",
            },
        )
        _add_geometry(cell, group.x, group.y, group.width, group.height)

    # Nodes.
    for node in NODES:
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": node.node_id,
                "value": node.label,
                "style": _NODE_STYLE.format(fill=node.fill, res_icon=node.res_icon),
                "vertex": "1",
                "parent": "1",
            },
        )
        _add_geometry(cell, node.x, node.y, node.width, node.height)

    # Edges.
    for index, edge in enumerate(EDGES):
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": f"edge-{index}",
                "value": edge.label,
                "style": _EDGE_STYLE.format(dashed="1" if edge.dashed else "0"),
                "edge": "1",
                "parent": "1",
                "source": edge.source,
                "target": edge.target,
            },
        )
        geom = ET.SubElement(cell, "mxGeometry")
        geom.set("relative", "1")
        geom.set("as", "geometry")

    ET.indent(mxfile, space="  ")
    xml_body = ET.tostring(mxfile, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_body}\n'


def _validate_references() -> None:
    """Verify every edge references a declared node id.

    Raises:
        ValueError: If any edge source/target is not a known node id.
    """
    node_ids = {node.node_id for node in NODES}
    for edge in EDGES:
        for endpoint in (edge.source, edge.target):
            if endpoint not in node_ids:
                raise ValueError(f"Edge references unknown node id: {endpoint!r}")


def generate(output_path: Path) -> int:
    """Generate the diagram and write it to ``output_path``.

    The generated XML is parsed back before writing to guarantee a well-formed
    document is never emitted.

    Args:
        output_path: Destination ``.drawio`` file path. Parent directories are
            created if missing.

    Returns:
        The number of nodes written (a positive count on success).

    Raises:
        ValueError: If the architecture model is internally inconsistent, or the
            generated XML fails to parse.
    """
    _validate_references()
    xml = build_diagram_xml()

    # Guarantee well-formedness before writing. The input to fromstring is XML
    # we just serialised ourselves (not untrusted external data), so the S314
    # XML-attack surface does not apply here.
    try:
        ET.fromstring(xml)  # noqa: S314
    except ET.ParseError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Generated XML is not well-formed: {exc}") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml, encoding="utf-8")

    logger.info(
        "Architecture diagram written",
        path=str(output_path),
        nodes=len(NODES),
        edges=len(EDGES),
        groups=len(GROUPS),
    )
    return len(NODES)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        The parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Generate the ImageNetOG Redux AWS architecture diagram (draw.io).",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output .drawio file path (default: {DEFAULT_OUTPUT}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code ``0`` on success.
    """
    args = parse_args(argv)
    generate(Path(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
