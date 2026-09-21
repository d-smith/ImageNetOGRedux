# Multi-Region Global Distribution — Analysis

> **Status: analysis only.** This document explores what it would take to run
> ImageNetOG Redux across multiple AWS regions. It is **not** a commitment to
> build, and describing a file as "affected" here means *it would need to
> change if we did this* — nothing in this document changes any code,
> Terraform, config, or steering.

## 1. Context & scope

Today the system runs in a single region (`us-east-1`). "Global distribution"
in this analysis means:

- A user's read requests (list collections, list/search images, get a presigned
  URL) are served from a region **close to them**, not always from `us-east-1`.
- The two data stores the read path depends on — the DynamoDB metadata tables
  and the per-collection **S3 Vectors** index — are present and queryable
  **locally in each region**.
- The event-driven **ingestion** pipeline (embed → describe → store) runs so
  that every region's local vector index and metadata are populated.

The central design question this document answers: the user proposed using
**S3 Cross-Region Replication (CRR) of the image bucket** as the fan-out
mechanism — replicate the raw image to each region and let the replication
event in each region drive local ingestion. This document evaluates that
proposal, compares it to an application-layer fan-out alternative, weighs the
two replication topologies, and enumerates the components each phase touches.

## 2. Current single-region assumptions

The project is single-region by deliberate design, and the assumption is baked
in at several layers:

- **Region is fixed to `us-east-1`, not merely defaulted.**
  - Each environment's `provider "aws"` block pins the region (dev via
    `var.aws_region`, staging/prod hardcoded).
  - `src/scripts/create_collection.py` defines `REGION = "us-east-1"` and
    creates all three boto3 clients (`s3`, `s3vectors`, `dynamodb`) with
    `region_name=REGION`.
  - The README bootstrap/deploy commands pass `--region us-east-1`.
  - `.kiro/steering/terraform-conventions.md` states the region is always
    `us-east-1`.

- **The naming convention has no region dimension.** Every resource is named
  `{env}-imagenetog-{descriptor}`:

  | Resource | Name pattern |
  |---|---|
  | DynamoDB collections table | `{env}-imagenetog-collections` |
  | DynamoDB images table | `{env}-imagenetog-images` |
  | Image bucket (per collection) | `{env}-imagenetog-{collection}-images` |
  | Vector bucket (per collection) | `{env}-imagenetog-{collection}-vectors` |

  Because **S3 bucket names are globally unique**, the same bucket name cannot
  exist in two regions. This is the central obstacle to going multi-region.

- **Bucket names are stored as data in DynamoDB and trusted downstream.** The
  `s3_bucket` and `s3vector_bucket` fields are written into the collection
  record by `create_collection.py::write_collection_record`, then read back and
  used verbatim:
  - **Read path** — `src/api_handler/services/images.py::_get_collection_record`
    returns the stored `s3vector_bucket`, passed directly to
    `s3vectors.query_vectors(vectorBucketName=...)`; `s3_bucket` is passed to
    `generate_presigned_url`.
  - **Write path** — `src/ingestion/event_utils.py` derives `s3vector_bucket`
    by regex-reparsing the image bucket name:
    `_IMAGE_BUCKET_RE = ^(?P<env>dev|staging|prod)-imagenetog-(?P<name>.+)-images$`.

  Since a global table replicates *values verbatim*, every region would read the
  same scalar bucket name — a name that physically exists in only one region.

- **DynamoDB clients are region-agnostic (this helps).**
  `services/images.py` and `services/collections.py` create
  `boto3.resource("dynamodb")` with **no region**, so they bind to the Lambda's
  own region. A Lambda deployed in another region with a global-table replica
  there reads locally with **zero code change**.

- **S3 Vectors is a hard regional dependency with no CRR primitive.** S3 Vectors
  buckets are not standard S3 buckets — `src/scripts/list_collections.py` notes
  they do not appear in `s3:ListBuckets`, and there is no cross-region
  replication for them. Populating a regional vector index means **running the
  embed step in that region** (or copying vectors out-of-band), not flipping a
  replication toggle.

