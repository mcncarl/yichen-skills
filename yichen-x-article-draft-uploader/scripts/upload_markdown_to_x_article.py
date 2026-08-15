#!/usr/bin/env python3
"""Upload a Markdown file to X Articles as a draft.

This intentionally creates a draft only and never clicks the final publish button.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import html as htmlmod
import json
import mimetypes
import os
import re
import stat
import string
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


DEFAULT_PARSE_SCRIPTS = [
    Path(__file__).resolve().parent / "parse_markdown.py",
]

WEAK_ANCHORS = {"", "-", "```", "~~~", "|"}
RECOMMENDED_COVER_RATIO = "5:2"
X_ARTICLE_MAX_BODY_MEDIA = 25
TABLE_MARKER_PREFIX = "X_TABLE_MARKER"
MAX_NATIVE_TABLE_ROWS = 10
MAX_NATIVE_TABLE_COLUMNS = 10
CONTENT_CHECKPOINT_COUNT = 5
CONTENT_CHECKPOINT_CHARS = 32
TABLE_MARKER_PATTERN = rf"{re.escape(TABLE_MARKER_PREFIX)}_\d{{3}}_DO_NOT_EDIT(?![A-Za-z0-9_])"
TABLE_MARKER_RE = re.compile(TABLE_MARKER_PATTERN)
IGNORED_EDITOR_WHITESPACE_RE = re.compile(r"[\s\u200b\ufeff]+")
CONTENT_LENGTH_UNIT = "unicode_code_points"
VERIFICATION_CONTRACT = "x-article-persistence-v1"
VISUAL_SIGNATURE_RE = re.compile(r"^visual-dhash-v1:[0-9a-f]{64}$")
VISUAL_RGB_SAMPLE_RE = re.compile(r"^visual-rgb8-v1:[0-9a-f]{384}$")
VISUAL_DHASH_BITS = 256
# A 64-bit radius (25% of the 256-bit dHash) remains the unconditional visual
# match boundary. X can occasionally transform an illustration more heavily:
# one verified production upload measured 71 bits while still being the unique
# nearest source by a 20-bit margin. Those cases may use the bounded adaptive
# path below, but only when aspect ratio and the rest of the placement contract
# also match. Historical wrong bindings started at 82 bits, so the adaptive cap
# deliberately stays below that boundary.
VISUAL_DHASH_MAX_DISTANCE = 64
VISUAL_DHASH_ADAPTIVE_MAX_DISTANCE = 80
VISUAL_DHASH_ADAPTIVE_MIN_MARGIN = 16
VISUAL_ASPECT_RATIO_MAX_RELATIVE_DRIFT = 0.03
VISUAL_RGB_SAMPLE_MAX_MAE = 0.12
VISUAL_LUMA_SAMPLE_MAX_MAE = 0.10
VISUAL_LUMA_CORRELATION_MIN = 0.88
VISUAL_SAMPLE_MIN_NEAREST_MARGIN = 0.008
# A media node that already existed immediately before the current paste is
# expected to decode to nearly the same pixels after X rerenders the composer.
# This is deliberately much tighter than local-source -> X-hosted matching:
# uploader-only DOM runtime attributes may disappear, but they must never let a
# different hosted image masquerade as the previously verified node.
VISUAL_PERSISTED_NODE_DHASH_MAX_DISTANCE = 16
VISUAL_PERSISTED_NODE_RGB_SAMPLE_MAX_MAE = 0.03
VISUAL_PERSISTED_NODE_LUMA_SAMPLE_MAX_MAE = 0.03
VISUAL_PERSISTED_NODE_LUMA_CORRELATION_MIN = 0.97
MAX_HOSTED_COVER_BYTES = 32 * 1024 * 1024
X_MEDIA_HOST_SUFFIXES = ("twimg.com", "x.com", "twitter.com")
MAX_COOKIE_FILE_BYTES = 5 * 1024 * 1024
X_COOKIE_HOST_SUFFIXES = ("x.com", "twitter.com")
REQUIRED_X_COOKIE_NAMES = frozenset({"auth_token", "ct0"})
DEFAULT_ARTIFACT_DIRECTORY = Path.home() / ".ailu" / "runs" / "x-article-draft-uploader"
DEFAULT_RESULT_JSON = DEFAULT_ARTIFACT_DIRECTORY / "result.json"
DEFAULT_DRAFT_URL_OUTPUT = DEFAULT_ARTIFACT_DIRECTORY / "draft-url.txt"
DEFAULT_SCREENSHOT = DEFAULT_ARTIFACT_DIRECTORY / "final.png"
MEDIA_PLACEMENT_AFTER_ANCHOR = "after-anchor"
MEDIA_PLACEMENT_COMPOSER_START = "composer-start"
MEDIA_START_MARKER = "X_MEDIA_START_MARKER_DO_NOT_EDIT"
MARKDOWN_ESCAPABLE_ASCII_CLASS = re.escape(string.punctuation)


def visual_sample_id(value: str) -> str:
    """Expose a stable non-reversible ID for a validated 8 x 8 RGB sample."""
    sample = str(value or "")
    if not VISUAL_RGB_SAMPLE_RE.fullmatch(sample):
        return ""
    return hashlib.sha256(sample.encode("ascii")).hexdigest()[:16]


def apply_body_media_limit(preflight: dict, expected_body_images: int) -> dict:
    """Fail closed before opening X when the body exceeds its independent quota."""
    errors = preflight.setdefault("errors", [])
    if (
        expected_body_images > X_ARTICLE_MAX_BODY_MEDIA
        and not any(error.get("type") == "body_media_limit_exceeded" for error in errors)
    ):
        errors.append(
            {
                "type": "body_media_limit_exceeded",
                "expected_body_images": expected_body_images,
                "maximum": X_ARTICLE_MAX_BODY_MEDIA,
                "cover_separate": True,
                "message": (
                    f"正文图片有 {expected_body_images} 张，超过 X 正文上限 "
                    f"{expected_body_images - X_ARTICLE_MAX_BODY_MEDIA} 张；"
                    f"请减少到 {X_ARTICLE_MAX_BODY_MEDIA} 张以内。"
                    "图片文件本身没有损坏；封面单独计算，不占正文名额。不会打开 X。"
                ),
            }
        )
    return preflight


def is_allowed_x_media_url(value: str) -> bool:
    """Restrict authenticated cover fetches to X-controlled HTTPS hosts."""
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in X_MEDIA_HOST_SUFFIXES)
    )


def is_allowed_x_draft_url(value: str) -> bool:
    """Accept only a concrete HTTPS X Article edit URL."""
    try:
        parsed = urllib.parse.urlparse(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == "x.com"
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and bool(re.fullmatch(r"/compose/articles/edit/[A-Za-z0-9_-]+/?", parsed.path))
    )


def is_allowed_x_cookie_domain(value: str) -> bool:
    hostname = str(value or "").strip().lower().lstrip(".")
    return any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in X_COOKIE_HOST_SUFFIXES
    )


async def read_bounded_x_image_response(response) -> tuple[bytes, str] | None:
    """Read an X-hosted image response only after validating its final URL and bounds."""
    if response is None or not response.ok or not is_allowed_x_media_url(str(response.url or "")):
        return None
    headers = response.headers or {}
    content_type = str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if not content_type.startswith("image/"):
        return None
    content_length = str(headers.get("content-length") or "").strip()
    if content_length:
        try:
            if int(content_length) > MAX_HOSTED_COVER_BYTES:
                return None
        except ValueError:
            return None
    body = await response.body()
    if not body or len(body) > MAX_HOSTED_COVER_BYTES:
        return None
    return body, content_type


async def fetch_hosted_cover_image_bytes(page, source_url: str) -> tuple[bytes, str, str] | None:
    """Fetch an X cover, falling back to the browser network path when APIRequest fails."""
    if not is_allowed_x_media_url(source_url):
        return None
    try:
        response = await page.context.request.get(source_url, timeout=30_000)
        fetched = await read_bounded_x_image_response(response)
        if fetched is not None:
            return fetched[0], fetched[1], "context-fetch"
    except Exception:
        # APIRequestContext can bypass the browser/system proxy route and fail even when the
        # page itself has already loaded the image. Keep strict checks and retry through a
        # temporary page in the same authenticated browser context.
        pass

    image_page = None
    try:
        image_page = await page.context.new_page()
        response = await image_page.goto(
            source_url,
            wait_until="commit",
            timeout=30_000,
        )
        fetched = await read_bounded_x_image_response(response)
        if fetched is not None:
            return fetched[0], fetched[1], "browser-page-fetch"
    except Exception:
        pass
    finally:
        if image_page is not None:
            try:
                await image_page.close()
            except Exception:
                pass
    return None


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Atomically replace a text result without exposing a truncated JSON file."""
    target = Path(path)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding=encoding,
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary_path = handle.name
    os.replace(temporary_path, target)


def atomic_write_result_json(path: str | Path, payload: dict) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_private_artifact_directory() -> None:
    """Create the default Ailu artifact directory without traversing nested symlinks."""
    cursor = Path.home()
    for component in (".ailu", "runs", "x-article-draft-uploader"):
        cursor /= component
        try:
            metadata = cursor.lstat()
        except FileNotFoundError:
            cursor.mkdir(mode=0o700)
            metadata = cursor.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"Default X Article artifact directory is unsafe: {cursor}")
        cursor.chmod(0o700)


def validate_artifact_target(path: str | Path) -> None:
    """Reject existing links/devices before URL, result, or screenshot writes."""
    target = Path(path).expanduser().absolute()
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"X Article artifact target must be a regular file: {target}")


def prepare_artifact_targets(args: argparse.Namespace) -> None:
    defaults = {
        str(DEFAULT_RESULT_JSON),
        str(DEFAULT_DRAFT_URL_OUTPUT),
        str(DEFAULT_SCREENSHOT),
    }
    if any(str(Path(value).expanduser().absolute()) in defaults for value in (
        args.result_json,
        args.url_output,
        args.screenshot,
    )):
        ensure_private_artifact_directory()
    for value in (args.result_json, args.url_output, args.screenshot):
        validate_artifact_target(value)


async def capture_optional_screenshot(page, path: str | Path | None) -> dict:
    """Write a diagnostic screenshot without weakening an already-proven draft.

    The screenshot is useful troubleshooting output, not persistence evidence.
    A renderer/disk failure here must therefore become a warning after the
    same-URL reload contract has passed, while the result JSON itself remains a
    required, fail-closed artifact.
    """
    if not path:
        return {
            "written": False,
            "path": "",
            "warning": {
                "type": "diagnostic_screenshot_skipped",
                "message": "未配置最终诊断截图路径；草稿最终持久化验收不受影响。",
            },
        }
    try:
        await page.screenshot(path=str(path), full_page=True)
    except Exception as error:
        return {
            "written": False,
            "path": str(path),
            "error_type": type(error).__name__,
            "error": str(error),
            "warning": {
                "type": "diagnostic_screenshot_failed",
                "error_type": type(error).__name__,
                "message": "最终诊断截图写入失败；同一草稿刷新后的核心持久化验收已通过。",
            },
        }
    return {"written": True, "path": str(path), "warning": None}


def emit_final_status(draft_url: str, ok: bool) -> None:
    """Emit the small stdout contract consumed by Ailu.

    The complete verification evidence lives in --result-json. Keeping stdout
    bounded prevents a large result payload from evicting the draft URL from
    the host process' diagnostic tail buffer.
    """
    print("draft_url=" + draft_url)
    print("RESULT_OK", ok)


def visual_signature_hamming_distance(left: str, right: str) -> int | None:
    """Return the bit distance between two visual-dhash-v1 signatures."""
    if not VISUAL_SIGNATURE_RE.fullmatch(left or "") or not VISUAL_SIGNATURE_RE.fullmatch(right or ""):
        return None
    left_bits = int(left.split(":", 1)[1], 16)
    right_bits = int(right.split(":", 1)[1], 16)
    return bin(left_bits ^ right_bits).count("1")


def visual_signatures_match(
    left: str,
    right: str,
    max_distance: int = VISUAL_DHASH_MAX_DISTANCE,
) -> bool:
    distance = visual_signature_hamming_distance(left, right)
    return distance is not None and distance <= max_distance


def decode_visual_rgb_sample(value: str) -> list[tuple[int, int, int]] | None:
    """Decode the 8 x 8 RGB thumbnail used for transform-tolerant comparison."""
    if not VISUAL_RGB_SAMPLE_RE.fullmatch(value or ""):
        return None
    raw = bytes.fromhex(value.split(":", 1)[1])
    return [tuple(raw[index : index + 3]) for index in range(0, len(raw), 3)]


def visual_rgb_sample_metrics(left: str, right: str) -> dict | None:
    """Measure low-resolution color and luminance similarity after X transforms."""
    left_pixels = decode_visual_rgb_sample(left)
    right_pixels = decode_visual_rgb_sample(right)
    if left_pixels is None or right_pixels is None or len(left_pixels) != len(right_pixels):
        return None
    rgb_error = sum(
        abs(left_channel - right_channel)
        for left_pixel, right_pixel in zip(left_pixels, right_pixels)
        for left_channel, right_channel in zip(left_pixel, right_pixel)
    ) / (len(left_pixels) * 3 * 255)
    left_luma = [
        (red * 299 + green * 587 + blue * 114) / (1000 * 255)
        for red, green, blue in left_pixels
    ]
    right_luma = [
        (red * 299 + green * 587 + blue * 114) / (1000 * 255)
        for red, green, blue in right_pixels
    ]
    luma_error = sum(
        abs(left_value - right_value)
        for left_value, right_value in zip(left_luma, right_luma)
    ) / len(left_luma)
    left_mean = sum(left_luma) / len(left_luma)
    right_mean = sum(right_luma) / len(right_luma)
    covariance = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left_luma, right_luma)
    )
    left_variance = sum((value - left_mean) ** 2 for value in left_luma)
    right_variance = sum((value - right_mean) ** 2 for value in right_luma)
    denominator = (left_variance * right_variance) ** 0.5
    correlation = covariance / denominator if denominator > 1e-12 else None
    return {
        "rgb_mean_absolute_error": rgb_error,
        "luma_mean_absolute_error": luma_error,
        "luma_correlation": correlation,
        "sample_distance_score": rgb_error * 0.6 + luma_error * 0.4,
    }


def compare_visual_sample_to_source_groups(
    observed_sample: str,
    expected_source_sample: str,
    source_contract: list[dict],
) -> dict:
    """Require the expected 8 x 8 source sample to be the unique nearest sample."""
    grouped: dict[str, int] = {}
    for item in source_contract:
        sample = str(item.get("source_visual_sample") or item.get("visualSample") or "")
        if VISUAL_RGB_SAMPLE_RE.fullmatch(sample):
            grouped[sample] = grouped.get(sample, 0) + 1
    distances = []
    for sample, occurrences in grouped.items():
        metrics = visual_rgb_sample_metrics(sample, observed_sample)
        distances.append(
            {
                "source_sample_id": visual_sample_id(sample),
                "source_group_occurrences": occurrences,
                **(metrics or {
                    "rgb_mean_absolute_error": None,
                    "luma_mean_absolute_error": None,
                    "luma_correlation": None,
                    "sample_distance_score": None,
                }),
                "_source_sample": sample,
            }
        )
    valid_distances = [
        item["sample_distance_score"]
        for item in distances
        if item["sample_distance_score"] is not None
    ]
    nearest_distance = min(valid_distances) if valid_distances else None
    nearest_samples = [
        item["_source_sample"]
        for item in distances
        if nearest_distance is not None
        and abs(item["sample_distance_score"] - nearest_distance) <= 1e-12
    ]
    expected_metrics = visual_rgb_sample_metrics(expected_source_sample, observed_sample)
    expected_is_unique_nearest = bool(
        expected_source_sample
        and nearest_samples == [expected_source_sample]
    )
    other_distances = [
        item["sample_distance_score"]
        for item in distances
        if item["_source_sample"] != expected_source_sample
        and item["sample_distance_score"] is not None
    ]
    second_nearest_distance = min(other_distances) if other_distances else None
    nearest_margin = (
        second_nearest_distance - expected_metrics["sample_distance_score"]
        if expected_is_unique_nearest
        and expected_metrics is not None
        and second_nearest_distance is not None
        else None
    )
    public_distances = [
        {key: value for key, value in item.items() if key != "_source_sample"}
        for item in distances
    ]
    return {
        "distinct_source_sample_group_count": len(distances),
        "source_sample_distances": public_distances,
        "nearest_source_sample_distance": nearest_distance,
        "second_nearest_source_sample_distance": second_nearest_distance,
        "nearest_source_sample_margin": nearest_margin,
        "expected_source_sample_id": visual_sample_id(expected_source_sample),
        "expected_source_sample_is_unique_nearest": expected_is_unique_nearest,
        "expected_source_sample_metrics": expected_metrics,
    }


def compare_signature_to_source_groups(
    observed_signature: str,
    expected_source_signature: str,
    source_contract: list[dict],
) -> dict:
    """Require the expected source to be the unique closest distinct source group."""
    grouped: dict[str, int] = {}
    for item in source_contract:
        signature = str(item.get("source_signature") or item.get("sourceSignature") or "")
        if VISUAL_SIGNATURE_RE.fullmatch(signature):
            grouped[signature] = grouped.get(signature, 0) + 1

    distances = [
        {
            "source_signature": signature,
            "source_group_occurrences": occurrences,
            "hamming_distance": visual_signature_hamming_distance(signature, observed_signature),
        }
        for signature, occurrences in grouped.items()
    ]
    valid_distances = [
        item["hamming_distance"]
        for item in distances
        if item["hamming_distance"] is not None
    ]
    nearest_distance = min(valid_distances) if valid_distances else None
    nearest_signatures = [
        item["source_signature"]
        for item in distances
        if nearest_distance is not None and item["hamming_distance"] == nearest_distance
    ]
    expected_distance = visual_signature_hamming_distance(
        expected_source_signature,
        observed_signature,
    )
    expected_is_unique_nearest = bool(
        expected_source_signature
        and nearest_signatures == [expected_source_signature]
    )
    other_source_distances = [
        item["hamming_distance"]
        for item in distances
        if item["source_signature"] != expected_source_signature
        and item["hamming_distance"] is not None
    ]
    second_nearest_source_distance = (
        min(other_source_distances) if other_source_distances else None
    )
    nearest_source_margin = (
        second_nearest_source_distance - expected_distance
        if expected_is_unique_nearest
        and expected_distance is not None
        and second_nearest_source_distance is not None
        else None
    )
    nearest_ambiguous = len(nearest_signatures) != 1
    source_ambiguous = not expected_is_unique_nearest
    return {
        "distinct_source_group_count": len(distances),
        "source_group_distances": distances,
        "nearest_source_distance": nearest_distance,
        "second_nearest_source_distance": second_nearest_source_distance,
        "nearest_source_margin": nearest_source_margin,
        "nearest_source_signatures": nearest_signatures,
        "nearest_source_ambiguous": nearest_ambiguous,
        "source_ambiguous": source_ambiguous,
        "expected_source_distance": expected_distance,
        "expected_source_is_unique_nearest": expected_is_unique_nearest,
        "expected_source_within_radius": bool(
            expected_distance is not None
            and expected_distance <= VISUAL_DHASH_MAX_DISTANCE
        ),
        "valid": bool(
            expected_is_unique_nearest
            and expected_distance is not None
            and expected_distance <= VISUAL_DHASH_MAX_DISTANCE
        ),
    }


def visual_aspect_ratio_evidence(
    source_width: int,
    source_height: int,
    observed_width: int,
    observed_height: int,
) -> dict:
    """Compare dimensions without requiring X to preserve the original size."""
    source_width = int(source_width or 0)
    source_height = int(source_height or 0)
    observed_width = int(observed_width or 0)
    observed_height = int(observed_height or 0)
    available = all(
        value > 0
        for value in (source_width, source_height, observed_width, observed_height)
    )
    source_ratio = source_width / source_height if available else None
    observed_ratio = observed_width / observed_height if available else None
    relative_drift = (
        abs(observed_ratio / source_ratio - 1.0)
        if available and source_ratio
        else None
    )
    return {
        "source_natural_width": source_width,
        "source_natural_height": source_height,
        "observed_natural_width": observed_width,
        "observed_natural_height": observed_height,
        "source_aspect_ratio": source_ratio,
        "observed_aspect_ratio": observed_ratio,
        "aspect_ratio_relative_drift": relative_drift,
        "aspect_ratio_available": available,
        "aspect_ratio_matches": bool(
            relative_drift is not None
            and relative_drift <= VISUAL_ASPECT_RATIO_MAX_RELATIVE_DRIFT
        ),
    }


def evaluate_source_visual_match(
    observed_signature: str,
    expected: dict,
    source_contract: list[dict],
    observed_width: int,
    observed_height: int,
    observed_visual_sample: str = "",
) -> dict:
    """Use strict pixels first, then a bounded multi-signal X transform fallback."""
    expected_source_signature = str(
        expected.get("source_signature") or expected.get("sourceSignature") or ""
    )
    comparison = compare_signature_to_source_groups(
        observed_signature,
        expected_source_signature,
        source_contract,
    )
    aspect = visual_aspect_ratio_evidence(
        expected.get("source_natural_width") or expected.get("naturalWidth") or 0,
        expected.get("source_natural_height") or expected.get("naturalHeight") or 0,
        observed_width,
        observed_height,
    )
    expected_visual_sample = str(
        expected.get("source_visual_sample") or expected.get("visualSample") or ""
    )
    sample_comparison = compare_visual_sample_to_source_groups(
        observed_visual_sample,
        expected_visual_sample,
        source_contract,
    )
    expected_sample_metrics = sample_comparison["expected_source_sample_metrics"]
    expected_distance = comparison["expected_source_distance"]
    nearest_margin = comparison["nearest_source_margin"]
    margin_matches = bool(
        comparison["distinct_source_group_count"] == 1
        or (
            nearest_margin is not None
            and nearest_margin >= VISUAL_DHASH_ADAPTIVE_MIN_MARGIN
        )
    )
    strict_match = bool(comparison["valid"])
    adaptive_match = bool(
        not strict_match
        and comparison["expected_source_is_unique_nearest"]
        and expected_distance is not None
        and expected_distance <= VISUAL_DHASH_ADAPTIVE_MAX_DISTANCE
        and margin_matches
        and aspect["aspect_ratio_matches"]
    )
    sample_similarity_matches = bool(
        expected_sample_metrics
        and expected_sample_metrics["rgb_mean_absolute_error"] <= VISUAL_RGB_SAMPLE_MAX_MAE
        and expected_sample_metrics["luma_mean_absolute_error"] <= VISUAL_LUMA_SAMPLE_MAX_MAE
        and (
            expected_sample_metrics["luma_correlation"] is None
            or expected_sample_metrics["luma_correlation"] >= VISUAL_LUMA_CORRELATION_MIN
        )
    )
    sample_margin_matches = bool(
        sample_comparison["distinct_source_sample_group_count"] == 1
        or (
            sample_comparison["nearest_source_sample_margin"] is not None
            and sample_comparison["nearest_source_sample_margin"]
            >= VISUAL_SAMPLE_MIN_NEAREST_MARGIN
        )
        or (
            nearest_margin is not None
            and nearest_margin >= VISUAL_DHASH_ADAPTIVE_MIN_MARGIN
        )
    )
    sample_consensus_match = bool(
        not strict_match
        and sample_comparison["expected_source_sample_is_unique_nearest"]
        and sample_similarity_matches
        and aspect["aspect_ratio_matches"]
    )
    match_policy = (
        "strict-radius"
        if strict_match
        else "multi-signal-consensus"
        if sample_consensus_match
        else "adaptive-unique-nearest"
        if adaptive_match
        else "rejected"
    )
    return {
        **comparison,
        **aspect,
        **sample_comparison,
        "strict_source_match": strict_match,
        "adaptive_source_match": adaptive_match,
        "sample_consensus_match": sample_consensus_match,
        "sample_similarity_matches": sample_similarity_matches,
        "sample_margin_matches": sample_margin_matches,
        "adaptive_margin_matches": margin_matches,
        "expected_source_within_adaptive_radius": bool(
            expected_distance is not None
            and expected_distance <= VISUAL_DHASH_ADAPTIVE_MAX_DISTANCE
        ),
        "match_policy": match_policy,
        "valid": bool(strict_match or sample_consensus_match or adaptive_match),
    }


