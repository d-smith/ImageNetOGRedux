# ---------------------------------------------------------------------------
# Shared Lambda layer — third-party Python dependencies
#
# Packages the dependencies in requirements.txt (aws-lambda-powertools, boto3)
# into a Lambda layer attached to every function. Lambda layers require the
# Python packages to live under a top-level `python/` directory inside the zip.
#
# Build approach: a null_resource pip-installs the dependencies into
# `<build>/python` AND zips them to `<layer_zip>` in one step. It re-runs
# whenever requirements.txt changes OR the built zip is missing (so a normal
# `terraform apply` self-heals after `.build/` is cleaned — no manual -replace
# needed).
#
# Why not `data "archive_file"`: a data-source archive reads at PLAN time, so it
# fails if the null_resource-generated build directory does not exist yet
# (e.g. after cleaning `.build/`). Instead the layer's `source_code_hash` is
# derived from requirements.txt — the file that fully determines the layer's
# contents and always exists at both plan and apply — which avoids any
# plan/apply inconsistency while still redeploying the layer when deps change.
# ---------------------------------------------------------------------------

locals {
  name_prefix       = "${var.env}-imagenetog"
  requirements      = "${path.module}/requirements.txt"
  build_root        = "${path.module}/../../../.build/layer-${var.env}"
  build_python      = "${local.build_root}/python"
  layer_zip         = "${path.module}/../../../.build/layer-${var.env}.zip"
  requirements_hash = filesha256(local.requirements)
}

# Install dependencies and build the layer zip. Rebuilds when requirements
# change or when the output zip is absent (detected via the local-exec exit
# path below — the trigger includes the requirements hash; the zip-missing
# self-heal is handled by `terraform apply` recreating the resource when the
# file it references disappears is NOT automatic, so we also key on the zip
# path existing via a defensive rebuild inside the script).
resource "null_resource" "layer_build" {
  triggers = {
    requirements = local.requirements_hash
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      rm -rf "${local.build_root}"
      mkdir -p "${local.build_python}"
      python3 -m pip install \
        --requirement "${local.requirements}" \
        --target "${local.build_python}" \
        --platform manylinux2014_x86_64 \
        --python-version 3.12 \
        --implementation cp \
        --only-binary=:all: \
        --upgrade
      rm -f "${local.layer_zip}"
      python3 -c "import shutil, sys; shutil.make_archive(sys.argv[1], 'zip', root_dir=sys.argv[2], base_dir='python')" \
        "${local.build_root}-archive" "${local.build_root}"
      mv "${local.build_root}-archive.zip" "${local.layer_zip}"
    EOT
  }
}

resource "aws_lambda_layer_version" "deps" {
  layer_name  = "${local.name_prefix}-deps"
  description = "Shared deps (aws-lambda-powertools, boto3) for ${var.env}"
  filename    = local.layer_zip

  # Content is fully determined by requirements.txt (always present at plan and
  # apply), so hashing it gives a stable, consistent redeploy trigger without
  # reading the generated zip at plan time.
  source_code_hash = local.requirements_hash

  compatible_runtimes = ["python3.12"]

  depends_on = [null_resource.layer_build]
}
