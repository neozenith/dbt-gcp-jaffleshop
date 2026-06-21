# syntax=docker/dockerfile:1
# ONE image for the whole dbt version-matrix suite, parametrised by build ARGs.
# tests/multiversion/test_multiversion.py builds it once per engine, passing that engine's buildargs.
# Every engine is a plain pip install of dbt-core + an adapter into an isolated venv — including the
# v2.0 alpha, which ships on PyPI as dbt-core==2.0.0a2 (no CDN installer, no Rust-binary branch). The
# build context (adaf_pkg/ + fixture/ + harness.py + this Dockerfile) is staged under tmp/ by the
# harness. Tier A: needs PyPI at build time.
#
# Build ARGs (all supplied by the harness's Engine.build_args()):
#   ENGINE_NAME        engine id, also baked as $ENGINE_NAME for harness.py          (e.g. dbt1-11-11)
#   DBT_CORE_SPEC      pip spec for dbt-core   (e.g. dbt-core==1.11.11)
#   DBT_ADAPTER_SPEC   pip spec for the adapter (e.g. dbt-duckdb==1.10.1)
#   PARSE_FLAGS        extra `dbt parse` flags baked for harness.py (e.g. --use-v2-parser)
#   ADAF_INSTALL_SPEC  adaf install target: /opt/adaf_pkg  or  /opt/adaf_pkg[fusion]
#   SELECTOR           adaf selector name the gates run under (matrix_demo)
#   PIP_PRERELEASE     uv --prerelease value: disallow | allow (allow for the beta/alpha pins)
FROM python:3.12-slim

ARG ENGINE_NAME
ARG DBT_CORE_SPEC
ARG DBT_ADAPTER_SPEC=dbt-duckdb==1.10.1
ARG PARSE_FLAGS=""
ARG ADAF_INSTALL_SPEC=/opt/adaf_pkg
ARG SELECTOR=matrix_demo
ARG PIP_PRERELEASE=disallow

# uv (pinned) builds both venvs. (curl/ca-certs no longer needed: every engine installs from PyPI.)
COPY --from=ghcr.io/astral-sh/uv:0.11.13 /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=automatic PYTHONUNBUFFERED=1 SHELL=/bin/sh

# adaf in its own Python 3.12 venv (adaf requires-python >=3.12), isolated from the dbt engine. The
# v2.0 alpha row passes /opt/adaf_pkg[fusion] so it can read a parquet artifact set; others pass
# /opt/adaf_pkg.
COPY adaf_pkg /opt/adaf_pkg
RUN uv venv --python 3.12 /opt/adaf-venv \
 && uv pip install --python /opt/adaf-venv/bin/python "${ADAF_INSTALL_SPEC}"

# The dbt engine — a dbt-core + adapter venv at /opt/dbt-venv. PIP_PRERELEASE=allow lets the beta/alpha
# pins resolve; a bad pin fails the build loudly (escalators-not-stairs: no silent skip, no fallback).
RUN uv venv --python 3.12 /opt/dbt-venv \
 && uv pip install --python /opt/dbt-venv/bin/python --prerelease="${PIP_PRERELEASE}" ${DBT_CORE_SPEC} ${DBT_ADAPTER_SPEC}

COPY fixture /fixture
COPY harness.py /harness.py

# The runtime contract harness.py reads. DBT_BIN / VERSION_PKGS are now invariant (every engine is a
# pip dbt-core+adapter venv), so they are baked directly rather than derived per engine. ADAF_PY is
# always the 3.12 adaf venv.
ENV ENGINE_NAME=${ENGINE_NAME} \
    DBT_BIN=/opt/dbt-venv/bin/dbt \
    ADAF_PY=/opt/adaf-venv/bin/python \
    PARSE_FLAGS=${PARSE_FLAGS} \
    SELECTOR=${SELECTOR} \
    VERSION_PKGS=dbt-core,dbt-duckdb

WORKDIR /fixture
ENTRYPOINT ["python", "/harness.py"]
