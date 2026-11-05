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
ARG BASE_IMAGE=public.ecr.aws/docker/library/python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
FROM --platform=linux/arm64 ${BASE_IMAGE} AS dependencies
RUN python -m venv /opt/runtime
ENV PATH="/opt/runtime/bin:$PATH"
COPY infra/agentcore/requirements.txt /tmp/requirements.txt
RUN --mount=type=secret,id=pip_index,required=false \
    --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/pip_index ]; then export PIP_INDEX_URL="$(cat /run/secrets/pip_index)"; fi; \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt

FROM --platform=linux/arm64 ${BASE_IMAGE}
COPY --from=dependencies /opt/runtime /opt/runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/runtime/bin:$PATH"
WORKDIR /app
# Hash-pinned (see requirements.in). `uv` is here so MCP servers launched with uvx (RODA) work.
# Just the modules the Harness imports. config.py finds ontology/ two levels above src/clayzer.
COPY src/clayzer/__init__.py src/clayzer/harness.py src/clayzer/grid.py \
     src/clayzer/trace.py src/clayzer/faults.py src/clayzer/tools.py \
     src/clayzer/allowlist.py src/clayzer/mcp_auth.py src/clayzer/config.py \
     src/clayzer/lgnd.py src/clayzer/verify.py src/clayzer/verifiers.py \
     src/clayzer/ontology.py ./src/clayzer/
COPY src/clayzer/agentcore/__init__.py src/clayzer/agentcore/contract.py \
     src/clayzer/agentcore/identity.py src/clayzer/agentcore/runtime.py \
     src/clayzer/agentcore/telemetry.py ./src/clayzer/agentcore/
COPY ontology/objects.toml ontology/verifiers.toml ./ontology/
ARG BUILD=unknown
ENV PYTHONPATH=/app/src \
    CLAYZER_BUILD=${BUILD} \
    OTEL_PYTHON_DISTRO=aws_distro \
    OTEL_PYTHON_CONFIGURATOR=aws_configurator \
    OTEL_SERVICE_NAME=clayzer-harness \
    OTEL_RESOURCE_ATTRIBUTES=service.name=clayzer-harness \
    OTEL_TRACES_EXPORTER=otlp
RUN useradd --create-home clayzer && chown -R clayzer /app
USER clayzer
EXPOSE 8080
# AgentCore Observability: run under ADOT auto-instrumentation so Bedrock and HTTP calls are
# traced and exported to CloudWatch. telemetry.py adds the named caption/turn/tool spans on top.
CMD ["opentelemetry-instrument", "python", "-m", "clayzer.agentcore.runtime"]
