"""Settings from the environment, with an optional .env file at the repo root.

Credentials in .env win over the shell: if .env sets AWS keys, a shell-level Bedrock bearer
token, profile, or region would otherwise take precedence over them in boto3.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

REPO = Path(__file__).resolve().parents[2]

_SHADOWING = ("AWS_BEARER_TOKEN_BEDROCK", "AWS_PROFILE", "AWS_REGION")


def load_env(path: Path = REPO / ".env") -> None:
    values = {k: v for k, v in dotenv_values(path).items() if v is not None}
    if not values:
        return
    if "AWS_ACCESS_KEY_ID" in values:
        for key in _SHADOWING:
            if key not in values:
                os.environ.pop(key, None)
    os.environ.update(values)


@dataclass(frozen=True)
class Settings:
    caption_model: str
    judge_model: str
    embed_model: str
    bedrock_endpoint_url: str | None
    data_dir: Path
    batches_dir: Path
    baselines_dir: Path
    store_url: str | None
    naip_source: str
    # The deployed site's URL, shown on the deck's closing slide wherever the deck is served.
    # Set it in .env, never in the repo (REQ-13); unset, the slide shows the serving host.
    public_url: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        return cls(
            caption_model=env("CLAYZER_CAPTION_MODEL", "us.amazon.nova-pro-v1:0"),
            judge_model=env("CLAYZER_JUDGE_MODEL", "us.anthropic.claude-opus-5-5"),
            embed_model=env("CLAYZER_EMBED_MODEL", "amazon.titan-embed-text-v2:0"),
            bedrock_endpoint_url=env("CLAYZER_BEDROCK_ENDPOINT_URL") or None,
            data_dir=Path(env("CLAYZER_DATA_DIR", REPO / "data")),
            batches_dir=Path(env("CLAYZER_BATCHES_DIR", REPO / "batches")),
            baselines_dir=Path(env("CLAYZER_BASELINES_DIR", REPO / "baselines")),
            store_url=env("CLAYZER_STORE") or None,
            naip_source=env("CLAYZER_NAIP_SOURCE", "pc"),
            public_url=env("CLAYZER_PUBLIC_URL") or None,
        )

    def store(self):
        from clayzer.store import open_store

        return open_store(self.store_url, self.data_dir, self.batches_dir)


def bedrock(settings: Settings):
    import boto3
    from botocore.config import Config

    # Adaptive retries absorb Bedrock throttling within a Batch instead of failing Runs.
    retries = Config(retries={"mode": "adaptive", "max_attempts": 8}, read_timeout=120)
    return boto3.client(
        "bedrock-runtime", endpoint_url=settings.bedrock_endpoint_url, config=retries
    )


def ca_bundle() -> str | None:
    """The CA bundle the shell already trusts, for GDAL's own HTTP client.

    GDAL_CURL_CA_BUNDLE isn't consulted: importing rasterio sets it to certifi's public bundle,
    which fails behind a TLS-intercepting proxy.
    """
    return os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