def media_identity_key(source_signature: str, occurrence: int, anchor: str, dom_order: int) -> str:
    """Build a stable identity from source pixels, occurrence, anchor and order."""
    payload = json.dumps(
        [source_signature, int(occurrence), normalize_media_anchor(anchor), int(dom_order)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "media-v1-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_source_media_contract(
    content_images: list[dict],
    source_items: list[dict],
    require_visual_sample: bool = False,
) -> list[dict]:
    """Bind each local file fingerprint to its occurrence, anchor and final DOM order."""
    if len(content_images) != len(source_items):
        raise ValueError(
            f"Local source fingerprint count mismatch: expected={len(content_images)} actual={len(source_items)}"
        )
    occurrences: Counter[str] = Counter()
    contract = []
    for dom_order, (content_image, source_item) in enumerate(zip(content_images, source_items)):
        source_signature = str(source_item.get("sourceSignature") or "")
        if not VISUAL_SIGNATURE_RE.fullmatch(source_signature):
            raise ValueError(
                f"Local source image {content_image.get('index', dom_order + 1)} has no readable visual fingerprint."
            )
        source_visual_sample = str(source_item.get("visualSample") or "")
        if require_visual_sample and not VISUAL_RGB_SAMPLE_RE.fullmatch(source_visual_sample):
            raise ValueError(
                f"Local source image {content_image.get('index', dom_order + 1)} "
                "has no readable RGB comparison sample."
            )
        occurrences[source_signature] += 1
        occurrence = occurrences[source_signature]
        anchor = content_image.get("expected_anchor") or ""
        contract.append(
            {
                **content_image,
                "source_signature": source_signature,
                "source_visual_sample": source_visual_sample,
                "source_visual_sample_id": visual_sample_id(source_visual_sample),
                "source_occurrence": occurrence,
                "expected_dom_order": dom_order,
                "source_natural_width": int(source_item.get("naturalWidth") or 0),
                "source_natural_height": int(source_item.get("naturalHeight") or 0),
                "identity_key": media_identity_key(source_signature, occurrence, anchor, dom_order),
            }
        )
    return contract


def clean_anchor(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"^>\s*", "", text)
    text = re.sub(r"^[-*+]\s+", "", text)
    text = re.sub(r"^\d+[.)、]\s*", "", text)
    return text.strip().strip("|").strip()


def inspect_leading_cover(markdown_file: Path) -> dict:
    """Check whether the first meaningful Markdown line is an image."""
    lines = markdown_file.read_text(encoding="utf-8-sig").splitlines()
    index = 0

    while index < len(lines) and not lines[index].strip():
        index += 1

    if index < len(lines) and lines[index].strip() == "---":
        closing_index = next(
            (
                line_index
                for line_index in range(index + 1, len(lines))
                if lines[line_index].strip() in {"---", "..."}
            ),
            None,
        )
        if closing_index is not None:
            index = closing_index + 1

    while index < len(lines) and not lines[index].strip():
        index += 1

    first_line = lines[index].strip() if index < len(lines) else ""
    first_line_images = _scan_markdown_images(first_line)
    starts_with_image = bool(
        first_line_images
        and first_line_images[0]["start"] == 0
        and first_line_images[0]["style"] == "inline"
    )
    return {
        "starts_with_image": starts_with_image,
        "first_content_line": index + 1 if first_line else None,
        "first_content_preview": first_line[:160],
    }


def _markdown_lines(markdown: str) -> tuple[list[str], int]:
    normalized = (markdown or "").removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    frontmatter_end = -1
    if lines and lines[0].strip() == "---":
        frontmatter_end = next(
            (index for index, line in enumerate(lines[1:], 1) if line.strip() in {"---", "..."}),
            -1,
        )
    return lines, frontmatter_end


def _update_markdown_fence(line: str, state: dict) -> bool:
    match = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
    if not match:
        return False
    delimiter = match.group(1)
    trailing = match.group(2)
    character = delimiter[0]
    if state["character"] is None:
        if character == "`" and "`" in trailing:
            return False
        state["character"] = character
        state["length"] = len(delimiter)
        return True
    if character == state["character"] and len(delimiter) >= state["length"] and not trailing.strip():
        state["character"] = None
        state["length"] = 0
        return True
    return False


def _lines_outside_frontmatter_and_fences(markdown: str) -> list[tuple[int, str]]:
    lines, frontmatter_end = _markdown_lines(markdown)
    state = {"character": None, "length": 0}
    visible = []
    for offset, line in enumerate(lines):
        if 0 <= offset <= frontmatter_end:
            continue
        delimiter = _update_markdown_fence(line, state)
        if delimiter or state["character"] is not None:
            continue
        visible.append((offset + 1, line))
    return visible


def _masked_markdown_outside_frontmatter_and_fences(markdown: str) -> str:
    lines, frontmatter_end = _markdown_lines(markdown)
    state = {"character": None, "length": 0}
    masked_lines = []
    for offset, line in enumerate(lines):
        in_frontmatter = 0 <= offset <= frontmatter_end
        delimiter = False if in_frontmatter else _update_markdown_fence(line, state)
        masked = in_frontmatter or delimiter or state["character"] is not None
        masked_lines.append(" " * len(line) if masked else line)
    return "\n".join(masked_lines)


def find_unsupported_raw_html(markdown: str) -> list[dict]:
    masked_markdown = _masked_markdown_outside_frontmatter_and_fences(markdown)
    pattern = re.compile(r"<!--[\s\S]*?(?:-->|$)|</?([A-Za-z][A-Za-z0-9-]*)\b[^>]*>")
    found = []
    for match in pattern.finditer(masked_markdown):
        raw = match.group(0)
        is_uri_autolink = bool(re.fullmatch(r"<[A-Za-z][A-Za-z0-9+.-]{1,31}:[^<>\s]*>", raw))
        is_email_autolink = bool(re.fullmatch(r"<[^\s<>]+@[^\s<>]+>", raw)) and not raw.startswith("</")
        if is_uri_autolink or is_email_autolink:
            continue
        found.append(
            {
                "line": masked_markdown.count("\n", 0, match.start()) + 1,
                "tag": "comment" if raw.startswith("<!--") else (match.group(1) or "html").lower(),
                "text": " ".join(raw.strip().split())[:180],
            }
        )
    return found


def _normalize_reference_label(value: str) -> str:
    unescaped = re.sub(r"\\(.)", r"\1", value or "")
    return re.sub(r"\s+", " ", unescaped.strip()).lower()


def _is_markdown_escaped(text: str, index: int) -> bool:
    slashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        slashes += 1
        cursor -= 1
    return slashes % 2 == 1


def _parse_balanced_markdown_brackets(text: str, opening_index: int) -> tuple[str, int] | None:
    if opening_index >= len(text) or text[opening_index] != "[":
        return None
    depth = 0
    cursor = opening_index
    while cursor < len(text):
        character = text[cursor]
        if character == "\\":
            cursor += 2
            continue
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return text[opening_index + 1 : cursor], cursor
        cursor += 1
    return None


def _parse_balanced_markdown_parentheses(text: str, opening_index: int) -> tuple[str, int] | None:
    if opening_index >= len(text) or text[opening_index] != "(":
        return None
    depth = 0
    cursor = opening_index
    while cursor < len(text):
        character = text[cursor]
        if character == "\\":
            cursor += 2
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return text[opening_index + 1 : cursor], cursor
        cursor += 1
    return None


def _inline_image_destination(value: str) -> str:
    source = (value or "").lstrip()
    if source.startswith("<"):
        closing = source.find(">", 1)
        destination = source[1:closing] if closing >= 0 else source[1:]
    else:
        destination_chars = []
        cursor = 0
        while cursor < len(source):
            character = source[cursor]
            if character.isspace():
                break
            if character == "\\" and cursor + 1 < len(source):
                cursor += 1
                character = source[cursor]
            destination_chars.append(character)
            cursor += 1
        destination = "".join(destination_chars)
    return htmlmod.unescape(destination).strip()


def _scan_markdown_images(markdown: str) -> list[dict]:
    masked_markdown = _masked_markdown_outside_frontmatter_and_fences(markdown)
    found = []
    cursor = 0
    while cursor < len(masked_markdown) - 1:
        if masked_markdown[cursor : cursor + 2] != "![" or _is_markdown_escaped(masked_markdown, cursor):
            cursor += 1
            continue

        alt = _parse_balanced_markdown_brackets(masked_markdown, cursor + 1)
        if not alt:
            cursor += 2
            continue
        raw_alt, alt_closing = alt
        following = alt_closing + 1

        # `![[target]]` is an Obsidian wiki embed only when the complete outer
        # alt is not immediately followed by standard Markdown image syntax.
        if (
            masked_markdown.startswith("![[", cursor)
            and (following >= len(masked_markdown) or masked_markdown[following] not in "([")
        ):
            cursor = following
            continue

        raw_label = raw_alt
        raw_end = alt_closing + 1
        style = "shortcut"
        destination = ""
        if following < len(masked_markdown) and masked_markdown[following] == "(":
            inline = _parse_balanced_markdown_parentheses(masked_markdown, following)
            if inline:
                raw_destination, inline_closing = inline
                raw_end = inline_closing + 1
                style = "inline"
                destination = _inline_image_destination(raw_destination)
        if following < len(masked_markdown) and masked_markdown[following] == "[":
            label = _parse_balanced_markdown_brackets(masked_markdown, following)
            if label:
                raw_reference, reference_closing = label
                raw_label = raw_reference or raw_alt
                raw_end = reference_closing + 1
                style = "collapsed" if not raw_reference else "full"

        normalized_label = _normalize_reference_label(raw_label)
        found.append(
            {
                "start": cursor,
                "line": masked_markdown.count("\n", 0, cursor) + 1,
                "label": normalized_label,
                "style": style,
                "destination": destination,
                "text": masked_markdown[cursor:raw_end],
            }
        )
        cursor = max(cursor + 2, raw_end)
    return found


def find_unsupported_reference_images(markdown: str) -> list[dict]:
    return [
        {key: value for key, value in image.items() if key not in {"start", "style", "destination"}}
        for image in _scan_markdown_images(markdown)
        if image["style"] != "inline"
    ]


def find_unsupported_remote_images(markdown: str) -> list[dict]:
    found = []
    for image in _scan_markdown_images(markdown):
        destination = image["destination"]
        if image["style"] != "inline" or not re.match(r"^(?:https?:)?//", destination, re.IGNORECASE):
            continue
        found.append(
            {
                "line": image["line"],
                "url": destination,
                "text": image["text"],
            }
        )
    return found


def parse_markdown(markdown_file: Path, parse_script: Path | None) -> dict:
    script = parse_script
    if script is None:
        script = next((candidate for candidate in DEFAULT_PARSE_SCRIPTS if candidate.exists()), None)
    if script is None or not script.exists():
        raise FileNotFoundError("No parse_markdown.py found. Pass --parse-script explicitly.")

    env = os.environ.copy()
    env["MARKDOWN_FILE"] = str(markdown_file)
    result = subprocess.run(
        [sys.executable, str(script)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    data = json.loads(result.stdout)
    required = ["title", "html", "cover_image", "content_images", "expected_image_count"]
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"Parser output missing keys: {missing}")
    return data


def _nearest_visible_source_segment(raw_line: str, masked_line: str) -> str:
    """Find the nearest complete text segment, excluding real image tokens."""
    if not (masked_line or "").strip():
        return ""
    images = _scan_markdown_images(masked_line)
    segments = []
    cursor = 0
    for image in images:
        start = int(image["start"])
        end = start + len(str(image.get("text") or ""))
        if masked_line[cursor:start].strip():
            segments.append(raw_line[cursor:start])
        cursor = end
    if masked_line[cursor:].strip():
        segments.append(raw_line[cursor:])
    for segment in reversed(segments):
        candidate = clean_anchor(segment)
        if candidate and candidate != "-":
            return candidate
    return ""


def _source_anchor_before_index(source: str, masked_source: str, index: int) -> str:
    """Resolve the closest complete visible segment before a source offset."""
    line_start = source.rfind("\n", 0, index) + 1
    same_line = _nearest_visible_source_segment(
        source[line_start:index],
        masked_source[line_start:index],
    )
    if same_line:
        return same_line

    line_end = line_start - 1
    while line_end > 0:
        previous_start = source.rfind("\n", 0, line_end) + 1
        raw_line = source[previous_start:line_end]
        masked_line = masked_source[previous_start:line_end]
        if masked_line.strip() != "---":
            candidate = _nearest_visible_source_segment(raw_line, masked_line)
            if candidate:
                return candidate
        line_end = previous_start - 1
    return ""


def find_line_anchor(
    markdown_lines: list[str],
    image_path: str,
    occurrence: int = 1,
    source_path: str | None = None,
    markdown_dir: Path | None = None,
) -> tuple[str, int | None]:
    def normalized_path(value: str) -> str:
        decoded = urllib.parse.unquote(urllib.parse.unquote(str(value or ""))).strip()
        if decoded.startswith("<") and decoded.endswith(">"):
            decoded = decoded[1:-1].strip()
        candidate = Path(decoded)
        if markdown_dir is not None and not candidate.is_absolute():
            candidate = markdown_dir / candidate
        return os.path.normcase(os.path.normpath(os.path.abspath(str(candidate))))

    source = "\n".join(markdown_lines)
    masked_source = _masked_markdown_outside_frontmatter_and_fences(source)
    target_path = normalized_path(source_path or image_path)
    base = Path(source_path or image_path).name
    found = None
    matched_occurrence = 0
    for image in _scan_markdown_images(source):
        destination = urllib.parse.unquote(str(image.get("destination") or ""))
        destination_matches = normalized_path(destination) == target_path
        if not destination_matches and (markdown_dir is not None or source_path):
            continue
        if not destination_matches and Path(destination).name != base:
            continue
        matched_occurrence += 1
        if matched_occurrence == max(1, int(occurrence or 1)):
            found = image
            break
    if found is None:
        return "", None
    line = int(found["line"])
    return _source_anchor_before_index(
        source,
        masked_source,
        int(found["start"]),
    ), line


def build_content_images(data: dict, markdown_file: Path, include_cover_as_body: bool = False) -> list[dict]:
    lines = markdown_file.read_text(encoding="utf-8-sig").splitlines()
    images = list(data["content_images"])
    if include_cover_as_body and data.get("cover_image"):
        first_image = dict(data.get("cover_image_item") or {})
        images.insert(
            0,
            {
                **first_image,
                "path": data["cover_image"],
                "original_path": first_image.get("original_path") or data["cover_image"],
                "exists": Path(data["cover_image"]).exists(),
                "alt": first_image.get("alt") or "",
                "block_index": int(first_image.get("block_index") or 0),
                "after_text": first_image.get("after_text") or "",
                "text_before": first_image.get("text_before") or "",
                "text_after": first_image.get("text_after") or "",
                "block_type": first_image.get("block_type") or "paragraph",
                "source_occurrence": int(first_image.get("source_occurrence") or 1),
            },
        )

    items = []
    fallback_occurrences: Counter[str] = Counter()
    if data.get("cover_image") and not include_cover_as_body:
        fallback_cover_path = os.path.normcase(os.path.normpath(str(data["cover_image"])))
        fallback_occurrences[fallback_cover_path] = 1
    for index, image in enumerate(images, 1):
        normalized_path = os.path.normcase(os.path.normpath(str(image.get("path") or "")))
        fallback_occurrences[normalized_path] += 1
        source_occurrence = int(image.get("source_occurrence") or fallback_occurrences[normalized_path])
        primary, line = find_line_anchor(
            lines,
            image["path"],
            source_occurrence,
            source_path=image.get("original_path"),
            markdown_dir=markdown_file.parent,
        )
        parser_candidates = []
        for key in ("text_before", "after_text"):
            for part in (image.get(key) or "").split("\n"):
                candidate = clean_anchor(part)
                if candidate and candidate != "-" and candidate not in parser_candidates:
                    parser_candidates.append(candidate)
        candidates = []
        # The parser has already split mixed text/image lines into their exact
        # visible segments, so its complete anchor is authoritative. Raw source
        # scanning is only a fallback and must never reintroduce an earlier
        # image token into the candidate chosen for final persistence checks.
        ordered_candidates = parser_candidates + ([primary] if primary else [])
        for candidate in ordered_candidates:
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        placement = (
            MEDIA_PLACEMENT_COMPOSER_START
            if image.get("block_index") is not None and int(image.get("block_index") or 0) == 0
            else MEDIA_PLACEMENT_AFTER_ANCHOR
        )
        if placement == MEDIA_PLACEMENT_COMPOSER_START:
            # parse_markdown removes the leading H1 from the body. Any image whose parsed
            # insertion index is still zero belongs before the first surviving composer block,
            # so an anchor recovered from the original H1 cannot exist in X's body DOM.
            candidates = []
        items.append(
            {
                **image,
                "index": index,
                "line": line,
                "source_occurrence": source_occurrence,
                "placement": placement,
                "expected_anchor": candidates[0] if candidates else "",
                "candidates": candidates,
            }
        )
    return items


class _RichHtmlPlainTextParser(HTMLParser):
    BLOCK_END_TAGS = {"p", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "table", "blockquote", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"br", "hr"}:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"th", "td"}:
            self.parts.append("\t")
        elif normalized in self.BLOCK_END_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()


def plain_text_from_html(rich_html: str) -> str:
    parser = _RichHtmlPlainTextParser()
    parser.feed(rich_html or "")
    parser.close()
    return parser.text()


def build_end_check_text(plain_text: str, max_chars: int = 80) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in plain_text.splitlines()]
    lines = [line for line in lines if line]
    for line in reversed(lines):
        sentences = re.findall(r"[^。！？!?]+[。！？!?]?", line)
        for sentence in reversed(sentences):
            sentence = sentence.strip()
            if len(sentence) >= 8:
                return sentence[-max_chars:]
        if len(line) >= 8:
            return line[-max_chars:]
    collapsed = re.sub(r"\s+", " ", plain_text).strip()
    return collapsed[-max_chars:]


def normalize_content_for_verification(text: str) -> str:
    """Return the editor text form used by both preflight and browser checks."""
    without_transient_table_markers = TABLE_MARKER_RE.sub("", text or "")
    compact = IGNORED_EDITOR_WHITESPACE_RE.sub("", without_transient_table_markers)
    return unicodedata.normalize("NFC", compact)