## 3. Target architecture

A multi-region deployment would consist of:

- **DynamoDB global table** for both the collections and images tables, so
  metadata records replicate to every region automatically. The API's
  region-agnostic DynamoDB clients then read the local replica for free.
- **Per-region API + ingestion stacks** — API Gateway, the api-handler Lambda,
  the ingestion Step Functions state machine, the three ingestion Lambdas, and
  the EventBridge rule, all deployed into each region.
- **Per-region S3 Vectors indexes** — each region has its own vector bucket and
  `images` index, populated by that region's ingestion pipeline.
- **A routing layer** (Route 53 latency/geo routing, or a Multi-Region Access
  Point) directing clients to the nearest healthy region.

The read path is then fully local in each region: local DynamoDB replica + local
S3 Vectors index + local image bucket for presigned URLs.

## 4. Primary proposal — CRR as the ingestion fan-out

**The idea:** enable S3 Cross-Region Replication on the per-collection image
bucket so the raw image lands in a bucket in each region. An object that arrives
via replication emits its **own** `s3:ObjectCreated:*` event (surfaced through
EventBridge as `Object Created`) in the destination region. Because ingestion is
already triggered by exactly that event, the identical rule and pipeline fire
locally in each region — each region embeds, describes, and stores against its
**own** local vector bucket and metadata, with **no new processing logic**.

This fits the existing architecture well. The ingestion write path already
derives everything it needs at runtime from the bucket name and the current
date (`enrich_event`), and does not depend on where the upload originated. The
EventBridge rule matches on the bucket-name prefix and image key suffix, both of
which a replica preserves.

### Mechanics that must line up

1. **Region-aware bucket naming.** A replica cannot reuse the globally-unique
   name `{env}-imagenetog-{collection}-images`; it needs a region-scoped name.
   But `enrich_event`'s regex is anchored to the current pattern and would fail
   to match (or fold the region into the collection name). So the naming scheme
   **and** the regex/derivation must become region-aware. See the two
   resolution strategies below.

2. **EventBridge notifications on every replica bucket.**
   `create_collection.py::create_image_bucket` enables
   `put_bucket_notification_configuration(...EventBridgeConfiguration...)` only
   on the bucket it creates. Each regional replica needs the same setting, or
   its `Object Created` events never reach EventBridge and local ingestion never
   fires.

3. **S3 does not replicate replicas by default (no chained replication).** An
   object that itself arrived via replication is not re-replicated onward unless
   explicitly configured, and even then the intent is metadata sync, not
   third-hop fan-out. This makes the **replication topology** a deliberate
   choice (see §6), not an afterthought.

4. **Per-region ingestion stack + Bedrock enablement.** The ingestion module
   (Lambdas, Step Functions, EventBridge rule, IAM roles) must be deployed in
   every region, and the Bedrock models it calls (Titan multimodal embeddings,
   Nova Lite) must be enabled in each region.

5. **Idempotency is already in our favor.** `ingestion_store` does an idempotent
   `put_item`, and `ingestion_embed` does `put_vectors` keyed by `image_key`
   (an idempotent overwrite), so re-delivery within a region is safe.

6. **N× embed/describe cost.** Because each region processes independently, the
   Bedrock embed **and** describe calls run once **per region**. This is the
   fundamental tradeoff: S3 Vectors has no replication primitive, so we trade
   "replicate the derived vector once" (not possible) for "recompute the vector
   everywhere" (which the event-driven design makes trivial). Cost scales
   roughly linearly with region count.

7. **Per-region description divergence.** The `describe` branch calls Nova Lite,
   which is non-deterministic. Each region generates its own description
   independently, so the stored `description` for the same image can differ
   across regions. Embeddings (Titan) are effectively deterministic and should
   match closely; the free-text description is the field that visibly diverges.

