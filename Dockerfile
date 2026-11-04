# syntax=docker/dockerfile:1.7
#
# The Clayzer web app. Defaults suit a machine with public PyPI and Docker Hub access:
#   docker build -t clayzer .
#   docker run --rm -p 8770:8770 -e AWS_REGION -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
#     -e AWS_SESSION_TOKEN -e CLAYZER_STORE clayzer
#
# Behind a private package mirror or TLS-intercepting proxy, pass both as optional build secrets:
#   --secret id=pip_index,src=<file with index URL>  --secret id=ca_bundle,src=<CA bundle .pem>
# and override BASE_IMAGE if Docker Hub isn't reachable. Neither ends up in an image layer.

ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN --mount=type=secret,id=pip_index,required=false \
    --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/pip_index ]; then export PIP_INDEX_URL="$(cat /run/secrets/pip_index)"; fi; \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install --no-cache-dir uv==0.12.22

# Hash-pinned runtime dependencies (core plus the ui extra). Regenerate with
#   uv export --frozen --extra ui --no-dev --no-emit-project -o requirements.lock
COPY requirements.lock ./
RUN --mount=type=secret,id=pip_index,required=false \
    --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/pip_index ]; then export UV_DEFAULT_INDEX="$(cat /run/secrets/pip_index)"; fi; \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv pip install --system --no-cache --require-hashes -r requirements.lock

# Editable install, so the app's repo-relative paths (docs/, GLOSSARY.md, baselines/, ontology/)
# resolve against /app.
COPY pyproject.toml README.md GLOSSARY.md ./
COPY src ./src
COPY docs ./docs
COPY ontology ./ontology
COPY baselines ./baselines
RUN --mount=type=secret,id=pip_index,required=false \
    --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/pip_index ]; then export UV_DEFAULT_INDEX="$(cat /run/secrets/pip_index)"; fi; \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv pip install --system --no-cache --no-deps -e .

RUN useradd --create-home clayzer && mkdir -p data batches && chown -R clayzer /app
USER clayzer

# Read-only by default: a hosted copy must not let anyone with the URL start Batches.
EXPOSE 8770
ENTRYPOINT ["clayzer"]
CMD ["ui", "--host", "0.0.0.0", "--port", "8770"]