def build_content_checkpoints(
    plain_text: str,
    count: int = CONTENT_CHECKPOINT_COUNT,
    max_chars: int = CONTENT_CHECKPOINT_CHARS,
) -> list[str]:
    """Build deterministic checkpoints without crossing transient table markers."""
    segments = [
        normalize_content_for_verification(segment)
        for segment in TABLE_MARKER_RE.split(plain_text or "")
    ]
    segments = [segment for segment in segments if segment]
    total_length = sum(len(segment) for segment in segments)
    if total_length == 0:
        return []

    if total_length < 3:
        return []

    checkpoint_count = min(5, max(3, count)) if total_length >= 160 else 3
    segment_spans = []
    consumed = 0
    for segment in segments:
        segment_spans.append((consumed, consumed + len(segment), segment))
        consumed += len(segment)

    checkpoints = []
    for index in range(checkpoint_count):
        bin_start = total_length * index // checkpoint_count
        bin_end = total_length * (index + 1) // checkpoint_count
        target = min(bin_end - 1, (bin_start + bin_end) // 2)
        selected_start, selected_end, selected = segment_spans[-1]
        for segment_start, segment_end, segment in segment_spans:
            if segment_start <= target < segment_end:
                selected_start, selected_end, selected = segment_start, segment_end, segment
                break
        available_start = max(bin_start, selected_start)
        available_end = min(bin_end, selected_end)
        width = min(max_chars, max(1, available_end - available_start))
        local_position = target - selected_start
        minimum_start = available_start - selected_start
        maximum_start = available_end - selected_start - width
        start = min(max(minimum_start, local_position - width // 2), maximum_start)
        checkpoints.append(selected[start : start + width])
    return checkpoints


def build_content_verification_contract(plain_text: str) -> dict:
    compact = normalize_content_for_verification(plain_text)
    expected_compact_length = len(compact)
    return {
        "content_checkpoints": build_content_checkpoints(plain_text),
        "expected_compact_length": expected_compact_length,
        "expected_compact_sha256": hashlib.sha256(compact.encode("utf-8")).hexdigest(),
        "compact_length_unit": CONTENT_LENGTH_UNIT,
        "checkpoint_position_unit": CONTENT_LENGTH_UNIT,
    }


def normalize_markdown_table(markdown: str) -> str:
    return "\n".join(line.rstrip() for line in (markdown or "").strip().splitlines())


def normalize_table_cell_text(value: str) -> str:
    """Normalize the semantic text X must visibly render in a table cell."""
    text = htmlmod.unescape(value or "")
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(`+)(.*?)\1", r"\2", text)
    text = re.sub(r"(?<!\\)(\*\*|__|~~)(.+?)(?<!\\)\1", r"\2", text)
    text = re.sub(r"(?<!\\)([*_])([^*_\n]+?)(?<!\\)\1", r"\2", text)
    text = re.sub(r"\\([\\`*{}\[\]()#+\-.!|>_])", r"\1", text)
    text = unicodedata.normalize("NFC", re.sub(r"\s+", " ", text).strip())
    return text


def expected_table_matrix(table: dict) -> list[list[str]]:
    rows = table.get("rows") or []
    return [[normalize_table_cell_text(str(cell)) for cell in row] for row in rows]


def validate_table_contract(table: dict) -> dict:
    """Build a fail-closed visible table contract for browser verification."""
    matrix = expected_table_matrix(table)
    expected_rows = int(table.get("row_count") or 0)
    expected_columns = int(table.get("column_count") or 0)
    dimensions_match = (
        expected_rows > 0
        and expected_columns > 0
        and len(matrix) == expected_rows
        and all(len(row) == expected_columns for row in matrix)
    )
    non_empty_cells = sum(1 for row in matrix for cell in row if cell)
    return {
        "rows": expected_rows,
        "columns": expected_columns,
        "matrix": matrix,
        "dimensions_match": dimensions_match,
        "non_empty_cells": non_empty_cells,
        "valid": dimensions_match and non_empty_cells > 0,
    }


def _replace_markdown_inline_links(value: str) -> str:
    """Keep visible link/image labels while discarding inline destinations."""
    source = value or ""
    rendered = []
    cursor = 0
    while cursor < len(source):
        image_prefix = source.startswith("![", cursor) and not _is_markdown_escaped(source, cursor)
        bracket_index = cursor + 1 if image_prefix else cursor
        if (
            bracket_index >= len(source)
            or source[bracket_index] != "["
            or _is_markdown_escaped(source, bracket_index)
        ):
            rendered.append(source[cursor])
            cursor += 1
            continue
        label = _parse_balanced_markdown_brackets(source, bracket_index)
        if not label:
            rendered.append(source[cursor])
            cursor += 1
            continue
        raw_label, label_closing = label
        following = label_closing + 1
        destination = _parse_balanced_markdown_parentheses(source, following)
        reference = _parse_balanced_markdown_brackets(source, following)
        if not destination and not reference:
            rendered.append(source[cursor])
            cursor += 1
            continue
        rendered.append(raw_label)
        cursor = (destination or reference)[1] + 1
    return "".join(rendered)


def _protect_markdown_code_spans(value: str) -> tuple[str, dict[str, str]]:
    """Protect visible code text from later Markdown emphasis processing."""
    protected: dict[str, str] = {}

    def replace(match: re.Match) -> str:
        content = re.sub(r"[\r\n]+", " ", match.group(2))
        if (
            len(content) >= 2
            and content.startswith(" ")
            and content.endswith(" ")
            and content.strip()
        ):
            content = content[1:-1]
        token_index = len(protected)
        token = f"\ue100XANCHORCODE{token_index:06d}\ue101"
        while token in (value or "") or token in protected:
            token_index += 1
            token = f"\ue100XANCHORCODE{token_index:06d}\ue101"
        protected[token] = content
        return token

    rendered = re.sub(
        r"(?<!\\)(`+)(.+?)(?<!`)\1(?!`)",
        replace,
        value or "",
        flags=re.DOTALL,
    )
    return rendered, protected


def _protect_markdown_escaped_punctuation(value: str) -> tuple[str, dict[str, str]]:
    """Protect escaped literal punctuation from entity/format parsing."""
    protected: dict[str, str] = {}

    def replace(match: re.Match) -> str:
        token_index = len(protected)
        token = f"\ue102XANCHORESC{token_index:06d}\ue103"
        while token in (value or "") or token in protected:
            token_index += 1
            token = f"\ue102XANCHORESC{token_index:06d}\ue103"
        protected[token] = match.group(1)
        return token

    rendered = re.sub(
        rf"\\([{MARKDOWN_ESCAPABLE_ASCII_CLASS}])",
        replace,
        value or "",
    )
    return rendered, protected


def normalize_visible_media_anchor(value: str) -> str:
    """Normalize text already rendered visibly by X without re-parsing Markdown."""
    text = value or ""
    text = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", text)
    text = clean_anchor(re.sub(r"\s+", " ", text))
    return unicodedata.normalize("NFC", text).strip()


def normalize_media_anchor(value: str) -> str:
    """Render a source Markdown anchor into its canonical visible semantic text."""
    text, protected_code = _protect_markdown_code_spans(value or "")
    text, protected_escapes = _protect_markdown_escaped_punctuation(text)
    text = htmlmod.unescape(text)
    text = _replace_markdown_inline_links(text)
    text = re.sub(
        r"<((?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^<>\s]*)|(?:[^\s<>]+@[^\s<>]+))>",
        r"\1",
        text,
    )
    # Remove only paired, unescaped inline formatting. Escaped punctuation is
    # unescaped afterwards so literal `\*` remains a visible asterisk.
    for pattern in (
        r"(?<!\\)(\*\*|__|~~)(?=\S)(.+?)(?<=\S)\1",
        r"(?<!\\)(\*|_)(?=\S)(.+?)(?<=\S)\1",
    ):
        previous = None
        while previous != text:
            previous = text
            text = re.sub(pattern, r"\2", text, flags=re.DOTALL)
    for token, content in protected_escapes.items():
        text = text.replace(token, content)
    for token, content in protected_code.items():
        text = text.replace(token, content)
    return normalize_visible_media_anchor(text)


def media_anchor_matches(expected: str, actual: str) -> bool:
    expected_anchor = normalize_media_anchor(expected)
    actual_anchor = normalize_visible_media_anchor(actual)
    return bool(
        expected_anchor
        and actual_anchor
        and (
            expected_anchor == actual_anchor
            # X can merge adjacent non-empty Markdown lines into one DOM block.
            # In that case the true nearest anchor remains the exact semantic
            # suffix. Do not accept a middle substring or truncated paragraph.
            or actual_anchor.endswith(expected_anchor)
        )
    )


def media_position_matches(
    expected: dict,
    actual_anchor: str,
    allow_temporary_start_marker: bool = False,
) -> bool:
    """Validate either a text anchor or an explicit body-start placement."""
    if expected.get("placement") == MEDIA_PLACEMENT_COMPOSER_START:
        normalized_actual = normalize_visible_media_anchor(actual_anchor)
        return not normalized_actual or bool(
            allow_temporary_start_marker and normalized_actual == MEDIA_START_MARKER
        )
    return media_anchor_matches(expected.get("expected_anchor") or "", actual_anchor)


def validate_composer_media_evidence(items: list[dict], content_images: list[dict]) -> dict:
    """Validate source-bound body media without assuming globally unique/exact hashes."""
    expected_count = len(content_images)
    details = []
    signatures = []
    observed_occurrences: Counter[str] = Counter()
    for index, (item, expected) in enumerate(zip(items, content_images), 1):
        observed_signature = str(item.get("sourceSignature") or "")
        local_source_signature = str(expected.get("source_signature") or "")
        expected_occurrence = int(expected.get("source_occurrence") or 0)
        expected_dom_order = int(expected.get("expected_dom_order", index - 1))
        source_comparison = evaluate_source_visual_match(
            observed_signature,
            expected,
            content_images,
            int(item.get("naturalWidth") or 0),
            int(item.get("naturalHeight") or 0),
            str(item.get("visualSample") or ""),
        )
        source_distance = source_comparison["expected_source_distance"]
        source_matches = source_comparison["valid"]
        if source_matches:
            observed_occurrences[local_source_signature] += 1
        actual_occurrence = observed_occurrences[local_source_signature]
        occurrence_matches = expected_occurrence > 0 and actual_occurrence == expected_occurrence
        actual_dom_order = int(item.get("mediaIndex", index - 1))
        dom_order_matches = actual_dom_order == expected_dom_order
        anchor_matches = media_position_matches(expected, item.get("anchorBefore") or "")
        recognizable = bool(
            VISUAL_SIGNATURE_RE.fullmatch(observed_signature)
            and int(item.get("naturalWidth") or 0) > 0
            and int(item.get("naturalHeight") or 0) > 0
        )
        identity_key = str(expected.get("identity_key") or "")
        expected_identity_key = media_identity_key(
            local_source_signature,
            expected_occurrence,
            expected.get("expected_anchor") or "",
            expected_dom_order,
        ) if VISUAL_SIGNATURE_RE.fullmatch(local_source_signature) and expected_occurrence > 0 else ""
        identity_matches = bool(identity_key and identity_key == expected_identity_key)
        signatures.append(observed_signature)
        details.append(
            {
                "index": index,
                "file": Path(expected.get("path") or "").name,
                "source_signature": local_source_signature,
                "observed_signature": observed_signature,
                "source_hamming_distance": source_distance,
                "source_matches": source_matches,
                "distinct_source_group_count": source_comparison["distinct_source_group_count"],
                "source_group_distances": source_comparison["source_group_distances"],
                "nearest_source_distance": source_comparison["nearest_source_distance"],
                "second_nearest_source_distance": source_comparison["second_nearest_source_distance"],
                "nearest_source_margin": source_comparison["nearest_source_margin"],
                "nearest_source_signatures": source_comparison["nearest_source_signatures"],
                "nearest_source_ambiguous": source_comparison["nearest_source_ambiguous"],
                "source_ambiguous": source_comparison["source_ambiguous"],
                "expected_source_is_unique_nearest": source_comparison["expected_source_is_unique_nearest"],
                "strict_source_match": source_comparison["strict_source_match"],
                "adaptive_source_match": source_comparison["adaptive_source_match"],
                "sample_consensus_match": source_comparison["sample_consensus_match"],
                "sample_similarity_matches": source_comparison["sample_similarity_matches"],
                "sample_margin_matches": source_comparison["sample_margin_matches"],
                "distinct_source_sample_group_count": source_comparison[
                    "distinct_source_sample_group_count"
                ],
                "source_sample_distances": source_comparison["source_sample_distances"],
                "nearest_source_sample_distance": source_comparison[
                    "nearest_source_sample_distance"
                ],
                "second_nearest_source_sample_distance": source_comparison[
                    "second_nearest_source_sample_distance"
                ],
                "expected_source_sample_id": source_comparison[
                    "expected_source_sample_id"
                ],
                "expected_source_sample_is_unique_nearest": source_comparison[
                    "expected_source_sample_is_unique_nearest"
                ],
                "rgb_mean_absolute_error": (
                    source_comparison["expected_source_sample_metrics"] or {}
                ).get("rgb_mean_absolute_error"),
                "luma_mean_absolute_error": (
                    source_comparison["expected_source_sample_metrics"] or {}
                ).get("luma_mean_absolute_error"),
                "luma_correlation": (
                    source_comparison["expected_source_sample_metrics"] or {}
                ).get("luma_correlation"),
                "nearest_source_sample_margin": source_comparison["nearest_source_sample_margin"],
                "adaptive_margin_matches": source_comparison["adaptive_margin_matches"],
                "match_policy": source_comparison["match_policy"],
                "source_natural_width": source_comparison["source_natural_width"],
                "source_natural_height": source_comparison["source_natural_height"],
                "aspect_ratio_relative_drift": source_comparison["aspect_ratio_relative_drift"],
                "aspect_ratio_matches": source_comparison["aspect_ratio_matches"],
                "signature_hamming_distance": source_distance,
                "signature_match": source_matches,
                "source_occurrence": expected_occurrence,
                "observed_occurrence": actual_occurrence,
                "occurrence": expected_occurrence,
                "occurrence_matches": occurrence_matches,
                "identity_key": identity_key,
                "binding_key": identity_key,
                "identity_matches": identity_matches,
                "natural_width": int(item.get("naturalWidth") or 0),
                "natural_height": int(item.get("naturalHeight") or 0),
                "dom_order": actual_dom_order,
                "expected_dom_order": expected_dom_order,
                "dom_order_matches": dom_order_matches,
                "block_index": item.get("blockIndex"),
                "anchor_before": item.get("anchorBefore") or "",
                "expected_anchor": expected.get("expected_anchor") or "",
                "anchor_matches": anchor_matches,
                "recognizable": recognizable,
            }
        )
    exact_count = len(items) == expected_count
    ordered_identity_keys = [item["identity_key"] for item in details]
    return {
        "expected_count": expected_count,
        "actual_count": len(items),
        "exact_count": exact_count,
        "duplicate_signatures_allowed": True,
        "ordered_signatures": signatures,
        "ordered_identity_keys": ordered_identity_keys,
        "ordered_binding_keys": ordered_identity_keys,
        "items": details,
        "valid": (
            exact_count
            and len(details) == expected_count
            and all(
                item["recognizable"]
                and item["source_matches"]
                and item["occurrence_matches"]
                and item["identity_matches"]
                and item["anchor_matches"]
                and item["dom_order_matches"]
                for item in details
            )
        ),
    }


def composer_media_identity_is_valid(evidence: dict) -> bool:
    """Validate all stable media facts except a transient DOM text anchor."""
    items = list((evidence or {}).get("items") or [])
    return bool(
        (evidence or {}).get("exact_count")
        and len(items) == int((evidence or {}).get("expected_count") or 0)
        and all(
            item.get("recognizable")
            and item.get("source_matches")
            and item.get("occurrence_matches")
            and item.get("identity_matches")
            and item.get("dom_order_matches")
            for item in items
        )
    )


def identify_single_new_media_signature(
    before_items: list[dict],
    after_items: list[dict],
    expected: dict | None = None,
    source_contract: list[dict] | None = None,
) -> dict:
    """Bind one paste to one DOM node and the expected local visual identity."""
    before_signatures = [str(item.get("sourceSignature") or "") for item in before_items]
    after_signatures = [str(item.get("sourceSignature") or "") for item in after_items]
    before_runtime_keys = [str(item.get("runtimeKey") or "") for item in before_items]
    after_runtime_keys = [str(item.get("runtimeKey") or "") for item in after_items]

    def observed_media_survives(before_item: dict, after_item: dict) -> bool:
        """Compare hosted pixels; uploader-only DOM attributes may vanish on rerender."""
        before_signature = str(before_item.get("sourceSignature") or "")
        after_signature = str(after_item.get("sourceSignature") or "")
        if visual_signatures_match(
            before_signature,
            after_signature,
            max_distance=VISUAL_PERSISTED_NODE_DHASH_MAX_DISTANCE,
        ):
            return True
        before_sample = str(before_item.get("visualSample") or "")
        after_sample = str(after_item.get("visualSample") or "")
        sample_metrics = visual_rgb_sample_metrics(before_sample, after_sample)
        aspect = visual_aspect_ratio_evidence(
            int(before_item.get("naturalWidth") or 0),
            int(before_item.get("naturalHeight") or 0),
            int(after_item.get("naturalWidth") or 0),
            int(after_item.get("naturalHeight") or 0),
        )
        return bool(
            sample_metrics
            and sample_metrics["rgb_mean_absolute_error"]
            <= VISUAL_PERSISTED_NODE_RGB_SAMPLE_MAX_MAE
            and sample_metrics["luma_mean_absolute_error"]
            <= VISUAL_PERSISTED_NODE_LUMA_SAMPLE_MAX_MAE
            and (
                sample_metrics["luma_correlation"] is None
                or sample_metrics["luma_correlation"]
                >= VISUAL_PERSISTED_NODE_LUMA_CORRELATION_MIN
            )
            and aspect["aspect_ratio_matches"]
        )

    def sequence_survives_removal(candidate_index: int) -> bool:
        remaining = after_items[:candidate_index] + after_items[candidate_index + 1 :]
        if len(remaining) != len(before_items):
            return False
        return all(
            observed_media_survives(before_item, after_item)
            for before_item, after_item in zip(before_items, remaining)
        )

    candidate_indices = [
        index for index in range(len(after_items)) if sequence_survives_removal(index)
    ]

    expected = expected or {}
    local_source_signature = str(expected.get("source_signature") or "")
    expected_anchor = expected.get("expected_anchor") or ""
    source_contract = source_contract or ([expected] if expected else [])
    matching_candidates = []
    identity_candidate_indices = []
    candidate_evidence = {}
    for candidate_index in candidate_indices:
        candidate = after_items[candidate_index]
        observed_signature = str(candidate.get("sourceSignature") or "")
        source_comparison = (
            evaluate_source_visual_match(
                observed_signature,
                expected,
                source_contract,
                int(candidate.get("naturalWidth") or 0),
                int(candidate.get("naturalHeight") or 0),
                str(candidate.get("visualSample") or ""),
            )
            if local_source_signature
            else {
                "distinct_source_group_count": 0,
                "source_group_distances": [],
                "nearest_source_distance": None,
                "second_nearest_source_distance": None,
                "nearest_source_margin": None,
                "nearest_source_signatures": [],
                "nearest_source_ambiguous": False,
                "source_ambiguous": False,
                "expected_source_distance": 0 if VISUAL_SIGNATURE_RE.fullmatch(observed_signature) else None,
                "expected_source_is_unique_nearest": True,
                "expected_source_within_radius": bool(VISUAL_SIGNATURE_RE.fullmatch(observed_signature)),
                "expected_source_within_adaptive_radius": bool(VISUAL_SIGNATURE_RE.fullmatch(observed_signature)),
                "strict_source_match": bool(VISUAL_SIGNATURE_RE.fullmatch(observed_signature)),
                "adaptive_source_match": False,
                "sample_consensus_match": False,
                "sample_similarity_matches": False,
                "sample_margin_matches": False,
                "distinct_source_sample_group_count": 0,
                "source_sample_distances": [],
                "nearest_source_sample_distance": None,
                "second_nearest_source_sample_distance": None,
                "nearest_source_sample_margin": None,
                "expected_source_sample_is_unique_nearest": False,
                "expected_source_sample_metrics": None,
                "adaptive_margin_matches": True,
                "match_policy": "unbound-recognizable" if VISUAL_SIGNATURE_RE.fullmatch(observed_signature) else "rejected",
                "source_natural_width": 0,
                "source_natural_height": 0,
                "observed_natural_width": int(candidate.get("naturalWidth") or 0),
                "observed_natural_height": int(candidate.get("naturalHeight") or 0),
                "aspect_ratio_relative_drift": None,
                "aspect_ratio_matches": False,
                "valid": bool(VISUAL_SIGNATURE_RE.fullmatch(observed_signature)),
            }
        )
        source_matches = source_comparison["valid"]
        anchor_matches = media_position_matches(
            expected,
            candidate.get("anchorBefore") or "",
            allow_temporary_start_marker=True,
        )
        candidate_evidence[candidate_index] = {
            "source_comparison": source_comparison,
            "anchor_matches": anchor_matches,
            "prior_sequence_preserved": sequence_survives_removal(candidate_index),
        }
        if (
            source_matches
            and candidate_evidence[candidate_index]["prior_sequence_preserved"]
        ):
            identity_candidate_indices.append(candidate_index)
        if (
            source_matches
            and anchor_matches
            and candidate_evidence[candidate_index]["prior_sequence_preserved"]
        ):
            matching_candidates.append(candidate_index)

    candidate_index = (
        matching_candidates[0]
        if len(matching_candidates) == 1
        else identity_candidate_indices[0]
        if len(identity_candidate_indices) == 1
        else candidate_indices[0]
        if len(candidate_indices) == 1
        else -1
    )
    candidate = after_items[candidate_index] if candidate_index >= 0 else {}
    observed_signature = str(candidate.get("sourceSignature") or "")
    source_comparison = candidate_evidence.get(candidate_index, {}).get(
        "source_comparison",
        {
            "distinct_source_group_count": 0,
            "source_group_distances": [],
            "nearest_source_distance": None,
            "second_nearest_source_distance": None,
            "nearest_source_margin": None,
            "nearest_source_signatures": [],
            "nearest_source_ambiguous": False,
            "source_ambiguous": False,
            "expected_source_distance": None,
            "expected_source_is_unique_nearest": False,
            "expected_source_within_radius": False,
            "expected_source_within_adaptive_radius": False,
            "strict_source_match": False,
            "adaptive_source_match": False,
            "sample_consensus_match": False,
            "sample_similarity_matches": False,
            "sample_margin_matches": False,
            "distinct_source_sample_group_count": 0,
            "source_sample_distances": [],
            "nearest_source_sample_distance": None,
            "second_nearest_source_sample_distance": None,
            "nearest_source_sample_margin": None,
            "expected_source_sample_is_unique_nearest": False,
            "expected_source_sample_metrics": None,
            "adaptive_margin_matches": False,
            "match_policy": "rejected",
            "source_natural_width": int(expected.get("source_natural_width") or 0),
            "source_natural_height": int(expected.get("source_natural_height") or 0),
            "observed_natural_width": int(candidate.get("naturalWidth") or 0),
            "observed_natural_height": int(candidate.get("naturalHeight") or 0),
            "aspect_ratio_relative_drift": None,
            "aspect_ratio_matches": False,
            "valid": False,
        },
    )
    source_distance = source_comparison["expected_source_distance"]
    recognizable = bool(VISUAL_SIGNATURE_RE.fullmatch(observed_signature))
    identity_key = str(expected.get("identity_key") or "")
    identity_binding_valid = bool(
        len(after_items) == len(before_items) + 1
        and len(identity_candidate_indices) == 1
        and recognizable
        and (not local_source_signature or source_comparison["valid"])
        and (not expected or bool(identity_key))
    )
    position_binding_valid = bool(
        identity_binding_valid and len(matching_candidates) == 1
    )
    return {
        "before_signatures": before_signatures,
        "after_signatures": after_signatures,
        "before_runtime_keys": before_runtime_keys,
        "after_runtime_keys": after_runtime_keys,
        "candidate_indices": candidate_indices,
        "identity_candidate_indices": identity_candidate_indices,
        "matching_candidate_indices": matching_candidates,
        "actual_dom_order": candidate_index,
        "expected_final_dom_order": expected.get("expected_dom_order"),
        "source_signature": local_source_signature or observed_signature,
        "observed_signature": observed_signature,
        "source_hamming_distance": source_distance,
        "distinct_source_group_count": source_comparison["distinct_source_group_count"],
        "source_group_distances": source_comparison["source_group_distances"],
        "nearest_source_distance": source_comparison["nearest_source_distance"],
        "second_nearest_source_distance": source_comparison["second_nearest_source_distance"],
        "nearest_source_margin": source_comparison["nearest_source_margin"],
        "nearest_source_signatures": source_comparison["nearest_source_signatures"],
        "nearest_source_ambiguous": source_comparison["nearest_source_ambiguous"],
        "source_ambiguous": source_comparison["source_ambiguous"],
        "expected_source_is_unique_nearest": source_comparison["expected_source_is_unique_nearest"],
        "strict_source_match": source_comparison["strict_source_match"],
        "adaptive_source_match": source_comparison["adaptive_source_match"],
        "sample_consensus_match": source_comparison["sample_consensus_match"],
        "sample_similarity_matches": source_comparison["sample_similarity_matches"],
        "sample_margin_matches": source_comparison["sample_margin_matches"],
        "rgb_mean_absolute_error": (
            source_comparison["expected_source_sample_metrics"] or {}
        ).get("rgb_mean_absolute_error"),
        "luma_mean_absolute_error": (
            source_comparison["expected_source_sample_metrics"] or {}
        ).get("luma_mean_absolute_error"),
        "luma_correlation": (
            source_comparison["expected_source_sample_metrics"] or {}
        ).get("luma_correlation"),
        "nearest_source_sample_margin": source_comparison["nearest_source_sample_margin"],
        "adaptive_margin_matches": source_comparison["adaptive_margin_matches"],
        "match_policy": source_comparison["match_policy"],
        "source_natural_width": source_comparison["source_natural_width"],
        "source_natural_height": source_comparison["source_natural_height"],
        "observed_natural_width": source_comparison["observed_natural_width"],
        "observed_natural_height": source_comparison["observed_natural_height"],
        "aspect_ratio_relative_drift": source_comparison["aspect_ratio_relative_drift"],
        "aspect_ratio_matches": source_comparison["aspect_ratio_matches"],
        "signature_hamming_distance": source_distance,
        "signature_match": bool(source_comparison["valid"] if local_source_signature else recognizable),
        "source_matches": bool(source_comparison["valid"]),
        "source_occurrence": expected.get("source_occurrence"),
        "occurrence": expected.get("source_occurrence"),
        "anchor_before": candidate.get("anchorBefore") or "",
        "expected_anchor": expected_anchor,
        "anchor_matches": bool(
            candidate_evidence.get(candidate_index, {}).get("anchor_matches")
        ),
        "prior_sequence_preserved": bool(
            candidate_evidence.get(candidate_index, {}).get("prior_sequence_preserved")
        ),
        "identity_key": identity_key,
        "binding_key": identity_key,
        "recognizable": recognizable,
        "identity_binding_valid": identity_binding_valid,
        "position_binding_valid": position_binding_valid,
        "position_verification_deferred": bool(
            identity_binding_valid and not position_binding_valid
        ),
        # This is transient diagnostic evidence only. The caller separately
        # requires an exact +1 media count for the paste, then independently
        # recomputes source identity/count/order/position after same-URL reload.
        "eligible_for_final_verification": identity_binding_valid,
        "valid": position_binding_valid,
    }


def validate_media_phase_persistence(before: dict, after: dict) -> dict:
    """Report cross-phase diagnostics while treating final evidence as authority."""
    before_items = before.get("items") or []
    after_items = after.get("items") or []
    distances = [
        visual_signature_hamming_distance(
            str(left.get("observed_signature") or ""),
            str(right.get("observed_signature") or ""),
        )
        for left, right in zip(before_items, after_items)
    ]
    ordered_identities_match = (
        before.get("ordered_identity_keys") == after.get("ordered_identity_keys")
    )
    before_identity_valid = composer_media_identity_is_valid(before)
    cross_phase_observation_valid = bool(
        before_identity_valid and after.get("valid") and ordered_identities_match
    )
    return {
        "before_valid": before_identity_valid,
        "before_position_valid": bool(before.get("valid")),
        "after_valid": bool(after.get("valid")),
        "ordered_identities_match": ordered_identities_match,
        "observed_pre_post_hamming_distances": distances,
        "exact_signatures_equal": before.get("ordered_signatures") == after.get("ordered_signatures"),
        "cross_phase_observation_valid": cross_phase_observation_valid,
        "valid": bool(after.get("valid")),
    }


def validate_final_media_contract(
    final_evidence: dict,
    source_contract: list[dict],
) -> dict:
    """Independently validate the authoritative post-reload media assignment."""
    expected_binding_keys = [
        item["identity_key"]
        for item in sorted(
            source_contract,
            key=lambda value: int(value["expected_dom_order"]),
        )
    ]
    actual_binding_keys = list((final_evidence or {}).get("ordered_identity_keys") or [])
    exact_count = int((final_evidence or {}).get("actual_count") or 0) == len(source_contract)
    return {
        "expected_binding_keys": expected_binding_keys,
        "actual_binding_keys": actual_binding_keys,
        "exact_count": exact_count,
        "source_identity_count_order_position_valid": bool(
            (final_evidence or {}).get("valid")
        ),
        "binding_keys_match": actual_binding_keys == expected_binding_keys,
        "valid": bool(
            exact_count
            and (final_evidence or {}).get("valid")
            and actual_binding_keys == expected_binding_keys
        ),
    }


def validate_cover_evidence(
    items: list[dict],
    expected: bool,
    source_item: dict | None = None,
    cleared_baseline_count: int | None = None,
) -> dict:
    signatures = [str(item.get("sourceSignature") or "") for item in items]
    exact_count = len(items) == (1 if expected else 0)
    recognizable = all(VISUAL_SIGNATURE_RE.fullmatch(signature) for signature in signatures)
    source_signature = str((source_item or {}).get("sourceSignature") or "")
    source_evidence = (
        evaluate_source_visual_match(
            signatures[0],
            source_item or {},
            [source_item or {}],
            int(items[0].get("naturalWidth") or 0),
            int(items[0].get("naturalHeight") or 0),
            str(items[0].get("visualSample") or ""),
        )
        if expected and len(signatures) == 1
        else None
    )
    source_distance = source_evidence["expected_source_distance"] if source_evidence else None
    source_matches = not expected or bool(source_evidence and source_evidence["valid"])
    source_sample_metrics = (
        (source_evidence or {}).get("expected_source_sample_metrics") or {}
    )
    added_from_cleared_state = (
        cleared_baseline_count is None
        or cleared_baseline_count == 0 and len(items) == (1 if expected else 0)
    )
    return {
        "expected_count": 1 if expected else 0,
        "actual_count": len(items),
        "exact_count": exact_count,
        "ordered_signatures": signatures,
        "source_signature": source_signature,
        "source_hamming_distance": source_distance,
        "source_matches": source_matches,
        "strict_source_match": bool(source_evidence and source_evidence["strict_source_match"]),
        "adaptive_source_match": bool(source_evidence and source_evidence["adaptive_source_match"]),
        "sample_consensus_match": bool(source_evidence and source_evidence["sample_consensus_match"]),
        "sample_similarity_matches": bool(source_evidence and source_evidence["sample_similarity_matches"]),
        "sample_margin_matches": bool(source_evidence and source_evidence["sample_margin_matches"]),
        "distinct_source_sample_group_count": int(
            (source_evidence or {}).get("distinct_source_sample_group_count") or 0
        ),
        "source_sample_distances": list(
            (source_evidence or {}).get("source_sample_distances") or []
        ),
        "nearest_source_sample_distance": (source_evidence or {}).get(
            "nearest_source_sample_distance"
        ),
        "second_nearest_source_sample_distance": (source_evidence or {}).get(
            "second_nearest_source_sample_distance"
        ),
        "nearest_source_sample_margin": (source_evidence or {}).get(
            "nearest_source_sample_margin"
        ),
        "expected_source_sample_id": (source_evidence or {}).get(
            "expected_source_sample_id"
        ) or "",
        "expected_source_sample_is_unique_nearest": bool(
            source_evidence
            and source_evidence["expected_source_sample_is_unique_nearest"]
        ),
        "rgb_mean_absolute_error": source_sample_metrics.get("rgb_mean_absolute_error"),
        "luma_mean_absolute_error": source_sample_metrics.get("luma_mean_absolute_error"),
        "luma_correlation": source_sample_metrics.get("luma_correlation"),
        "match_policy": source_evidence["match_policy"] if source_evidence else "not-applicable",
        "distinct_source_group_count": int(
            (source_evidence or {}).get("distinct_source_group_count") or 0
        ),
        "nearest_source_distance": (source_evidence or {}).get("nearest_source_distance"),
        "second_nearest_source_distance": (source_evidence or {}).get(
            "second_nearest_source_distance"
        ),
        "nearest_source_margin": source_evidence["nearest_source_margin"] if source_evidence else None,
        "expected_source_is_unique_nearest": bool(
            source_evidence and source_evidence["expected_source_is_unique_nearest"]
        ),
        "adaptive_margin_matches": bool(
            source_evidence and source_evidence["adaptive_margin_matches"]
        ),
        "source_natural_width": int(
            (source_evidence or {}).get("source_natural_width") or 0
        ),
        "source_natural_height": int(
            (source_evidence or {}).get("source_natural_height") or 0
        ),
        "observed_natural_width": int(
            (source_evidence or {}).get("observed_natural_width") or 0
        ),
        "observed_natural_height": int(
            (source_evidence or {}).get("observed_natural_height") or 0
        ),
        "aspect_ratio_relative_drift": source_evidence["aspect_ratio_relative_drift"] if source_evidence else None,
        "aspect_ratio_matches": bool(source_evidence and source_evidence["aspect_ratio_matches"]),
        "signature_hamming_distance": source_distance,
        "signature_match": source_matches,
        "cleared_baseline_count": cleared_baseline_count,
        "added_from_cleared_state": added_from_cleared_state,
        "items": items,
        "recognizable": recognizable,
        "valid": exact_count and recognizable and source_matches and added_from_cleared_state,
    }


def validate_resume_images_only_state(
    state: dict,
    upload_cover: bool,
    cover_source_item: dict | None,
) -> dict:
    """Fail closed before image-only resume can write or duplicate any media."""
    body_media = list(state.get("bodyMedia") or [])
    body_media_count = int(state.get("bodyMediaCount") or len(body_media))
    cover_media = list(state.get("coverMedia") or [])
    cover_evidence = validate_cover_evidence(
        cover_media,
        upload_cover,
        source_item=cover_source_item,
        cleared_baseline_count=None,
    )
    body_media_empty = body_media_count == 0 and len(body_media) == 0
    return {
        "mode": "resume_images_only",
        "body_media_count": body_media_count,
        "body_media_items_count": len(body_media),
        "body_media_empty": body_media_empty,
        "cover": cover_evidence,
        "verified": bool(body_media_empty and cover_evidence["valid"]),
    }


def validate_autosave_epoch_evidence(raw: dict, expected_epoch: str) -> dict:
    """Require post-mutation evidence from a real bounded save-status node."""
    events = list(raw.get("events") or [])
    cursor = int(
        raw.get("lastMutationSequence")
        if raw.get("lastMutationSequence") is not None
        else raw.get("lastMutationEventCursor") or 0
    )
    sequenced_events = [
        item
        for item in events
        if isinstance(item.get("sequence"), (int, float))
    ]
    relevant = (
        [item for item in sequenced_events if int(item["sequence"]) > cursor]
        if sequenced_events
        else events[cursor:]
    )
    last_mutation_at = int(raw.get("lastMutationAt") or 0)
    saved_now = [item for item in (raw.get("current") or []) if item.get("state") == "saved"]
    saved_now_by_channel = {
        item.get("channelKey"): item
        for item in saved_now
        if item.get("channelKey")
    }

    def recent_saved(item: dict) -> bool:
        text = str(item.get("text") or "").strip()
        return bool(
            re.search(
                r"(?:刚刚最后保存|刚刚保存|Last saved\s+(?:just now|now)|^Saved(?:\b|\s|$))",
                text,
                re.IGNORECASE,
            )
        )

    mutation_baseline = {
        item.get("channelKey"): item
        for item in (raw.get("mutationBaseline") or [])
        if item.get("channelKey")
    }
    previous_by_channel = dict(mutation_baseline)
    channel_changed_sequences: set[int] = set()
    for item in relevant:
        channel = item.get("channelKey")
        sequence = int(item.get("sequence") or 0)
        previous = previous_by_channel.get(channel)
        if channel and sequence > cursor and (
            previous is None
            or item.get("token") != previous.get("token")
            or item.get("nodeInstance") != previous.get("nodeInstance")
        ):
            channel_changed_sequences.add(sequence)
        if channel:
            previous_by_channel[channel] = item

    def event_is_current_channel(item: dict, exact: bool = False) -> bool:
        current = saved_now_by_channel.get(item.get("channelKey"))
        if not current:
            return False
        if not exact:
            return True
        return bool(
            item.get("token") == current.get("token")
            and item.get("nodeInstance") == current.get("nodeInstance")
        )

    def event_is_post_mutation(item: dict) -> bool:
        return bool(
            int(item.get("sequence") or 0) > cursor
            and int(item.get("observedAt") or 0) > last_mutation_at
        )

    transitions = []
    for saving_index, saving in enumerate(relevant):
        if saving.get("state") != "saving" or not event_is_post_mutation(saving):
            continue
        for saved in relevant[saving_index + 1 :]:
            if (
                saved.get("state") == "saved"
                and saved.get("channelKey") == saving.get("channelKey")
                and event_is_post_mutation(saved)
                and event_is_current_channel(saved, exact=True)
            ):
                transitions.append(
                    {
                        "channel_key": saving.get("channelKey"),
                        "saving_sequence": saving.get("sequence"),
                        "saved_sequence": saved.get("sequence"),
                    }
                )
                break
    changed_saved_nodes = [
        item
        for item in relevant
        if item.get("state") == "saved"
        and item.get("channelKey") in mutation_baseline
        and int(item.get("sequence") or 0) in channel_changed_sequences
        and (
            item.get("token") != mutation_baseline[item.get("channelKey")].get("token")
            or item.get("nodeInstance")
            != mutation_baseline[item.get("channelKey")].get("nodeInstance")
        )
        and event_is_post_mutation(item)
        and recent_saved(item)
        and event_is_current_channel(item, exact=True)
    ]
    # X can update the visible Saved age, temporarily leave the bounded save
    # state, and then return to a new or identical Saved token.  That is only
    # valid evidence when the same-channel tombstone faithfully names the most
    # recent live token/node and the later Saved observation is the exact
    # token/node that is still current.  Never accept a replayed Saved event
    # merely because it appeared after the sequence cursor.
    previous_live_by_channel = dict(mutation_baseline)
    departed_by_channel: dict[str, dict] = {}
    departure_to_saved_transitions = []
    post_mutation_saved_observations = []
    for item in relevant:
        channel = item.get("channelKey")
        if not channel or not event_is_post_mutation(item):
            continue
        if item.get("state") in {"departed", "unclassified"}:
            previous_live = previous_live_by_channel.get(channel)
            tombstone_matches_previous_live = bool(
                previous_live
                and item.get("previousToken") == previous_live.get("token")
                and item.get("nodeInstance") == previous_live.get("nodeInstance")
            )
            if tombstone_matches_previous_live:
                departed_by_channel[channel] = {
                    "departure": item,
                    "previous_live": previous_live,
                }
            else:
                departed_by_channel.pop(channel, None)
            continue
        if item.get("state") not in {"saving", "saved"}:
            continue
        departure_pair = departed_by_channel.get(channel)
        if item.get("state") == "saved" and departure_pair:
            current = saved_now_by_channel.get(channel)
            same_current_binding = bool(
                current
                and item.get("token") == current.get("token")
                and item.get("nodeInstance") == current.get("nodeInstance")
            )
            if recent_saved(item) and same_current_binding:
                departure = departure_pair["departure"]
                previous_live = departure_pair["previous_live"]
                departure_to_saved_transitions.append(
                    {
                        "channel_key": channel,
                        "previous_live_sequence": previous_live.get("sequence"),
                        "previous_live_token": previous_live.get("token"),
                        "previous_live_node_instance": previous_live.get("nodeInstance"),
                        "departure_sequence": departure.get("sequence"),
                        "saved_sequence": item.get("sequence"),
                        "saved_token": item.get("token"),
                        "saved_node_instance": item.get("nodeInstance"),
                    }
                )
                post_mutation_saved_observations.append(item)
            # A tombstone proves only the first later Saved observation.  It
            # cannot be retained to authorize an arbitrary replay after that.
            departed_by_channel.pop(channel, None)
        previous_live_by_channel[channel] = item
    epoch_matches = raw.get("epoch") == expected_epoch
    mutation_count = int(raw.get("mutationCount") or 0)
    verified = bool(
        epoch_matches
        and mutation_count > 0
        and saved_now
        and (transitions or changed_saved_nodes or departure_to_saved_transitions)
    )
    return {
        **raw,
        "epoch_matches": epoch_matches,
        "last_mutation_sequence": cursor,
        "relevant_events": relevant,
        "saving_to_saved_transitions": transitions,
        "changed_saved_nodes": changed_saved_nodes,
        "departure_to_saved_transitions": departure_to_saved_transitions,
        "post_mutation_saved_observations": post_mutation_saved_observations,
        "saved_state_present": bool(saved_now),
        "verified": verified,
    }


def resolve_autosave_verification(
    ui_evidence: dict,
    reload_core_persistence_verified: bool,
) -> dict:
    """Prefer bounded UI evidence, but let exact reload persistence prove saving."""
    ui_verified = bool((ui_evidence or {}).get("verified"))
    saved_text = next(
        (
            str(item.get("text") or "").strip()
            for item in reversed((ui_evidence or {}).get("current") or [])
            if item.get("state") == "saved" and str(item.get("text") or "").strip()
        ),
        "",
    )
    fallback_verified = bool(not ui_verified and reload_core_persistence_verified)
    warnings = []
    if fallback_verified:
        warnings.append(
            {
                "type": "autosave_ui_evidence_missing",
                "message": (
                    "未捕获到本轮 X 自动保存状态节点，但同一草稿刷新后标题、正文、"
                    "表格、封面和全部正文图片的持久化证据均已通过。"
                ),
            }
        )
    if not saved_text and (ui_verified or fallback_verified):
        warnings.append(
            {
                "type": "autosave_saved_text_missing",
                "message": "X 未提供可读的保存状态文案；最终刷新持久化结果不受影响。",
            }
        )
    return {
        "ui_verified": ui_verified,
        "reload_persistence_fallback": fallback_verified,
        "mode": (
            "bounded_ui_event"
            if ui_verified
            else "reload_persistence_fallback"
            if fallback_verified
            else "unverified"
        ),
        "saved_text": saved_text,
        "warnings": warnings,
        "verified": bool(ui_verified or fallback_verified),
    }


def is_weak_anchor(anchor: str) -> bool:
    cleaned = normalize_media_anchor(anchor)
    return cleaned in WEAK_ANCHORS or len(cleaned) < 4


def validate_preflight(data: dict, cover_policy: dict, content_images: list[dict], markdown_source: str = "") -> dict:
    errors = []
    warnings = []

    if MEDIA_START_MARKER in (markdown_source or ""):
        errors.append(
            {
                "type": "reserved_internal_marker",
                "marker": MEDIA_START_MARKER,
                "message": "正文包含上传器保留的内部定位标记。不会打开 X。",
            }
        )

    cover_image = data.get("cover_image")
    upload_cover = bool(cover_policy["starts_with_image"] and cover_image)
    if not cover_policy["starts_with_image"]:
        warnings.append(
            {
                "type": "missing_leading_cover",
                "line": cover_policy["first_content_line"],
                "preview": cover_policy["first_content_preview"],
                "recommended_cover_ratio": RECOMMENDED_COVER_RATIO,
                "message": f"文章第一个有效内容不是图片。本次会跳过封面上传，直接上传标题、正文和正文图片；完成后提醒用户补一张 {RECOMMENDED_COVER_RATIO} 封面图。",
            }
        )
    if cover_policy["starts_with_image"] and not cover_image:
        errors.append({"type": "missing_cover_image", "message": "解析结果没有封面图。"})
    elif upload_cover and not Path(cover_image).is_file():
        errors.append({"type": "missing_cover_file", "path": cover_image, "message": "封面文件不存在。"})

    expected = int(data.get("expected_image_count") or 0)
    if expected != len(content_images):
        errors.append(
            {
                "type": "image_count_mismatch",
                "expected": expected,
                "actual": len(content_images),
                "message": "解析出的正文图片数量和待插入图片数量不一致。",
            }
        )

    anchor_seen = {}
    seen_after_anchor_media = False
    for item in content_images:
        path = item.get("path") or ""
        anchor = item.get("expected_anchor") or ""
        normalized_anchor = normalize_media_anchor(anchor)
        placement = item.get("placement") or MEDIA_PLACEMENT_AFTER_ANCHOR
        if placement == MEDIA_PLACEMENT_COMPOSER_START:
            if normalized_anchor or item.get("candidates"):
                errors.append(
                    {
                        "type": "invalid_composer_start_anchor",
                        "index": item["index"],
                        "anchor": anchor,
                        "message": "正文起始图片必须使用空锚点，并由 occurrence/DOM 顺序定位。",
                    }
                )
            if seen_after_anchor_media:
                errors.append(
                    {
                        "type": "composer_start_not_prefix",
                        "index": item["index"],
                        "message": "composer-start 图片只能形成正文图片序列的连续前缀。",
                    }
                )
        else:
            seen_after_anchor_media = True
        if not path or not Path(path).is_file() or not item.get("exists", True):
            errors.append(
                {
                    "type": "missing_body_image",
                    "index": item["index"],
                    "line": item.get("line"),
                    "path": path,
                    "message": "正文图片文件不存在。先修 Markdown 图片路径，不要打开 X。",
                }
            )
        if (
            placement != MEDIA_PLACEMENT_COMPOSER_START
            and (not item.get("candidates") or is_weak_anchor(anchor))
        ):
            errors.append(
                {
                    "type": "weak_image_anchor",
                    "index": item["index"],
                    "line": item.get("line"),
                    "file": Path(path).name if path else "",
                    "anchor": anchor,
                    "message": "正文图片缺少稳定锚点。先在图片前补一行唯一说明文字。",
                }
            )
        elif (
            placement != MEDIA_PLACEMENT_COMPOSER_START
            and normalized_anchor in anchor_seen
            and item["index"] - anchor_seen[normalized_anchor] > 1
        ):
            errors.append(
                {
                    "type": "reused_anchor",
                    "index": item["index"],
                    "previous_index": anchor_seen[normalized_anchor],
                    "anchor": anchor,
                    "normalized_anchor": normalized_anchor,
                    "message": "同一个锚点被非相邻图片复用，无法稳定证明图片位置。先为图片补唯一说明文字。",
                }
            )
        elif placement != MEDIA_PLACEMENT_COMPOSER_START:
            # Adjacent images may intentionally share one paragraph and are
            # distinguished by occurrence/order. Track the latest occurrence
            # so a run of 3+ adjacent images is not misclassified as reuse.
            anchor_seen[normalized_anchor] = item["index"]

    for table in data.get("tables") or []:
        rows = int(table.get("row_count") or 0)
        columns = int(table.get("column_count") or 0)
        contract = validate_table_contract(table)
        if not contract["valid"]:
            errors.append(
                {
                    "type": "invalid_or_empty_table",
                    "index": table.get("index"),
                    "rows": rows,
                    "columns": columns,
                    "non_empty_cells": contract["non_empty_cells"],
                    "message": "表格行列或可见单元格矩阵无效/全空。不会打开 X。",
                }
            )
        if rows > MAX_NATIVE_TABLE_ROWS or columns > MAX_NATIVE_TABLE_COLUMNS:
            errors.append(
                {
                    "type": "table_too_large",
                    "index": table.get("index"),
                    "rows": rows,
                    "columns": columns,
                    "max_rows": MAX_NATIVE_TABLE_ROWS,
                    "max_columns": MAX_NATIVE_TABLE_COLUMNS,
                    "message": "X Article 当前表格尺寸选择器最大为 10 x 10。请先拆表或改成图片/正文段落。",
                }
            )

    raw_html = find_unsupported_raw_html(markdown_source)
    if raw_html:
        errors.append(
            {
                "type": "unsupported_raw_html",
                "message": "X Article 上传不支持围栏外 raw HTML。请先改成 Markdown；不会打开 X。",
                "details": {"elements": raw_html},
            }
        )

    remote_images = find_unsupported_remote_images(markdown_source)
    if remote_images:
        errors.append(
            {
                "type": "unsupported_remote_image",
                "message": "X Article 上传不支持远程图片地址。请先下载到本地并改用本地路径；不会打开 X。",
                "details": {"images": remote_images},
            }
        )

    reference_images = find_unsupported_reference_images(markdown_source)
    if reference_images:
        errors.append(
            {
                "type": "unsupported_reference_image",
                "message": "X Article 上传不支持 reference-style 图片。请先改成 inline image 语法；不会打开 X。",
                "details": {"images": reference_images},
            }
        )

    return {"errors": errors, "warnings": warnings}


def load_cookies(path: Path) -> list[dict]:
    """Load a private, bounded X-only cookie file without exposing values."""
    path = path.expanduser().absolute()
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ValueError(f"X Cookie file does not exist: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("X Cookie path must be a regular file, not a symlink or device.")
    if metadata.st_size > MAX_COOKIE_FILE_BYTES:
        raise ValueError(f"X Cookie file exceeds {MAX_COOKIE_FILE_BYTES} bytes.")
    if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("X Cookie file permissions are too broad; run chmod 600 on the file.")

    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        if set(raw) != {"cookies"} or not isinstance(raw.get("cookies"), list):
            raise ValueError('X Cookie JSON object must contain only a "cookies" array.')
        records = raw["cookies"]
    elif isinstance(raw, list):
        records = raw
    else:
        raise ValueError("X Cookie JSON must be an array or an object containing only a cookies array.")

    now = time.time()
    normalized = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"X Cookie record {index} must be an object.")
        name = record.get("name")
        value = record.get("value")
        domain = record.get("domain")
        if not isinstance(name, str) or not name:
            raise ValueError(f"X Cookie record {index} has no valid name.")
        if not isinstance(value, str) or not value:
            raise ValueError(f"X Cookie record {index} has no valid value.")
        if not isinstance(domain, str) or not is_allowed_x_cookie_domain(domain):
            raise ValueError(f"X Cookie record {index} is outside x.com/twitter.com.")
        expires = record.get("expires")
        if expires is not None and (
            isinstance(expires, bool) or not isinstance(expires, (int, float))
        ):
            raise ValueError(f"X Cookie record {index} has an invalid expires value.")
        if isinstance(expires, (int, float)) and expires > 0 and expires <= now:
            continue
        normalized.append(record)

    present = {
        str(record["name"])
        for record in normalized
        if str(record.get("domain") or "").strip().lower().lstrip(".") == "x.com"
    }
    missing = sorted(REQUIRED_X_COOKIE_NAMES - present)
    if missing:
        raise ValueError("X Cookie file is missing required x.com cookies: " + ", ".join(missing))
    return normalized


async def run_upload(args: argparse.Namespace, data: dict, content_images: list[dict]) -> dict:
    from playwright.async_api import Error as PlaywrightError, async_playwright

    args._last_phase = "launch_browser"
    args._draft_url = ""
    source_rich_html = data["html"]
    plain = plain_text_from_html(source_rich_html)
    has_composer_start_media = any(
        (item.get("placement") or MEDIA_PLACEMENT_AFTER_ANCHOR)
        == MEDIA_PLACEMENT_COMPOSER_START
        for item in content_images
    )
    rich_html = (
        f"<p>{MEDIA_START_MARKER}</p>{source_rich_html}"
        if has_composer_start_media
        else source_rich_html
    )
    end_check_text = build_end_check_text(plain)
    content_contract = build_content_verification_contract(plain)
    content_checkpoints = content_contract["content_checkpoints"]
    expected_compact_length = content_contract["expected_compact_length"]
    expected_compact_sha256 = content_contract["expected_compact_sha256"]
    cookies = load_cookies(Path(args.cookies_json))
    upload_cover = bool(data.get("cover_image"))

    async def composer_media_items(page, runtime_prefix="", verified_binding_keys=None):
        """Inspect only actual image blocks inside the article composer."""
        return await page.evaluate(
            r"""async ({runtimePrefix,verifiedBindingKeys}) => {
              const composer=document.querySelector('[data-testid="composer"]');
              if (!composer) return [];
              const normalize=(value)=>{
                let text=String(value||'')
                  .replace(/[\u200b\u200c\u200d\u2060\ufeff]/g,'')
                  .replace(/\u00a0/g,' ')
                  .normalize('NFC')
                  .trim();
                text=text
                  .replace(/^#+\s*/,'')
                  .replace(/^>\s*/,'')
                  .replace(/^[-*+]\s+/,'')
                  .replace(/^\d+[.)、]\s*/,'')
                  .replace(/^\|+|\|+$/g,'');
                return text.replace(/\s+/g,' ').trim();
              };
              const visualSignature=(img)=>{
                if (!img.complete || !img.naturalWidth || !img.naturalHeight) return '';
                try {
                  // X persists article images behind page-local blob URLs. Those URLs change on
                  // reload, so identity must come from decoded pixels rather than the transport URL.
                  const canvas=document.createElement('canvas');
                  canvas.width=17;
                  canvas.height=16;
                  const context=canvas.getContext('2d',{willReadFrequently:true});
                  if (!context) return '';
                  context.imageSmoothingEnabled=true;
                  context.imageSmoothingQuality='high';
                  context.drawImage(img,0,0,17,16);
                  const pixels=context.getImageData(0,0,17,16).data;
                  let hex='';
                  let nibble=0;
                  let bitCount=0;
                  for (let y=0; y<16; y+=1) {
                    for (let x=0; x<16; x+=1) {
                      const left=(y*17+x)*4;
                      const right=left+4;
                      const leftGray=pixels[left]*299+pixels[left+1]*587+pixels[left+2]*114;
                      const rightGray=pixels[right]*299+pixels[right+1]*587+pixels[right+2]*114;
                      nibble=(nibble<<1) | (leftGray>rightGray ? 1 : 0);
                      bitCount+=1;
                      if (bitCount===4) {
                        hex+=nibble.toString(16);
                        nibble=0;
                        bitCount=0;
                      }
                    }
                  }
                  return `visual-dhash-v1:${hex}`;
                } catch (_) {
                  // A tainted/unreadable canvas is not stable evidence. Fail closed and retry.
                  return '';
                }
              };
              const visualSample=(img)=>{
                if (!img.complete || !img.naturalWidth || !img.naturalHeight) return '';
                try {
                  const canvas=document.createElement('canvas');
                  canvas.width=8;
                  canvas.height=8;
                  const context=canvas.getContext('2d',{willReadFrequently:true});
                  if (!context) return '';
                  context.fillStyle='#fff';
                  context.fillRect(0,0,8,8);
                  context.imageSmoothingEnabled=true;
                  context.imageSmoothingQuality='high';
                  context.drawImage(img,0,0,8,8);
                  const pixels=context.getImageData(0,0,8,8).data;
                  let hex='';
                  for (let index=0; index<pixels.length; index+=4) {
                    hex+=pixels[index].toString(16).padStart(2,'0');
                    hex+=pixels[index+1].toString(16).padStart(2,'0');
                    hex+=pixels[index+2].toString(16).padStart(2,'0');
                  }
                  return `visual-rgb8-v1:${hex}`;
                } catch (_) {
                  return '';
                }
              };
              const topLevelBlock=(img)=>{
                const draft=img.closest('[data-block="true"]')
                  || img.closest('figure')
                  || img.closest('.public-DraftStyleDefault-block');
                if (draft) return draft;
                let node=img;
                while (node.parentElement && node.parentElement !== composer) node=node.parentElement;
                return node;
              };
              const candidates=[];
              for (const img of composer.querySelectorAll('img')) {
                const src=img.currentSrc || img.src || '';
                if (!src || src.includes('profile_images') || src.includes('/emoji/')) continue;
                if (img.closest('table,[role="table"],[role="grid"],[role="toolbar"]')) continue;
                const rect=img.getBoundingClientRect();
                const naturalWidth=Number(img.naturalWidth||0);
                const naturalHeight=Number(img.naturalHeight||0);
                if (Math.max(rect.width,naturalWidth) < 40 || Math.max(rect.height,naturalHeight) < 40) continue;
                const block=topLevelBlock(img);
                if (!block || !composer.contains(block)) continue;
                candidates.push({img,block,area:Math.max(rect.width,1)*Math.max(rect.height,1)});
              }
              const bestByBlock=new Map();
              for (const candidate of candidates) {
                const current=bestByBlock.get(candidate.block);
                if (!current || candidate.area>current.area) bestByBlock.set(candidate.block,candidate);
              }
              const ordered=[...bestByBlock.values()].sort((a,b)=>{
                const position=a.block.compareDocumentPosition(b.block);
                return position & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
              });
              if (verifiedBindingKeys !== null) {
                composer.querySelectorAll('[data-x-uploader-verified-media-key]')
                  .forEach((root)=>{
                    try { root.removeAttribute('data-x-uploader-verified-media-key'); } catch (_) {}
                  });
                const annotationKeysAreUsable=(
                  verifiedBindingKeys.length === ordered.length
                  && new Set(verifiedBindingKeys).size === verifiedBindingKeys.length
                );
                if (annotationKeysAreUsable) {
                  ordered.forEach(({block},index)=>{
                    try {
                      block.setAttribute('data-x-uploader-verified-media-key',verifiedBindingKeys[index]);
                    } catch (_) {
                      // Runtime-only annotation is diagnostic. Pixel/count/order evidence is
                      // returned independently and the final reload contract remains authoritative.
                    }
                  });
                }
              }
              if (runtimePrefix) {
                ordered.forEach(({block},index)=>{
                  try {
                    if (!block.getAttribute('data-x-uploader-media-runtime-key')) {
                      block.setAttribute('data-x-uploader-media-runtime-key',`${runtimePrefix}-${index}`);
                    }
                  } catch (_) {
                    // A rerender may reject a transient DOM annotation. Runtime keys never
                    // establish source identity and therefore must not abort media inspection.
                  }
                });
              }
              const textBlocks=[...composer.querySelectorAll('.public-DraftStyleDefault-block,[data-block="true"]')];
              const documentBlocks=[...new Set([...textBlocks,...ordered.map((item)=>item.block)])]
                .filter((candidate,index,all)=>!all.some((other,otherIndex)=>
                  otherIndex!==index && other.contains(candidate) && other.querySelector('img')
                ))
                .sort((a,b)=>{
                  if (a===b) return 0;
                  const position=a.compareDocumentPosition(b);
                  return position & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
                });
              return ordered.map(({img,block}, mediaIndex)=>{
                const blockIndex=documentBlocks.indexOf(block);
                let anchorBefore='';
                const start=blockIndex - 1;
                for (let index=start; index>=0; index-=1) {
                  const candidate=documentBlocks[index];
                  if (candidate===block || candidate.querySelector('img')) continue;
                  const text=normalize(candidate.innerText || candidate.textContent || '');
                  if (text) { anchorBefore=text; break; }
                }
                return {
                  mediaIndex,
                  blockIndex,
                  anchorBefore,
                  runtimeKey:block.getAttribute('data-x-uploader-media-runtime-key') || '',
                  verifiedBindingKey:block.getAttribute('data-x-uploader-verified-media-key') || '',
                  sourceSignature:visualSignature(img),
                  visualSample:visualSample(img),
                  sourceUrlKind:/^blob:/i.test(img.currentSrc || img.src || '')?'blob':'hosted',
                  naturalWidth:Number(img.naturalWidth||0),
                  naturalHeight:Number(img.naturalHeight||0),
                  alt:img.getAttribute('alt') || ''
                };
              });
            }""",
            {
                "runtimePrefix": runtime_prefix,
                "verifiedBindingKeys": verified_binding_keys,
            },
        )

    async def count_composer_media(page):
        return len(await composer_media_items(page))

    async def visual_signature_from_bytes(page, image_bytes, mime):
        encoded = base64.b64encode(image_bytes).decode()
        return await page.evaluate(
            r"""async ({encoded,mime}) => {
              const bytes=Uint8Array.from(atob(encoded), c=>c.charCodeAt(0));
              const blob=new Blob([bytes],{type:mime});
              const url=URL.createObjectURL(blob);
              try {
                const img=new Image();
                img.src=url;
                await img.decode();
                const canvas=document.createElement('canvas');
                canvas.width=17;
                canvas.height=16;
                const context=canvas.getContext('2d',{willReadFrequently:true});
                if (!context) return {sourceSignature:'',naturalWidth:0,naturalHeight:0};
                context.imageSmoothingEnabled=true;
                context.imageSmoothingQuality='high';
                context.drawImage(img,0,0,17,16);
                const pixels=context.getImageData(0,0,17,16).data;
                let hex='';
                let nibble=0;
                let bitCount=0;
                for (let y=0; y<16; y+=1) {
                  for (let x=0; x<16; x+=1) {
                    const left=(y*17+x)*4;
                    const right=left+4;
                    const leftGray=pixels[left]*299+pixels[left+1]*587+pixels[left+2]*114;
                    const rightGray=pixels[right]*299+pixels[right+1]*587+pixels[right+2]*114;
                    nibble=(nibble<<1) | (leftGray>rightGray ? 1 : 0);
                    bitCount+=1;
                    if (bitCount===4) {
                      hex+=nibble.toString(16);
                      nibble=0;
                      bitCount=0;
                    }
                  }
                }
                const sampleCanvas=document.createElement('canvas');
                sampleCanvas.width=8;
                sampleCanvas.height=8;
                const sampleContext=sampleCanvas.getContext('2d',{willReadFrequently:true});
                if (!sampleContext) {
                  return {
                    sourceSignature:`visual-dhash-v1:${hex}`,
                    visualSample:'',
                    naturalWidth:Number(img.naturalWidth||0),
                    naturalHeight:Number(img.naturalHeight||0)
                  };
                }
                sampleContext.fillStyle='#fff';
                sampleContext.fillRect(0,0,8,8);
                sampleContext.imageSmoothingEnabled=true;
                sampleContext.imageSmoothingQuality='high';
                sampleContext.drawImage(img,0,0,8,8);
                const samplePixels=sampleContext.getImageData(0,0,8,8).data;
                let sampleHex='';
                for (let index=0; index<samplePixels.length; index+=4) {
                  sampleHex+=samplePixels[index].toString(16).padStart(2,'0');
                  sampleHex+=samplePixels[index+1].toString(16).padStart(2,'0');
                  sampleHex+=samplePixels[index+2].toString(16).padStart(2,'0');
                }
                return {
                  sourceSignature:`visual-dhash-v1:${hex}`,
                  visualSample:`visual-rgb8-v1:${sampleHex}`,
                  naturalWidth:Number(img.naturalWidth||0),
                  naturalHeight:Number(img.naturalHeight||0)
                };
              } finally {
                URL.revokeObjectURL(url);
              }
            }""",
            {"encoded": encoded, "mime": mime},
        )

    async def cover_media_items(page):
        """Inspect only the bounded cover uploader region, never arbitrary page images."""
        items = await page.evaluate(
            r"""() => {
              const input=document.querySelector('input[data-testid="fileInput"][type="file"][accept*="image"]')
                || document.querySelector('input[type="file"][accept*="image"]');
              if (!input) return [];
              const composer=document.querySelector('[data-testid="composer"]');
              const eligible=(img)=>{
                if (composer?.contains(img) || !img.complete || !img.naturalWidth || !img.naturalHeight) return false;
                const src=img.currentSrc || img.src || '';
                if (!src || src.includes('profile_images') || src.includes('/emoji/')) return false;
                const rect=img.getBoundingClientRect();
                return Math.max(rect.width,Number(img.naturalWidth||0))>=200
                  && Math.max(rect.height,Number(img.naturalHeight||0))>=80;
              };
              // Select the smallest input ancestor that contains a plausible image. This binds
              // evidence to the cover control rather than avatars or unrelated timeline images.
              let node=input.parentElement;
              let images=[];
              for (let depth=0; node && depth<10; depth+=1,node=node.parentElement) {
                images=[...node.querySelectorAll('img')].filter(eligible);
                if (images.length) break;
              }
              const visualSignature=(img)=>{
                try {
                  const canvas=document.createElement('canvas');
                  canvas.width=17;
                  canvas.height=16;
                  const context=canvas.getContext('2d',{willReadFrequently:true});
                  if (!context) return '';
                  context.imageSmoothingEnabled=true;
                  context.imageSmoothingQuality='high';
                  context.drawImage(img,0,0,17,16);
                  const pixels=context.getImageData(0,0,17,16).data;
                  let hex='';
                  let nibble=0;
                  let bitCount=0;
                  for (let y=0; y<16; y+=1) {
                    for (let x=0; x<16; x+=1) {
                      const left=(y*17+x)*4;
                      const right=left+4;
                      const leftGray=pixels[left]*299+pixels[left+1]*587+pixels[left+2]*114;
                      const rightGray=pixels[right]*299+pixels[right+1]*587+pixels[right+2]*114;
                      nibble=(nibble<<1) | (leftGray>rightGray ? 1 : 0);
                      bitCount+=1;
                      if (bitCount===4) {
                        hex+=nibble.toString(16);
                        nibble=0;
                        bitCount=0;
                      }
                    }
                  }
                  return `visual-dhash-v1:${hex}`;
                } catch (_) {
                  return '';
                }
              };
              const visualSample=(img)=>{
                try {
                  const canvas=document.createElement('canvas');
                  canvas.width=8;
                  canvas.height=8;
                  const context=canvas.getContext('2d',{willReadFrequently:true});
                  if (!context) return '';
                  context.fillStyle='#fff';
                  context.fillRect(0,0,8,8);
                  context.imageSmoothingEnabled=true;
                  context.imageSmoothingQuality='high';
                  context.drawImage(img,0,0,8,8);
                  const pixels=context.getImageData(0,0,8,8).data;
                  let hex='';
                  for (let index=0; index<pixels.length; index+=4) {
                    hex+=pixels[index].toString(16).padStart(2,'0');
                    hex+=pixels[index+1].toString(16).padStart(2,'0');
                    hex+=pixels[index+2].toString(16).padStart(2,'0');
                  }
                  return `visual-rgb8-v1:${hex}`;
                } catch (_) {
                  return '';
                }
              };
              return images.map((img)=>({
                sourceSignature:visualSignature(img),
                visualSample:visualSample(img),
                naturalWidth:Number(img.naturalWidth||0),
                naturalHeight:Number(img.naturalHeight||0),
                sourceUrlKind:/^blob:/i.test(img.currentSrc || img.src || '')?'blob':'hosted',
                sourceUrl:img.currentSrc || img.src || ''
              }));
            }"""
        )
        for item in items:
            source_url = str(item.pop("sourceUrl", ""))
            if VISUAL_SIGNATURE_RE.fullmatch(str(item.get("sourceSignature") or "")):
                item["signatureSource"] = "dom-canvas"
                continue
            item["signatureSource"] = "unavailable"
            if item.get("sourceUrlKind") != "hosted" or not is_allowed_x_media_url(source_url):
                continue
            try:
                hosted_image = await fetch_hosted_cover_image_bytes(page, source_url)
                if hosted_image is None:
                    continue
                body, content_type, signature_source = hosted_image
                fetched = await visual_signature_from_bytes(page, body, content_type)
                signature = str(fetched.get("sourceSignature") or "")
                if not VISUAL_SIGNATURE_RE.fullmatch(signature):
                    continue
                item["sourceSignature"] = signature
                item["visualSample"] = str(fetched.get("visualSample") or "")
                item["signatureSource"] = signature_source
            except (PlaywrightError, TypeError, ValueError, OSError):
                continue
        return items

    async def cover_media_count(page):
        return len(await cover_media_items(page))

    async def local_visual_signature(page, image_path):
        path = Path(image_path)
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        if mime == "image/jpg":
            mime = "image/jpeg"
        return await visual_signature_from_bytes(page, path.read_bytes(), mime)

    async def wait_for_cover_evidence(
        page,
        expected,
        source_item,
        cleared_baseline_count=None,
        timeout_s=90,
    ):
        deadline = time.time() + timeout_s
        last = {}
        while time.time() < deadline:
            last = validate_cover_evidence(
                await cover_media_items(page),
                expected,
                source_item=source_item,
                cleared_baseline_count=cleared_baseline_count,
            )
            if last["valid"]:
                return last
            await page.wait_for_timeout(900)
        return {
            **last,
            "timed_out": True,
            "observation_warning": {
                "type": "cover_upload_observation_uncertain",
                "message": (
                    "封面上传后的瞬时 DOM/解码证据未稳定；将由同一草稿刷新后的"
                    "封面数量与本地源图身份严格验收。"
                ),
            },
        }

    async def click_apply_if_present(page, timeout_s=25):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            locator = page.locator('[data-testid="applyButton"]')
            try:
                if await locator.count():
                    await locator.last.click(timeout=2500)
                    await page.wait_for_timeout(4500)
                    return True
            except Exception:
                pass
            await page.wait_for_timeout(700)
        return False

    async def table_count(page):
        return len(await inspect_visible_tables(page))

    async def begin_autosave_epoch(page, epoch):
        return await page.evaluate(
            r"""({epoch}) => {
              const previous=window.__xUploaderAutosaveEpoch;
              if (previous?.observer) previous.observer.disconnect();
              const selector=[
                '#detail-header',
                '[role="status"]',
                '[aria-live="polite"]',
                '[aria-live="assertive"]',
                '[data-testid*="save" i]',
                '[aria-label*="save" i]',
                '[aria-label*="保存"]'
              ].join(',');
              const classify=(value)=>{
                const text=String(value||'').replace(/\s+/g,' ').trim();
                if (!text || text.length>180) return '';
                if (/(?:正在保存|保存中|\bSaving\b)/i.test(text)) return 'saving';
                if (/(?:刚刚最后保存|上一次保存|\bLast saved\b|^Saved(?:\b|\s))/i.test(text)) return 'saved';
                return '';
              };
              const nodeInstances=new WeakMap();
              let nextNodeInstance=0;
              const collectStatusNodes=()=>{
                const composer=document.querySelector('[data-testid="composer"]');
                const title=document.querySelector('textarea[placeholder="添加标题"]');
                const nodes=[...document.querySelectorAll(selector)];
                return nodes.map((node,index)=>{
                  if (composer?.contains(node) || title===node || node===document.body || node===document.documentElement) return null;
                  const text=(node.innerText || node.textContent || node.getAttribute('aria-label') || '')
                    .replace(/\s+/g,' ').trim();
                  const state=classify(text);
                  if (!state) return null;
                  const testId=node.getAttribute('data-testid') || '';
                  const role=node.getAttribute('role') || '';
                  const live=node.getAttribute('aria-live') || '';
                  const label=node.getAttribute('aria-label') || '';
                  const channelKey=testId
                    ? `testid:${testId}`
                    : node.id
                      ? `id:${node.id}`
                      : `role:${role}|live:${live}|label:${label}|index:${index}`;
                  const attributes={
                    state:node.getAttribute('data-state') || '',
                    status:node.getAttribute('data-status') || '',
                    version:node.getAttribute('data-version') || '',
                    busy:node.getAttribute('aria-busy') || '',
                    datetime:node.getAttribute('datetime') || ''
                  };
                  if (!nodeInstances.has(node)) {
                    nextNodeInstance+=1;
                    nodeInstances.set(node,nextNodeInstance);
                  }
                  return {
                    channelKey,
                    nodeInstance:nodeInstances.get(node),
                    state,
                    text,
                    attributes,
                    token:JSON.stringify([state,text,attributes])
                  };
                }).filter(Boolean);
              };
              const state={
                epoch,
                startedAt:Date.now(),
                mutationCount:0,
                lastMutationAt:0,
                lastMutationLabel:'',
                lastMutationEventCursor:0,
                lastMutationSequence:0,
                mutationBaseline:collectStatusNodes(),
                events:[],
                sequence:0,
                lastSnapshot:'',
                lastSeenByChannel:new Map()
              };
              state.lastSeenByChannel=new Map(
                state.mutationBaseline.map((item)=>[item.channelKey,{
                  token:item.token,
                  nodeInstance:item.nodeInstance,
                  state:item.state,
                  text:item.text,
                  attributes:item.attributes
                }])
              );
              const record=()=>{
                const nodes=collectStatusNodes();
                const snapshot=JSON.stringify(nodes.map((item)=>[item.channelKey,item.token,item.nodeInstance]));
                if (snapshot===state.lastSnapshot) return;
                state.lastSnapshot=snapshot;
                const observedAt=Date.now();
                const currentByChannel=new Map(nodes.map((item)=>[item.channelKey,item]));
                for (const [channelKey,previous] of state.lastSeenByChannel.entries()) {
                  if (currentByChannel.has(channelKey)) continue;
                  state.sequence+=1;
                  state.events.push({
                    channelKey,
                    nodeInstance:previous.nodeInstance,
                    state:'departed',
                    text:'',
                    attributes:{},
                    token:'',
                    previousState:previous.state || '',
                    previousText:previous.text || '',
                    previousToken:previous.token || '',
                    departureReason:'departed_or_unclassified',
                    sequence:state.sequence,
                    observedAt
                  });
                }
                for (const item of nodes) {
                  const previous=state.lastSeenByChannel.get(item.channelKey);
                  if (previous
                      && previous.token===item.token
                      && previous.nodeInstance===item.nodeInstance) continue;
                  state.sequence+=1;
                  state.events.push({...item,sequence:state.sequence,observedAt});
                }
                state.lastSeenByChannel=new Map(nodes.map((item)=>[item.channelKey,{
                  token:item.token,
                  nodeInstance:item.nodeInstance,
                  state:item.state,
                  text:item.text,
                  attributes:item.attributes
                }]));
                if (state.events.length>160) state.events.splice(0,state.events.length-160);
              };
              state.collectStatusNodes=collectStatusNodes;
              state.record=record;
              state.observer=new MutationObserver(record);
              state.observer.observe(document.documentElement,{
                subtree:true,childList:true,characterData:true,attributes:true,
                attributeFilter:['aria-busy','aria-label','data-state','data-status','data-version','datetime']
              });
              state.lastSnapshot=JSON.stringify(
                state.mutationBaseline.map((item)=>[item.channelKey,item.token,item.nodeInstance])
              );
              window.__xUploaderAutosaveEpoch=state;
              return {epoch,stateNodeCount:state.mutationBaseline.length,baseline:state.mutationBaseline};
            }""",
            {"epoch": epoch},
        )

    async def mark_mutation_epoch(page, epoch, label):
        try:
            marked = await page.evaluate(
                r"""({epoch,label}) => {
              const state=window.__xUploaderAutosaveEpoch;
              if (!state || state.epoch!==epoch) return {ok:false,reason:'epoch_missing_or_replaced'};
              state.record();
              state.mutationCount+=1;
              state.lastMutationAt=Date.now();
              state.lastMutationLabel=label;
              state.lastMutationSequence=state.sequence;
              // Kept for result-schema compatibility; it is a monotonic sequence,
              // never an array index, because the bounded event array is trimmed.
              state.lastMutationEventCursor=state.lastMutationSequence;
              state.mutationBaseline=state.collectStatusNodes();
              return {
                ok:true,
                epoch:state.epoch,
                mutationCount:state.mutationCount,
                lastMutationLabel:state.lastMutationLabel,
                lastMutationEventCursor:state.lastMutationEventCursor,
                lastMutationSequence:state.lastMutationSequence,
                mutationBaseline:state.mutationBaseline
              };
            }""",
                {"epoch": epoch, "label": label},
            )
        except Exception as error:
            marked = {
                "ok": False,
                "reason": f"{type(error).__name__}: {error}",
                "label": label,
            }
        if not marked.get("ok"):
            if not any(
                warning.get("type") == "autosave_epoch_tracking_unavailable"
                for warning in pre_reload_observation_warnings
            ):
                pre_reload_observation_warnings.append(
                    {
                        "type": "autosave_epoch_tracking_unavailable",
                        "message": (
                            "本轮 autosave mutation epoch 观测不可用；将仅以同一草稿"
                            "刷新后的完整持久化证据兜底。"
                        ),
                        "evidence": marked,
                    }
                )
        return marked

    async def inspect_autosave_epoch(page, epoch):
        raw = await page.evaluate(
            r"""({epoch}) => {
              const state=window.__xUploaderAutosaveEpoch;
              if (!state || state.epoch!==epoch) return {epoch:'',current:[],events:[],mutationCount:0};
              state.record();
              return {
                epoch:state.epoch,
                startedAt:state.startedAt,
                mutationCount:state.mutationCount,
                lastMutationAt:state.lastMutationAt,
                lastMutationLabel:state.lastMutationLabel,
                lastMutationEventCursor:state.lastMutationEventCursor,
                lastMutationSequence:state.lastMutationSequence,
                mutationBaseline:state.mutationBaseline,
                current:state.collectStatusNodes(),
                events:state.events
              };
            }""",
            {"epoch": epoch},
        )
        return validate_autosave_epoch_evidence(raw, epoch)

    async def wait_for_autosave(page, epoch, timeout_s=150):
        deadline = time.time() + timeout_s
        last = {"epoch": epoch, "verified": False}
        observation_errors = []
        while time.time() < deadline:
            try:
                last = await inspect_autosave_epoch(page, epoch)
            except Exception as error:
                observation_errors.append(
                    {"error_type": type(error).__name__, "message": str(error)}
                )
                last = {
                    "epoch": epoch,
                    "verified": False,
                    "observation_errors": observation_errors[-5:],
                }
            if last.get("verified"):
                return last
            # A slow, healthy save is expected; keep polling the bounded status nodes.
            await page.wait_for_timeout(900)
        # The save-status UI is observational and can disappear or keep stale
        # wording. Continue to the same-URL reload; only exact persisted content,
        # tables, cover and media may substitute for this missing UI signal.
        return {
            **last,
            "verified": False,
            "timed_out": True,
            "observation_errors": observation_errors[-5:],
            "warning": {
                "type": "autosave_ui_observation_timeout",
                "message": "未捕获到本轮 X 自动保存状态；将由同一草稿刷新后的完整持久化验收兜底。",
            },
        }

    async def wait_for_reloaded_assets(
        page,
        expected_tables,
        expected_media,
        expected_cover,
        cover_source_item,
        timeout_s=150,
    ):
        deadline = time.time() + timeout_s
        last = {"tables": -1, "media": -1, "media_signatures": []}
        while time.time() < deadline:
            media_items = await composer_media_items(page)
            table_total = await table_count(page)
            signatures = [str(item.get("sourceSignature") or "") for item in media_items]
            cover_evidence = validate_cover_evidence(
                await cover_media_items(page),
                expected_cover,
                source_item=cover_source_item,
            )
            last = {
                "tables": table_total,
                "media": len(media_items),
                "media_signatures": signatures,
                "cover": cover_evidence,
            }
            if (
                table_total == expected_tables
                and len(media_items) == expected_media
                and all(VISUAL_SIGNATURE_RE.fullmatch(signature) for signature in signatures)
                and cover_evidence["valid"]
            ):
                return last
            await page.wait_for_timeout(1800)
        raise RuntimeError("Reloaded X draft assets did not stabilize: " + json.dumps(last, ensure_ascii=False))

    async def inspect_visible_tables(page):
        return await page.evaluate(
            r"""() => {
              const composer=document.querySelector('[data-testid="composer"]');
              if (!composer) return [];
              const normalize=(value)=>String(value||'')
                .replace(/\u00a0/g,' ')
                .replace(/\s+/g,' ')
                .normalize('NFC')
                .trim();
              return [...composer.querySelectorAll('table')].map((table,domIndex)=>{
                const rows=[...table.querySelectorAll('tr')]
                  .filter((row)=>row.closest('table')===table)
                  .map((row)=>[...row.querySelectorAll('th,td')]
                    .filter((cell)=>cell.closest('tr')===row && cell.closest('table')===table)
                    .map((cell)=>normalize(cell.innerText || cell.textContent || '')));
                return {
                  domIndex,
                  logicalIndex:table.getAttribute('data-x-uploader-logical-index') || '',
                  rowCount:rows.length,
                  columnCounts:rows.map((row)=>row.length),
                  matrix:rows,
                  nonEmptyCells:rows.flat().filter(Boolean).length,
                  visible:Boolean(table.getClientRects().length)
                };
              });
            }"""
        )

    async def mark_existing_tables(page, operation_id):
        return await page.evaluate(
            r"""({operationId}) => {
              const tables=[...document.querySelectorAll('[data-testid="composer"] table')];
              return tables.map((table,index)=>{
                const key=`${operationId}-before-${index}`;
                table.setAttribute('data-x-uploader-before-key',key);
                return key;
              });
            }""",
            {"operationId": operation_id},
        )

    async def identify_new_table(page, before_keys, logical_index, before_count, rows, columns):
        return await page.evaluate(
            r"""({beforeKeys,logicalIndex,beforeCount,rows,columns}) => {
              const tables=[...document.querySelectorAll('[data-testid="composer"] table')];
              const known=new Set(beforeKeys);
              const newTables=tables.filter((table)=>!known.has(table.getAttribute('data-x-uploader-before-key')||''));
              let table=null;
              let identificationMode='dom_identity';
              if (newTables.length===1) {
                table=newTables[0];
              } else if (tables.length===beforeCount+1) {
                const candidate=tables[logicalIndex-1];
                const candidateRows=[...(candidate?.querySelectorAll('tr') || [])]
                  .filter((row)=>row.closest('table')===candidate);
                const columnCounts=candidateRows.map((row)=>[...row.querySelectorAll('th,td')]
                  .filter((cell)=>cell.closest('tr')===row && cell.closest('table')===candidate).length);
                if (candidateRows.length===rows && columnCounts.every((count)=>count===columns)) {
                  table=candidate;
                  identificationMode='document_position_and_dimensions';
                }
              }
              if (!table) {
                return {ok:false,newCount:newTables.length,total:tables.length,identificationMode:'ambiguous'};
              }
              table.setAttribute('data-x-uploader-logical-index',String(logicalIndex));
              return {ok:true,domIndex:tables.indexOf(table),total:tables.length,identificationMode};
            }""",
            {
                "beforeKeys": before_keys,
                "logicalIndex": logical_index,
                "beforeCount": before_count,
                "rows": rows,
                "columns": columns,
            },
        )

    async def select_marker_block(page, marker):
        return await page.evaluate(
            r"""({marker}) => {
              const blocks=[...document.querySelectorAll('[data-testid="composer"] .public-DraftStyleDefault-block')];
              const block=blocks.find((item)=>((item.innerText||'').trim() === marker) || (item.innerText||'').includes(marker));
              if (!block) return null;
              block.scrollIntoView({block:'center'});
              const r=block.getBoundingClientRect();
              return {x:r.left + r.width / 2, y:r.top + r.height / 2, text:block.innerText};
            }""",
            {"marker": marker},
        )

    async def click_and_delete_marker_block(page, marker):
        """Move Draft's real selection into the marker block, then delete the block.

        A synthetic ClipboardEvent paste leaves Draft's internal editor selection
        unsynced from the DOM, so `range.selectNodeContents` + Backspace alone is
        unreliable. A real mouse click first lets Draft sync its own selection to
        the marker block; reselecting the block contents afterwards makes the
        Backspace delete the whole block deterministically.
        """
        selected = await select_marker_block(page, marker)
        if not selected:
            return False
        await page.mouse.click(selected["x"], selected["y"])
        await page.wait_for_timeout(300)
        reselected = await page.evaluate(
            r"""({marker}) => {
              const blocks=[...document.querySelectorAll('[data-testid="composer"] .public-DraftStyleDefault-block')];
              const block=blocks.find((item)=>((item.innerText||'').trim() === marker) || (item.innerText||'').includes(marker));
              if (!block) return false;
              block.scrollIntoView({block:'center'});
              const range=document.createRange();
              range.selectNodeContents(block);
              const selection=window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              return true;
            }""",
            {"marker": marker},
        )
        if not reselected:
            return False
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(700)
        return True

    async def ensure_marker_removed(page, marker):
        for _ in range(8):
            text = await page.evaluate(
                r"""({marker}) => document.querySelector('[data-testid="composer"]')?.innerText.includes(marker) || false""",
                {"marker": marker},
            )
            if not text:
                return True
            if not await click_and_delete_marker_block(page, marker):
                return False
        return False

    async def click_table_edit_button(page, table_index, logical_index=None):
        target = await page.evaluate(
            r"""({tableIndex,logicalIndex}) => {
              const editor=document.querySelector('[data-testid="composer"]');
              const tables=[...(editor?.querySelectorAll('table') || [])];
              const tagged=logicalIndex == null
                ? null
                : editor?.querySelector(`table[data-x-uploader-logical-index="${logicalIndex}"]`);
              const table=tagged || tables[tableIndex];
              if (!table) return null;
              let container=table.closest('section') || table.parentElement;
              while (container && !container.querySelector('button[aria-label="编辑块"]')) {
                container=container.parentElement;
              }
              const button=container?.querySelector('button[aria-label="编辑块"]');
              if (!button) return null;
              button.scrollIntoView({block:'center'});
              const r=button.getBoundingClientRect();
              return {x:r.left + r.width / 2, y:r.top + r.height / 2};
            }""",
            {"tableIndex": table_index, "logicalIndex": logical_index},
        )
        if not target:
            return False
        await page.mouse.click(target["x"], target["y"])
        return True

    async def read_native_table_markdown(page, table_index, logical_index=None):
        if not await click_table_edit_button(page, table_index, logical_index=logical_index):
            raise RuntimeError(f"Table {table_index + 1} edit button not found for readback.")
        await page.wait_for_selector('[data-testid="sheetDialog"] textarea', timeout=30000)
        source = await page.locator('[data-testid="sheetDialog"] textarea').first.input_value()
        try:
            await page.locator('[data-testid="sheetDialog"] [data-testid="app-bar-close"]').first.click(timeout=3000)
        except Exception:
            await page.keyboard.press("Escape")
        await page.wait_for_timeout(900)
        return source

    async def insert_native_table(page, table):
        marker = table["marker"]
        if not await click_and_delete_marker_block(page, marker):
            raise RuntimeError(f"Table marker not found: {marker}")
        await page.wait_for_timeout(900)

        before = await table_count(page)
        operation_id = f"table-{int(table['index']):03d}-{time.time_ns()}"
        before_keys = await mark_existing_tables(page, operation_id)
        rows = int(table.get("row_count") or 0)
        columns = int(table.get("column_count") or 0)
        contract = validate_table_contract(table)
        if not contract["valid"]:
            raise RuntimeError(f"Table {table['index']} has an invalid or empty expected matrix.")
        await page.locator('button[aria-label="添加媒体内容"]').click()
        await page.wait_for_timeout(500)
        await page.get_by_text("表格", exact=True).click()
        await page.wait_for_timeout(500)
        await page.locator(f'[aria-label="插入 {rows} x {columns} 表格"]').click()
        for _ in range(20):
            await page.wait_for_timeout(700)
            if await table_count(page) >= before + 1:
                break
        if await table_count(page) < before + 1:
            raise RuntimeError(f"Table {table['index']} was not inserted.")

        identified = await identify_new_table(
            page,
            before_keys,
            int(table["index"]),
            before,
            rows,
            columns,
        )
        if not identified.get("ok"):
            raise RuntimeError(
                f"Table {table['index']} new DOM node was ambiguous: "
                f"new={identified.get('newCount')} total={identified.get('total')}."
            )
        table_dom_index = int(identified["domIndex"])
        expected_dom_index = int(table["index"]) - 1
        if table_dom_index != expected_dom_index:
            raise RuntimeError(
                f"Table {table['index']} was inserted at DOM index {table_dom_index}; "
                f"expected {expected_dom_index}."
            )

        if not await click_table_edit_button(page, table_dom_index, logical_index=int(table["index"])):
            raise RuntimeError(f"Table {table['index']} edit button not found.")
        await page.wait_for_selector('[data-testid="sheetDialog"] textarea', timeout=30000)
        await page.locator('[data-testid="sheetDialog"] textarea').first.fill(table["markdown"])
        await page.get_by_text("更新", exact=True).click()
        for _ in range(20):
            await page.wait_for_timeout(800)
            visible_tables = await inspect_visible_tables(page)
            if len(visible_tables) > table_dom_index and visible_tables[table_dom_index]["nonEmptyCells"] > 0:
                break
        if not await ensure_marker_removed(page, marker):
            raise RuntimeError(f"Table marker remained after insertion: {marker}")
        visible_tables = await inspect_visible_tables(page)
        if len(visible_tables) <= table_dom_index:
            raise RuntimeError(f"Table {table['index']} disappeared before visible verification.")
        visible = visible_tables[table_dom_index]
        visible_matrix_matches = (
            visible["visible"]
            and visible["rowCount"] == rows
            and visible["columnCounts"] == [columns] * rows
            and visible["nonEmptyCells"] > 0
            and visible["matrix"] == contract["matrix"]
        )
        observation_warnings = []
        if not visible_matrix_matches:
            observation_warnings.append(
                {
                    "type": "inserted_table_visible_observation_uncertain",
                    "table_index": table["index"],
                    "message": (
                        "表格刚更新后的可见矩阵尚未稳定；将以同一草稿刷新后的"
                        "行列、非空矩阵和 Markdown 回读为最终裁决。"
                    ),
                }
            )
        readback_markdown = ""
        readback_error = ""
        try:
            readback_markdown = await read_native_table_markdown(
                page,
                table_dom_index,
                logical_index=int(table["index"]),
            )
        except Exception as error:
            readback_error = f"{type(error).__name__}: {error}"
        readback_matches = bool(
            not readback_error
            and normalize_markdown_table(readback_markdown)
            == normalize_markdown_table(table["markdown"])
        )
        if not readback_matches:
            observation_warnings.append(
                {
                    "type": "inserted_table_readback_observation_uncertain",
                    "table_index": table["index"],
                    "error": readback_error,
                    "message": (
                        "表格刚更新后的 Markdown 回读尚未稳定；将以同一草稿"
                        "刷新后的精确回读为最终裁决。"
                    ),
                }
            )
        return {
            "index": table["index"],
            "rows": rows,
            "columns": columns,
            "marker": marker,
            "table_dom_index": table_dom_index,
            "identification_mode": identified["identificationMode"],
            "expected_matrix": contract["matrix"],
            "visible_matrix": visible["matrix"],
            "visible_matrix_matches": visible_matrix_matches,
            "visible_non_empty_cells": visible["nonEmptyCells"],
            "readback_markdown": readback_markdown,
            "readback_matches": readback_matches,
            "observation_warnings": observation_warnings,
        }

    async def verify_all_tables(page, expected_tables, phase):
        visible_tables = await inspect_visible_tables(page)
        if len(visible_tables) != len(expected_tables):
            raise RuntimeError(
                f"{phase}: visible table count mismatch "
                f"expected={len(expected_tables)} actual={len(visible_tables)}."
            )
        evidence = []
        for dom_index, table in enumerate(expected_tables):
            contract = validate_table_contract(table)
            visible = visible_tables[dom_index]
            rows = contract["rows"]
            columns = contract["columns"]
            visible_matrix_matches = (
                contract["valid"]
                and visible["visible"]
                and visible["rowCount"] == rows
                and visible["columnCounts"] == [columns] * rows
                and visible["nonEmptyCells"] > 0
                and visible["matrix"] == contract["matrix"]
            )
            if not visible_matrix_matches:
                raise RuntimeError(
                    f"{phase}: table {table['index']} visible matrix mismatch: "
                    f"expected={contract['matrix']!r} actual={visible.get('matrix')!r}."
                )
            readback_markdown = await read_native_table_markdown(page, dom_index)
            readback_matches = (
                normalize_markdown_table(readback_markdown)
                == normalize_markdown_table(table["markdown"])
            )
            if not readback_matches:
                raise RuntimeError(f"{phase}: table {table['index']} Markdown readback mismatch.")
            evidence.append(
                {
                    "index": table["index"],
                    "dom_index": dom_index,
                    "rows": rows,
                    "columns": columns,
                    "expected_matrix": contract["matrix"],
                    "visible_matrix": visible["matrix"],
                    "visible_matrix_matches": visible_matrix_matches,
                    "visible_non_empty_cells": visible["nonEmptyCells"],
                    "readback_markdown": readback_markdown,
                    "readback_matches": readback_matches,
                    "phase": phase,
                }
            )
        return evidence

    async def find_target(page, candidates):
        return await page.evaluate(
            r"""({candidates}) => {
              function replaceInlineLinks(value){
                let rendered='';
                let cursor=0;
                const escaped=(text,index)=>{
                  let slashes=0;
                  for (let i=index-1;i>=0 && text[i]==='\\';i-=1) slashes+=1;
                  return slashes%2===1;
                };
                const balanced=(text,opening,open,close)=>{
                  if (text[opening]!==open) return null;
                  let depth=0;
                  for (let i=opening;i<text.length;i+=1) {
                    if (text[i]==='\\') { i+=1; continue; }
                    if (text[i]===open) depth+=1;
                    else if (text[i]===close) {
                      depth-=1;
                      if (depth===0) return {content:text.slice(opening+1,i),closing:i};
                    }
                  }
                  return null;
                };
                while (cursor<value.length) {
                  const image=value.startsWith('![',cursor) && !escaped(value,cursor);
                  const opening=image ? cursor+1 : cursor;
                  if (value[opening]!=='[' || escaped(value,opening)) {
                    rendered+=value[cursor++] || '';
                    continue;
                  }
                  const label=balanced(value,opening,'[',']');
                  const destination=label && balanced(value,label.closing+1,'(',')');
                  const reference=label && balanced(value,label.closing+1,'[',']');
                  if (!label || (!destination && !reference)) {
                    rendered+=value[cursor++] || '';
                    continue;
                  }
                  rendered+=label.content;
                  cursor=(destination || reference).closing+1;
                }
                return rendered;
              }
              function norm(s,markdownSource=false){
                let text=String(s||'');
                if (markdownSource) {
                  const code=[];
                  text=text.replace(/(?<!\\)(`+)([\s\S]+?)(?<!`)\1(?!`)/g,(_match,_ticks,content)=>{
                    let visible=content.replace(/[\r\n]+/g,' ');
                    if (visible.length>=2 && visible.startsWith(' ') && visible.endsWith(' ') && visible.trim()) {
                      visible=visible.slice(1,-1);
                    }
                    const token=`\uE100XANCHORCODE${String(code.length).padStart(6,'0')}\uE101`;
                    code.push([token,visible]);
                    return token;
                  });
                  const escaped=[];
                  text=text.replace(/\\([!-/:-@\[-`{-~])/g,(_match,punctuation)=>{
                    const token=`\uE102XANCHORESC${String(escaped.length).padStart(6,'0')}\uE103`;
                    escaped.push([token,punctuation]);
                    return token;
                  });
                  const decoder=document.createElement('textarea');
                  decoder.innerHTML=text;
                  text=replaceInlineLinks(decoder.value)
                    .replace(/<((?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^<>\s]*)|(?:[^\s<>]+@[^\s<>]+))>/g,'$1');
                  for (const pattern of [
                    /(^|[^\\])(\*\*|__|~~)(?=\S)([\s\S]+?\S)\2/g,
                    /(^|[^\\])(\*|_)(?=\S)([\s\S]+?\S)\2/g
                  ]) {
                    let previous=null;
                    while (previous!==text) {
                      previous=text;
                      text=text.replace(pattern,(_matched,prefix,_marker,content)=>prefix+content);
                    }
                  }
                  for (const [token,punctuation] of escaped) text=text.split(token).join(punctuation);
                  for (const [token,visible] of code) text=text.split(token).join(visible);
                }
                text=text
                  .replace(/[\u200b\u200c\u200d\u2060\ufeff]/g,'')
                  .replace(/\u00a0/g,' ')
                  .normalize('NFC')
                  .trim()
                  .replace(/^#+\s*/,'')
                  .replace(/^>\s*/,'')
                  .replace(/^[-*+]\s+/,'')
                  .replace(/^\d+[.)、]\s*/,'')
                  .replace(/^\|+|\|+$/g,'');
                return text.replace(/\s+/g,' ').trim();
              }
              const ordered=[];
              for (const raw of candidates || []) {
                const parts=String(raw).split(/\n+/).map(x=>norm(x,true)).filter(x=>x.length>1 && x !== '-');
                const full=norm(raw,true);
                const all=[];
                if (full) all.push(full);
                for (const p of parts) all.push(p);
                for (const p of all) if (p && !ordered.includes(p)) ordered.push(p);
              }
              const blocks=[...document.querySelectorAll('[data-testid="composer"] .public-DraftStyleDefault-block')];
              let chosen=null;
              for (const c of ordered) {
                let best=null;
                for (const [bi,b] of blocks.entries()) {
                  const bt=norm(b.innerText,false);
                  if (!bt) continue;
                  let score=0;
                  if (bt === c) score=10000;
                  else if (c.length >= 4 && bt.endsWith(c)) score=8000;
                  if (score && (!best || score>best.score || (score===best.score && bt.length>best.blockText.length))) {
                    best={node:b, score, bi, blockText:bt, candidate:c};
                  }
                }
                if (best) { chosen=best; break; }
              }
              if (!chosen) return null;
              const n=chosen.node;
              n.scrollIntoView({block:'center'});
              function lastTextNode(node){
                const walker=document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
                let cur,last=null;
                while(cur=walker.nextNode()) if(cur.nodeValue && cur.nodeValue.trim()) last=cur;
                return last;
              }
              const t=lastTextNode(n);
              let x,y;
              if (t && t.nodeValue.length) {
                const range=document.createRange();
                range.setStart(t, Math.max(0,t.nodeValue.length-1));
                range.setEnd(t, t.nodeValue.length);
                const r=range.getBoundingClientRect();
                x=Math.min(Math.max(r.right+3, 720), 1360);
                y=Math.min(Math.max(r.top+r.height/2, 115), 1040);
              } else {
                const r=n.getBoundingClientRect();
                x=Math.min(r.right-8,1360);
                y=Math.min(Math.max(r.top+r.height/2,115),1040);
              }
              return {x,y,blockText:chosen.blockText,candidate:chosen.candidate,score:chosen.score,blockIndex:chosen.bi};
            }""",
            {"candidates": candidates},
        )

    async def paste_image_at_current_selection(page, image_path):
        path = Path(image_path)
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        if mime == "image/jpg":
            mime = "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode()
        return await page.evaluate(
            r"""async ({encoded,mime,name}) => {
              const editor=document.querySelector('[data-testid="composer"]');
              editor?.focus();
              const bytes=Uint8Array.from(atob(encoded), c=>c.charCodeAt(0));
              const file=new File([bytes], name, {type:mime});
              const dt=new DataTransfer();
              dt.items.add(file);
              editor.dispatchEvent(new ClipboardEvent('paste', {bubbles:true, cancelable:true, clipboardData:dt}));
              await new Promise(r=>setTimeout(r,3000));
              return {allImages:document.images.length};
            }""",
            {"encoded": encoded, "mime": mime, "name": path.name},
        )

    async def wait_media_increment(page, before, timeout_s=75):
        deadline = time.time() + timeout_s
        last = before
        while time.time() < deadline:
            await page.wait_for_timeout(2500)
            last = await count_composer_media(page)
            if last >= before + 1:
                return last
        return last

    async def inspect_draft_state(page):
        structural = await page.evaluate(
            r"""() => {
              const editor=document.querySelector('[data-testid="composer"]');
              const title=document.querySelector('textarea[placeholder="添加标题"]');
              return {
                title:(title?.value || '').trim(),
                bodyText:(editor?.innerText || '').replace(/[\s\u200b\ufeff]+/g,''),
                tableCount:editor?.querySelectorAll('table').length || 0
              };
            }"""
        )
        body_media = await composer_media_items(page)
        cover_media = await cover_media_items(page)
        return {
            **structural,
            "bodyMediaCount": len(body_media),
            "coverMediaCount": len(cover_media),
            "bodyMedia": body_media,
            "coverMedia": cover_media,
        }

    def zero_draft_state(state):
        fields = {
            "title": state.get("title") or "",
            "body_text": state.get("bodyText") or "",
            "table_count": int(state.get("tableCount") or 0),
            "body_media_count": int(state.get("bodyMediaCount") or 0),
            "cover_media_count": int(state.get("coverMediaCount") or 0),
        }
        return {
            **fields,
            "verified": not fields["title"]
            and not fields["body_text"]
            and fields["table_count"] == 0
            and fields["body_media_count"] == 0
            and fields["cover_media_count"] == 0,
        }

    async def click_bounded_cover_remove(page):
        return await page.evaluate(
            r"""() => {
              const input=document.querySelector('input[data-testid="fileInput"][type="file"][accept*="image"]')
                || document.querySelector('input[type="file"][accept*="image"]');
              const composer=document.querySelector('[data-testid="composer"]');
              if (!input) return {clicked:false,reason:'cover_input_missing'};
              const eligible=(img)=>{
                if (composer?.contains(img)) return false;
                const src=img.currentSrc || img.src || '';
                return Boolean(src && !src.includes('profile_images') && !src.includes('/emoji/'));
              };
              let region=input.parentElement;
              let images=[];
              for (let depth=0; region && depth<10; depth+=1,region=region.parentElement) {
                images=[...region.querySelectorAll('img')].filter(eligible);
                if (images.length) break;
              }
              if (!region || !images.length) return {clicked:false,reason:'bounded_cover_region_missing'};
              const controls=[...region.querySelectorAll('button,[role="button"]')].map((button)=>{
                const label=[
                  button.getAttribute('aria-label') || '',
                  button.getAttribute('data-testid') || '',
                  button.getAttribute('title') || '',
                  button.innerText || button.textContent || ''
                ].join(' ').replace(/\s+/g,' ').trim();
                return {button,label};
              });
              const exact=controls.find(({label})=>
                /^(?:删除|移除)(?:封面|图片|媒体|照片)?$/i.test(label)
                || /^(?:remove|delete)(?: cover| image| media| photo)?$/i.test(label)
              );
              const explicit=exact || controls.find(({label})=>
                /(?:删除|移除).*(?:封面|图片|媒体|照片)|(?:remove|delete).*(?:cover|image|media|photo)/i.test(label)
              );
              if (!explicit) {
                return {clicked:false,reason:'bounded_remove_control_missing',controls:controls.map(({label})=>label)};
              }
              explicit.button.click();
              return {clicked:true,label:explicit.label,coverImagesBefore:images.length};
            }"""
        )

    async def clear_existing_draft_for_replacement(page, mutation_epoch, timeout_s=60):
        """Clear title/body/tables/body media/cover, then prove every field is zero."""
        initial = await inspect_draft_state(page)
        editor = page.locator('[data-testid="composer"]')
        title = page.locator('textarea[placeholder="添加标题"]').first
        if initial.get("title"):
            await mark_mutation_epoch(page, mutation_epoch, "clear_existing_title")
            await title.fill("")
        if initial.get("bodyText") or initial.get("tableCount") or initial.get("bodyMediaCount"):
            await mark_mutation_epoch(page, mutation_epoch, "clear_existing_body_tables_media")
            await editor.click(position={"x": 24, "y": 24})
            await page.keyboard.press("Meta+A")
            await page.keyboard.press("Backspace")
        if initial.get("coverMediaCount"):
            await mark_mutation_epoch(page, mutation_epoch, "clear_existing_cover")
            removal = await click_bounded_cover_remove(page)
            if not removal.get("clicked"):
                raise RuntimeError(
                    "Existing draft cover could not be removed inside the bounded cover control: "
                    + json.dumps(removal, ensure_ascii=False)
                )

        deadline = time.time() + timeout_s
        stable_zero_reads = 0
        last = zero_draft_state(initial)
        while time.time() < deadline:
            current = await inspect_draft_state(page)
            last = zero_draft_state(current)
            stable_zero_reads = stable_zero_reads + 1 if last["verified"] else 0
            if stable_zero_reads >= 2:
                return {"initial": zero_draft_state(initial), "cleared": last}
            await page.wait_for_timeout(900)
        return {
            "initial": zero_draft_state(initial),
            "cleared": last,
            "timed_out": True,
            "observation_warning": {
                "type": "replacement_baseline_observation_uncertain",
                "message": (
                    "替换写入前未能稳定观察到全零基线；将以同一草稿刷新后的"
                    "完整标题、正文、表格、封面和正文图片为最终裁决。"
                ),
            },
        }

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=not args.headed)
        context = await browser.new_context(viewport={"width": 1440, "height": 1200}, locale="zh-CN")
        await context.add_cookies(cookies)
        page = await context.new_page()
        page.set_default_timeout(70000)

        # Decode and fingerprint every local image on the blank page before X is opened.
        # Unsupported/corrupt inputs must not create an empty or partial remote draft.
        args._last_phase = "fingerprint_local_sources"
        cover_source_item = (
            await local_visual_signature(page, data["cover_image"])
            if upload_cover
            else None
        )
        if cover_source_item and not VISUAL_RGB_SAMPLE_RE.fullmatch(
            str(cover_source_item.get("visualSample") or "")
        ):
            raise ValueError("Local cover image has no readable RGB comparison sample.")
        source_items = [await local_visual_signature(page, item["path"]) for item in content_images]
        source_content_images = build_source_media_contract(
            content_images,
            source_items,
            require_visual_sample=True,
        )

        if args.draft_url:
            args._last_phase = "open_existing_draft"
            print("[1/5] open existing draft")
            await page.goto(args.draft_url, wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(6000)
            if "/login" in page.url:
                raise RuntimeError("X login is stale; export cookies again.")
            if "/compose/articles/edit/" not in page.url:
                raise RuntimeError(f"Did not enter edit page: {page.url}")
            draft_url = page.url
        else:
            args._last_phase = "create_fresh_draft"
            print("[1/5] create fresh draft")
            await page.goto("https://x.com/compose/articles", wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(6000)
            if "/login" in page.url:
                raise RuntimeError("X login is stale; export cookies again.")
            await page.locator('button[aria-label="create"]').first.click()
            for _ in range(15):
                await page.wait_for_timeout(2500)
                if "/compose/articles/edit/" in page.url:
                    break
            if "/compose/articles/edit/" not in page.url:
                raise RuntimeError(f"Did not enter edit page: {page.url}")
            draft_url = page.url
        args._last_phase = "write_draft_url"
        atomic_write_text(args.url_output, draft_url, encoding="utf-8")
        args._draft_url = draft_url
        print("draft_url=" + draft_url)

        await page.wait_for_selector('textarea[placeholder="添加标题"]', timeout=70000)
        await page.wait_for_selector('[data-testid="composer"]', timeout=70000)
        mutation_epoch = f"x-article-upload-{time.time_ns()}"
        args._mutation_epoch = mutation_epoch
        args._last_phase = "begin_autosave_epoch"
        pre_reload_observation_warnings = []
        try:
            await begin_autosave_epoch(page, mutation_epoch)
        except Exception as error:
            pre_reload_observation_warnings.append(
                {
                    "type": "autosave_epoch_tracking_unavailable",
                    "message": (
                        "无法建立本轮 autosave UI 观测；将仅以同一草稿刷新后的"
                        "完整持久化证据兜底。"
                    ),
                    "error": f"{type(error).__name__}: {error}",
                }
            )

        replacement_clear_evidence = None
        cleared_cover_baseline_count = None
        if args.resume_images_only:
            args._last_phase = "resume_validate_existing_media_before_writes"
            print("[2/5] validate image-only resume baseline")
            try:
                resume_state = await inspect_draft_state(page)
                replacement_clear_evidence = validate_resume_images_only_state(
                    resume_state,
                    upload_cover,
                    cover_source_item,
                )
            except Exception as error:
                replacement_clear_evidence = {
                    "verified": False,
                    "observation_error": f"{type(error).__name__}: {error}",
                }
            if not replacement_clear_evidence["verified"]:
                pre_reload_observation_warnings.append(
                    {
                        "type": "resume_baseline_observation_uncertain",
                        "message": (
                            "resume-images-only 的瞬时基线未能稳定确认；最终同 URL reload "
                            "仍会独立严格验收标题、正文、表格、封面和全部正文图片。"
                        ),
                        "evidence": replacement_clear_evidence,
                    }
                )
            replacement_clear_evidence["reason"] = (
                "resume_images_only preserves existing title/body/tables while final reload "
                "independently validates the complete expected draft"
            )
        else:
            args._last_phase = "clear_replacement_before_writes"
            if args.draft_url:
                try:
                    replacement_clear_evidence = await clear_existing_draft_for_replacement(
                        page,
                        mutation_epoch,
                    )
                except Exception as error:
                    replacement_clear_evidence = {
                        "mode": "replacement_baseline_observation_failed",
                        "cleared": {"verified": False},
                        "observation_error": f"{type(error).__name__}: {error}",
                    }
            else:
                try:
                    initial_new_state = zero_draft_state(await inspect_draft_state(page))
                except Exception as error:
                    initial_new_state = {
                        "verified": False,
                        "observation_error": f"{type(error).__name__}: {error}",
                    }
                if not initial_new_state["verified"]:
                    pre_reload_observation_warnings.append(
                        {
                            "type": "new_draft_baseline_observation_uncertain",
                            "message": (
                                "新草稿写入前的空白 DOM 基线未稳定；最终同 URL reload "
                                "仍会独立严格验收完整草稿。"
                            ),
                            "evidence": initial_new_state,
                        }
                    )
                replacement_clear_evidence = {
                    "mode": "new_draft_blank",
                    "initial": initial_new_state,
                    "cleared": initial_new_state,
                }
            if not replacement_clear_evidence.get("cleared", {}).get("verified"):
                pre_reload_observation_warnings.append(
                    {
                        "type": "replacement_baseline_observation_uncertain",
                        "message": (
                            "替换写入前的清空基线未能稳定确认；最终同 URL reload "
                            "将独立严格验收完整草稿。"
                        ),
                        "evidence": replacement_clear_evidence,
                    }
                )
            cleared_cover_baseline_count = int(
                replacement_clear_evidence.get("cleared", {}).get("cover_media_count") or 0
            )

            print("[2/5] cover step")
            if upload_cover:
                args._last_phase = "upload_cover_from_cleared_state"
                await mark_mutation_epoch(page, mutation_epoch, "upload_cover")
                await page.locator('input[type="file"][accept*="image"]').first.set_input_files(data["cover_image"])
                await click_apply_if_present(page, timeout_s=35)
                args._last_phase = "verify_uploaded_cover"
                cover_upload_observation = await wait_for_cover_evidence(
                    page,
                    True,
                    cover_source_item,
                    cleared_baseline_count=cleared_cover_baseline_count,
                )
                if not cover_upload_observation.get("valid"):
                    pre_reload_observation_warnings.append(
                        {
                            **(cover_upload_observation.get("observation_warning") or {}),
                            "evidence": cover_upload_observation,
                        }
                    )
            else:
                print(f"cover_skipped=true recommended_cover_ratio={RECOMMENDED_COVER_RATIO}")

            print("[3/5] fill title and body")
            args._last_phase = "write_title"
            await mark_mutation_epoch(page, mutation_epoch, "write_title")
            await page.locator('textarea[placeholder="添加标题"]').first.fill(args.title or data["title"])
            args._last_phase = "write_body"
            await mark_mutation_epoch(page, mutation_epoch, "write_body")
            body_state = await page.evaluate(
                r"""async ({richHtml, plain, endText, checkpoints, expectedCompactLength, expectedCompactSha256, tableMarkerPattern, mediaStartMarker, compactLengthUnit}) => {
                  function normalizeContent(value){
                    const markerPattern=new RegExp(tableMarkerPattern, 'g');
                    return String(value || '')
                      .replace(markerPattern, '')
                      .split(mediaStartMarker).join('')
                      .replace(/[\s\u200b\ufeff]+/g, '')
                      .normalize('NFC');
                  }
                  async function sha256Hex(value){
                    const digest=await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
                    return [...new Uint8Array(digest)].map((byte)=>byte.toString(16).padStart(2,'0')).join('');
                  }
                  function codePointLength(value){
                    return Array.from(value).length;
                  }
                  function orderedCheckpointPositions(value, expectedCheckpoints){
                    const valuePoints=Array.from(value);
                    const positions=[];
                    let cursor=0;
                    for (const checkpoint of expectedCheckpoints) {
                      const checkpointPoints=Array.from(checkpoint);
                      let position=-1;
                      search: for (let index=cursor; index <= valuePoints.length - checkpointPoints.length; index += 1) {
                        for (let offset=0; offset < checkpointPoints.length; offset += 1) {
                          if (valuePoints[index + offset] !== checkpointPoints[offset]) continue search;
                        }
                        position=index;
                        break;
                      }
                      positions.push(position);
                      cursor=position < 0 ? valuePoints.length + 1 : position + checkpointPoints.length;
                    }
                    return positions;
                  }
                  const editor=document.querySelector('[data-testid="composer"]');
                  editor.focus();
                  const dt=new DataTransfer();
                  dt.setData('text/html', richHtml);
                  dt.setData('text/plain', plain);
                  editor.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:dt}));
                  await new Promise(r=>setTimeout(r,5000));
                  const text=editor.innerText || '';
                  const compact=normalizeContent(text);
                  const contentCompactSha256=await sha256Hex(compact);
                  const checkpointPositions=orderedCheckpointPositions(compact, checkpoints);
                  const matchedCheckpoints=checkpoints.filter((_, index)=>checkpointPositions[index] >= 0);
                  const allCheckpointsMatched=matchedCheckpoints.length === checkpoints.length && checkpoints.length >= 3;
                  const checkpointsInOrder=allCheckpointsMatched && checkpointPositions.every((position)=>position >= 0);
                  const compactTextLength=codePointLength(compact);
                  const exactCompactLength=compactTextLength === expectedCompactLength;
                  const exactCompactSha256=contentCompactSha256 === expectedCompactSha256;
                  return {
                    len:codePointLength(text),
                    compactTextLength,
                    expectedCompactLength,
                    compactLengthUnit,
                    checkpointPositionUnit:compactLengthUnit,
                    expectedCompactSha256,
                    contentCompactSha256,
                    contentCheckpoints:checkpoints,
                    matchedCheckpoints,
                    checkpointPositions,
                    allCheckpointsMatched,
                    checkpointsInOrder,
                    exactCompactLength,
                    exactCompactSha256,
                    hasExpectedLength:exactCompactLength,
                    hasEnd:!endText || text.includes(endText),
                    marker:text.includes('MPH_MARKER')
                  };
                }""",
                {
                    "richHtml": rich_html,
                    "plain": plain,
                    "endText": end_check_text,
                    "checkpoints": content_checkpoints,
                    "expectedCompactLength": expected_compact_length,
                    "expectedCompactSha256": expected_compact_sha256,
                    "tableMarkerPattern": TABLE_MARKER_PATTERN,
                    "mediaStartMarker": MEDIA_START_MARKER,
                    "compactLengthUnit": CONTENT_LENGTH_UNIT,
                },
            )
            print("body=" + json.dumps(body_state, ensure_ascii=False))
            if (
                not body_state["allCheckpointsMatched"]
                or not body_state["checkpointsInOrder"]
                or not body_state["exactCompactLength"]
                or not body_state["exactCompactSha256"]
                or not body_state["hasEnd"]
                or body_state["marker"]
            ):
                pre_reload_observation_warnings.append(
                    {
                        "type": "body_paste_observation_uncertain",
                        "message": (
                            "正文粘贴后的瞬时 DOM 文本校验未稳定；将以同一草稿"
                            "刷新后的标题、正文哈希与有序检查点为最终裁决。"
                        ),
                        "evidence": body_state,
                    }
                )

        inserted_tables = []
        print("[4/6] insert native tables")
        if args.resume_images_only:
            print("tables_skipped=true resume_images_only=true")
        else:
            for table in data.get("tables") or []:
                args._last_phase = f"insert_table_{int(table['index'])}"
                await mark_mutation_epoch(
                    page,
                    mutation_epoch,
                    f"insert_table_{int(table['index'])}",
                )
                print(f"table {table['index']:02d}/{len(data.get('tables') or [])} rows={table.get('row_count')} columns={table.get('column_count')}")
                inserted_table = await insert_native_table(page, table)
                inserted_tables.append(inserted_table)
                pre_reload_observation_warnings.extend(
                    inserted_table.get("observation_warnings") or []
                )
                await page.wait_for_timeout(1800)

        print("[5/6] insert body images")
        inserted = []
        for item in sorted(source_content_images, key=lambda value: value["index"], reverse=True):
            args._last_phase = f"insert_body_image_{int(item['index'])}"
            before_items = await composer_media_items(
                page,
                runtime_prefix=f"{mutation_epoch}-before-{int(item['index'])}",
            )
            before = len(before_items)
            placement = item.get("placement") or MEDIA_PLACEMENT_AFTER_ANCHOR
            target_candidates = (
                [MEDIA_START_MARKER]
                if placement == MEDIA_PLACEMENT_COMPOSER_START
                else item["candidates"]
            )
            target = await find_target(page, target_candidates)
            if not target:
                if placement == MEDIA_PLACEMENT_COMPOSER_START:
                    raise RuntimeError(f"Image {item['index']} could not locate the composer-start marker.")
                raise RuntimeError(f"Image {item['index']} anchor not found: {item['candidates'][:3]}")
            print(f"image {item['index']:02d}/{len(content_images)} anchor={target['candidate'][:60]} media={before}")
            await mark_mutation_epoch(
                page,
                mutation_epoch,
                f"insert_body_image_{int(item['index'])}",
            )
            await page.mouse.click(target["x"], target["y"])
            await page.keyboard.press("End")
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(600)
            await paste_image_at_current_selection(page, item["path"])
            await click_apply_if_present(page, timeout_s=3)
            after = await wait_media_increment(page, before, timeout_s=75)
            if after != before + 1:
                raise RuntimeError(f"Image {item['index']} failed: media {before}->{after}")
            binding_deadline = time.time() + 35
            binding_evidence = None
            binding_observation_errors = []
            while time.time() < binding_deadline:
                try:
                    after_items = await composer_media_items(page)
                    binding_evidence = identify_single_new_media_signature(
                        before_items,
                        after_items,
                        item,
                        source_content_images,
                    )
                except Exception as error:
                    binding_observation_errors.append(
                        f"{type(error).__name__}: {error}"
                    )
                    binding_evidence = {
                        "eligible_for_final_verification": False,
                        "position_verification_deferred": True,
                        "observation_errors": binding_observation_errors[-5:],
                    }
                if binding_evidence.get("eligible_for_final_verification"):
                    break
                await page.wait_for_timeout(1800)
            binding_evidence = binding_evidence or {
                "eligible_for_final_verification": False,
                "position_verification_deferred": True,
            }
            if not binding_evidence.get("eligible_for_final_verification"):
                pre_reload_observation_warnings.append(
                    {
                        "type": "transient_media_binding_observation_uncertain",
                        "image_index": item["index"],
                        "message": (
                            "该图片粘贴后的瞬时 identity/position binding 未能稳定确认；"
                            "本次粘贴的媒体数量已精确 +1，将由同一草稿刷新后的全部"
                            "源图身份、数量、occurrence、顺序和语义位置独立裁决。"
                        ),
                        "evidence": binding_evidence,
                    }
                )
            inserted.append(
                {
                    "index": item["index"],
                    "file": Path(item["path"]).name,
                    "anchor_used": target["candidate"],
                    "expected_anchor": item["expected_anchor"],
                    "placement": placement,
                    "count_after": after,
                    "source_signature": item["source_signature"],
                    "observed_signature": binding_evidence.get("observed_signature") or "",
                    "signature_hamming_distance": binding_evidence.get("source_hamming_distance"),
                    "signature_match": bool(binding_evidence.get("source_matches")),
                    "occurrence": item["source_occurrence"],
                    "expected_dom_order": item["expected_dom_order"],
                    "binding_key": item["identity_key"],
                    "position_verification_deferred": bool(
                        binding_evidence.get("position_verification_deferred")
                        or not binding_evidence.get("eligible_for_final_verification")
                    ),
                    "paste_binding": binding_evidence,
                }
            )
            await page.wait_for_timeout(2500)

        if has_composer_start_media:
            args._last_phase = "remove_composer_start_marker"
            if not await ensure_marker_removed(page, MEDIA_START_MARKER):
                pre_reload_observation_warnings.append(
                    {
                        "type": "composer_start_marker_removal_observation_uncertain",
                        "message": (
                            "正文起始图片的临时 marker 未能在瞬时 DOM 中确认移除；"
                            "最终 reload 正文哈希仍会严格阻断真实残留。"
                        ),
                    }
                )

        print("[6/6] verify autosave")
        args._last_phase = "verify_mutation_epoch_autosave"
        autosave_epoch_available = not any(
            warning.get("type") == "autosave_epoch_tracking_unavailable"
            for warning in pre_reload_observation_warnings
        )
        pre_reload_autosave = (
            await wait_for_autosave(page, mutation_epoch)
            if autosave_epoch_available
            else {
                "epoch": mutation_epoch,
                "verified": False,
                "tracking_unavailable": True,
                "warning": {
                    "type": "autosave_epoch_tracking_unavailable",
                    "message": "autosave UI 观测不可用；等待同 URL reload 最终验收。",
                },
            }
        )
        args._last_phase = "verify_pre_reload_tables"
        try:
            pre_reload_table_evidence = await verify_all_tables(
                page,
                data.get("tables") or [],
                "pre_reload",
            )
        except Exception as error:
            pre_reload_table_evidence = []
            pre_reload_observation_warnings.append(
                {
                    "type": "pre_reload_table_observation_uncertain",
                    "message": str(error),
                }
            )
        args._last_phase = "verify_pre_reload_cover"
        pre_reload_cover_observation_error = ""
        try:
            pre_reload_cover_items = await cover_media_items(page)
        except Exception as error:
            pre_reload_cover_items = []
            pre_reload_cover_observation_error = f"{type(error).__name__}: {error}"
        pre_reload_cover_evidence = validate_cover_evidence(
            pre_reload_cover_items,
            upload_cover,
            source_item=cover_source_item,
            cleared_baseline_count=(
                None if args.resume_images_only else cleared_cover_baseline_count
            ),
        )
        if pre_reload_cover_observation_error or not pre_reload_cover_evidence["valid"]:
            pre_reload_observation_warnings.append(
                {
                    "type": "pre_reload_cover_observation_uncertain",
                    "error": pre_reload_cover_observation_error,
                    "evidence": pre_reload_cover_evidence,
                }
            )
        args._last_phase = "verify_pre_reload_media"
        pre_reload_media_observation_error = ""
        try:
            pre_reload_media_items = await composer_media_items(page)
        except Exception as error:
            pre_reload_media_items = []
            pre_reload_media_observation_error = f"{type(error).__name__}: {error}"
        pre_reload_media_evidence = validate_composer_media_evidence(
            pre_reload_media_items,
            source_content_images,
        )
        inserted_by_index = {int(item["index"]): item for item in inserted}
        expected_indices = list(range(1, len(content_images) + 1))
        binding_indices = sorted(inserted_by_index)
        observed_paste_binding_keys = [
            inserted_by_index[index].get("binding_key") or ""
            for index in expected_indices
            if index in inserted_by_index
        ]
        bound_ordered_binding_keys = [
            item["identity_key"]
            for item in sorted(
                source_content_images,
                key=lambda value: int(value["expected_dom_order"]),
            )
        ]
        paste_identity_bindings_verified = (
            binding_indices == expected_indices
            and all(
                inserted_by_index[index]
                .get("paste_binding", {})
                .get("eligible_for_final_verification")
                for index in expected_indices
            )
        )
        deferred_position_indices = sorted(
            {
                index
                for index in expected_indices
                if inserted_by_index[index].get("position_verification_deferred")
            }
            | {
                int(item.get("index") or 0)
                for item in pre_reload_media_evidence.get("items") or []
                if not item.get("anchor_matches") and int(item.get("index") or 0) > 0
            }
        )
        pre_reload_media_identity_verified = composer_media_identity_is_valid(
            pre_reload_media_evidence
        )
        paste_bindings_verified = (
            paste_identity_bindings_verified
            and observed_paste_binding_keys == bound_ordered_binding_keys
        )
        if not paste_bindings_verified:
            pre_reload_observation_warnings.append(
                {
                    "type": "pre_reload_paste_binding_observation_uncertain",
                    "message": (
                        "图片粘贴阶段的 DOM binding 证据不完整；最终 same-URL reload "
                        "将按本地源图契约独立重算 identity/count/occurrence/order/anchor。"
                    ),
                    "evidence": {
                        "media": pre_reload_media_evidence,
                        "pre_reload_media_identity_verified": pre_reload_media_identity_verified,
                        "paste_identity_bindings_verified": paste_identity_bindings_verified,
                        "paste_bindings_verified": paste_bindings_verified,
                        "deferred_position_indices": deferred_position_indices,
                        "observed_paste_binding_keys": observed_paste_binding_keys,
                        "bound_ordered_binding_keys": bound_ordered_binding_keys,
                    },
                }
            )
        if pre_reload_media_identity_verified and not pre_reload_media_observation_error:
            try:
                await composer_media_items(
                    page,
                    verified_binding_keys=pre_reload_media_evidence["ordered_identity_keys"],
                )
            except Exception as error:
                pre_reload_observation_warnings.append(
                    {
                        "type": "pre_reload_media_dom_annotation_failed",
                        "message": "瞬时媒体 DOM annotation 失败；最终 reload 将独立验收。",
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
        else:
            pre_reload_observation_warnings.append(
                {
                    "type": "pre_reload_media_observation_uncertain",
                    "error": pre_reload_media_observation_error,
                    "evidence": pre_reload_media_evidence,
                }
            )

        editor_verification_js = r"""async ({endText,checkpoints,expectedCompactLength,expectedCompactSha256,expectedTableCount,expectedMediaCount,verifiedMediaBindingKeys,mediaEvidenceVerified,tableMarkerPattern,compactLengthUnit}) => {
              function normalizeContent(value){
                const markerPattern=new RegExp(tableMarkerPattern, 'g');
                return String(value || '')
                  .replace(markerPattern, '')
                  .replace(/[\s\u200b\ufeff]+/g, '')
                  .normalize('NFC');
              }
              async function sha256Hex(value){
                const digest=await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
                return [...new Uint8Array(digest)].map((byte)=>byte.toString(16).padStart(2,'0')).join('');
              }
              function codePointLength(value){
                return Array.from(value).length;
              }
              function orderedCheckpointPositions(value, expectedCheckpoints){
                const valuePoints=Array.from(value);
                const positions=[];
                let cursor=0;
                for (const checkpoint of expectedCheckpoints) {
                  const checkpointPoints=Array.from(checkpoint);
                  let position=-1;
                  search: for (let index=cursor; index <= valuePoints.length - checkpointPoints.length; index += 1) {
                    for (let offset=0; offset < checkpointPoints.length; offset += 1) {
                      if (valuePoints[index + offset] !== checkpointPoints[offset]) continue search;
                    }
                    position=index;
                    break;
                  }
                  positions.push(position);
                  cursor=position < 0 ? valuePoints.length + 1 : position + checkpointPoints.length;
                }
                return positions;
              }
              function inspectTables(root){
                if (!root) return {count:0, details:[]};
                const tables=[...root.querySelectorAll('table')];
                const details=tables.map((table)=>({
                  tag:table.tagName.toLowerCase(),
                  role:table.getAttribute('role') || '',
                  rows:table.querySelectorAll('tr,[role="row"]').length,
                  cells:table.querySelectorAll('th,td,[role="cell"],[role="columnheader"]').length,
                  text:(table.innerText||'').replace(/\s+/g,' ').trim().slice(0,120)
                }));
                return {count:tables.length, details};
              }

              function stripVerifiedNonTextBlocksFromClone(source, tableState){
                const collectFallbackMediaRoots=(root)=>{
                  const images=[...root.querySelectorAll('img')].filter((img)=>{
                    const src=img.currentSrc || img.getAttribute('src') || '';
                    if (!src || src.includes('profile_images') || src.includes('/emoji/')) return false;
                    return !img.closest('table,[role="table"],[role="grid"],[role="toolbar"]');
                  });
                  const candidates=[...new Set(images.map((img)=>
                    img.closest('[data-block="true"]')
                      || img.closest('figure')
                      || img.closest('.public-DraftStyleDefault-block')
                      || img.parentElement
                  ).filter(Boolean))];
                  return candidates.filter((candidate,index,all)=>!all.some((other,otherIndex)=>
                    otherIndex!==index && other.contains(candidate)
                  ));
                };
                const sourceMediaRoots=[...source.querySelectorAll('[data-x-uploader-verified-media-key]')];
                const sourceMediaKeys=sourceMediaRoots.map((root)=>
                  root.getAttribute('data-x-uploader-verified-media-key') || ''
                );
                const annotatedBindingsExact=sourceMediaRoots.length === expectedMediaCount
                  && new Set(sourceMediaKeys).size === sourceMediaKeys.length
                  && sourceMediaKeys.length === verifiedMediaBindingKeys.length
                  && sourceMediaKeys.every((key,index)=>key === verifiedMediaBindingKeys[index])
                  && sourceMediaRoots.every((root)=>root.querySelector('img'));
                const sourceFallbackMediaRoots=collectFallbackMediaRoots(source);
                const fallbackBindingsExact=Boolean(mediaEvidenceVerified)
                  && sourceFallbackMediaRoots.length === expectedMediaCount
                  && verifiedMediaBindingKeys.length === expectedMediaCount;
                const mediaBindingsExact=annotatedBindingsExact || fallbackBindingsExact;
                const clone=source.cloneNode(true);
                const mediaRoots=annotatedBindingsExact
                  ? [...clone.querySelectorAll('[data-x-uploader-verified-media-key]')]
                  : collectFallbackMediaRoots(clone);
                mediaRoots.forEach((root)=>root.remove());
                const mediaReliable=mediaBindingsExact
                  && (annotatedBindingsExact
                    ? clone.querySelectorAll('[data-x-uploader-verified-media-key]').length === 0
                    : collectFallbackMediaRoots(clone).length === 0);
                const tableSelector='table';
                const candidates=[...clone.querySelectorAll(tableSelector)];
                const roots=candidates.filter((candidate)=>!candidates.some((other)=>other !== candidate && other.contains(candidate)));
                let reliable=tableState.count === expectedTableCount && roots.length === expectedTableCount;

                for (const root of roots) {
                  let removable=root;
                  const container=root.closest('section');
                  if (container && container !== clone && container.querySelectorAll(tableSelector).length === 1) {
                    const probe=container.cloneNode(true);
                    probe.querySelectorAll(tableSelector).forEach((node)=>node.remove());
                    probe.querySelectorAll('button,[role="toolbar"],svg,[aria-label="编辑块"]').forEach((node)=>node.remove());
                    const residue=normalizeContent(probe.innerText || probe.textContent || '');
                    if (!residue) removable=container;
                  }
                  removable.remove();
                }

                if (clone.querySelectorAll(tableSelector).length !== 0) reliable=false;
                return {
                  clone,
                  reliable:reliable && mediaReliable,
                  tableReliable:reliable,
                  mediaReliable,
                  mediaBindingKeys:annotatedBindingsExact ? sourceMediaKeys : verifiedMediaBindingKeys,
                  rootCount:roots.length,
                  mediaRootCount:mediaRoots.length
                };
              }

              const editor=document.querySelector('[data-testid="composer"]');
              if (!editor) throw new Error('Composer not found during final verification.');
              const text=editor.innerText||'';
              const tableState=inspectTables(editor);
              const stripped=stripVerifiedNonTextBlocksFromClone(editor, tableState);
              const sandbox=document.createElement('div');
              sandbox.setAttribute('aria-hidden', 'true');
              sandbox.style.cssText='position:fixed;left:-100000px;top:0;width:1000px;pointer-events:none;';
              sandbox.appendChild(stripped.clone);
              document.body.appendChild(sandbox);
              let nonTableText='';
              try {
                nonTableText=stripped.clone.innerText || '';
              } finally {
                sandbox.remove();
              }
              const compact=normalizeContent(nonTableText);
              const contentCompactSha256=await sha256Hex(compact);
              const checkpointPositions=orderedCheckpointPositions(compact, checkpoints);
              const matchedCheckpoints=checkpoints.filter((_, index)=>checkpointPositions[index] >= 0);
              const allCheckpointsMatched=matchedCheckpoints.length === checkpoints.length && checkpoints.length >= 3;
              const checkpointsInOrder=allCheckpointsMatched && checkpointPositions.every((position)=>position >= 0);
              const compactTextLength=codePointLength(compact);
              const exactCompactLength=compactTextLength === expectedCompactLength;
              const exactCompactSha256=contentCompactSha256 === expectedCompactSha256;
              return {
                title:document.querySelector('textarea[placeholder="添加标题"]')?.value||'',
                textLength:codePointLength(text),
                compactTextLength,
                expectedCompactLength,
                compactLengthUnit,
                checkpointPositionUnit:compactLengthUnit,
                expectedCompactSha256,
                contentCompactSha256,
                contentCheckpoints:checkpoints,
                matchedCheckpoints,
                checkpointPositions,
                allCheckpointsMatched,
                checkpointsInOrder,
                exactCompactLength,
                exactCompactSha256,
                hasExpectedLength:exactCompactLength,
                hasStart:allCheckpointsMatched && checkpointsInOrder && exactCompactLength && exactCompactSha256 && stripped.reliable,
                hasEnd:!endText || nonTableText.includes(endText),
                endCheckText:endText,
                marker:text.includes('MPH_MARKER'),
                tableMarker:new RegExp(tableMarkerPattern).test(text),
                tableStripReliable:stripped.reliable,
                mediaStripReliable:stripped.mediaReliable,
                verifiedMediaBindingKeys:stripped.mediaBindingKeys,
                nativeTableNodesFound:stripped.rootCount,
                nativeMediaNodesFound:stripped.mediaRootCount,
                tableCount:tableState.count,
                tableDetails:tableState.details
              };
            }"""
        verification_args = {
            "endText": end_check_text,
            "checkpoints": content_checkpoints,
            "expectedCompactLength": expected_compact_length,
            "expectedCompactSha256": expected_compact_sha256,
            "expectedTableCount": int(data.get("table_count") or 0),
            "expectedMediaCount": len(content_images),
            "verifiedMediaBindingKeys": pre_reload_media_evidence["ordered_identity_keys"],
            "mediaEvidenceVerified": False,
            "tableMarkerPattern": TABLE_MARKER_PATTERN,
            "compactLengthUnit": CONTENT_LENGTH_UNIT,
        }
        args._last_phase = "verify_pre_reload_content"
        try:
            pre_reload_final = await page.evaluate(
                editor_verification_js,
                verification_args,
            )
        except Exception as error:
            pre_reload_final = {
                "observation_error": f"{type(error).__name__}: {error}",
                "hasStart": False,
                "allCheckpointsMatched": False,
                "checkpointsInOrder": False,
                "exactCompactLength": False,
                "exactCompactSha256": False,
                "tableStripReliable": False,
                "mediaStripReliable": False,
                "hasEnd": False,
                "marker": False,
                "tableMarker": False,
            }

        args._last_phase = "reload_draft_for_persistence_check"
        await page.reload(wait_until="domcontentloaded", timeout=90000)
        if page.url != draft_url:
            raise RuntimeError(f"Reload left the draft URL: before={draft_url} after={page.url}")
        args._last_phase = "wait_post_reload_editor"
        await page.wait_for_selector('textarea[placeholder="添加标题"]', timeout=70000)
        await page.wait_for_selector('[data-testid="composer"]', timeout=70000)
        args._last_phase = "wait_post_reload_assets"
        await wait_for_reloaded_assets(
            page,
            int(data.get("table_count") or 0),
            len(content_images),
            upload_cover,
            cover_source_item,
        )
        post_reload_autosave = {
            "verification_required": False,
            "reason": "autosave proof is bound to the pre-reload mutation epoch; reload performs no mutation",
        }

        args._last_phase = "verify_post_reload_tables"
        post_reload_table_evidence = await verify_all_tables(
            page,
            data.get("tables") or [],
            "post_reload",
        )
        args._last_phase = "verify_post_reload_media"
        post_reload_media_items = await composer_media_items(page)
        args._last_phase = "verify_post_reload_cover"
        post_reload_cover_evidence = validate_cover_evidence(
            await cover_media_items(page),
            upload_cover,
            source_item=cover_source_item,
        )
        post_reload_cover_count = post_reload_cover_evidence["actual_count"]
        cover_pre_post_hamming_distance = (
            visual_signature_hamming_distance(
                pre_reload_cover_evidence["ordered_signatures"][0],
                post_reload_cover_evidence["ordered_signatures"][0],
            )
            if upload_cover
            and pre_reload_cover_evidence["ordered_signatures"]
            and post_reload_cover_evidence["ordered_signatures"]
            else None
        )
        cover_signatures_exact = (
            pre_reload_cover_evidence["ordered_signatures"]
            == post_reload_cover_evidence["ordered_signatures"]
        )
        # The same-URL reload is the authoritative persistence proof. A
        # pre-reload decode/DOM observation is useful diagnostics, not a second
        # mandatory success gate when the final source-bound cover is exact.
        cover_signature_persisted = bool(post_reload_cover_evidence["valid"])
        cover_persisted = bool(post_reload_cover_evidence["valid"])
        args._last_phase = "verify_post_reload_media_persistence"
        post_reload_media_evidence = validate_composer_media_evidence(
            post_reload_media_items,
            source_content_images,
        )
        media_phase_persistence = validate_media_phase_persistence(
            pre_reload_media_evidence,
            post_reload_media_evidence,
        )
        final_media_contract = validate_final_media_contract(
            post_reload_media_evidence,
            source_content_images,
        )
        # These success fields are derived only from the authoritative final
        # source-bound assignment. Pre-reload/paste observations remain useful
        # diagnostics but cannot veto an independently exact final result.
        media_signatures_persisted = bool(final_media_contract["valid"])
        hosted_media_identity_persisted = bool(final_media_contract["valid"])
        post_reload_media_by_index = {
            int(item["index"]): item for item in post_reload_media_evidence["items"]
        }
        media_bindings_persisted = (
            final_media_contract["valid"]
            and sorted(post_reload_media_by_index) == expected_indices
        )
        if (
            not final_media_contract["valid"]
            or not cover_persisted
        ):
            raise RuntimeError(
                "Post-reload composer media persistence verification failed: "
                + json.dumps(
                    {
                        "post_reload": post_reload_media_evidence,
                        "final_media_contract": final_media_contract,
                        "signatures_persisted": media_signatures_persisted,
                        "hosted_media_identity_persisted": hosted_media_identity_persisted,
                        "media_bindings_persisted": media_bindings_persisted,
                        "cover_persisted": cover_persisted,
                        "cover_before_reload": pre_reload_cover_evidence,
                        "cover_after_reload": post_reload_cover_evidence,
                    },
                    ensure_ascii=False,
                )
            )
        for media_item in post_reload_media_evidence["items"]:
            record = inserted_by_index.get(int(media_item["index"]))
            if record is not None:
                record["persisted_media"] = media_item
                record["binding_persisted"] = (
                    record.get("binding_key") == media_item.get("identity_key")
                )
        inserted = [inserted_by_index[index] for index in sorted(inserted_by_index)]
        try:
            await composer_media_items(
                page,
                verified_binding_keys=post_reload_media_evidence["ordered_identity_keys"],
            )
        except Exception as error:
            pre_reload_observation_warnings.append(
                {
                    "type": "final_media_dom_annotation_failed",
                    "message": (
                        "最终源图身份、数量、顺序和语义位置已独立通过，但用于正文"
                        "剥离的临时 DOM annotation 写入失败。"
                    ),
                    "error": f"{type(error).__name__}: {error}",
                }
            )
        args._last_phase = "verify_post_reload_content"
        verification_args["verifiedMediaBindingKeys"] = final_media_contract[
            "expected_binding_keys"
        ]
        verification_args["mediaEvidenceVerified"] = bool(final_media_contract["valid"])
        final = await page.evaluate(editor_verification_js, verification_args)
        pre_reload_content_verified = all(
            (
                pre_reload_final.get("hasStart"),
                pre_reload_final.get("allCheckpointsMatched"),
                pre_reload_final.get("checkpointsInOrder"),
                pre_reload_final.get("exactCompactLength"),
                pre_reload_final.get("exactCompactSha256"),
                pre_reload_final.get("tableStripReliable"),
                pre_reload_final.get("mediaStripReliable"),
                pre_reload_final.get("hasEnd"),
                not pre_reload_final.get("marker"),
                not pre_reload_final.get("tableMarker"),
            )
        )
        post_reload_content_verified = all(
            (
                final.get("hasStart"),
                final.get("allCheckpointsMatched"),
                final.get("checkpointsInOrder"),
                final.get("exactCompactLength"),
                final.get("exactCompactSha256"),
                final.get("tableStripReliable"),
                final.get("mediaStripReliable"),
                final.get("hasEnd"),
                not final.get("marker"),
                not final.get("tableMarker"),
            )
        )
        if not pre_reload_content_verified:
            pre_reload_observation_warnings.append(
                {
                    "type": "pre_reload_content_observation_uncertain",
                    "evidence": pre_reload_final,
                }
            )
        replacement_baseline_verified = bool(
            replacement_clear_evidence.get("verified")
            if args.resume_images_only
            else replacement_clear_evidence.get("cleared", {}).get("verified")
        )
        reload_core_persistence_verified = bool(
            page.url == draft_url
            and len(post_reload_table_evidence) == int(data.get("table_count") or 0)
            and final_media_contract["valid"]
            and cover_persisted
            and post_reload_content_verified
        )
        autosave_resolution = resolve_autosave_verification(
            pre_reload_autosave,
            reload_core_persistence_verified,
        )
        verification_warnings = list(pre_reload_observation_warnings)
        verification_warnings.extend(autosave_resolution["warnings"])
        if deferred_position_indices:
            verification_warnings.append(
                {
                    "type": "transient_media_anchor_deferred",
                    "image_indices": deferred_position_indices,
                    "message": (
                        "部分图片粘贴后的瞬时 DOM 锚点无法确定；其图片身份、最终顺序、"
                        "语义位置和刷新持久化均已通过严格验收。"
                    ),
                }
            )
        args._last_phase = "assemble_persistence_evidence"
        persistence_evidence = {
            "reloaded": True,
            "draft_url_before_reload": draft_url,
            "draft_url_after_reload": page.url,
            "content_before_reload": pre_reload_final,
            "content_before_reload_verified": pre_reload_content_verified,
            "content_after_reload_verified": post_reload_content_verified,
            "tables_before_reload": pre_reload_table_evidence,
            "tables_after_reload": post_reload_table_evidence,
            "media_before_reload": pre_reload_media_evidence,
            "media_after_reload": post_reload_media_evidence,
            "final_media_contract": final_media_contract,
            "media_signatures_persisted": media_signatures_persisted,
            "media_phase_persistence": media_phase_persistence,
            "paste_bindings_verified": paste_bindings_verified,
            "ordered_binding_keys": bound_ordered_binding_keys,
            "hosted_media_identity_persisted": hosted_media_identity_persisted,
            "media_bindings_persisted": media_bindings_persisted,
            "mutation_epoch": mutation_epoch,
            "autosave_before_reload": pre_reload_autosave,
            "autosave_after_reload": post_reload_autosave,
            "autosave_ui_verified": autosave_resolution["ui_verified"],
            "autosave_verification_mode": autosave_resolution["mode"],
            "autosave_verified": autosave_resolution["verified"],
            "reload_core_persistence_verified": reload_core_persistence_verified,
            "verification_warnings": verification_warnings,
            "replacement_clear": replacement_clear_evidence,
            "replacement_baseline_verified": replacement_baseline_verified,
            "cover_before_reload": pre_reload_cover_evidence,
            "cover_after_reload": post_reload_cover_evidence,
            "cover_count_after_reload": post_reload_cover_count,
            "cover_signature_persisted": cover_signature_persisted,
            "cover_signatures_exact": cover_signatures_exact,
            "cover_pre_post_hamming_distance": cover_pre_post_hamming_distance,
            "cover_persisted": cover_persisted,
            "verified": bool(
                reload_core_persistence_verified and autosave_resolution["verified"]
            ),
        }
        save_text = autosave_resolution["saved_text"]
        final.update(
            {
                "verification_contract": VERIFICATION_CONTRACT,
                "draft_url": draft_url,
                "media_count": len(post_reload_media_items) + (1 if upload_cover and cover_persisted else 0),
                "body_media_count": len(post_reload_media_items),
                "expected_body_media": data["expected_image_count"],
                "expected_total_media": data["expected_image_count"] + (1 if upload_cover else 0),
                "expected_table_count": int(data.get("table_count") or 0),
                "cover_uploaded": upload_cover,
                "cover_missing": not upload_cover,
                "recommended_cover_ratio": RECOMMENDED_COVER_RATIO,
                "inserted_tables": inserted_tables,
                "inserted": inserted,
                "source_media_contract": [
                    {
                        "index": item["index"],
                        "file": Path(item["path"]).name,
                        "source_signature": item["source_signature"],
                        "expected_source_sample_id": item["source_visual_sample_id"],
                        "source_natural_width": item["source_natural_width"],
                        "source_natural_height": item["source_natural_height"],
                        "occurrence": item["source_occurrence"],
                        "expected_anchor": item["expected_anchor"],
                        "placement": item.get("placement") or MEDIA_PLACEMENT_AFTER_ANCHOR,
                        "expected_dom_order": item["expected_dom_order"],
                        "binding_key": item["identity_key"],
                    }
                    for item in source_content_images
                ],
                "ordered_binding_keys": bound_ordered_binding_keys,
                "saveText": save_text,
                "autosave_verified": persistence_evidence["autosave_verified"],
                "autosave_ui_verified": persistence_evidence["autosave_ui_verified"],
                "autosave_verification_mode": persistence_evidence[
                    "autosave_verification_mode"
                ],
                "verification_warnings": verification_warnings,
                "persistence_verified": persistence_evidence["verified"],
                "media_bindings_persisted": media_bindings_persisted,
                "persistence_evidence": persistence_evidence,
            }
        )
        args._last_phase = "final_success_gate"
        ok = (
            final["verification_contract"] == VERIFICATION_CONTRACT
            and final["title"] == (args.title or data["title"])
            and final["hasStart"]
            and final["allCheckpointsMatched"]
            and final["checkpointsInOrder"]
            and final["exactCompactLength"]
            and final["exactCompactSha256"]
            and final["tableStripReliable"]
            and final["mediaStripReliable"]
            and final["hasEnd"]
            and not final["marker"]
            and not final["tableMarker"]
            and final["body_media_count"] == final["expected_body_media"]
            and final["media_count"] == final["expected_total_media"]
            and final["tableCount"] == final["expected_table_count"]
            and final["autosave_verified"]
            and final["persistence_verified"]
            and all(table.get("visible_matrix_matches") and table.get("readback_matches") for table in final["persistence_evidence"]["tables_after_reload"])
            and final["persistence_evidence"]["final_media_contract"]["valid"]
        )
        if not ok:
            emit_final_status(draft_url, False)
            try:
                await browser.close()
            except Exception:
                pass
            raise RuntimeError("Final verification failed.")

        args._last_phase = "write_success_screenshot"
        screenshot_evidence = await capture_optional_screenshot(page, args.screenshot)
        if screenshot_evidence.get("warning"):
            verification_warnings.append(screenshot_evidence["warning"])
        final["screenshot_written"] = bool(screenshot_evidence.get("written"))
        final["screenshot_evidence"] = screenshot_evidence

        args._last_phase = "close_success_browser"
        try:
            await browser.close()
            final["browser_closed"] = True
        except Exception as error:
            final["browser_closed"] = False
            verification_warnings.append(
                {
                    "type": "browser_cleanup_failed",
                    "error_type": type(error).__name__,
                    "message": "草稿已通过最终验收，但独立浏览器会话清理失败。",
                }
            )

        # Result JSON is a required success artifact and is written only after
        # the strict final gate. Diagnostic screenshot/browser cleanup failures
        # are represented as warnings in this same atomic result.
        args._last_phase = "write_success_result"
        atomic_write_result_json(args.result_json, final)
        emit_final_status(draft_url, True)
        if not upload_cover:
            print(f"COVER_REMINDER 你这篇文章忘补封面图了，是否需要我帮你补一张 {RECOMMENDED_COVER_RATIO} 封面图？")
        return final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown_file")
    parser.add_argument(
        "--cookies-json",
        default=str(Path.home() / ".ailu" / "secrets" / "x" / "cookies.json"),
    )
    parser.add_argument("--parse-script")
    parser.add_argument("--title")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--draft-url")
    parser.add_argument("--confirm-existing-draft-write", action="store_true")
    parser.add_argument("--resume-images-only", action="store_true")
    parser.add_argument("--result-json", default=str(DEFAULT_RESULT_JSON))
    parser.add_argument("--url-output", default=str(DEFAULT_DRAFT_URL_OUTPUT))
    parser.add_argument("--screenshot", default=str(DEFAULT_SCREENSHOT))
    args = parser.parse_args()

    if args.resume_images_only and not args.draft_url:
        parser.error("--resume-images-only requires --draft-url.")
    if args.draft_url:
        if not is_allowed_x_draft_url(args.draft_url):
            parser.error("--draft-url must be an exact https://x.com/compose/articles/edit/... URL.")
        if not args.confirm_existing_draft_write:
            parser.error(
                "--draft-url writes to an existing draft; pass --confirm-existing-draft-write "
                "only after the user confirms that exact URL in the current task."
            )
    elif args.confirm_existing_draft_write:
        parser.error("--confirm-existing-draft-write requires --draft-url.")

    markdown_file = Path(args.markdown_file).expanduser()
    markdown_source = markdown_file.read_text(encoding="utf-8-sig")
    cover_policy = inspect_leading_cover(markdown_file)
    data = parse_markdown(markdown_file, Path(args.parse_script).expanduser() if args.parse_script else None)
    if args.title:
        data["title"] = args.title

    upload_cover = bool(cover_policy["starts_with_image"] and data.get("cover_image"))
    content_images = build_content_images(data, markdown_file, include_cover_as_body=not upload_cover)
    if not upload_cover:
        data["cover_image"] = None
        data["cover_exists"] = True
    data["expected_image_count"] = len(content_images)
    preflight = validate_preflight(data, cover_policy, content_images, markdown_source)
    apply_body_media_limit(preflight, len(content_images))
    plain = plain_text_from_html(data["html"])
    content_contract = build_content_verification_contract(plain)
    if len(content_contract["content_checkpoints"]) < 3:
        preflight["errors"].append(
            {
                "type": "content_too_short_for_verification",
                "expected_compact_length": content_contract["expected_compact_length"],
                "message": "正文过短，无法生成至少 3 个有序内容检查点。不会打开 X。",
            }
        )

    print(
        json.dumps(
            {
                "title": data["title"],
                "cover_image": data["cover_image"],
                "recommended_cover_ratio": RECOMMENDED_COVER_RATIO,
                "cover_policy": cover_policy,
                "cover_upload": upload_cover,
                "cover_missing": not upload_cover,
                "post_upload_cover_reminder": (
                    f"你这篇文章忘补封面图了，是否需要我帮你补一张 {RECOMMENDED_COVER_RATIO} 封面图？" if not upload_cover else ""
                ),
                "expected_body_images": data["expected_image_count"],
                "expected_tables": int(data.get("table_count") or 0),
                "tables": [
                    {
                        "index": table.get("index"),
                        "rows": table.get("row_count"),
                        "columns": table.get("column_count"),
                        "marker": table.get("marker"),
                        "normalized_matrix": validate_table_contract(table)["matrix"],
                        "non_empty_cells": validate_table_contract(table)["non_empty_cells"],
                    }
                    for table in data.get("tables") or []
                ],
                "end_check_text": build_end_check_text(plain),
                "content_checkpoints": content_contract["content_checkpoints"],
                "expected_compact_length": content_contract["expected_compact_length"],
                "expected_compact_sha256": content_contract["expected_compact_sha256"],
                "compact_length_unit": content_contract["compact_length_unit"],
                "checkpoint_position_unit": content_contract["checkpoint_position_unit"],
                "preflight": preflight,
                "anchors": [
                    {
                        "index": item["index"],
                        "file": Path(item["path"]).name,
                        "anchor": item["expected_anchor"],
                        "placement": item.get("placement") or MEDIA_PLACEMENT_AFTER_ANCHOR,
                    }
                    for item in content_images
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if preflight["errors"]:
        print("预检失败：不会打开 X，也不会创建草稿。请先修复上面的 preflight.errors。", file=sys.stderr)
        raise SystemExit(2)
    if args.dry_run:
        return
    prepare_artifact_targets(args)
    try:
        asyncio.run(run_upload(args, data, content_images))
    except Exception as error:
        failure = {
            "verification_contract": VERIFICATION_CONTRACT,
            "status": "partial",
            "result_ok": False,
            "persistence_verified": False,
            "autosave_verified": False,
            "phase": getattr(args, "_last_phase", "run_upload"),
            "mutation_epoch": getattr(args, "_mutation_epoch", ""),
            "draft_url": getattr(args, "_draft_url", ""),
            "resume_images_only": bool(args.resume_images_only),
            "error_type": type(error).__name__,
            "error": str(error),
            "screenshot_written": False,
        }
        atomic_write_result_json(args.result_json, failure)
        print("UPLOAD_PARTIAL " + json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        print("RESULT_OK False")
        raise


if __name__ == "__main__":
    main()