8. **Dual asynchronous replication lag, with graceful read-path degradation.**
   Two independent async replications are now in flight per region: S3 CRR (the
   image bytes) and the DynamoDB global table (the metadata). They land at
   slightly different times, plus the local vector is written by local
   ingestion. The read path already tolerates some skew:
   - `services/images.py::_batch_get_images` silently drops vector-search keys
     that have no matching DynamoDB record, so a "vector present, metadata not
     yet replicated" race degrades to **fewer results**, not an error.
   - The reverse race (metadata present, image bytes not yet replicated) only
     bites when a presigned URL is fetched before the object lands in the local
     image bucket.

### Bucket-name resolution strategies

Both strategies preserve the security invariant that the bucket name used comes
from a **confirmed** collection record, never from raw caller input.

- **Option A — store a region-agnostic identifier, derive the local bucket at
  runtime.** Keep DynamoDB storing only the collection identity, and have the
  code compute the local bucket from the Lambda's own region, e.g.
  `{env}-{region}-imagenetog-{collection}-vectors`. Every region self-resolves
  to its local bucket. Keeps the global table clean (no per-region names to keep
  consistent). Requires changing the naming convention, `create_collection.py`
  (create buckets in N regions), `event_utils.py` (regex + derivation), and the
  read path to *derive rather than read* the bucket name.

- **Option B — store a region → bucket map in the record.** Replace the scalar
  `s3_bucket` / `s3vector_bucket` with a map such as
  `{"us-east-1": "...", "eu-west-1": "..."}`, and have each region select its
  own entry. More explicit and tolerant of irregular naming, but more data to
  keep consistent and a slightly more involved lookup.

Option A is cleaner and carries less consistency burden; Option B is more
explicit and flexible. Both keep "the bucket name comes from the confirmed
record" intact — Option B simply indexes that record by region.

## 5. Alternative — application-layer fan-out

Instead of CRR-driven per-region ingestion, the `embed` Lambda could embed the
image **once** and write the resulting vector to **every** region's S3 Vectors
index in a single invocation (one `invoke_model`, N `put_vectors` calls). Raw
images would still need to exist locally in each region for presigned URLs
(so some image replication is still required), and metadata would still flow via
the DynamoDB global table.

| Dimension | CRR-driven (proposal) | App-layer fan-out |
|---|---|---|
| Embed/describe cost | N× (recomputed per region) | 1× |
| Bytes moved | Full image to each region (CRR) | Full image to each region (still needed for presigned URLs) + vectors to each region |
| Coupling | Fully decoupled; each region self-contained | `embed` Lambda must know all regions and hold cross-region S3 Vectors permissions |
| Failure isolation | A down region simply lags, then catches up when CRR resumes | One Lambda must succeed across all regions, or partially fail and require compensation |
| Description consistency | Diverges per region (Nova Lite) | Identical (computed once) |
| Complexity | Provisioning: buckets + notifications + ingestion stack per region | Cross-region IAM + retry/partial-failure logic concentrated in one function |

The CRR approach **wins** on decoupling, failure isolation, and architectural
consistency (it preserves the "an S3 event drives a local pipeline" grain). It
**loses** on cost (recompute everywhere) and description consistency. The
app-layer approach inverts those tradeoffs.

## 6. Replication topologies

- **Hub-and-spoke.** One primary bucket (where all users upload) replicates to N
  regional read-replica buckets. Simple and safe: a single, unambiguous source
  of truth, one-directional replication, no loop risk. The cost is upload
  latency for users far from the primary — though **processing** still happens
  locally in every region, so *reads* are fast everywhere regardless.

- **Active-active.** Any region can accept uploads. This needs Multi-Region
  Access Points and/or bidirectional CRR, and bidirectional replication requires
  care: S3 does not forward replicas by default, so you must reason carefully
  about replica-modification settings and loop avoidance. Materially more
  complex to configure and operate.

**Recommendation.** Start with **hub-and-spoke** as the pragmatic default. It
delivers the primary goal — fast, local reads and search in every region — with
the least operational risk, and it keeps the "single source of truth for
uploads" model that matches the current single-writer design. Adopt
**active-active** only when local **write/upload** latency becomes a real
requirement (e.g. large uploads from users far from the hub), and budget for the
extra MRAP/bidirectional-CRR configuration and loop-avoidance testing that
entails.

