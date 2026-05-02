"""Helpers for normalizing applicant PDF download URLs."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse


BLANK_URL_VALUES = {"", "tiada maklumat", "nan", "none", "null", "n/a", "na", "-"}
CLOUDFRONT_TO_S3_HOSTS = {
    "d3j85m1nd79zoa.cloudfront.net": "eplacement-2.s3.ap-southeast-5.amazonaws.com",
}


def normalize_download_url(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if normalized.casefold() in BLANK_URL_VALUES:
        return None
    if not normalized.lower().startswith(("http://", "https://")):
        return None

    parsed = urlparse(normalized)
    replacement_host = CLOUDFRONT_TO_S3_HOSTS.get(parsed.netloc.casefold())
    if not replacement_host:
        return normalized

    rewritten = parsed._replace(netloc=replacement_host)
    return urlunparse(rewritten)
