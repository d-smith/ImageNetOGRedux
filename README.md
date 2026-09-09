# ImageNetOG Redux

Before there was ImageNet, there was [ImageNet](https://ieeexplore.ieee.org/document/244984).

TODO: Text blurb setting the context for the original ImageNet PACS... context then, and how we'd reimagine building something its ilk today.

## Development

All Python tooling is pinned in `pyproject.toml` and installed into the project
virtualenv at `.venv/`. Activate it to drop the `.venv/bin/` prefix from the
commands below:

```bash
source .venv/bin/activate
```

The commands below assume you are in the repository root and show the explicit
`.venv/bin/` prefix so they work whether or not the virtualenv is activated.

### Running tests

Test configuration lives in `pyproject.toml` (`[tool.pytest.ini_options]`):
`testpaths` is set to `tests/unit` and `tests/property`, and coverage reporting
is enabled by default. Required Lambda environment variables and the
`src/` import path are set automatically by `tests/conftest.py`, so no manual
setup is needed.

Run the full suite:

```bash
.venv/bin/pytest
```

The property-based tests (under `tests/property/`) run 100 Hypothesis examples
each and take a couple of minutes. For fast iteration, run the unit tests only
and skip coverage:

```bash
.venv/bin/pytest tests/unit --no-cov -q
```

Run a single file or a single test:

```bash
.venv/bin/pytest tests/unit/test_error_handler.py --no-cov -q
.venv/bin/pytest tests/unit/test_router.py::TestMethodEnforcement --no-cov
```

Filter tests by keyword with `-k`:

```bash
.venv/bin/pytest tests/unit tests/property -k "error or param or router"
```

### Linting and formatting

Linting and formatting use [`ruff`](https://docs.astral.sh/ruff/):

```bash
.venv/bin/ruff check src/ tests/          # lint
.venv/bin/ruff format --check src/ tests/ # verify formatting (no changes written)
```

To apply fixes and formatting in place:

```bash
.venv/bin/ruff check --fix src/ tests/
.venv/bin/ruff format src/ tests/
```

### Type checking

Static type checking uses [`mypy`](https://mypy.readthedocs.io/) in strict mode:

```bash
.venv/bin/mypy --explicit-package-bases src/
```

> **Note:** `--explicit-package-bases` is required. Because `pyproject.toml`
> sets `mypy_path = "src"`, running a bare `mypy src/` makes each module
> resolvable under two names (e.g. `api_handler.foo` and `src.api_handler.foo`)
> and mypy aborts with a "source file found twice" error. The flag disambiguates
> the package root.


