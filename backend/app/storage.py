"""Where uploaded flood photos live.

Local disk by default. Point the S3_* settings at any S3-compatible bucket —
Supabase Storage, Cloudflare R2, Backblaze B2 — and photos go there instead,
which is the only way they survive on a host with no persistent disk: on the
free plan every deploy wipes the container's filesystem, so reports keep their
text, depth and position while the picture — usually the most convincing part
of the report — disappears.

This module is also the single place that decides whether a photo URL is one of
ours. `photo_url` arrives on the report payload as a plain string from whoever
is filing, and it is rendered in an <img> on the moderation screen, so an
unchecked value means anyone can make a moderator's browser fetch a URL of their
choosing. Validating here rather than in the page keeps the rule in one place
and keeps it enforced even if a future screen forgets to guard.
"""
import logging
import os
import re
import threading

from .config import settings

logger = logging.getLogger("floodwatch.storage")

# Exactly what save_jpeg() names a file: date, then a random hex id.
UPLOAD_NAME = re.compile(r"^\d{8}-[0-9a-f]{12}\.jpg$")

LOCAL_PREFIX = "/uploads/"

_client_lock = threading.Lock()
_client = None


def bucket_enabled() -> bool:
    return bool(settings.s3_bucket and settings.s3_endpoint_url
                and settings.s3_access_key_id and settings.s3_secret_access_key
                and settings.s3_public_base_url)


def backend_name() -> str:
    return "bucket" if bucket_enabled() else "local"


def _public_base() -> str:
    return settings.s3_public_base_url.rstrip("/") + "/"


def public_prefixes() -> list[str]:
    """Every prefix a photo of ours may start with.

    The local prefix stays valid even after the bucket is switched on, so photos
    filed before the switch keep resolving instead of becoming broken images.
    """
    prefixes = [LOCAL_PREFIX]
    if bucket_enabled():
        prefixes.append(_public_base())
    return prefixes


def is_managed_url(url: str | None) -> bool:
    """True only for a URL this app's own upload endpoint produced."""
    if not url:
        return False
    for prefix in public_prefixes():
        if url.startswith(prefix):
            return bool(UPLOAD_NAME.fullmatch(url[len(prefix):]))
    return False


def _get_client():
    """One boto3 client, built on first use.

    Built lazily so that a deployment with no bucket configured never imports
    boto3 at all, and so a typo in the credentials surfaces on the first upload
    rather than taking the whole app down at boot.
    """
    global _client
    with _client_lock:
        if _client is None:
            import boto3
            from botocore.config import Config

            _client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=settings.s3_secret_access_key,
                region_name=settings.s3_region or "auto",
                config=Config(
                    signature_version="s3v4",
                    # Bucket in the path, not the hostname. Providers serving
                    # from a shared domain cannot do virtual-host style at all,
                    # and the ones that can accept path style too.
                    s3={"addressing_style": "path"},
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
        return _client


def save_jpeg(data: bytes, name: str) -> str:
    """Store one processed JPEG and return the URL it is served from."""
    if not UPLOAD_NAME.fullmatch(name):
        raise ValueError(f"ชื่อไฟล์ไม่ถูกรูปแบบ: {name}")

    if bucket_enabled():
        _get_client().put_object(
            Bucket=settings.s3_bucket,
            Key=name,
            Body=data,
            ContentType="image/jpeg",
            # Photos never change once written, so let browsers and any CDN in
            # front of the bucket keep them for a year.
            CacheControl="public, max-age=31536000, immutable",
        )
        return _public_base() + name

    os.makedirs(settings.upload_dir, exist_ok=True)
    path = os.path.join(settings.upload_dir, name)
    with open(path, "wb") as handle:
        handle.write(data)
    return LOCAL_PREFIX + name