## 7. Affected components by phase

### Phase 1 — Region-aware foundation

Make names and lookups region-aware before anything is deployed to a second
region.

- `.kiro/steering/terraform-conventions.md` — revise the naming convention to
  add a region dimension; relax the "region is always us-east-1" rule.
- `src/scripts/create_collection.py` — parameterize region; create image and
  vector buckets in each target region; region-aware names.
- `src/scripts/delete_collection.py` — tear down per-region resources.
- `src/scripts/list_collections.py` — region-aware orphan discovery.
- `src/ingestion/event_utils.py` — update `_IMAGE_BUCKET_RE` and the
  `s3vector_bucket` derivation to be region-aware (resolve to the **local**
  bucket).
- `src/api_handler/services/images.py` — resolve the vector/image bucket by
  **deriving or mapping** (Option A or B in §4) instead of trusting the stored
  scalar.
- `terraform/modules/ingestion/iam.tf` — the `s3:GetObject` ARN
  (`{env}-imagenetog-*-images/*`), the Bedrock ARNs (`:{region}::foundation-model/...`),
  and the s3vectors write ARNs (`:{region}:{account}:bucket/{env}-imagenetog-*-vectors[/index/*]`)
  must accommodate region-scoped names and per-region deployment.
- `terraform/environments/dev/main.tf` and `terraform/environments/prod/main.tf`
  — the admin policy's bucket/vector-creation ARN patterns.
- `.kiro/steering/security-patterns.md` — the documented role boundaries and
  ARN patterns reflecting region-scoped names.

### Phase 2 — DynamoDB global table + multi-region reads

- `terraform/modules/storage/main.tf` — add global-table replica configuration
  for the collections and images tables.
- Environment roots / provider aliases — introduce per-region providers (or a
  region dimension in the env roots) so resources can be created in each region.
- Deploy the API stack (`terraform/modules/api`) into each region; the
  region-agnostic DynamoDB clients then read locally with no code change.

### Phase 3 — CRR + per-region ingestion

- Image-bucket CRR configuration (replication role, rules, destination buckets)
  — likely added where per-collection buckets are provisioned
  (`create_collection.py`) and/or a new Terraform surface.
- EventBridge notifications enabled on **every** replica image bucket (mirror
  the `EventBridgeConfiguration` step from `create_collection.py`).
- Deploy `terraform/modules/ingestion` into each region (Step Functions,
  Lambdas, EventBridge rule, roles).
- Bedrock model enablement (Titan embed, Nova Lite) in each region.
- `terraform/versions.tf` and the env roots — accommodate a region dimension.

### Phase 4 — Routing & validation

- Route 53 latency/geo routing, or a Multi-Region Access Point, to direct
  clients to the nearest healthy region.
- Multi-region integration tests under `tests/integration/` — assert that an
  image uploaded to the hub becomes searchable in each region, and that reads
  are served locally.

## 8. Open questions & risks

- **N× Bedrock cost.** The CRR-driven approach recomputes embeddings and
  descriptions in every region. Confirm the cost multiplier is acceptable versus
  the app-layer "embed once, fan out vectors" alternative.
- **Description divergence.** Nova Lite is non-deterministic, so the stored
  `description` can differ per region. Decide whether descriptions are
  acceptably region-local, or must be computed once and propagated (which erodes
  the per-region independence that makes CRR fan-out attractive).
- **Consistency during replication lag.** S3 CRR, DynamoDB global-table
  replication, and local vector writes are independent and asynchronous. The
  read path degrades gracefully for the common races, but define acceptable
  staleness windows and whether any read needs stronger guarantees.
- **Cognito multi-region strategy.** Decide between a single user pool whose
  tokens are validated by per-region authorizers versus a multi-region pool
  strategy; token validation, hosted UI, and app-client configuration all need a
  regional story.
- **S3 Vectors regional availability.** S3 Vectors is comparatively new; confirm
  it is available in every target region before committing to a topology.
