# syntax=docker/dockerfile:1.7
#
# The Clayzer Harness as an Amazon Bedrock AgentCore Runtime. AgentCore runs ARM64 containers and
# talks to this one over HTTP on port 8080 (`GET /ping`, `POST /invocations`).
#
# Build from the repo root (infra/agentcore_app.py does this for you):
#   docker buildx build --platform linux/arm64 -f infra/agentcore/Dockerfile --build-arg BUILD=$(git rev-parse --short HEAD) .
#
# It holds only what a Run needs: the Harness code, the ontology, and boto3 plus the MCP client.
# No Cases, Chips, Reference Labels, scorers, or web app go in (ADR-0006), and the Runtime's IAM
# role can't reach the store either.
ARG BASE_IMAGE=public.ecr.aws/docker/library/python:3.12-slim
FROM --platform=linux/arm64 ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy
WORKDIR /app
# Hash-pinned (see requirements.in). `uv` is here so MCP servers launched with uvx (RODA) work.
COPY infra/agentcore/requirements.txt ./
RUN --mount=type=secret,id=pip_index,required=false \
    --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/pip_index ]; then export PIP_INDEX_URL="$(cat /run/secrets/pip_index)"; fi; \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install --no-cache-dir --require-hashes -r requirements.txt
# Just the modules the Harness imports. config.py finds ontology/ two levels above src/clayzer.
COPY src/clayzer/*.py ./src/clayzer/
COPY src/clayzer/agentcore ./src/clayzer/agentcore
COPY ontology ./ontology
ARG BUILD=unknown
ENV PYTHONPATH=/app/src \
    CLAYZER_BUILD=${BUILD}
RUN useradd --create-home clayzer && chown -R clayzer /app
USER clayzer
EXPOSE 8080
CMD ["python", "-m", "clayzer.agentcore.runtime"]
