#!/usr/bin/env python3
"""A guarded yt-dlp desktop and command-line client.

This application is intended only for media the user owns or is authorized
to download. It does not provide DRM, login, cookie, or access-control bypass.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import queue
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python 3.9+ normally has zoneinfo
    ZoneInfo = None  # type: ignore[assignment]

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    TK_IMPORT_ERROR: Optional[BaseException] = None
except Exception as exc:  # CLI diagnostics/path checks must survive GUI-runtime failure
    tk = None  # type: ignore[assignment]
    filedialog = messagebox = ttk = None  # type: ignore[assignment]
    TK_IMPORT_ERROR = exc

APP_NAME = "Safe Video Downloader"
APP_VERSION = "1.14.1"
EXPORT_SCHEMA_VERSION = 4
DIAGNOSTIC_EXPORT_SCHEMA_VERSION = "1.14.1"
DIAGNOSTIC_MAX_FILES = 20
DIAGNOSTIC_LOG_TAIL_LIMIT = 250
QUEUE_CAPACITY = 500
INSTANCE_LOCK_STALE_SECONDS = 24 * 60 * 60
PUBLIC_DEPENDENCY_REVIEW_DATE = "2026-07-18"
MAX_HASH_BYTES = 50 * 1024 * 1024
DEFAULT_OUTPUT_TEMPLATE = "%(title).200B [%(id)s].%(ext)s"
RATE_LIMIT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMG]?)(?:B(?:/s)?)?\s*$", re.IGNORECASE)
URL_RE = re.compile(r"^(https?://|ftp://)", re.IGNORECASE)
WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
URL_IN_TEXT_RE = re.compile(r"\b(?:https?|ftp)://[^\s<>{}\[\]\\\"\\\']+", re.IGNORECASE)
SECRET_KEY_RE = re.compile(r"(api[_-]?key|authorization|bearer|cookie|credential|license[_-]?key|password|passwd|secret|session|token)", re.IGNORECASE)
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")
LOG_ENTRY_LIMIT = 10_000
LOG_RETENTION_MAX_FILES = 30
LOG_RETENTION_MAX_BYTES = 5 * 1024 * 1024
QUEUE_STATE_SCHEMA_VERSION = 1
QUEUE_RECOVERY_MAX_BYTES = 1 * 1024 * 1024
SHUTDOWN_GRACE_SECONDS = 6.0
SOCKET_TIMEOUT_SECONDS = 30
HTTP_RETRIES = 8
FRAGMENT_RETRIES = 12
EXTRACTOR_RETRIES = 3
FILE_ACCESS_RETRIES = 3
PROGRESS_UPDATE_SECONDS = 0.5
PREFLIGHT_DISK_RESERVE_BYTES = 256 * 1024 * 1024
FFPROBE_TIMEOUT_SECONDS = 20
SMART_RESILIENCE_DEFAULT = True
HIDE_MEDIA_DEFAULT = False
SMART_OUTER_ATTEMPTS = 2
SMART_THROTTLED_RATE_BYTES = 32 * 1024
SMART_MANUAL_RATE_DISABLE_THRESHOLD = 128 * 1024
SMART_NETWORK_COOLDOWN_SECONDS = 5.0
SMART_STALE_SESSION_COOLDOWN_SECONDS = 4.0
SMART_RATE_LIMIT_COOLDOWN_SECONDS = 15.0
SMART_RECOVERY_SOCKET_TIMEOUT_SECONDS = 45
SMART_REQUEST_SLEEP_SECONDS = 0.75
SMART_DOWNLOAD_SLEEP_MIN_SECONDS = 2.0
SMART_DOWNLOAD_SLEEP_MAX_SECONDS = 5.0
SMART_CAUTION_JOBS_AFTER_RATE_LIMIT = 2
FRAGMENT_CONCURRENCY_CONSERVATIVE = 3
FRAGMENT_CONCURRENCY_TOLERANT = 5
FRAGMENT_CONCURRENCY_RECOVERY = 1
SITE_TOLERANCE_SCHEMA_VERSION = 1
SITE_TOLERANCE_MAX_BYTES = 1 * 1024 * 1024
SITE_TOLERANCE_MAX_ENTRIES = 512
SITE_TOLERANCE_PROMOTION_SUCCESSES = 3
SITE_TOLERANCE_NETWORK_COOLDOWN_JOBS = 3
SITE_TOLERANCE_RATE_LIMIT_COOLDOWN_JOBS = 5
MEDIA_INDEX_SCHEMA_VERSION = 1
MEDIA_INDEX_MAX_BYTES = 4 * 1024 * 1024
MEDIA_INDEX_MAX_ENTRIES = 10_000
WORKER_SPEC_SCHEMA_VERSION = 1
WORKER_SPEC_MAX_BYTES = 1 * 1024 * 1024
CANCEL_POLL_SECONDS = 0.10
CANCEL_GRACE_SECONDS = 2.0
CANCEL_FORCE_WAIT_SECONDS = 3.0
WORKER_EVENT_PREFIX = "SVD_EVENT:"
DUPLICATE_TRACKING_QUERY_KEYS = frozenset({"feature", "pp", "si"})
YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"})
_MEDIA_INDEX_LOCK = threading.Lock()
_SITE_TOLERANCE_LOCK = threading.Lock()
TEXT_PORTABILITY_SCAN_FILES = (
    "safe_media_downloader.py",
    "run_safe_video_downloader.bat",
    "README.md",
    "LICENSE.md",
    "SECURITY.md",
    "requirements.txt",
    "tests/test_safety_behavior.py",
)

ASSET_METADATA_SCHEMA_VERSION = "public-support-metadata-v1"
PROJECT_SLUG = "safe-video-downloader"
ASSET_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"asset_id": "SVD-SOURCE", "path": "safe_media_downloader.py", "title": "Application source", "purpose": "GUI and CLI implementation", "asset_class": "source", "role": "runtime", "format": "py", "status": "current", "sensitivity": "public", "source_of_truth": True, "tags": ["python", "yt-dlp"], "aliases": [], "metadata_depth": "file"},
    {"asset_id": "SVD-LAUNCHER", "path": "run_safe_video_downloader.bat", "title": "Windows launcher", "purpose": "Portable GUI launcher", "asset_class": "launcher", "role": "runtime", "format": "bat", "status": "current", "sensitivity": "public", "source_of_truth": True, "tags": ["windows", "launcher"], "aliases": [], "metadata_depth": "file"},
    {"asset_id": "SVD-README", "path": "README.md", "title": "Project README", "purpose": "Setup and safety guide", "asset_class": "documentation", "role": "guide", "format": "md", "status": "current", "sensitivity": "public", "source_of_truth": True, "tags": ["documentation"], "aliases": [], "metadata_depth": "file"},
    {"asset_id": "SVD-LICENSE", "path": "LICENSE.md", "title": "License", "purpose": "Copyright and use terms", "asset_class": "documentation", "role": "license", "format": "md", "status": "current", "sensitivity": "public", "source_of_truth": True, "tags": ["license"], "aliases": [], "metadata_depth": "file"},
    {"asset_id": "SVD-SECURITY", "path": "SECURITY.md", "title": "Security policy", "purpose": "Vulnerability reporting guidance", "asset_class": "documentation", "role": "security", "format": "md", "status": "current", "sensitivity": "public", "source_of_truth": True, "tags": ["security"], "aliases": [], "metadata_depth": "file"},
    {"asset_id": "SVD-REQUIREMENTS", "path": "requirements.txt", "title": "Runtime dependencies", "purpose": "Pinned runtime dependency", "asset_class": "configuration", "role": "dependencies", "format": "txt", "status": "current", "sensitivity": "public", "source_of_truth": True, "tags": ["dependencies"], "aliases": [], "metadata_depth": "file"},
    {"asset_id": "SVD-TESTS", "path": "tests/test_safety_behavior.py", "title": "Safety behavior tests", "purpose": "Offline safety and parsing regression tests", "asset_class": "test", "role": "verification", "format": "py", "status": "current", "sensitivity": "public", "source_of_truth": False, "tags": ["tests"], "aliases": [], "metadata_depth": "file"},
)


class DownloadCancelled(Exception):
    """Raised inside yt-dlp hooks when the user presses Stop."""


@dataclass(frozen=True)
class DownloadSettings:
    output_dir: Path
    mode: str
    max_height: Optional[int]
    custom_format: str
    include_playlist: bool
    embed_metadata: bool
    write_subtitles: bool
    restrict_filenames: bool
    use_archive: bool
    rate_limit_bytes: Optional[int]
    prefer_mp4: bool
    ffmpeg_location: Optional[str]
    hide_media: bool
    smart_resilience: bool = SMART_RESILIENCE_DEFAULT


@dataclass
class AdaptiveRunState:
    """Small transparent controller for per-run reconnect/throttle behavior."""

    enabled: bool = SMART_RESILIENCE_DEFAULT
    caution_profile: str = "normal"
    caution_jobs_remaining: int = 0
    rate_limit_events: int = 0
    network_events: int = 0
    stale_session_events: int = 0
    reconnect_attempts: int = 0
    recovery_successes: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def starting_profile(self) -> str:
        if not self.enabled or self.caution_jobs_remaining <= 0:
            return "normal"
        return self.caution_profile

    def note_retry(self, category: str, profile: str, delay_seconds: float) -> None:
        self.reconnect_attempts += 1
        if category == "rate_limit":
            self.rate_limit_events += 1
            self.caution_profile = "rate_limit_recovery"
            self.caution_jobs_remaining = max(self.caution_jobs_remaining, SMART_CAUTION_JOBS_AFTER_RATE_LIMIT)
        elif category == "stale_session":
            self.stale_session_events += 1
            self.caution_profile = "network_recovery"
            self.caution_jobs_remaining = max(self.caution_jobs_remaining, 1)
        else:
            self.network_events += 1
            self.caution_profile = "network_recovery"
            self.caution_jobs_remaining = max(self.caution_jobs_remaining, 1)
        self.history.append({
            "timestamp_utc": utc_now_iso(),
            "event": "session_rebuild",
            "category": category,
            "next_profile": profile,
            "cooldown_seconds": delay_seconds,
        })
        self.history[:] = self.history[-20:]

    def note_success(self, profile: str, attempts_used: int) -> None:
        if profile != "normal" or attempts_used > 1:
            self.recovery_successes += 1
        if self.caution_jobs_remaining > 0:
            self.caution_jobs_remaining -= 1
            if self.caution_jobs_remaining <= 0:
                self.caution_profile = "normal"

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "caution_profile": self.caution_profile,
            "caution_jobs_remaining": self.caution_jobs_remaining,
            "rate_limit_events": self.rate_limit_events,
            "network_events": self.network_events,
            "stale_session_events": self.stale_session_events,
            "reconnect_attempts": self.reconnect_attempts,
            "recovery_successes": self.recovery_successes,
            "history": list(self.history),
        }


@dataclass
class DownloadJob:
    item_id: str
    url: str
    status: str = "Queued"
    result: dict[str, Any] = field(default_factory=dict)


def settings_to_worker_payload(settings: DownloadSettings) -> dict[str, Any]:
    """Serialize only the bounded settings required by an isolated worker."""
    return {
        "output_dir": str(settings.output_dir),
        "mode": settings.mode,
        "max_height": settings.max_height,
        "custom_format": settings.custom_format,
        "include_playlist": settings.include_playlist,
        "embed_metadata": settings.embed_metadata,
        "write_subtitles": settings.write_subtitles,
        "restrict_filenames": settings.restrict_filenames,
        "use_archive": settings.use_archive,
        "rate_limit_bytes": settings.rate_limit_bytes,
        "prefer_mp4": settings.prefer_mp4,
        "ffmpeg_location": settings.ffmpeg_location,
        "hide_media": settings.hide_media,
        "smart_resilience": settings.smart_resilience,
    }


def settings_from_worker_payload(payload: dict[str, Any]) -> DownloadSettings:
    """Validate a worker settings payload without accepting arbitrary keys."""
    allowed = {
        "output_dir", "mode", "max_height", "custom_format", "include_playlist",
        "embed_metadata", "write_subtitles", "restrict_filenames", "use_archive",
        "rate_limit_bytes", "prefer_mp4", "ffmpeg_location", "hide_media",
        "smart_resilience",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"worker settings contain unsupported keys: {', '.join(unknown)}")
    output_dir = resolve_output_dir(str(payload.get("output_dir") or "Downloads"))
    mode = str(payload.get("mode") or "Video (best MP4)")
    if mode not in {"Video (best MP4)", "Audio (MP3)", "Audio (original/best)", "Custom yt-dlp format"}:
        raise ValueError("worker settings contain an unsupported mode")
    raw_height = payload.get("max_height")
    max_height = None if raw_height in (None, "", 0) else int(raw_height)
    if max_height is not None and max_height <= 0:
        raise ValueError("worker max_height must be positive or null")
    rate_limit = payload.get("rate_limit_bytes")
    if rate_limit is not None:
        rate_limit = int(rate_limit)
        if rate_limit <= 0:
            raise ValueError("worker rate_limit_bytes must be positive or null")
    return DownloadSettings(
        output_dir=output_dir,
        mode=mode,
        max_height=max_height,
        custom_format=str(payload.get("custom_format") or ""),
        include_playlist=bool(payload.get("include_playlist")),
        embed_metadata=bool(payload.get("embed_metadata")),
        write_subtitles=bool(payload.get("write_subtitles")),
        restrict_filenames=bool(payload.get("restrict_filenames")),
        use_archive=bool(payload.get("use_archive")),
        rate_limit_bytes=rate_limit,
        prefer_mp4=bool(payload.get("prefer_mp4")),
        ffmpeg_location=str(payload.get("ffmpeg_location")) if payload.get("ffmpeg_location") else None,
        hide_media=bool(payload.get("hide_media")),
        smart_resilience=bool(payload.get("smart_resilience", SMART_RESILIENCE_DEFAULT)),
    )


def app_base_dir() -> Path:
    """Return the folder containing the source file or frozen executable."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def tools_dir() -> Path:
    return app_base_dir() / "tools"


def state_dir() -> Path:
    return app_base_dir() / "state"


def logs_dir() -> Path:
    return app_base_dir() / "logs"


def exports_dir() -> Path:
    return app_base_dir() / "exports"


def diagnostics_dir() -> Path:
    return app_base_dir() / "diagnostics"


def prepend_tools_to_path() -> None:
    """Make locally supplied helper binaries discoverable without shell tricks."""
    folder = tools_dir()
    if not folder.exists():
        return
    current = os.environ.get("PATH", "")
    current_parts = [part for part in current.split(os.pathsep) if part]
    resolved_folder = str(folder.resolve())
    resolved_parts = {str(Path(part).resolve()) for part in current_parts if part}
    if resolved_folder not in resolved_parts:
        os.environ["PATH"] = resolved_folder + (os.pathsep + current if current else "")


def default_download_dir() -> Path:
    return Path.home() / "Downloads" / APP_NAME.replace(" ", "")


def resolve_output_dir(value: Any) -> Path:
    """Resolve a user output target predictably after project relocation.

    Environment variables and ``~`` are expanded. Relative paths are anchored
    to the application folder rather than the process working directory, so a
    moved ZIP or a direct Python launch keeps deterministic targeting.
    """
    raw = os.path.expandvars(str(value or "").strip())
    if not raw:
        raise ValueError("Output folder cannot be empty.")
    candidate = Path(raw).expanduser()
    windows_absolute = bool(WINDOWS_ABSOLUTE_PATH_RE.match(raw))
    if not candidate.is_absolute() and not windows_absolute:
        candidate = app_base_dir() / candidate
    # pathlib on non-Windows hosts does not recognize C:\... as absolute. Keep
    # the literal target there so diagnostics/tests do not invent a sandbox path.
    if not windows_absolute or platform.system() == "Windows":
        candidate = candidate.resolve(strict=False)
    if candidate.exists() and not candidate.is_dir():
        raise ValueError(f"Output target is a file, not a folder: {candidate}")
    return candidate


def resolve_export_destination(value: Any, default_folder: Path) -> Path:
    """Resolve a report/diagnostic destination; relative names stay project-local."""
    raw = os.path.expandvars(str(value or "").strip())
    if not raw:
        raise ValueError("Export destination cannot be empty.")
    candidate = Path(raw).expanduser()
    windows_absolute = bool(WINDOWS_ABSOLUTE_PATH_RE.match(raw))
    if not candidate.is_absolute() and not windows_absolute:
        candidate = default_folder / candidate
    if not windows_absolute or platform.system() == "Windows":
        candidate = candidate.resolve(strict=False)
    return candidate


def canonical_url_key(value: str) -> str:
    """Return a conservative identity key for queue duplicate detection.

    The original URL is never modified. This key only collapses harmless URL
    presentation differences such as fragments, tracking parameters, query
    ordering, and common YouTube URL forms.
    """
    raw = str(value or "").strip()
    try:
        parts = urlsplit(raw)
    except Exception:
        return raw
    host = (parts.hostname or "").lower()
    path = parts.path or "/"
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    if host in YOUTUBE_HOSTS:
        media_id: Optional[str] = None
        if host.endswith("youtu.be"):
            media_id = path.strip("/").split("/", 1)[0] or None
        else:
            path_parts = [part for part in path.split("/") if part]
            if path == "/watch":
                media_id = next((value for key, value in query_pairs if key == "v" and value), None)
            elif path_parts and path_parts[0] in {"shorts", "live", "embed"} and len(path_parts) > 1:
                media_id = path_parts[1]
        if media_id and re.fullmatch(r"[A-Za-z0-9_-]{6,64}", media_id):
            return f"youtube:{media_id}"
    cleaned_query = []
    for key, item_value in query_pairs:
        key_lower = key.lower()
        if key_lower.startswith("utm_") or key_lower in DUPLICATE_TRACKING_QUERY_KEYS:
            continue
        cleaned_query.append((key, item_value))
    cleaned_query.sort()
    scheme = (parts.scheme or "").lower()
    netloc = (parts.netloc or "").lower()
    return urlunsplit((scheme, netloc, path, urlencode(cleaned_query, doseq=True), ""))


def normalize_urls_with_stats(text: str) -> tuple[list[str], int]:
    """Return valid URL lines plus the number auto-collapsed as duplicates."""
    urls: list[str] = []
    seen: set[str] = set()
    duplicates = 0
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#") or not URL_RE.match(line):
            continue
        key = canonical_url_key(line)
        if key in seen:
            duplicates += 1
            continue
        urls.append(line)
        seen.add(key)
    return urls, duplicates


def normalize_urls(text: str) -> list[str]:
    """Split text into URL-looking lines and collapse equivalent duplicates."""
    return normalize_urls_with_stats(text)[0]


def normalize_cli_urls(values: Iterable[str]) -> list[str]:
    """Validate and identity-deduplicate CLI URL arguments."""
    urls: list[str] = []
    seen: set[str] = set()
    invalid: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        if not URL_RE.match(value):
            invalid.append(value[:80])
            continue
        key = canonical_url_key(value)
        if key not in seen:
            urls.append(value)
            seen.add(key)
    if invalid:
        preview = ", ".join(redact_text(item) for item in invalid[:3])
        raise ValueError(f"Only http, https, and ftp URL arguments are accepted; rejected: {preview}")
    return urls

def parse_rate_limit(text: str) -> Optional[int]:
    """Parse yt-dlp-style rate limits such as 500K, 2M, or 1.5G into bytes/s."""
    text = (text or "").strip()
    if not text:
        return None
    match = RATE_LIMIT_RE.match(text)
    if not match:
        raise ValueError("Use a value like 500K, 2M, or leave the field blank.")
    value = float(match.group(1))
    suffix = match.group(2).upper()
    multiplier = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}[suffix]
    parsed = int(value * multiplier)
    if parsed <= 0:
        raise ValueError("Rate limit must be greater than zero.")
    return parsed


def format_bytes(num: Optional[float]) -> str:
    if num is None:
        return "?"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0:
            return f"{value:3.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} PB"


def format_eta(seconds: Optional[float]) -> str:
    if seconds is None:
        return "?"
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def executable_names(name: str) -> list[str]:
    """Return likely executable names for the current OS."""
    names = [name]
    if platform.system() == "Windows" and not name.lower().endswith(".exe"):
        names.insert(0, f"{name}.exe")
    return names


def find_executable(name: str) -> Optional[Path]:
    """Find an executable in tools, the app folder, then PATH."""
    prepend_tools_to_path()
    for folder in (tools_dir(), app_base_dir()):
        for candidate in executable_names(name):
            path = folder / candidate
            if path.is_file():
                return path.resolve()
    found = shutil.which(name)
    if found:
        return Path(found).resolve()
    return None


def find_ffmpeg_location() -> Optional[str]:
    """Return a folder path for yt-dlp's ffmpeg_location option, or None."""
    ffmpeg = find_executable("ffmpeg")
    if ffmpeg:
        return str(ffmpeg.parent)
    return None


def find_js_runtime() -> Optional[tuple[str, str]]:
    """Return the best supported JavaScript runtime for yt-dlp.

    Deno is preferred. Node is a bounded fallback. Runtime versions are probed
    only during normal startup/download preparation; diagnostic export reuses
    cached evidence and never runs helper binaries just to fill fields.
    """
    snapshot = javascript_runtime_snapshot(execute_versions=True)
    selected = snapshot.get("selected")
    if isinstance(selected, dict) and selected.get("path"):
        return str(selected.get("name")), str(selected.get("path"))
    return None

_JS_RUNTIME_PROBE_CACHE: dict[str, dict[str, Any]] = {}


def parse_program_version(text: str) -> Optional[tuple[int, ...]]:
    """Extract a conservative dotted numeric version tuple from tool output."""
    match = re.search(r"(?<!\d)(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text or ""))
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def probe_program_version(path: Path, *, timeout: float = 3.0) -> dict[str, Any]:
    """Probe a local executable with --version using no shell and a hard timeout."""
    key = str(path.resolve())
    cached = _JS_RUNTIME_PROBE_CACHE.get(key)
    if cached is not None:
        return dict(cached)
    result: dict[str, Any]
    try:
        completed = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=max(0.5, float(timeout)),
            check=False,
            shell=False,
        )
        output = (completed.stdout or completed.stderr or "").strip().splitlines()
        version_text = output[0][:160] if output else ""
        parsed = parse_program_version(version_text)
        result = {
            "status": "ok" if completed.returncode == 0 and parsed else "unverified",
            "version_text": version_text,
            "version_tuple": list(parsed) if parsed else None,
            "exit_code": completed.returncode,
        }
    except subprocess.TimeoutExpired:
        result = {"status": "timeout", "version_text": "", "version_tuple": None}
    except Exception as exc:
        result = {"status": "unavailable", "version_text": redact_text(exc), "version_tuple": None}
    _JS_RUNTIME_PROBE_CACHE[key] = dict(result)
    return result


def javascript_runtime_snapshot(*, execute_versions: bool = False) -> dict[str, Any]:
    """Describe supported JS runtimes without network access.

    When execute_versions=False, only already-cached version evidence is used.
    This keeps diagnostic export read-only with respect to helper execution.
    """
    specs = (("deno", (2, 3, 0), True), ("node", (22, 0, 0), False))
    candidates: list[dict[str, Any]] = []
    selected: Optional[dict[str, Any]] = None
    for name, minimum, recommended in specs:
        path = find_executable(name)
        if not path:
            candidates.append({"name": name, "present": False, "minimum": list(minimum), "recommended": recommended, "status": "missing"})
            continue
        cache_key = str(path.resolve())
        evidence = probe_program_version(path) if execute_versions else dict(_JS_RUNTIME_PROBE_CACHE.get(cache_key) or {})
        version_tuple_raw = evidence.get("version_tuple")
        version_tuple = tuple(int(v) for v in version_tuple_raw) if isinstance(version_tuple_raw, list) else None
        if version_tuple is None:
            status = "detected_unverified"
            supported = False
        else:
            supported = version_tuple >= minimum
            status = "supported" if supported else "unsupported_version"
        item = {
            "name": name,
            "present": True,
            "path": str(path),
            "minimum": list(minimum),
            "recommended": recommended,
            "status": status,
            "version_text": evidence.get("version_text"),
            "version_tuple": list(version_tuple) if version_tuple else None,
        }
        candidates.append(item)
        if selected is None and supported:
            selected = item
    return {
        "selected": selected,
        "candidates": candidates,
        "selection_order": ["deno", "node"],
        "probe_policy": "normal startup/download executes a bounded local --version probe; unverified candidates are reported but not selected; diagnostics serialize cached/path-only evidence",
        "remote_components_enabled": False,
    }


def make_retry_sleep_function(start: float, maximum: float) -> Callable[..., float]:
    """Return deterministic bounded exponential backoff for yt-dlp retries."""
    def retry_sleep(*, n: int, **_kwargs: Any) -> float:
        attempt = max(1, int(n or 1))
        return min(float(maximum), float(start) * (2 ** (attempt - 1)))
    return retry_sleep


def smart_throttled_rate(settings: DownloadSettings) -> Optional[int]:
    """Return a conservative low-speed re-extraction threshold.

    Manual caps below 128 KiB/s disable this guard so an intentionally slow
    connection is not mistaken for provider throttling.
    """
    if not settings.smart_resilience:
        return None
    if settings.rate_limit_bytes is not None and settings.rate_limit_bytes < SMART_MANUAL_RATE_DISABLE_THRESHOLD:
        return None
    return SMART_THROTTLED_RATE_BYTES


def resilience_profile_snapshot(
    settings: DownloadSettings,
    profile: str = "normal",
    *,
    normal_fragment_limit: Optional[int] = None,
) -> dict[str, Any]:
    """Return the bounded transport profile for one attempt.

    Normal segmented transfers are always limited to either three or five
    fragments. Five is selected only after clean site history; manual rate caps
    and recovery attempts remain single-fragment.
    """
    requested = int(normal_fragment_limit or FRAGMENT_CONCURRENCY_CONSERVATIVE)
    bounded_normal = (
        FRAGMENT_CONCURRENCY_TOLERANT
        if requested >= FRAGMENT_CONCURRENCY_TOLERANT
        else FRAGMENT_CONCURRENCY_CONSERVATIVE
    )
    normal_fragments = FRAGMENT_CONCURRENCY_RECOVERY if settings.rate_limit_bytes else bounded_normal
    snapshot: dict[str, Any] = {
        "name": profile,
        "socket_timeout_seconds": SOCKET_TIMEOUT_SECONDS,
        "concurrent_fragments": normal_fragments,
        "normal_fragment_limit": bounded_normal,
        "fragment_policy": "site-tolerance-auto-3-or-5",
        "sleep_requests_seconds": 0.0,
        "download_sleep_min_seconds": 0.0,
        "download_sleep_max_seconds": 0.0,
        "throttled_rate_bytes": smart_throttled_rate(settings),
    }
    if profile == "network_recovery":
        snapshot.update({
            "socket_timeout_seconds": SMART_RECOVERY_SOCKET_TIMEOUT_SECONDS,
            "concurrent_fragments": FRAGMENT_CONCURRENCY_RECOVERY,
        })
    elif profile == "rate_limit_recovery":
        snapshot.update({
            "socket_timeout_seconds": SMART_RECOVERY_SOCKET_TIMEOUT_SECONDS,
            "concurrent_fragments": FRAGMENT_CONCURRENCY_RECOVERY,
            "sleep_requests_seconds": SMART_REQUEST_SLEEP_SECONDS,
            "download_sleep_min_seconds": SMART_DOWNLOAD_SLEEP_MIN_SECONDS,
            "download_sleep_max_seconds": SMART_DOWNLOAD_SLEEP_MAX_SECONDS,
        })
    return snapshot


def retry_policy_snapshot(rate_limited: bool = False, smart_resilience: bool = SMART_RESILIENCE_DEFAULT) -> dict[str, Any]:
    return {
        "socket_timeout_seconds": SOCKET_TIMEOUT_SECONDS,
        "http_retries": HTTP_RETRIES,
        "fragment_retries": FRAGMENT_RETRIES,
        "extractor_retries": EXTRACTOR_RETRIES,
        "file_access_retries": FILE_ACCESS_RETRIES,
        "backoff": {"http": "exp 1..20s", "fragment": "exp 1..20s", "extractor": "exp 1..8s", "file_access": "exp 0.5..4s"},
        "concurrent_fragments": FRAGMENT_CONCURRENCY_RECOVERY if rate_limited else FRAGMENT_CONCURRENCY_CONSERVATIVE,
        "fragment_tolerance": {
            "policy": "auto_3_or_5",
            "conservative_limit": FRAGMENT_CONCURRENCY_CONSERVATIVE,
            "tolerant_limit": FRAGMENT_CONCURRENCY_TOLERANT,
            "promotion_after_clean_successes": SITE_TOLERANCE_PROMOTION_SUCCESSES,
            "stress_downgrade": FRAGMENT_CONCURRENCY_CONSERVATIVE,
            "recovery_limit": FRAGMENT_CONCURRENCY_RECOVERY,
            "manual_rate_cap_limit": FRAGMENT_CONCURRENCY_RECOVERY,
        },
        "skip_unavailable_fragments": False,
        "check_selected_formats": True,
        "progress_update_seconds": PROGRESS_UPDATE_SECONDS,
        "cancellation": {
            "isolated_worker_process": True,
            "cooperative_marker": True,
            "automatic_hard_stop_after_seconds": CANCEL_GRACE_SECONDS,
            "second_click_force_stop": True,
            "process_tree_termination": True,
            "partial_resume_preserved": True,
        },
        "smart_resilience": {
            "enabled": bool(smart_resilience),
            "outer_attempts": SMART_OUTER_ATTEMPTS if smart_resilience else 1,
            "resume_partial_files": True,
            "session_rebuild_on": ["network", "rate_limit", "stale_session"],
            "throttled_rate_bytes": SMART_THROTTLED_RATE_BYTES if smart_resilience else None,
            "network_cooldown_seconds": SMART_NETWORK_COOLDOWN_SECONDS,
            "rate_limit_cooldown_seconds": SMART_RATE_LIMIT_COOLDOWN_SECONDS,
            "recovery_fragment_concurrency": FRAGMENT_CONCURRENCY_RECOVERY,
            "rate_limit_request_sleep_seconds": SMART_REQUEST_SLEEP_SECONDS,
        },
    }


def _selected_format_records(info: dict[str, Any]) -> list[dict[str, Any]]:
    requested = info.get("requested_formats")
    raw_formats = requested if isinstance(requested, list) and requested else [info]
    records: list[dict[str, Any]] = []
    for fmt in raw_formats:
        if not isinstance(fmt, dict):
            continue
        records.append({
            "format_id": str(fmt.get("format_id") or "unknown"),
            "ext": fmt.get("ext"),
            "vcodec": fmt.get("vcodec"),
            "acodec": fmt.get("acodec"),
            "width": fmt.get("width"),
            "height": fmt.get("height"),
            "fps": fmt.get("fps"),
            "protocol": fmt.get("protocol"),
            "filesize": fmt.get("filesize"),
            "filesize_approx": fmt.get("filesize_approx"),
            "tbr": fmt.get("tbr"),
            "has_drm": bool(fmt.get("has_drm")),
        })
    return records


def estimate_selected_download_bytes(info: dict[str, Any]) -> Optional[int]:
    """Estimate selected payload size without making additional requests."""
    records = _selected_format_records(info)
    total = 0.0
    known = False
    duration = info.get("duration")
    try:
        duration_value = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_value = None
    for record in records:
        size = record.get("filesize") or record.get("filesize_approx")
        if size:
            try:
                total += float(size)
                known = True
                continue
            except (TypeError, ValueError):
                pass
        tbr = record.get("tbr")
        if duration_value and tbr:
            try:
                total += duration_value * float(tbr) * 1000.0 / 8.0
                known = True
            except (TypeError, ValueError):
                pass
    return int(total) if known and total > 0 else None


def build_download_plan(info: dict[str, Any], settings: DownloadSettings) -> dict[str, Any]:
    """Create a compact exact-selection plan from yt-dlp's chosen info dict."""
    formats = _selected_format_records(info)
    estimated = estimate_selected_download_bytes(info)
    stream_count = len(formats)
    if settings.mode == "Audio (MP3)":
        multiplier = 1.7
    elif stream_count > 1:
        multiplier = 2.2
    else:
        multiplier = 1.25
    required = int((estimated or 0) * multiplier) + PREFLIGHT_DISK_RESERVE_BYTES
    protocols = [str(record.get("protocol") or "").lower() for record in formats]
    fragmented_transfer = any(
        token in protocol
        for protocol in protocols
        for token in ("m3u8", "dash", "ism")
    )
    return {
        "media_id": str(info.get("id") or "unknown"),
        "extractor": str(info.get("extractor_key") or info.get("extractor") or "unknown"),
        "format_ids": [record.get("format_id") for record in formats],
        "formats": formats,
        "stream_count": stream_count,
        "estimated_download_bytes": estimated,
        "peak_disk_multiplier": multiplier,
        "required_free_bytes": required,
        "is_live": bool(info.get("is_live")),
        "has_drm": bool(info.get("has_drm")) or any(bool(record.get("has_drm")) for record in formats),
        "expected_duration_seconds": info.get("duration"),
        "expected_output_ext": info.get("ext"),
        "protocols": protocols,
        "fragmented_transfer": fragmented_transfer,
        "integrity_policy": "abort on selected DRM flag, abort on known insufficient disk, abort on unavailable fragments, verify final media when possible",
    }


def assess_disk_capacity(output_dir: Path, required_bytes: int) -> dict[str, Any]:
    parent = _existing_parent_for_disk(output_dir)
    try:
        usage = shutil.disk_usage(parent)
        free = int(usage.free)
        return {
            "status": "ok" if free >= required_bytes else "insufficient",
            "free_bytes": free,
            "required_bytes": int(required_bytes),
            "margin_bytes": free - int(required_bytes),
            "checked_path": str(parent),
        }
    except Exception as exc:
        return {"status": "unavailable", "required_bytes": int(required_bytes), "reason": redact_text(exc), "checked_path": str(parent)}


def verify_media_file(path: Path, settings: DownloadSettings, info: Optional[dict[str, Any]] = None, *, timeout: int = FFPROBE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Verify a final file with ffprobe when available, otherwise basic I/O checks."""
    result: dict[str, Any] = {"path": str(path), "method": "basic", "status": "failed", "checked_at_utc": utc_now_iso()}
    try:
        if not path.is_file():
            result["reason"] = "final media file does not exist"
            return result
        size = int(path.stat().st_size)
        result["file_size_bytes"] = size
        if size <= 0:
            result["reason"] = "final media file is empty"
            return result
    except Exception as exc:
        result["reason"] = redact_text(exc)
        return result

    ffprobe = find_executable("ffprobe")
    if not ffprobe:
        result.update({"status": "basic_ok", "reason": "ffprobe not detected; existence and nonzero size verified"})
        return result
    command = [
        str(ffprobe), "-v", "error", "-show_entries",
        "format=duration,size,format_name:stream=index,codec_type,codec_name,width,height",
        "-of", "json", str(path),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=max(1, int(timeout)), check=False, shell=False)
    except subprocess.TimeoutExpired:
        result.update({"method": "ffprobe", "reason": f"ffprobe timed out after {timeout}s"})
        return result
    except Exception as exc:
        result.update({"method": "ffprobe", "reason": redact_text(exc)})
        return result
    if completed.returncode != 0:
        result.update({"method": "ffprobe", "reason": redact_text((completed.stderr or completed.stdout or "ffprobe failed")[:500]), "exit_code": completed.returncode})
        return result
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        result.update({"method": "ffprobe", "reason": f"invalid ffprobe JSON: {exc}"})
        return result
    streams = payload.get("streams") if isinstance(payload, dict) else []
    streams = streams if isinstance(streams, list) else []
    stream_types = sorted({str(stream.get("codec_type")) for stream in streams if isinstance(stream, dict) and stream.get("codec_type")})
    expected = "audio" if settings.mode.startswith("Audio") else "video" if settings.mode.startswith("Video") else "any"
    valid_stream = bool(stream_types) if expected == "any" else expected in stream_types
    duration_raw = (payload.get("format") or {}).get("duration") if isinstance(payload, dict) else None
    try:
        duration = float(duration_raw) if duration_raw not in (None, "N/A") else None
    except (TypeError, ValueError):
        duration = None
    result.update({"method": "ffprobe", "stream_types": stream_types, "duration_seconds": duration, "expected_stream": expected})
    if not valid_stream:
        result.update({"status": "failed", "reason": f"expected {expected} stream was not found"})
        return result
    warning = None
    expected_duration = (info or {}).get("duration")
    try:
        expected_duration_value = float(expected_duration) if expected_duration else None
    except (TypeError, ValueError):
        expected_duration_value = None
    if expected_duration_value and duration and not bool((info or {}).get("is_live")) and expected_duration_value > 10 and duration < expected_duration_value * 0.70:
        warning = "final duration is materially shorter than extractor metadata; review source or log"
    result.update({"status": "warning" if warning else "verified", "reason": warning or "final media container and expected stream verified"})
    return result


def apply_media_visibility(path: Path, hide: bool = HIDE_MEDIA_DEFAULT) -> dict[str, Any]:
    """Apply or clear the Windows hidden attribute on one final media file.

    The operation is best-effort and never hides output folders, logs, exports,
    diagnostics, queue state, or download-archive files. Non-Windows platforms
    report ``not_applicable`` without changing the file.
    """
    target = Path(path)
    result: dict[str, Any] = {
        "requested": "hidden" if hide else "visible",
        "platform": platform.system(),
        "applied": False,
        "status": "not_applied",
        "file_name": target.name,
    }
    if platform.system() != "Windows":
        result.update({"status": "not_applicable", "reason": "Windows hidden attributes are not available on this platform"})
        return result
    if not target.is_file():
        result.update({"status": "failed", "reason": "final media file was not found"})
        return result
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        get_attrs = kernel32.GetFileAttributesW
        set_attrs = kernel32.SetFileAttributesW
        get_attrs.argtypes = [wintypes.LPCWSTR]
        get_attrs.restype = wintypes.DWORD
        set_attrs.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        set_attrs.restype = wintypes.BOOL

        invalid = 0xFFFFFFFF
        hidden_flag = 0x00000002
        current = int(get_attrs(str(target)))
        if current == invalid:
            result.update({"status": "failed", "reason": "Windows could not read the final media file attributes"})
            return result
        desired = (current | hidden_flag) if hide else (current & ~hidden_flag)
        if desired == current:
            result.update({
                "status": "already_hidden" if hide else "already_visible",
                "applied": True,
                "hidden": bool(current & hidden_flag),
            })
            return result
        if not bool(set_attrs(str(target), desired)):
            result.update({"status": "failed", "reason": "Windows could not update the final media file attributes"})
            return result
        result.update({
            "status": "hidden" if hide else "visible",
            "applied": True,
            "hidden": bool(desired & hidden_flag),
        })
        return result
    except Exception as exc:
        result.update({"status": "failed", "reason": redact_text(exc)})
        return result


def classify_download_error(exc: BaseException) -> str:
    text = str(exc).lower()
    if isinstance(exc, DownloadCancelled) or "cancel" in text:
        return "cancelled"
    if any(token in text for token in ("http error 429", "too many requests", "rate limit", "ratelimit", "server throttling", "throttled")):
        return "rate_limit"
    if ("http error 403" in text or "forbidden" in text) and any(token in text for token in ("fragment", "expired", "signature", "signed url", "url has expired")):
        return "stale_session"
    if "ffmpeg" in text or "ffprobe" in text or "javascript runtime" in text or "deno" in text:
        return "dependency"
    if "disk" in text or "no space" in text or "insufficient" in text:
        return "disk"
    if "verify" in text or "expected video stream" in text or "expected audio stream" in text:
        return "verification"
    if any(token in text for token in (
        "timed out", "timeout", "network", "connection", "temporary failure",
        "http error 5", "remote end closed", "connection reset", "broken pipe",
        "name resolution", "getaddrinfo failed", "network is unreachable",
    )):
        return "network"
    if any(token in text for token in ("private", "login", "forbidden", "unauthorized", "not available", "geo")):
        return "access"
    if "format" in text:
        return "format"
    return "unknown"


def adaptive_retry_profile(category: str) -> str:
    return "rate_limit_recovery" if category == "rate_limit" else "network_recovery"


def adaptive_retry_delay(category: str) -> float:
    if category == "rate_limit":
        return SMART_RATE_LIMIT_COOLDOWN_SECONDS
    if category == "stale_session":
        return SMART_STALE_SESSION_COOLDOWN_SECONDS
    return SMART_NETWORK_COOLDOWN_SECONDS


def is_adaptive_retryable(category: str) -> bool:
    return category in {"network", "rate_limit", "stale_session"}


def interruptible_wait(stop_event: threading.Event, seconds: float) -> bool:
    """Wait without busy looping. Return True when cancellation was requested."""
    return bool(stop_event.wait(max(0.0, float(seconds))))


def attach_safety_postprocessors(
    ydl: Any,
    settings: DownloadSettings,
    ui_queue: "queue.Queue[tuple[Any, ...]]",
    item_id: str,
    stop_event: threading.Event,
    telemetry: dict[str, Any],
) -> None:
    """Attach exact-format preflight and after-move verification to one yt-dlp run."""
    from yt_dlp.postprocessor import PostProcessor  # type: ignore
    from yt_dlp.utils import PostProcessingError  # type: ignore

    def emit(level: str, message: str) -> None:
        ui_queue.put(("log", level, message))

    class SmartPreflightPP(PostProcessor):
        def run(self, info: dict[str, Any]):
            if stop_event.is_set():
                raise DownloadCancelled("Cancelled by user")
            plan = build_download_plan(info, settings)
            disk = assess_disk_capacity(settings.output_dir, int(plan["required_free_bytes"]))
            plan["disk_preflight"] = disk
            telemetry["preflight"] = plan
            ui_queue.put(("job_result", item_id, {"preflight": plan}))
            emit(
                "info",
                "Smart preflight: formats " + ",".join(str(value) for value in plan.get("format_ids", []))
                + f"; estimated {format_bytes(plan.get('estimated_download_bytes'))}; disk {disk.get('status')}",
            )
            if plan.get("has_drm"):
                raise PostProcessingError("Selected media reports DRM/access control; this app will not attempt the download")
            if disk.get("status") == "insufficient":
                raise PostProcessingError(
                    f"Insufficient disk space: need about {format_bytes(disk.get('required_bytes'))}, have {format_bytes(disk.get('free_bytes'))}"
                )
            return [], info

    class FinalMediaVerificationPP(PostProcessor):
        def run(self, info: dict[str, Any]):
            if stop_event.is_set():
                raise DownloadCancelled("Cancelled by user")
            raw_path = info.get("filepath") or info.get("_filename")
            if not raw_path:
                raw_path = self._downloader.prepare_filename(info)
            final_path = Path(str(raw_path))
            verification = verify_media_file(final_path, settings, info)
            if verification.get("status") == "failed":
                telemetry["verification"] = verification
                ui_queue.put(("job_result", item_id, {"verification": verification}))
                emit("error", f"Final media verification failed: {verification.get('reason')}")
                raise PostProcessingError(f"Final media verification failed: {verification.get('reason')}")
            visibility = apply_media_visibility(final_path, settings.hide_media)
            verification["media_visibility"] = visibility
            telemetry["verification"] = verification
            telemetry["media_visibility"] = visibility
            duplicate_record = record_media_completion(info, settings, final_path, verification)
            telemetry["duplicate_detection"] = {"status": "new_media_recorded", "source": "verified_media_index", "index_update": duplicate_record}
            ui_queue.put(("job_result", item_id, {"verification": verification, "media_visibility": visibility, "duplicate_detection": telemetry["duplicate_detection"]}))
            level = "warning" if verification.get("status") in {"warning", "basic_ok"} else "info"
            emit(level, f"Final media verification: {verification.get('status')} via {verification.get('method')}")
            if visibility.get("status") == "failed":
                emit("warning", f"Media visibility could not be applied: {visibility.get('reason')}")
            elif visibility.get("status") != "not_applicable":
                emit("info", f"Final media visibility: {visibility.get('status')}")
            return [], info

    ydl.add_post_processor(SmartPreflightPP(), when="before_dl")
    ydl.add_post_processor(FinalMediaVerificationPP(), when="after_move")


def site_tolerance_path() -> Path:
    return state_dir() / "site-tolerance.json"


def site_tolerance_key(url: str) -> str:
    """Return a privacy-minimized stable key for one submitted site."""
    try:
        host = (urlsplit(str(url or "")).hostname or "").strip().lower().rstrip(".")
    except Exception:
        host = ""
    if host in YOUTUBE_HOSTS:
        host = "youtube.com"
    elif host.startswith("www."):
        host = host[4:]
    if not host:
        host = "unknown-site"
    return hashlib.sha256(host.encode("utf-8")).hexdigest()


def load_site_tolerance_state(*, path: Optional[Path] = None) -> dict[str, Any]:
    target = path or site_tolerance_path()
    if not target.is_file():
        return {"schema_version": SITE_TOLERANCE_SCHEMA_VERSION, "entries": {}, "status": "absent"}
    try:
        if target.stat().st_size > SITE_TOLERANCE_MAX_BYTES:
            return {"schema_version": SITE_TOLERANCE_SCHEMA_VERSION, "entries": {}, "status": "oversize_ignored"}
        payload = json.loads(target.read_text(encoding="utf-8"))
        schema = int(payload.get("schema_version", 0))
        if schema > SITE_TOLERANCE_SCHEMA_VERSION:
            return {"schema_version": schema, "entries": {}, "status": "newer_schema_read_only"}
        entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
        return {"schema_version": SITE_TOLERANCE_SCHEMA_VERSION, "entries": entries, "status": "ok"}
    except Exception as exc:
        return {
            "schema_version": SITE_TOLERANCE_SCHEMA_VERSION,
            "entries": {},
            "status": "invalid_ignored",
            "reason": redact_text(exc),
        }


def save_site_tolerance_state(entries: dict[str, Any], *, path: Optional[Path] = None) -> dict[str, Any]:
    target = path or site_tolerance_path()
    bounded_items = sorted(
        entries.items(),
        key=lambda item: str((item[1] or {}).get("updated_at_utc") or ""),
        reverse=True,
    )[:SITE_TOLERANCE_MAX_ENTRIES]
    payload = {
        "schema_version": SITE_TOLERANCE_SCHEMA_VERSION,
        "updated_at_utc": utc_now_iso(),
        "entry_count": len(bounded_items),
        "entries": dict(bounded_items),
    }
    data = safe_json_dumps(payload).encode("utf-8")
    if len(data) > SITE_TOLERANCE_MAX_BYTES:
        raise ValueError("site-tolerance state exceeds the bounded size limit")
    atomic_write_bytes(target, data)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return {"status": "written", "entry_count": len(bounded_items), "bytes": len(data)}


def site_tolerance_decision(url: str, settings: DownloadSettings, *, path: Optional[Path] = None) -> dict[str, Any]:
    """Choose a three- or five-fragment normal profile from bounded site history."""
    site_key = site_tolerance_key(url)
    payload = load_site_tolerance_state(path=path)
    entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
    entry = entries.get(site_key) if isinstance(entries.get(site_key), dict) else {}
    clean_successes = max(0, int(entry.get("clean_successes") or 0))
    cooldown = max(0, int(entry.get("cooldown_jobs_remaining") or 0))
    if settings.rate_limit_bytes is not None:
        limit = FRAGMENT_CONCURRENCY_RECOVERY
        tier = "manual_rate_cap"
        reason = "manual rate cap keeps fragment concurrency at one"
    elif payload.get("status") in {"newer_schema_read_only", "invalid_ignored", "oversize_ignored"}:
        limit = FRAGMENT_CONCURRENCY_CONSERVATIVE
        tier = "conservative"
        reason = "tolerance history is unavailable or read-only; fail-safe limit selected"
    elif cooldown > 0:
        limit = FRAGMENT_CONCURRENCY_CONSERVATIVE
        tier = "conservative"
        reason = "recent site stress keeps the conservative limit active"
    elif clean_successes >= SITE_TOLERANCE_PROMOTION_SUCCESSES:
        limit = FRAGMENT_CONCURRENCY_TOLERANT
        tier = "tolerant"
        reason = "site earned the five-fragment limit through clean completions"
    else:
        limit = FRAGMENT_CONCURRENCY_CONSERVATIVE
        tier = "conservative"
        reason = "new or unproven site starts at the three-fragment limit"
    return {
        "status": payload.get("status"),
        "policy": "auto_3_or_5",
        "tier": tier,
        "selected_fragment_limit": limit,
        "clean_successes": clean_successes,
        "promotion_after_clean_successes": SITE_TOLERANCE_PROMOTION_SUCCESSES,
        "cooldown_jobs_remaining": cooldown,
        "site_key_hash": site_key[:16],
        "site_identity_exported": False,
        "reason": reason,
    }


def update_site_tolerance(
    url: str,
    event: str,
    selected_fragment_limit: int,
    *,
    path: Optional[Path] = None,
) -> dict[str, Any]:
    """Atomically record a clean completion or one stress event for a site."""
    target = path or site_tolerance_path()
    site_key = site_tolerance_key(url)
    with _SITE_TOLERANCE_LOCK:
        payload = load_site_tolerance_state(path=target)
        if payload.get("status") == "newer_schema_read_only":
            return {"status": "newer_schema_read_only", "updated": False}
        entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
        entry = entries.get(site_key) if isinstance(entries.get(site_key), dict) else {}
        clean_successes = max(0, int(entry.get("clean_successes") or 0))
        stress_events = max(0, int(entry.get("stress_events") or 0))
        cooldown = max(0, int(entry.get("cooldown_jobs_remaining") or 0))
        if event in {"rate_limit", "network", "stale_session"}:
            stress_events += 1
            clean_successes = 0
            cooldown_target = (
                SITE_TOLERANCE_RATE_LIMIT_COOLDOWN_JOBS
                if event == "rate_limit"
                else SITE_TOLERANCE_NETWORK_COOLDOWN_JOBS
            )
            cooldown = max(cooldown, cooldown_target)
        elif event == "clean_success":
            if cooldown > 0:
                cooldown -= 1
            if cooldown <= 0:
                clean_successes = min(100, clean_successes + 1)
        elif event == "recovered_after_stress":
            pass
        else:
            return {"status": "ignored", "updated": False, "reason": "unsupported event"}
        entries[site_key] = {
            "clean_successes": clean_successes,
            "stress_events": stress_events,
            "cooldown_jobs_remaining": cooldown,
            "last_event": event,
            "last_fragment_limit": int(selected_fragment_limit),
            "updated_at_utc": utc_now_iso(),
        }
        try:
            written = save_site_tolerance_state(entries, path=target)
        except Exception as exc:
            return {"status": "not_recorded", "updated": False, "reason": redact_text(exc)}
    return {
        "status": written.get("status"),
        "updated": True,
        "event": event,
        "clean_successes": clean_successes,
        "stress_events": stress_events,
        "cooldown_jobs_remaining": cooldown,
        "next_normal_fragment_limit": (
            FRAGMENT_CONCURRENCY_TOLERANT
            if cooldown <= 0 and clean_successes >= SITE_TOLERANCE_PROMOTION_SUCCESSES
            else FRAGMENT_CONCURRENCY_CONSERVATIVE
        ),
        "site_key_hash": site_key[:16],
    }


def site_tolerance_summary(*, path: Optional[Path] = None) -> dict[str, Any]:
    payload = load_site_tolerance_state(path=path)
    entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
    tolerant = 0
    conservative = 0
    cooldown = 0
    for value in entries.values():
        if not isinstance(value, dict):
            continue
        clean = max(0, int(value.get("clean_successes") or 0))
        pending = max(0, int(value.get("cooldown_jobs_remaining") or 0))
        if pending > 0:
            cooldown += 1
            conservative += 1
        elif clean >= SITE_TOLERANCE_PROMOTION_SUCCESSES:
            tolerant += 1
        else:
            conservative += 1
    target = path or site_tolerance_path()
    summary: dict[str, Any] = {
        "status": payload.get("status"),
        "schema_version": payload.get("schema_version"),
        "entry_count": len(entries),
        "tolerant_site_count": tolerant,
        "conservative_site_count": conservative,
        "cooldown_site_count": cooldown,
        "policy": "new sites=3; proven tolerant sites=5; recovery/manual rate cap=1",
        "promotion_after_clean_successes": SITE_TOLERANCE_PROMOTION_SUCCESSES,
        "max_entries": SITE_TOLERANCE_MAX_ENTRIES,
        "site_names_exported": False,
        "site_hashes_exported": False,
        "path_redacted": redact_path(target),
    }
    if target.is_file():
        try:
            summary["bytes"] = target.stat().st_size
            summary["hash"] = sha256_file(target)
        except OSError:
            pass
    return summary


def media_index_path() -> Path:
    return state_dir() / "media-index.json"


def duplicate_variant_key(settings: DownloadSettings) -> str:
    """Different requested output variants are not treated as duplicates."""
    if settings.mode == "Audio (MP3)":
        core = "audio-mp3"
    elif settings.mode == "Audio (original/best)":
        core = "audio-original"
    elif settings.mode.startswith("Custom"):
        digest = hashlib.sha256(settings.custom_format.encode("utf-8")).hexdigest()[:12]
        core = f"custom-{digest}"
    else:
        core = f"video-{settings.max_height or 'best'}-{'mp4' if settings.prefer_mp4 else 'native'}"
    return f"{core}-meta{int(settings.embed_metadata)}-subs{int(settings.write_subtitles)}"


def media_identity_key(info: dict[str, Any], settings: DownloadSettings) -> Optional[str]:
    media_id = str(info.get("id") or "").strip()
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").strip().lower()
    if not media_id or not extractor:
        return None
    try:
        output_identity = str(settings.output_dir.resolve(strict=False)).casefold()
    except Exception:
        output_identity = str(settings.output_dir).casefold()
    raw = "|".join((output_identity, extractor, media_id, duplicate_variant_key(settings)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def download_archive_path(settings: DownloadSettings) -> Path:
    """Return a project-local archive scoped to the requested output variant."""
    safe_variant = re.sub(r"[^A-Za-z0-9._-]+", "-", duplicate_variant_key(settings)).strip("-") or "default"
    return state_dir() / f"download-archive-{safe_variant}.txt"


def prepare_download_archive(settings: DownloadSettings) -> dict[str, Any]:
    """Create a variant archive target and conservatively import the legacy default archive."""
    target = download_archive_path(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return {"status": "existing", "path": target}
    default_variant = "video-1080-mp4-meta1-subs0"
    legacy = settings.output_dir / "download-archive.txt"
    if duplicate_variant_key(settings) == default_variant and legacy.is_file():
        try:
            data = legacy.read_bytes()
            if len(data) <= 10 * 1024 * 1024:
                atomic_write_bytes(target, data)
                return {"status": "legacy_default_imported", "path": target, "legacy_path": legacy}
        except Exception as exc:
            return {"status": "legacy_import_failed", "path": target, "reason": redact_text(exc)}
    return {"status": "new_variant_archive", "path": target}


def load_media_index(*, path: Optional[Path] = None) -> dict[str, Any]:
    target = path or media_index_path()
    if not target.is_file():
        return {"schema_version": MEDIA_INDEX_SCHEMA_VERSION, "entries": {}, "status": "absent"}
    try:
        if target.stat().st_size > MEDIA_INDEX_MAX_BYTES:
            return {"schema_version": MEDIA_INDEX_SCHEMA_VERSION, "entries": {}, "status": "oversize_ignored"}
        payload = json.loads(target.read_text(encoding="utf-8"))
        if int(payload.get("schema_version", 0)) > MEDIA_INDEX_SCHEMA_VERSION:
            return {"schema_version": payload.get("schema_version"), "entries": {}, "status": "newer_schema_read_only"}
        entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
        return {"schema_version": MEDIA_INDEX_SCHEMA_VERSION, "entries": entries, "status": "ok"}
    except Exception as exc:
        return {"schema_version": MEDIA_INDEX_SCHEMA_VERSION, "entries": {}, "status": "invalid_ignored", "reason": redact_text(exc)}


def save_media_index(entries: dict[str, Any], *, path: Optional[Path] = None) -> dict[str, Any]:
    target = path or media_index_path()
    bounded_items = sorted(
        entries.items(),
        key=lambda item: str((item[1] or {}).get("completed_at_utc") or ""),
        reverse=True,
    )[:MEDIA_INDEX_MAX_ENTRIES]
    payload = {
        "schema_version": MEDIA_INDEX_SCHEMA_VERSION,
        "updated_at_utc": utc_now_iso(),
        "entry_count": len(bounded_items),
        "entries": dict(bounded_items),
    }
    data = safe_json_dumps(payload).encode("utf-8")
    if len(data) > MEDIA_INDEX_MAX_BYTES:
        raise ValueError("media duplicate index exceeded its bounded size")
    atomic_write_bytes(target, data)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return {"status": "written", "entry_count": len(bounded_items), "bytes": len(data)}


def detect_indexed_duplicate(info: dict[str, Any], settings: DownloadSettings) -> dict[str, Any]:
    """Check a verified local identity record; stale entries fail open and repair."""
    if not settings.use_archive:
        return {"status": "disabled", "source": "media_index"}
    identity = media_identity_key(info, settings)
    if not identity:
        return {"status": "identity_unavailable", "source": "media_index"}
    with _MEDIA_INDEX_LOCK:
        payload = load_media_index()
        if payload.get("status") == "newer_schema_read_only":
            return {"status": "newer_schema_read_only", "source": "media_index", "identity_hash": identity[:16]}
        entries = dict(payload.get("entries") or {})
        record = entries.get(identity)
        if not isinstance(record, dict):
            return {"status": "not_found", "source": "media_index", "identity_hash": identity[:16], "index_status": payload.get("status")}
        relative = str(record.get("relative_path") or "")
        candidate = settings.output_dir / relative
        try:
            valid = bool(relative) and candidate.is_file() and candidate.stat().st_size > 0
        except Exception:
            valid = False
        if valid:
            return {
                "status": "duplicate",
                "source": "verified_media_index",
                "identity_hash": identity[:16],
                "existing_file_redacted": redact_path(candidate),
                "recorded_verification": record.get("verification_status"),
            }
        entries.pop(identity, None)
        try:
            save_media_index(entries)
        except Exception:
            pass
        return {"status": "stale_entry_repaired", "source": "media_index", "identity_hash": identity[:16]}


def record_media_completion(info: dict[str, Any], settings: DownloadSettings, final_path: Path, verification: dict[str, Any]) -> dict[str, Any]:
    if not settings.use_archive:
        return {"status": "disabled"}
    identity = media_identity_key(info, settings)
    if not identity:
        return {"status": "identity_unavailable"}
    try:
        relative = final_path.resolve().relative_to(settings.output_dir.resolve()).as_posix()
        size = int(final_path.stat().st_size)
    except Exception as exc:
        return {"status": "not_recorded", "reason": redact_text(exc)}
    with _MEDIA_INDEX_LOCK:
        payload = load_media_index()
        if payload.get("status") == "newer_schema_read_only":
            return {"status": "not_recorded_newer_schema", "identity_hash": identity[:16]}
        entries = dict(payload.get("entries") or {})
        entries[identity] = {
            "relative_path": relative,
            "size_bytes": size,
            "verification_status": verification.get("status"),
            "variant": duplicate_variant_key(settings),
            "completed_at_utc": utc_now_iso(),
        }
        try:
            written = save_media_index(entries)
        except Exception as exc:
            return {"status": "not_recorded", "reason": redact_text(exc)}
    return {"status": "recorded", "identity_hash": identity[:16], "entry_count": written.get("entry_count")}


def media_index_summary() -> dict[str, Any]:
    payload = load_media_index()
    entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
    target = media_index_path()
    summary = {
        "status": payload.get("status"),
        "schema_version": payload.get("schema_version"),
        "entries": len(entries),
        "max_entries": MEDIA_INDEX_MAX_ENTRIES,
        "contents_exported": False,
        "path_redacted": redact_path(target),
    }
    if target.is_file():
        summary["bytes"] = target.stat().st_size
        summary["hash"] = sha256_file(target)
    return summary


def queue_recovery_path() -> Path:
    return state_dir() / "queue-recovery.json"


def save_queue_recovery(jobs: list[dict[str, Any]], settings: dict[str, Any], *, path: Optional[Path] = None, reason: str = "state_change") -> dict[str, Any]:
    """Atomically save only unfinished queue work and UI settings."""
    target = path or queue_recovery_path()
    unfinished = []
    for job in jobs[:QUEUE_CAPACITY]:
        status = str(job.get("status", "Queued"))
        url = str(job.get("url", "")).strip()
        if status in {"Done", "Skipped duplicate", "Cancelled", "Failed"} or not URL_RE.match(url):
            continue
        unfinished.append({"item_id": str(job.get("item_id", "")), "url": url, "status": status, "result": {}})
    if not unfinished:
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass
        return {"status": "cleared", "count": 0, "path": str(target)}
    payload = {
        "schema_version": QUEUE_STATE_SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "saved_at_utc": utc_now_iso(),
        "reason": str(reason),
        "privacy_note": "Local recovery state contains full queued URLs and output settings. Diagnostic export reports summary only.",
        "settings": dict(settings),
        "jobs": unfinished,
    }
    encoded = safe_json_dumps(payload).encode("utf-8")
    if len(encoded) > QUEUE_RECOVERY_MAX_BYTES:
        raise ValueError("queue recovery state exceeds the 1 MiB safety limit")
    atomic_write_bytes(target, encoded)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return {"status": "saved", "count": len(unfinished), "path": str(target), "bytes": len(encoded)}


def load_queue_recovery(*, path: Optional[Path] = None) -> dict[str, Any]:
    target = path or queue_recovery_path()
    if not target.exists():
        return {"status": "absent", "jobs": [], "settings": {}, "path": str(target)}
    try:
        if target.stat().st_size > QUEUE_RECOVERY_MAX_BYTES:
            return {"status": "rejected_oversize", "jobs": [], "settings": {}, "path": str(target)}
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("recovery root is not an object")
        schema = int(payload.get("schema_version", 0))
        if schema > QUEUE_STATE_SCHEMA_VERSION:
            return {"status": "newer_schema", "schema_version": schema, "jobs": [], "settings": {}, "path": str(target)}
        if schema != QUEUE_STATE_SCHEMA_VERSION:
            return {"status": "unsupported_schema", "schema_version": schema, "jobs": [], "settings": {}, "path": str(target)}
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in payload.get("jobs", [])[:QUEUE_CAPACITY]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not URL_RE.match(url) or url in seen:
                continue
            seen.add(url)
            jobs.append({"item_id": str(item.get("item_id") or f"recovered{len(jobs)+1}"), "url": url, "status": "Queued", "result": {"recovered_from_status": str(item.get("status", "unknown"))}})
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        return {"status": "loaded", "schema_version": schema, "saved_at_utc": payload.get("saved_at_utc"), "jobs": jobs, "settings": settings, "path": str(target)}
    except Exception as exc:
        return {"status": "corrupt", "reason": redact_text(exc), "jobs": [], "settings": {}, "path": str(target)}


def queue_recovery_diagnostic_summary() -> dict[str, Any]:
    target = queue_recovery_path()
    loaded = load_queue_recovery(path=target)
    summary: dict[str, Any] = {
        "status": loaded.get("status"),
        "schema_version": loaded.get("schema_version"),
        "recoverable_job_count": len(loaded.get("jobs", [])),
        "full_urls_exported": False,
        "path": redact_path(target),
        "max_bytes": QUEUE_RECOVERY_MAX_BYTES,
    }
    try:
        if target.exists():
            summary.update({"bytes": target.stat().st_size, "modified_utc": datetime.fromtimestamp(target.stat().st_mtime, timezone.utc).isoformat(), "sha256": sha256_file(target).get("sha256")})
    except Exception as exc:
        summary["metadata_warning"] = redact_text(exc)
    return summary




def build_format_selector(settings: DownloadSettings) -> str:
    """Return a yt-dlp format selector for the selected mode.

    When FFmpeg is missing, avoid selectors containing '+'. A '+' selector asks
    yt-dlp to download separate streams and merge them, which fails without
    FFmpeg. The fallback is a single-file format, usually lower quality but much
    more reliable on a fresh Windows install.
    """
    mode = settings.mode
    custom = settings.custom_format.strip()
    if mode.startswith("Custom"):
        if not custom:
            raise ValueError("Custom format mode requires a format selector.")
        return custom

    if mode.startswith("Audio"):
        return "bestaudio/best"

    height_filter = f"[height<={settings.max_height}]" if settings.max_height else ""
    has_ffmpeg = bool(settings.ffmpeg_location)

    if not has_ffmpeg:
        if settings.prefer_mp4:
            return f"b{height_filter}[ext=mp4]/best{height_filter}[ext=mp4]/b{height_filter}/best"
        return f"b{height_filter}/best"

    if settings.prefer_mp4:
        return (
            f"bv*{height_filter}[ext=mp4]+ba[ext=m4a]/"
            f"b{height_filter}[ext=mp4]/"
            f"bv*{height_filter}+ba/"
            f"b{height_filter}/best"
        )
    return f"bv*{height_filter}+ba/b{height_filter}/best"


def dependency_warnings(settings: DownloadSettings) -> list[str]:
    """Human-readable warnings for options that degrade without helpers."""
    warnings: list[str] = []
    if not settings.ffmpeg_location:
        if settings.mode.startswith("Video"):
            warnings.append("FFmpeg was not detected, so video downloads will use a single-file fallback instead of separate best video/audio streams. Install FFmpeg for higher-quality merges.")
        if settings.mode == "Audio (MP3)":
            warnings.append("FFmpeg was not detected, so MP3 conversion will be skipped and the best original audio file will be saved instead.")
        if settings.embed_metadata:
            warnings.append("FFmpeg was not detected, so metadata embedding will be skipped.")
        if settings.write_subtitles:
            warnings.append("FFmpeg was not detected, so subtitles can be written as sidecar files but will not be embedded.")
        if settings.mode.startswith("Custom") and "+" in settings.custom_format:
            warnings.append("The custom format selector contains '+', which normally requires FFmpeg for merging.")
    js = javascript_runtime_snapshot(execute_versions=True)
    selected = js.get("selected")
    if not selected:
        warnings.append("No supported JavaScript runtime was detected. Install Deno 2.3+ (recommended) or Node 22+, or place the executable in the tools folder.")
    unverified = [item for item in js.get("candidates", []) if item.get("status") == "detected_unverified"]
    for item in unverified:
        warnings.append(f"{item.get('name')} was found but its version could not be verified, so it will not be selected until its local --version probe succeeds.")
    unsupported = [item for item in js.get("candidates", []) if item.get("status") == "unsupported_version"]
    for item in unsupported:
        warnings.append(f"{item.get('name')} is below the supported minimum {'.'.join(map(str, item.get('minimum', [])))} and will not be selected.")
    return warnings



def settings_to_export(settings: DownloadSettings) -> dict[str, Any]:
    return {
        "output_dir": str(settings.output_dir),
        "mode": settings.mode,
        "max_height": settings.max_height,
        "custom_format": settings.custom_format,
        "include_playlist": settings.include_playlist,
        "embed_metadata": settings.embed_metadata,
        "write_subtitles": settings.write_subtitles,
        "restrict_filenames": settings.restrict_filenames,
        "use_archive": settings.use_archive,
        "duplicate_detection": {"enabled": settings.use_archive, "layers": ["canonical queue URL", "yt-dlp download archive", "verified local media index", "no-overwrite output guard"]},
        "rate_limit_bytes": settings.rate_limit_bytes,
        "prefer_mp4": settings.prefer_mp4,
        "ffmpeg_location": settings.ffmpeg_location,
        "hide_media": settings.hide_media,
        "smart_resilience": settings.smart_resilience,
        "format_selector": build_format_selector(settings),
    }


def dependency_snapshot() -> dict[str, Any]:
    js = javascript_runtime_snapshot(execute_versions=False)
    return {
        "tools_dir": str(tools_dir()),
        "ffmpeg_location": find_ffmpeg_location(),
        "ffprobe_path": str(find_executable("ffprobe")) if find_executable("ffprobe") else None,
        "javascript_runtime": js,
        "retry_policy": retry_policy_snapshot(smart_resilience=SMART_RESILIENCE_DEFAULT),
        "smart_preflight": {"enabled": True, "disk_reserve_bytes": PREFLIGHT_DISK_RESERVE_BYTES, "drm_fail_closed": True},
        "final_media_verification": {"enabled": True, "ffprobe_timeout_seconds": FFPROBE_TIMEOUT_SECONDS, "basic_fallback": True},
        "media_visibility": {"default_hidden_on_windows": HIDE_MEDIA_DEFAULT, "scope": "final downloaded media files only", "failure_policy": "warn and keep download successful"},
        "duplicate_detection": {"default_enabled": True, "media_index_schema": MEDIA_INDEX_SCHEMA_VERSION, "max_entries": MEDIA_INDEX_MAX_ENTRIES, "archive_file": "state/download-archive-<output-variant>.txt", "false_positive_guard": "mode/height/custom format/metadata/subtitle variant included in identity"},
        "cancellation": {
            "isolated_worker_process": True,
            "graceful_then_hard_stop": True,
            "hard_stop_after_seconds": CANCEL_GRACE_SECONDS,
            "second_click_force_stop": True,
            "process_tree_scope": "yt-dlp worker plus helper processes; GUI remains alive",
            "partial_resume_preserved": True,
        },
        "adaptive_resilience": {
            "default_enabled": SMART_RESILIENCE_DEFAULT,
            "outer_attempts": SMART_OUTER_ATTEMPTS,
            "session_rebuild": "new YoutubeDL session after bounded transient failure; existing .part files resume",
            "smart_throttled_rate_bytes": SMART_THROTTLED_RATE_BYTES,
            "profiles": ["normal", "network_recovery", "rate_limit_recovery"],
            "fragment_tolerance": {
                "normal_limits": [FRAGMENT_CONCURRENCY_CONSERVATIVE, FRAGMENT_CONCURRENCY_TOLERANT],
                "recovery_limit": FRAGMENT_CONCURRENCY_RECOVERY,
                "promotion_after_clean_successes": SITE_TOLERANCE_PROMOTION_SUCCESSES,
                "persistent_summary": site_tolerance_summary(),
            },
        },
    }



def gui_runtime_snapshot(*, create_window: bool = False) -> dict[str, Any]:
    """Inspect Tkinter and optionally prove that a real hidden Tk window can open.

    Diagnostics use import-only mode so export remains noninteractive. The Command
    Center uses create_window=True before GUI launch to catch Tcl/Tk/display issues
    with a precise, bounded failure message instead of silently returning to menu.
    """
    snapshot: dict[str, Any] = {
        "status": "unavailable",
        "tkinter_import_available": tk is not None and TK_IMPORT_ERROR is None,
        "tkinter_error": redact_text(TK_IMPORT_ERROR) if TK_IMPORT_ERROR is not None else None,
        "python_version": platform.python_version(),
        "python_executable": redact_path(sys.executable),
        "tk_version": getattr(tk, "TkVersion", None) if tk is not None else None,
        "tcl_version": getattr(tk, "TclVersion", None) if tk is not None else None,
        "window_probe_attempted": bool(create_window),
        "window_probe_success": False,
        "window_probe_error": None,
    }
    if tk is None or TK_IMPORT_ERROR is not None:
        return snapshot
    if not create_window:
        snapshot["status"] = "import_available"
        return snapshot
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        snapshot["status"] = "ok"
        snapshot["window_probe_success"] = True
    except Exception as exc:
        snapshot["status"] = "window_probe_failed"
        snapshot["window_probe_error"] = redact_text(exc)
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
    return snapshot


def csv_safe(value: Any) -> str:
    """Prevent spreadsheet formula injection in exported CSV cells."""
    text = "" if value is None else str(value)
    if text.startswith(CSV_FORMULA_PREFIXES):
        return "'" + text
    return text


def jobs_to_csv_rows(jobs: list[dict[str, Any]]) -> list[list[str]]:
    rows = [["item_id", "status", "url", "media_id", "format_ids", "estimated_bytes", "verification", "error_category", "elapsed_seconds"]]
    for job in jobs:
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        preflight = result.get("preflight") if isinstance(result.get("preflight"), dict) else {}
        verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
        rows.append([
            csv_safe(job.get("item_id", "")), csv_safe(job.get("status", "")), csv_safe(job.get("url", "")),
            csv_safe(preflight.get("media_id", "")), csv_safe(",".join(str(v) for v in preflight.get("format_ids", []) if v is not None)),
            csv_safe(preflight.get("estimated_download_bytes", "")), csv_safe(verification.get("status", "")),
            csv_safe(result.get("error_category", "")), csv_safe(result.get("elapsed_seconds", "")),
        ])
    return rows



def rows_to_csv_text(rows: list[list[str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerows(rows)
    return buffer.getvalue()


def logs_to_text(logs: list[dict[str, Any]]) -> str:
    if not logs:
        return "No log entries were captured.\n"
    lines: list[str] = []
    for entry in logs:
        timestamp = entry.get("timestamp_local") or entry.get("timestamp_utc") or ""
        level = str(entry.get("level", "info")).upper()
        message = str(entry.get("message", ""))
        lines.append(f"{timestamp} [{level}] {message}")
    return "\n".join(lines) + "\n"


def make_log_entry(run_id: str, level: str, message: str) -> dict[str, str]:
    """Create one centrally timestamped, run-ID tagged log record."""
    return {
        "timestamp_local": chicago_now().strftime("%Y-%m-%d %H:%M:%S %z %Z"),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": str(run_id),
        "level": str(level or "info"),
        "message": str(message),
    }


def append_persistent_log_entry(path: Path, entry: dict[str, Any]) -> None:
    """Append a redacted single-line record. Logging failure must not break the app."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        level = str(entry.get("level", "info")).lower()
        prefix = {"info": "[info]", "warning": "[warn]", "error": "[error]", "debug": "[debug]"}.get(level, "[info]")
        line = f"{entry.get('timestamp_local', '')} {prefix} [run {redact_text(entry.get('run_id', ''))}] {redact_text(entry.get('message', ''))}"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def prune_old_logs(max_files: int = LOG_RETENTION_MAX_FILES, max_bytes: int = LOG_RETENTION_MAX_BYTES) -> dict[str, Any]:
    """Cap log growth by removing oldest generated logs and truncating oversized latest tails."""
    summary = {"status": "ok", "removed_files": 0, "truncated_files": 0, "max_files": max_files, "max_bytes_per_file": max_bytes}
    try:
        logs_dir().mkdir(parents=True, exist_ok=True)
        candidates = sorted(logs_dir().glob("SafeVideoDownloader-*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old_path in candidates[max_files:]:
            try:
                old_path.unlink()
                summary["removed_files"] += 1
            except Exception:
                continue
        for log_path in candidates[:max_files]:
            try:
                size = log_path.stat().st_size
                if size > max_bytes:
                    data = log_path.read_bytes()[-max_bytes:]
                    atomic_write_bytes(log_path, b"[log truncated to newest retained bytes]\n" + data)
                    summary["truncated_files"] += 1
            except Exception:
                continue
    except Exception as exc:
        summary = {"status": "unavailable", "reason": redact_text(exc), "max_files": max_files, "max_bytes_per_file": max_bytes}
    return summary


def summarize_export_jobs(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a compact, deterministic integrity ledger for normal reports."""
    status_counts: dict[str, int] = {}
    error_categories: dict[str, int] = {}
    preflight_count = 0
    verification_counts: dict[str, int] = {}
    duplicate_counts: dict[str, int] = {}
    elapsed_total = 0.0
    for job in jobs:
        status = str(job.get("status") or "Unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        if isinstance(result.get("preflight"), dict):
            preflight_count += 1
        verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
        verification_status = str(verification.get("status") or "not_recorded")
        verification_counts[verification_status] = verification_counts.get(verification_status, 0) + 1
        duplicate = result.get("duplicate_detection") if isinstance(result.get("duplicate_detection"), dict) else {}
        duplicate_status = str(duplicate.get("status") or "not_recorded")
        duplicate_counts[duplicate_status] = duplicate_counts.get(duplicate_status, 0) + 1
        error_category = str(result.get("error_category") or "").strip()
        if error_category:
            error_categories[error_category] = error_categories.get(error_category, 0) + 1
        try:
            elapsed_total += max(0.0, float(result.get("elapsed_seconds") or 0.0))
        except (TypeError, ValueError):
            pass
    terminal_states = {"Done", "Skipped duplicate", "Failed", "Cancelled"}
    successful_states = {"Done", "Skipped duplicate"}
    if not jobs:
        terminal_status = "empty"
    elif all(str(job.get("status")) in terminal_states for job in jobs):
        terminal_status = "completed_with_errors" if any(str(job.get("status")) not in successful_states for job in jobs) else "completed"
    elif any(str(job.get("status")) in {"Downloading", "Processing"} for job in jobs):
        terminal_status = "running"
    else:
        terminal_status = "planned_or_queued"
    return {
        "terminal_status": terminal_status,
        "job_count": len(jobs),
        "status_counts": dict(sorted(status_counts.items())),
        "preflight_recorded": preflight_count,
        "verification_counts": dict(sorted(verification_counts.items())),
        "duplicate_detection_counts": dict(sorted(duplicate_counts.items())),
        "error_categories": dict(sorted(error_categories.items())),
        "job_elapsed_seconds_total": round(elapsed_total, 3),
    }


def build_export_snapshot(
    jobs: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    settings: dict[str, Any],
    dependencies: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    report_fingerprint = hashlib.sha256(
        safe_json_dumps({"jobs": jobs, "settings": settings, "generated_at_utc": now.isoformat()}).encode("utf-8")
    ).hexdigest()[:10].upper()
    report_asset_id = f"SVD-REPORT-{now.strftime('%Y%m%dT%H%M%SZ')}-{report_fingerprint}"
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "export_kind": "general_report_nonredacted",
        "asset_metadata": {
            "metadata_schema": ASSET_METADATA_SCHEMA_VERSION,
            "asset_id": report_asset_id,
            "title": f"{APP_NAME} Operational Report",
            "asset_class": "operational-report",
            "role": "run-evidence",
            "project_slug": PROJECT_SLUG,
            "version": APP_VERSION,
            "status": "generated",
            "sensitivity": "sensitive",
            "source_of_truth": False,
            "tags": ["safe-video-downloader", "operational-report", "queue", "run-evidence"],
            "aliases": ["download report", "queue export"],
            "lineage": "derived from the current in-memory queue, settings, dependency snapshot, and logs",
        },
        "privacy_note": "This report may contain queued URLs, statuses, local folder paths, dependency paths, and application logs. It does not include downloaded media, cookies, passwords, or browser credentials.",
        "app": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "run_summary": summarize_export_jobs(jobs),
        "settings": settings,
        "dependencies": dependencies,
        "jobs": jobs,
        "logs": logs,
    }


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        with tmp.open("wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def write_export_json(path: Path, snapshot: dict[str, Any]) -> None:
    data = json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")
    atomic_write_bytes(path, data)


def write_export_csv(path: Path, snapshot: dict[str, Any]) -> None:
    text = rows_to_csv_text(jobs_to_csv_rows(list(snapshot.get("jobs", []))))
    atomic_write_bytes(path, text.encode("utf-8-sig"))


def write_export_log(path: Path, snapshot: dict[str, Any]) -> None:
    atomic_write_bytes(path, logs_to_text(list(snapshot.get("logs", []))).encode("utf-8"))


def _zip_member_name_is_safe(name: str) -> bool:
    normalized = name.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    return bool(parts) and not normalized.startswith("/") and ":" not in parts[0] and ".." not in parts


def sha256_file(path: Path, *, max_bytes: int = MAX_HASH_BYTES) -> dict[str, Any]:
    try:
        path = path.resolve()
        size = path.stat().st_size
        if size > max_bytes:
            return {"available": False, "reason": f"skipped because file is larger than {max_bytes} bytes", "size_bytes": size}
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return {"available": True, "sha256": h.hexdigest(), "size_bytes": size}
    except Exception as exc:
        return {"available": False, "reason": str(exc)}


def atomic_write_zip_entries(
    path: Path,
    entries: list[tuple[str, bytes | str]],
    *,
    max_files: Optional[int] = None,
    zip_comment: Optional[str] = None,
) -> dict[str, Any]:
    """Write a ZIP through a same-folder temp file, verify it, then replace atomically."""
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if max_files is not None and len(entries) > max_files:
        raise ValueError(f"Refusing to write {len(entries)} files; diagnostic cap is {max_files} files.")
    member_names = [name for name, _payload in entries]
    if len(member_names) != len(set(member_names)):
        duplicates = sorted({name for name in member_names if member_names.count(name) > 1})
        raise ValueError(f"Duplicate ZIP member name(s) refused: {duplicates}")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            if zip_comment:
                archive.comment = str(zip_comment).encode("utf-8")[:65535]
            for member_name, payload in entries:
                if not _zip_member_name_is_safe(member_name):
                    raise ValueError(f"Unsafe ZIP member name: {member_name!r}")
                data = payload.encode("utf-8") if isinstance(payload, str) else payload
                archive.writestr(member_name, data)
        with zipfile.ZipFile(tmp, "r") as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise IOError(f"ZIP integrity check failed at member: {bad_member}")
            names = archive.namelist()
            if max_files is not None and len(names) > max_files:
                raise ValueError(f"ZIP entry count {len(names)} exceeds cap {max_files}")
        os.replace(tmp, path)
        return {
            "path": str(path),
            "entry_count": len(entries),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path, max_bytes=10 * 1024 * 1024 * 1024).get("sha256"),
        }
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def write_export_zip(path: Path, snapshot: dict[str, Any]) -> None:
    json_text = json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True)
    csv_text = rows_to_csv_text(jobs_to_csv_rows(list(snapshot.get("jobs", []))))
    log_text = logs_to_text(list(snapshot.get("logs", [])))
    metadata = snapshot.get("asset_metadata", {}) if isinstance(snapshot.get("asset_metadata"), dict) else {}
    readme = (
        f"{APP_NAME} export report\n"
        f"Asset ID: {metadata.get('asset_id', 'unavailable')}\n"
        f"Version/status: {metadata.get('version', APP_VERSION)} / {metadata.get('status', 'generated')}\n"
        f"Sensitivity: {metadata.get('sensitivity', 'sensitive')}\n"
        f"Generated UTC: {snapshot.get('generated_at_utc', '')}\n\n"
        "Files included:\n"
        "- report.json: full structured export\n"
        "- queue.csv: queue/status export safe for spreadsheets\n"
        "- log.txt: plain-text application log\n\n"
        "Privacy note: this export may include queued URLs and local folder paths. It does not include downloaded media, cookies, passwords, or browser credentials.\n"
    )
    atomic_write_zip_entries(
        path,
        [
            ("report.json", json_text),
            ("queue.csv", csv_text.encode("utf-8-sig")),
            ("log.txt", log_text),
            ("README-export.txt", readme),
        ],
        zip_comment=(
            f"asset_id={metadata.get('asset_id', 'SVD-REPORT')};"
            f"project={PROJECT_SLUG};version={APP_VERSION};status=generated;"
            "tags=operational-report,queue,run-evidence;manifest=report.json"
        ),
    )


def write_export_by_suffix(path: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Write a normal report using the destination suffix, matching GUI and CLI behavior."""
    path = path.expanduser()
    if not path.suffix:
        path = path.with_suffix(".zip")
    suffix = path.suffix.lower()
    if suffix == ".json":
        write_export_json(path, snapshot)
        export_type = "json"
    elif suffix == ".csv":
        write_export_csv(path, snapshot)
        export_type = "csv"
    elif suffix == ".txt":
        write_export_log(path, snapshot)
        export_type = "log"
    else:
        write_export_zip(path, snapshot)
        export_type = "zip"
    return {"path": str(path.resolve()), "type": export_type, "sha256": sha256_file(path, max_bytes=10 * 1024 * 1024 * 1024).get("sha256"), "size_bytes": path.stat().st_size if path.exists() else None}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def chicago_now() -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("America/Chicago"))
        except Exception:
            pass
    return datetime.now().astimezone()


def windows_safe_timestamp() -> str:
    dt = chicago_now()
    zone = re.sub(r"[^A-Za-z0-9_-]+", "-", dt.strftime("%Z") or "local").strip("-") or "local"
    return f"{dt.strftime('%Y%m%d-%H%M%S')}-{zone}"


def default_diagnostic_zip_path() -> Path:
    return diagnostics_dir() / f"SafeVideoDownloader-diagnostics-{windows_safe_timestamp()}.zip"


def make_run_id(prefix: str = "svd") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"


def safe_filename_token(value: str, *, limit: int = 60) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-") or "run"
    return token[:limit]


def default_run_log_path(component: str, run_id: str) -> Path:
    return logs_dir() / f"SafeVideoDownloader-{safe_filename_token(component)}-{windows_safe_timestamp()}-{safe_filename_token(run_id, limit=40)}.log"


def latest_persistent_log_tail(max_lines: int = DIAGNOSTIC_LOG_TAIL_LIMIT) -> str:
    try:
        candidates = sorted(logs_dir().glob("SafeVideoDownloader-*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
    except Exception:
        return ""
    for path in candidates[:3]:
        try:
            data = path.read_bytes()[-256 * 1024 :]
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()[-max_lines:]
            if lines:
                return "\n".join(redact_text(line) for line in lines) + "\n"
        except Exception:
            continue
    return ""


def pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if platform.system() == "Windows":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def process_start_signature(pid: int) -> Optional[str]:
    """Return a stable process-start signature when the OS exposes one.

    PID liveness alone is insufficient because PIDs can be reused. The lock
    guard uses this signature when available and otherwise fails conservatively.
    """
    if pid <= 0:
        return None
    if platform.system() == "Windows":
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return None
            try:
                creation = wintypes.FILETIME()
                exit_time = wintypes.FILETIME()
                kernel = wintypes.FILETIME()
                user = wintypes.FILETIME()
                ok = ctypes.windll.kernel32.GetProcessTimes(
                    handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)
                )
                if not ok:
                    return None
                value = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
                return f"windows-filetime:{value}"
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return None
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        text = proc_stat.read_text(encoding="utf-8", errors="replace")
        end_comm = text.rfind(")")
        if end_comm < 0:
            return None
        fields_after_comm = text[end_comm + 2 :].split()
        # /proc/<pid>/stat field 22 (starttime); field 3 is index 0 here.
        start_ticks = fields_after_comm[19]
        boot_id = "unknown-boot"
        try:
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() or boot_id
        except Exception:
            pass
        return f"proc-start:{boot_id}:{start_ticks}"
    except Exception:
        return None


class InstanceGuard:
    """Project-local top-level lock for the GUI process."""

    def __init__(self, component: str, run_id: str, root: Optional[Path] = None) -> None:
        self.component = component
        self.run_id = run_id
        self.root = (root or app_base_dir()).resolve()
        self.lock_path = self.root / "state" / f"{safe_filename_token(component)}.lock"
        self.acquired = False
        self.last_message = "not acquired"

    def _owner_record(self) -> dict[str, Any]:
        now = utc_now_iso()
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "component": self.component,
            "pid": os.getpid(),
            "run_id": self.run_id,
            "project_root": redact_path(self.root),
            "process_signature": {
                "start": process_start_signature(os.getpid()),
                "executable": redact_path(sys.executable),
                "argv0": redact_path(sys.argv[0] if sys.argv else ""),
            },
            "acquired_at_utc": now,
            "heartbeat_utc": now,
            "stale_after_seconds": INSTANCE_LOCK_STALE_SECONDS,
        }

    def _read_owner(self) -> dict[str, Any]:
        try:
            return json.loads(self.lock_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _owner_heartbeat_age_seconds(self, owner: dict[str, Any]) -> Optional[float]:
        raw = owner.get("heartbeat_utc") or owner.get("acquired_at_utc")
        if not raw:
            return None
        try:
            text = str(raw).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
        except Exception:
            return None

    def _owner_is_verified_live(self, owner: dict[str, Any]) -> bool:
        """Verify a live owner without breaking a lock solely for stale heartbeat age."""
        try:
            if owner.get("app") != APP_NAME or owner.get("component") != self.component:
                return False
            pid = int(owner.get("pid", -1))
            if not pid_is_running(pid):
                return False
            recorded = owner.get("process_signature") if isinstance(owner.get("process_signature"), dict) else {}
            recorded_start = recorded.get("start")
            current_start = process_start_signature(pid)
            if recorded_start and current_start and recorded_start != current_start:
                return False
            # If the OS cannot expose a start signature, a live PID is treated
            # conservatively as owned. Heartbeat age is diagnostic only and is
            # never sufficient by itself to break a verified live lock.
            return True
        except Exception:
            return False

    def acquire(self) -> tuple[bool, str]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        record = self._owner_record()
        for _attempt in range(2):
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(record, fh, indent=2, sort_keys=True)
                self.acquired = True
                self.last_message = f"acquired {self.lock_path}"
                return True, self.last_message
            except FileExistsError:
                owner = self._read_owner()
                if self._owner_is_verified_live(owner):
                    self.last_message = f"Another {APP_NAME} GUI is already running (PID {owner.get('pid')}, run {owner.get('run_id')}). Close it before starting a second copy."
                    return False, self.last_message
                try:
                    self.lock_path.unlink()
                    self.last_message = "stale or invalid lock recovered"
                    continue
                except Exception as exc:
                    self.last_message = f"Could not recover stale lock {self.lock_path}: {exc}"
                    return False, self.last_message
        return False, self.last_message

    def heartbeat(self) -> None:
        if not self.acquired:
            return
        record = self._read_owner()
        if record.get("run_id") != self.run_id or record.get("pid") != os.getpid():
            self.acquired = False
            self.last_message = "lock ownership changed; heartbeat stopped"
            return
        record["heartbeat_utc"] = utc_now_iso()
        record.setdefault("acquired_at_utc", utc_now_iso())
        record.setdefault("process_signature", self._owner_record().get("process_signature"))
        try:
            atomic_write_bytes(self.lock_path, safe_json_dumps(record).encode("utf-8"))
        except Exception as exc:
            self.last_message = f"heartbeat write failed: {redact_text(exc)}"

    def release(self) -> None:
        if not self.acquired:
            return
        owner = self._read_owner()
        try:
            if owner.get("run_id") == self.run_id and owner.get("pid") == os.getpid():
                self.lock_path.unlink(missing_ok=True)
        except Exception:
            pass
        finally:
            self.acquired = False

    def snapshot(self) -> dict[str, Any]:
        owner = self._read_owner() if self.lock_path.exists() else {}
        recorded_signature = owner.get("process_signature") if isinstance(owner.get("process_signature"), dict) else {}
        owner_pid = int(owner.get("pid", -1)) if owner else -1
        current_start = process_start_signature(owner_pid) if owner_pid > 0 and pid_is_running(owner_pid) else None
        recorded_start = recorded_signature.get("start") if isinstance(recorded_signature, dict) else None
        signature_match = None if not recorded_start or not current_start else recorded_start == current_start
        return {
            "status": "acquired" if self.acquired else "not_acquired",
            "component": self.component,
            "run_id": redact_text(self.run_id),
            "lock_path": redact_path(self.lock_path),
            "owner_pid": owner.get("pid"),
            "owner_run_id": redact_text(owner.get("run_id", "")),
            "owner_heartbeat_utc": redact_text(owner.get("heartbeat_utc", "")),
            "owner_heartbeat_age_seconds": self._owner_heartbeat_age_seconds(owner) if owner else None,
            "process_signature_present": isinstance(owner.get("process_signature"), dict),
            "process_start_signature_present": bool(recorded_start),
            "process_start_signature_match": signature_match,
            "stale_after_seconds": INSTANCE_LOCK_STALE_SECONDS,
            "heartbeat_policy": "diagnostic freshness signal only; a verified live process is not displaced solely for stale heartbeat age",
            "second_launch_behavior": "second GUI process exits with an explicit owner/status message; CLI diagnostics remain available",
        }


def safe_json_dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=str)


def stable_fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def safe_package_version(package_name: str) -> dict[str, Any]:
    try:
        return {"installed": True, "version": importlib.metadata.version(package_name)}
    except importlib.metadata.PackageNotFoundError:
        return {"installed": False, "version": None}
    except Exception as exc:
        return {"installed": False, "version": None, "error": str(exc)}


def _looks_like_ip_or_local(host: str) -> bool:
    if not host:
        return True
    if host.lower() in {"localhost", "127.0.0.1", "::1"}:
        return True
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        return True
    if ":" in host and re.fullmatch(r"[0-9a-fA-F:]+", host):
        return True
    return False


def redact_url(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8", errors="replace")).hexdigest()[:16]
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or "host"
        if _looks_like_ip_or_local(host):
            host = "redacted-host"
        scheme = parsed.scheme or "url"
        return f"{scheme}://{host}/<redacted-url:{digest}>"
    except Exception:
        return f"<redacted-url:{digest}>"


def redact_text(value: Any) -> str:
    """Remove secrets and private identifiers while leaving diagnostic shape useful."""
    text = "" if value is None else str(value)
    if not text:
        return text
    text = URL_IN_TEXT_RE.sub(lambda match: redact_url(match.group(0)), text)
    text = re.sub(r"(?i)\b([A-Z]:\\Users\\)[^\\\s]+", r"\1<user>", text)
    text = re.sub(r"(?i)\b([A-Z]:/Users/)[^/\s]+", r"\1<user>", text)
    text = re.sub(r"(?i)\b(/home/)[^/\s]+", r"\1<user>", text)
    text = re.sub(r"(?i)\b(/Users/)[^/\s]+", r"\1<user>", text)
    for sensitive_path, replacement in ((Path.home(), "~"), (app_base_dir(), "<app_root>")):
        try:
            resolved = str(sensitive_path.expanduser().resolve())
            if resolved:
                text = text.replace(resolved, replacement)
                text = text.replace(resolved.replace("\\", "/"), replacement)
        except Exception:
            pass
    # Redact remaining absolute paths outside the project/home roots. URLs have
    # already been normalized, and the look-behinds avoid treating URL slashes
    # as local POSIX paths.
    # Preserve separate path placeholders when multiple absolute paths occur in
    # one message. This keeps diagnostics useful without exposing either path.
    text = re.sub(
        r"(?<![\w:/>~])/(?:[A-Za-z0-9._~ -]+/)+[A-Za-z0-9._~ ()@+,=-]*?(?=(?:\s+(?:[A-Za-z]:[\\/]|/))|[,;\r\n)\]}]|$)",
        "<redacted-path>",
        text,
    )
    text = re.sub(
        r"(?i)(?<!\w)[A-Z]:[\\/][^,;\r\n)\]}]*?(?=(?:\s+(?:[A-Z]:[\\/]|/))|[,;\r\n)\]}]|$)",
        "<redacted-path>",
        text,
    )
    text = re.sub(
        r"(?i)\b(api[_-]?key|authorization|bearer|cookie|credential|license[_-]?key|password|passwd|secret|session|token)\b\s*[:=]\s*[^\s,;]+",
        lambda m: f"{m.group(1)}=<redacted-secret>",
        text,
    )
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*", "Bearer <redacted-secret>", text)
    text = re.sub(r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![0-9a-f:])", "<redacted-ip>", text)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<redacted-ip>", text)
    text = re.sub(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b", "<redacted-mac>", text)
    text = re.sub(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b", "<redacted-uuid>", text)
    text = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "<redacted-email>", text)
    return text


def redact_path(path: Any) -> str:
    return redact_text(path)


def redact_command_line(args: Iterable[Any]) -> str:
    """Redact command arguments individually so paths containing spaces stay private."""
    rendered: list[str] = []
    for index, raw in enumerate(args):
        text = str(raw or "")
        if URL_RE.match(text):
            rendered.append(redact_url(text))
            continue
        windows_absolute = bool(WINDOWS_ABSOLUTE_PATH_RE.match(text))
        posix_absolute = text.startswith("/")
        if windows_absolute or posix_absolute:
            if index == 0 or text.lower().endswith((".py", ".pyw")):
                rendered.append(Path(text.replace("\\", "/")).name or "<script>")
            else:
                rendered.append("<redacted-path>")
            continue
        rendered.append(redact_text(text))
    return " ".join(rendered)


def redact_for_export(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if SECRET_KEY_RE.search(key_text):
                cleaned[key_text] = "<redacted-secret>"
            else:
                cleaned[key_text] = redact_for_export(item)
        return cleaned
    if isinstance(value, list):
        return [redact_for_export(item) for item in value]
    if isinstance(value, tuple):
        return [redact_for_export(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_strings_for_export(value: Any) -> Any:
    """Recursively redact string content while preserving diagnostic key names.

    Collector inputs use ``redact_for_export`` where secret-bearing keys may be
    present. This second, archive-level boundary protects paths/URLs embedded in
    otherwise trusted collector output without erasing policy keys such as
    ``credential_policy``.
    """
    if isinstance(value, dict):
        return {str(key): redact_strings_for_export(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_strings_for_export(item) for item in value]
    if isinstance(value, tuple):
        return [redact_strings_for_export(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def diagnostic_json(value: Any) -> str:
    """Serialize diagnostic JSON through the final privacy boundary."""
    return safe_json_dumps(redact_strings_for_export(value))


def summarize_url(url: str) -> dict[str, Any]:
    digest = hashlib.sha256(url.encode("utf-8", errors="replace")).hexdigest()
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or "unknown"
        safe_host = "redacted-host" if _looks_like_ip_or_local(host) else host.lower()
        scheme = parsed.scheme or "unknown"
    except Exception:
        safe_host = "unknown"
        scheme = "unknown"
    return {
        "scheme": scheme,
        "host": safe_host,
        "url_hash_sha256_prefix": digest[:16],
        "url_redacted": redact_url(url),
        "full_url_exported": False,
    }


def url_log_label(url: str) -> str:
    """Return a useful, stable log label without persisting a full URL/query."""
    summary = summarize_url(str(url or ""))
    return f"{summary.get('host', 'unknown')}#{str(summary.get('url_hash_sha256_prefix', ''))[:10]}"


def sanitize_jobs_for_diagnostics(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(str(job.get("status", "Unknown")) for job in jobs)
    hosts = Counter()
    items: list[dict[str, Any]] = []
    verification_counts = Counter()
    error_categories = Counter()
    for job in jobs:
        url = str(job.get("url", ""))
        url_summary = summarize_url(url) if url else {"scheme": "", "host": "", "url_hash_sha256_prefix": "", "url_redacted": "", "full_url_exported": False}
        if url_summary.get("host"):
            hosts[str(url_summary["host"])] += 1
        raw_result = job.get("result") if isinstance(job.get("result"), dict) else {}
        preflight = raw_result.get("preflight") if isinstance(raw_result.get("preflight"), dict) else {}
        verification = raw_result.get("verification") if isinstance(raw_result.get("verification"), dict) else {}
        tolerance = raw_result.get("site_tolerance") if isinstance(raw_result.get("site_tolerance"), dict) else {}
        if verification.get("status"):
            verification_counts[str(verification.get("status"))] += 1
        if raw_result.get("error_category"):
            error_categories[str(raw_result.get("error_category"))] += 1
        safe_result = {
            "preflight": {
                "media_id": redact_text(preflight.get("media_id", "")),
                "extractor": redact_text(preflight.get("extractor", "")),
                "format_ids": [redact_text(v) for v in preflight.get("format_ids", [])],
                "stream_count": preflight.get("stream_count"),
                "estimated_download_bytes": preflight.get("estimated_download_bytes"),
                "disk_status": (preflight.get("disk_preflight") or {}).get("status") if isinstance(preflight.get("disk_preflight"), dict) else None,
                "has_drm": preflight.get("has_drm"),
                "fragmented_transfer": preflight.get("fragmented_transfer"),
            },
            "site_tolerance": {
                "policy": tolerance.get("policy"),
                "tier": tolerance.get("tier"),
                "selected_fragment_limit": tolerance.get("selected_fragment_limit"),
                "clean_successes": tolerance.get("clean_successes"),
                "promotion_after_clean_successes": tolerance.get("promotion_after_clean_successes"),
                "cooldown_jobs_remaining": tolerance.get("cooldown_jobs_remaining"),
                "terminal_status": (tolerance.get("terminal_update") or {}).get("status") if isinstance(tolerance.get("terminal_update"), dict) else None,
                "terminal_event": (tolerance.get("terminal_update") or {}).get("event") if isinstance(tolerance.get("terminal_update"), dict) else None,
                "next_normal_fragment_limit": (tolerance.get("terminal_update") or {}).get("next_normal_fragment_limit") if isinstance(tolerance.get("terminal_update"), dict) else None,
                "site_identity_exported": False,
            },
            "verification": {
                "status": verification.get("status"), "method": verification.get("method"), "file_size_bytes": verification.get("file_size_bytes"),
                "stream_types": verification.get("stream_types"), "duration_seconds": verification.get("duration_seconds"), "reason": redact_text(verification.get("reason", "")),
                "path_redacted": redact_path(verification.get("path", "")) if verification.get("path") else None,
            },
            "error_category": redact_text(raw_result.get("error_category", "")),
            "elapsed_seconds": raw_result.get("elapsed_seconds"),
        }
        items.append({"item_id": redact_text(job.get("item_id", "")), "status": redact_text(job.get("status", "")), "url": url_summary, "result": safe_result})
    return {
        "count": len(jobs), "status_counts": dict(statuses), "host_counts": dict(hosts), "verification_counts": dict(verification_counts),
        "error_category_counts": dict(error_categories), "items": items,
        "payload_policy": "Queued URLs are sensitive payloads and are represented by host plus stable hash prefix only; output paths are redacted.",
    }



def sanitize_log_entries(logs: list[dict[str, Any]], *, limit: int = DIAGNOSTIC_LOG_TAIL_LIMIT) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    for entry in logs[-limit:]:
        sanitized.append(
            {
                "timestamp_local": redact_text(entry.get("timestamp_local", "")),
                "timestamp_utc": redact_text(entry.get("timestamp_utc", "")),
                "level": redact_text(entry.get("level", "info")),
                "message": redact_text(entry.get("message", "")),
            }
        )
    return sanitized


def asset_definition_for_path(relative_path: str) -> dict[str, Any]:
    normalized = relative_path.replace("\\", "/")
    for definition in ASSET_DEFINITIONS:
        if definition["path"] == normalized:
            return dict(definition)
    return {
        "asset_id": f"SVD-ASSET-{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:12].upper()}",
        "path": normalized,
        "title": Path(normalized).name,
        "purpose": "Retained project asset",
        "asset_class": "other",
        "role": "retained-asset",
        "format": Path(normalized).suffix.lstrip(".").lower() or "unknown",
        "status": "current",
        "sensitivity": "public",
        "source_of_truth": False,
        "tags": [PROJECT_SLUG, "retained-asset"],
        "aliases": [],
        "metadata_depth": "file",
    }


def _asset_timestamp_fields(stat: os.stat_result) -> dict[str, Any]:
    modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    if ZoneInfo is not None:
        try:
            modified_local = modified.astimezone(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %I:%M:%S %p %Z / America/Chicago")
        except Exception:
            modified_local = modified.isoformat()
    else:
        modified_local = modified.isoformat()
    return {
        "created_utc": modified.isoformat(),
        "modified_utc": modified.isoformat(),
        "created_local": modified_local,
        "modified_local": modified_local,
        "created_time_basis": "filesystem mtime fallback; original creation time is not portable across ZIP extraction",
    }


def file_metadata_for_manifest(relative_path: str, purpose: Optional[str] = None, status: Optional[str] = None) -> dict[str, Any]:
    definition = asset_definition_for_path(relative_path)
    path = app_base_dir() / definition["path"]
    record: dict[str, Any] = {
        "asset_id": definition["asset_id"],
        "file": definition["path"],
        "path": definition["path"],
        "title": definition["title"],
        "purpose": purpose or definition["purpose"],
        "asset_class": definition["asset_class"],
        "role": definition["role"],
        "format": definition["format"],
        "project_slug": PROJECT_SLUG,
        "version": APP_VERSION,
        "status": status or definition["status"],
        "lifecycle_status": status or definition["status"],
        "sensitivity": definition["sensitivity"],
        "source_of_truth": bool(definition["source_of_truth"]),
        "tags": list(definition["tags"]),
        "aliases": list(definition["aliases"]),
        "lineage": "tracked application file",
        "metadata_depth": definition["metadata_depth"],
        "absolute_path_exported": False,
    }
    try:
        stat = path.stat()
        observed_times = _asset_timestamp_fields(stat)
        observed_hash = sha256_file(path)
        record.update({"exists": True, "size_bytes": stat.st_size, "bytes": stat.st_size})
        record.update(observed_times)
        record.update(observed_hash)

        record["integrity_status"] = "observed"
    except FileNotFoundError:
        record.update({"exists": False, "warning": "file not found", "size_bytes": None, "sha256": None})
    except Exception as exc:
        record.update({"exists": False, "warning": redact_text(exc), "size_bytes": None, "sha256": None})
    return record


def reconcile_asset_metadata(records: list[dict[str, Any]]) -> dict[str, Any]:
    required_fields = (
        "asset_id", "path", "title", "purpose", "asset_class", "role", "format", "project_slug",
        "version", "status", "sensitivity", "source_of_truth", "tags", "aliases", "lineage",
        "created_utc", "modified_utc", "size_bytes", "sha256",
    )
    ids = [str(record.get("asset_id") or "") for record in records]
    paths = [str(record.get("path") or "") for record in records]
    duplicate_ids = sorted({value for value in ids if value and ids.count(value) > 1})
    duplicate_paths = sorted({value for value in paths if value and paths.count(value) > 1})
    missing_fields: dict[str, list[str]] = {}
    missing_files: list[str] = []
    stale_versions: list[str] = []
    stale_header_metadata: list[str] = []
    inherited_package_metadata: list[str] = []
    integrity_mismatches: list[str] = []
    for record in records:
        path = str(record.get("path") or "<unknown>")
        absent = [field for field in required_fields if record.get(field) in (None, "")]
        if absent:
            missing_fields[path] = absent
        if not record.get("exists"):
            missing_files.append(path)
        if record.get("version") != APP_VERSION:
            stale_versions.append(path)
        depth = record.get("metadata_depth")
        if depth == "header+manifest" and record.get("exists"):
            try:
                header = (app_base_dir() / path).read_text(encoding="utf-8", errors="replace")[:4000]
                if str(record.get("asset_id")) not in header or APP_VERSION not in header:
                    stale_header_metadata.append(path)
            except Exception:
                stale_header_metadata.append(path)
        elif depth == "manifest-only":
            inherited_package_metadata.append(path)
        if record.get("integrity_status") == "runtime_drift":
            integrity_mismatches.append(path)
    status = "ok" if not (duplicate_ids or duplicate_paths or missing_fields or missing_files or stale_versions or stale_header_metadata or integrity_mismatches) else "warning"
    return {
        "metadata_schema": ASSET_METADATA_SCHEMA_VERSION,
        "status": status,
        "retained_asset_count": len(records),
        "manifest_coverage_count": sum(1 for record in records if record.get("asset_id") and record.get("path")),
        "coverage_complete": len(records) == sum(1 for record in records if record.get("asset_id") and record.get("path")),
        "duplicate_asset_ids": duplicate_ids,
        "duplicate_paths": duplicate_paths,
        "missing_fields": missing_fields,
        "missing_files": missing_files,
        "stale_versions": stale_versions,
        "stale_or_missing_key_headers": stale_header_metadata,
        "runtime_integrity_mismatches": integrity_mismatches,
        "file_metadata_only": inherited_package_metadata,
        "unsupported_metadata_policy": "diagnostics use live file metadata and do not create sidecar files",
        "secrets_policy": "support metadata must not include credentials, private identifiers, or local absolute paths",
    }


def support_export_scope_snapshot() -> dict[str, Any]:
    """Describe the local-only boundary of a support diagnostic export."""
    return {
        "status": "local_only",
        "network_requests": False,
        "external_accounts": False,
        "includes_downloaded_media": False,
        "review_before_sharing": True,
    }


def project_file_manifest() -> dict[str, Any]:
    records = [file_metadata_for_manifest(definition["path"]) for definition in ASSET_DEFINITIONS]
    reconciliation = reconcile_asset_metadata(records)
    generated_at = utc_now_iso()
    return {
        "metadata_schema": ASSET_METADATA_SCHEMA_VERSION,
        "app": APP_NAME,
        "project_slug": PROJECT_SLUG,
        "version": APP_VERSION,
        "status": "current",
        "sensitivity": "public",
        "generated_at_utc": generated_at,
        "modified_at_utc": generated_at,
        "tags": ["safe-video-downloader", "diagnostics", "public-support"],
        "file_count": len(records),
        "diagnostic_schema_version": DIAGNOSTIC_EXPORT_SCHEMA_VERSION,
        "support_export_scope": support_export_scope_snapshot(),
        "metadata_reconciliation": reconciliation,
        "files": records,
    }


def _existing_parent_for_disk(path: Path) -> Path:
    candidate = path.expanduser()
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate if candidate.exists() else app_base_dir()


def _disk_summary(path: Path) -> dict[str, Any]:
    try:
        target = _existing_parent_for_disk(path)
        usage = shutil.disk_usage(str(target))
        return {"path": redact_path(target), "total_gb": round(usage.total / (1024 ** 3), 2), "free_gb": round(usage.free / (1024 ** 3), 2), "used_gb": round(usage.used / (1024 ** 3), 2)}
    except Exception as exc:
        return {"status": "unavailable", "reason": redact_text(exc)}


def _ram_class() -> str:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        total_gb = page_size * pages / (1024 ** 3)
        if total_gb < 4:
            return "under 4 GB"
        if total_gb < 8:
            return "4-8 GB"
        if total_gb < 16:
            return "8-16 GB"
        if total_gb < 32:
            return "16-32 GB"
        return "32+ GB"
    except Exception:
        return "not collected on this platform"


def scan_stale_absolute_paths(*, max_findings: int = 12) -> dict[str, Any]:
    """Find likely hard-coded runtime paths without reading large/runtime folders.

    This is a static, read-only portability check. Findings are evidence for review,
    not automatic failures, because docs/tests may intentionally contain examples.
    """
    patterns = [
        ("windows_user_path", re.compile(r"[A-Za-z]:\\\\Users\\\\[^\\\r\n\t ]+", re.IGNORECASE)),
        ("unix_sandbox_path", re.compile(r"/mnt/data/[^\s)\]}'\"]+", re.IGNORECASE)),
        ("downloads_path", re.compile(r"[A-Za-z]:\\\\[^\r\n]*Downloads[^\r\n]*", re.IGNORECASE)),
    ]
    findings: list[dict[str, Any]] = []
    scanned = 0
    for rel in TEXT_PORTABILITY_SCAN_FILES:
        path = app_base_dir() / rel
        if not path.is_file():
            continue
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            findings.append({"file": rel, "line": None, "kind": "read_error", "snippet": redact_text(exc)})
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            # Do not flag this scanner's own regex definitions as stale runtime paths.
            if "unix_sandbox_path" in line or "windows_user_path" in line or "downloads_path" in line:
                continue
            for kind, pattern in patterns:
                if pattern.search(line):
                    lower = line.lower()
                    classification = "example_or_test" if any(word in lower for word in ("example", "test", "sample", "diagnostic", "default", "redact", "c:\\\\bots")) else "review"
                    findings.append({"file": rel, "line": lineno, "kind": kind, "classification": classification, "snippet": redact_text(line.strip()[:240])})
                    break
            if len(findings) >= max_findings:
                break
        if len(findings) >= max_findings:
            break
    return {
        "status": "ok",
        "scanned_files": scanned,
        "finding_count_returned": len(findings),
        "max_findings": max_findings,
        "findings": findings,
        "interpretation": "review findings after moves; example/test findings are not runtime blockers",
    }


def path_portability_snapshot(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Return a move-safe/path-targeting snapshot for diagnostics and --path-check."""
    settings = settings or {}
    root = app_base_dir().resolve()
    output_dir_raw = settings.get("output_dir") or default_download_dir()
    try:
        output_dir = resolve_output_dir(output_dir_raw)
        output_resolution = "normalized"
    except Exception as exc:
        output_dir = Path(str(output_dir_raw)).expanduser()
        output_resolution = f"invalid: {redact_text(exc)}"
    folder_map = {"app_root": root, "logs": logs_dir(), "exports": exports_dir(), "diagnostics": diagnostics_dir(), "state": state_dir(), "tools": tools_dir(), "output_dir": output_dir}
    return {
        "status": "ok",
        "root_detection": "frozen executable folder when compiled; otherwise folder containing safe_media_downloader.py",
        "project_root_redacted": redact_path(root),
        "project_root_exists": root.exists(),
        "project_root_has_spaces": " " in str(root),
        "folder_local_runtime_paths": {name: redact_path(path) for name, path in folder_map.items() if name != "output_dir"},
        "output_dir_redacted": redact_path(output_dir),
        "output_resolution_status": output_resolution,
        "relative_output_policy": "relative paths resolve from the application root, not the caller working directory",
        "output_dir_is_user_selected_or_default": True,
        "external_storage_is_runtime_dependency": False,
        "portable_after_move": "expected because the launcher uses its own folder and Python uses app_base_dir()",
        "repair_reinstall_fallback": "Recreate the project-local virtual environment from requirements.txt; runtime data remains separate",
        "stale_absolute_path_scan": scan_stale_absolute_paths(),
    }


def system_snapshot(settings: dict[str, Any]) -> dict[str, Any]:
    try:
        output_dir = resolve_output_dir(settings.get("output_dir") or default_download_dir())
    except Exception:
        output_dir = default_download_dir()
    return {
        "os": {"system": platform.system(), "release": platform.release(), "version": redact_text(platform.version()), "platform": redact_text(platform.platform()), "machine": platform.machine(), "architecture": platform.architecture()[0]},
        "runtime": {"python_version": platform.python_version(), "python_executable": redact_path(sys.executable), "frozen_executable": bool(getattr(sys, "frozen", False)), "tkinter_available": tk is not None and TK_IMPORT_ERROR is None, "tkinter_error": redact_text(TK_IMPORT_ERROR) if TK_IMPORT_ERROR is not None else None, "gui_runtime": gui_runtime_snapshot(create_window=False)},
        "hardware_class": {"cpu_class": redact_text(platform.processor() or platform.machine() or "unknown"), "ram_class": _ram_class(), "gpu_driver_cuda": "not collected; no GPU/CUDA dependency for this app"},
        "storage_summary": {"project_drive": _disk_summary(app_base_dir()), "output_drive": _disk_summary(output_dir)},
        "security_vpn_status": "not collected by design; local IP, MAC, account IDs, and VPN state are not exported",
        "project_root": redact_path(app_base_dir()),
        "folder_local_paths": {"logs": redact_path(logs_dir()), "exports": redact_path(exports_dir()), "diagnostics": redact_path(diagnostics_dir()), "state": redact_path(state_dir())},
        "path_portability": path_portability_snapshot(settings),
        "log_retention": {"max_files": LOG_RETENTION_MAX_FILES, "max_bytes_per_file": LOG_RETENTION_MAX_BYTES},
    }


def executable_snapshot(name: str) -> dict[str, Any]:
    path = find_executable(name)
    if not path:
        return {"present": False, "path": None, "hash": None}
    return {"present": True, "path": redact_path(path), "hash": sha256_file(path), "provenance_note": "Path detected locally; diagnostic export does not execute this binary."}


def dependency_provenance_snapshot() -> dict[str, Any]:
    packages = {pkg: safe_package_version(pkg) for pkg in ("yt-dlp", "yt-dlp-ejs", "certifi", "requests", "websockets", "pyinstaller")}
    javascript_runtimes = javascript_runtime_snapshot(execute_versions=False)
    # Runtime selection needs the real executable path, but exported provenance
    # only needs presence/version/status. Never carry a raw helper path into the
    # diagnostic ZIP.
    for candidate in javascript_runtimes.get("candidates", []):
        if isinstance(candidate, dict) and candidate.get("path"):
            candidate["path"] = redact_path(candidate.get("path"))
    selected_runtime = javascript_runtimes.get("selected")
    if isinstance(selected_runtime, dict) and selected_runtime.get("path"):
        selected_runtime["path"] = redact_path(selected_runtime.get("path"))
    return {
        "python_packages": packages,
        "helper_binaries": {"ffmpeg": executable_snapshot("ffmpeg"), "ffprobe": executable_snapshot("ffprobe"), "javascript_runtimes": javascript_runtimes},
        "requirements_files": {"requirements.txt": file_metadata_for_manifest("requirements.txt", "Runtime dependency pin", "required")},
        "official_review": {"checked_at": PUBLIC_DEPENDENCY_REVIEW_DATE, "latest_yt_dlp_release_seen": "2026.07.04", "minimum_recommended_python": "3.11", "notes": "Official yt-dlp documentation was reviewed for fragment concurrency and JavaScript-runtime guidance."},
        "trust_policy": "Install pinned Python packages from pip requirements; use trusted official/package-manager helper installs; no remote EJS components are enabled by this app.",
        "upgrade_policy": "No silent upgrades or helper downloads during diagnostics; updates remain user-initiated.",
    }



def compatibility_matrix(settings: dict[str, Any]) -> dict[str, Any]:
    js = javascript_runtime_snapshot(execute_versions=False)
    return {
        "confirmed_current": {"os": f"{platform.system()} {platform.release()}", "python": platform.python_version(), "ffmpeg_detected": bool(find_ffmpeg_location()), "ffprobe_detected": bool(find_executable("ffprobe")), "javascript_runtime_detected": bool(js.get("selected")), "mode": redact_text(settings.get("mode", "unknown"))},
        "supported_assumptions": {"os": "Windows 10/11 recommended", "shell": "BAT launcher is Windows-specific; Python CLI is portable", "runtime": "Python 3.11+", "package_manager": "pip; winget optional for helpers", "terminal": "Tkinter GUI or CLI", "external_platform": "yt-dlp extractor behavior may change", "queue_capacity": QUEUE_CAPACITY},
        "integrity_features": {"smart_preflight": True, "selected_format_check": True, "known_disk_guard": True, "abort_unavailable_fragments": True, "post_download_ffprobe": True, "queue_recovery_schema": QUEUE_STATE_SCHEMA_VERSION, "media_index_schema": MEDIA_INDEX_SCHEMA_VERSION, "duplicate_guard": True},
        "unsupported_modes": ["DRM/access-control bypass", "credential/cookie/browser-profile extraction", "silent proxy/VPN bypass", "unbounded automation"],
    }



def launcher_snapshot(run_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "primary_launcher_type": "Tkinter GUI via run_safe_video_downloader.bat; CLI via safe_media_downloader.py --cli",
        "current_mode": redact_text(run_context.get("mode", "unknown")),
        "run_id": redact_text(run_context.get("run_id", "unknown")),
        "command_used_redacted": redact_command_line(sys.argv),
        "cwd": redact_path(Path.cwd()),
        "app_root": redact_path(app_base_dir()),
        "python_executable": redact_path(sys.executable),
        "elevation_requirement": "normal user is expected; administrator is not required except optional winget installs may prompt",
        "installer_package_type": "portable ZIP/source with per-project .venv; optional PyInstaller one-file EXE built by user",
        "rollback_uninstall_path": "Delete the project folder or restore the prior ZIP; remove .venv/build/dist if desired.",
    }


def effective_input_snapshot(settings: dict[str, Any], jobs_summary: dict[str, Any]) -> dict[str, Any]:
    redacted_settings = redact_for_export(settings)
    input_contract_registry = {
        "download_urls": {"source": "GUI or CLI", "sensitivity": "sensitive", "validation": "http/https/ftp allowlist and deduplication", "destination": "yt-dlp URL list", "confirmation": "success plus final-media verification"},
        "output_dir": {"source": "GUI/CLI/default", "sensitivity": "sensitive local path", "validation": "environment/~ expansion, relative-to-app-root normalization, file-vs-folder rejection, and disk preflight", "destination": "yt-dlp output template"},
        "format_settings": {"source": "mode/height/custom/MP4 plus helper detection", "validation": "fixed modes; no-FFmpeg merge avoidance; selected format availability check", "destination": "yt-dlp format and postprocessors", "confirmation": "exact format plan captured before bytes transfer"},
        "rate_limit_bytes": {"source": "GUI or CLI", "validation": "positive K/M/G bytes/s", "destination": "yt-dlp ratelimit and fragment concurrency=1 when set"},
        "hide_media": {"source": "GUI/CLI/default=false", "validation": "boolean", "destination": "Windows hidden attribute on final media file only", "confirmation": "per-job media_visibility result"},
        "smart_resilience": {"source": "GUI/CLI/default=true", "validation": "boolean", "destination": "bounded outer session rebuild, conservative throttled-rate guard, and recovery profiles", "confirmation": "per-job adaptive_resilience telemetry"},
        "duplicate_detection": {"source": "GUI/CLI/default=true", "validation": "boolean plus extractor/media identity and output-variant key", "destination": "queue dedupe, yt-dlp archive, state/media-index.json, and no-overwrite guard", "confirmation": "per-job duplicate_detection telemetry and bounded index summary"},
    }
    return {
        "schema_version": 3,
        "source_precedence": ["GUI/CLI", "built-in defaults", "optional helper auto-detection"],
        "redacted_effective_settings": redacted_settings,
        "recognized_inputs": sorted(redacted_settings.keys()),
        "input_contract_registry": input_contract_registry,
        "validated_normalized_status": {"output_dir": "normalized; known free-space guard at before_dl", "mode": "fixed mode list", "rate_limit_bytes": "parsed or null", "smart_resilience": "boolean; default enabled", "format_selector": "derived and selected formats checked", "playlist": "explicit opt-in", "queue_capacity": QUEUE_CAPACITY},
        "unknown_or_unsupported_inputs": [], "ignored_unconsumed_inputs": [], "queue_payloads": jobs_summary.get("payload_policy"),
        "fingerprint_sha256": stable_fingerprint({"settings": redacted_settings, "queue": jobs_summary.get("items", [])}),
        "assurance_stage": "recognized -> validated -> normalized -> mapped -> exact selected-format preflight -> final-media verification when a real run occurs",
    }



def platform_api_snapshot(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "integration_registry": [
            {"name": "yt-dlp", "version": safe_package_version("yt-dlp"), "status": "verified-at-release", "official_sources_reviewed": ["official releases", "README options", "EJS wiki"], "last_review": PUBLIC_DEPENDENCY_REVIEW_DATE, "freshness_target": "30 days or immediately after extractor errors", "runtime_controls": retry_policy_snapshot(bool(settings.get("rate_limit_bytes")), bool(settings.get("smart_resilience", True)))},
            {"name": "FFmpeg/FFprobe", "status": "present" if find_ffmpeg_location() else "warning/missing", "role": "merge/transcode and final-media verification", "diagnostic_probe": "path/hash only; binaries are not executed during export"},
            {"name": "Deno/Node", "status": "cached/path-only evidence", "minimums": {"deno": "2.3.0", "node": "22.0.0"}, "remote_components": "disabled"},
            {
                "name": "Tkinter",
                "status": "available" if tk is not None and TK_IMPORT_ERROR is None else "missing_or_broken",
                "cli_recovery_available_without_tk": True,
                "error_redacted": redact_text(TK_IMPORT_ERROR) if TK_IMPORT_ERROR else None,
            },
        ],
        "input_to_destination_mapping_redacted": {"output_dir": "outtmpl plus disk preflight", "format inputs": "format selector/check_formats/format plan", "rate_limit": "ratelimit plus bounded concurrency", "metadata/subtitles": "postprocessors"},
        "active_deprecations_or_deadlines": "Python 3.11 is the current recommended floor; this package now requires 3.11+.",
        "credential_policy": "no credentials, cookies, browser profiles, or private headers collected/exported",
        "support_export_scope": support_export_scope_snapshot(),
    }



def time_trace_summary(run_context: dict[str, Any], logs: list[dict[str, Any]]) -> dict[str, Any]:
    last_log = logs[-1] if logs else {}
    last_error = next((entry for entry in reversed(logs) if str(entry.get("level", "")).lower() in {"error", "debug", "warning"}), None)
    return {
        "run_id": redact_text(run_context.get("run_id", "unknown")),
        "machine_time_utc": utc_now_iso(),
        "machine_time_local": chicago_now().strftime("%Y-%m-%d %H:%M:%S %z %Z"),
        "run_start_utc": redact_text(run_context.get("started_at_utc") or "unknown"),
        "elapsed_seconds_monotonic": run_context.get("elapsed_seconds"),
        "last_progress_time": redact_text(last_log.get("timestamp_utc", "none")),
        "last_successful_step": "see recent log tail; exporter does not infer success beyond recorded log messages",
        "last_warning_or_error": redact_for_export(last_error) if last_error else None,
        "shutdown_reason": "not applicable while app is running" if run_context.get("mode") == "gui" else "CLI export path",
        "export_timestamp_utc": utc_now_iso(),
        "monotonic_clock_used": True,
    }


def troubleshooting_evidence(run_context: dict[str, Any], settings_fingerprint: str, logs: list[dict[str, Any]]) -> dict[str, Any]:
    error_tail = [entry for entry in sanitize_log_entries(logs, limit=50) if entry.get("level", "").lower() in {"error", "debug", "warning"}]
    return {"command_used_redacted": redact_command_line(sys.argv), "exact_redacted_error_tail": error_tail[-10:], "timestamp_utc": utc_now_iso(), "run_id": redact_text(run_context.get("run_id", "unknown")), "active_config_fingerprint_sha256": settings_fingerprint, "environment_snapshot_reference": "05-system-snapshot.json", "recent_log_tail_reference": "09-recent-log-tail.txt", "public_files_reference": "02-public-files.json", "collection_note": "Collection is local and read-only; no network probes or system changes are performed."}


def run_history_health_summary(jobs_summary: dict[str, Any], logs: list[dict[str, Any]]) -> dict[str, Any]:
    levels = Counter(str(entry.get("level", "info")).lower() for entry in logs)
    return {"queue_status_counts": jobs_summary.get("status_counts", {}), "log_level_counts": dict(levels), "recent_log_count_exported": min(len(logs), DIAGNOSTIC_LOG_TAIL_LIMIT), "health_state": "warning" if levels.get("error") else "ok_or_unknown", "stale_or_stall_detection": "manual GUI app; project-local GUI lock has heartbeat metadata; current worker state is reflected by queue statuses and log tail"}


def output_recovery_artifact_summary(output_dir: Path, *, max_entries: int = 200) -> dict[str, Any]:
    """Summarize resumable artifacts without exporting names or file contents."""
    try:
        target = resolve_output_dir(output_dir)
    except Exception as exc:
        return {"status": "invalid_output_dir", "reason": redact_text(exc), "names_exported": False}
    if not target.is_dir():
        return {"status": "absent", "count": 0, "names_exported": False}
    count = 0
    total = 0
    oldest = None
    newest = None
    truncated = False
    try:
        for item in target.iterdir():
            if count >= max_entries:
                truncated = True
                break
            if not item.is_file() or not (item.name.endswith(".part") or item.name.endswith(".ytdl") or ".part-Frag" in item.name):
                continue
            stat = item.stat()
            count += 1
            total += int(stat.st_size)
            oldest = stat.st_mtime if oldest is None else min(oldest, stat.st_mtime)
            newest = stat.st_mtime if newest is None else max(newest, stat.st_mtime)
        return {
            "status": "ok", "count": count, "total_bytes": total, "scan_cap": max_entries, "scan_truncated": truncated,
            "oldest_modified_utc": datetime.fromtimestamp(oldest, timezone.utc).isoformat() if oldest else None,
            "newest_modified_utc": datetime.fromtimestamp(newest, timezone.utc).isoformat() if newest else None,
            "names_exported": False, "scope": "top-level .part/.ytdl artifacts only",
        }
    except Exception as exc:
        return {"status": "unavailable", "reason": redact_text(exc), "count": count, "names_exported": False}


def download_archive_summary(settings: Any, enabled: Optional[bool] = None) -> dict[str, Any]:
    """Return bounded archive metadata, never IDs or full contents.

    Current callers pass ``DownloadSettings``. The two-argument form remains a
    narrow compatibility boundary for diagnostics that inspect the older
    output-folder archive.
    """
    if isinstance(settings, DownloadSettings):
        if not settings.use_archive:
            return {"status": "disabled", "entries": None, "contents_exported": False}
        target = download_archive_path(settings)
        variant = duplicate_variant_key(settings)
    else:
        if not enabled:
            return {"status": "disabled", "entries": None, "contents_exported": False}
        target = resolve_output_dir(settings) / "download-archive.txt"
        variant = "legacy-global"
    try:
        if not target.is_file():
            return {"status": "absent", "path": redact_path(target), "variant": variant, "entries": 0, "contents_exported": False}
        size = target.stat().st_size
        if size > 10 * 1024 * 1024:
            return {"status": "oversize_not_counted", "path": redact_path(target), "variant": variant, "bytes": size, "hash": sha256_file(target), "contents_exported": False}
        with target.open("rb") as handle:
            entries = sum(1 for line in handle if line.strip())
        return {"status": "ok", "path": redact_path(target), "variant": variant, "bytes": size, "entries": entries, "hash": sha256_file(target), "contents_exported": False}
    except Exception as exc:
        return {"status": "unavailable", "reason": redact_text(exc), "contents_exported": False}


def worker_control_summary(*, max_entries: int = 200) -> dict[str, Any]:
    """Summarize isolated-worker control artifacts without exposing names or URLs."""
    folder = worker_task_dir()
    if not folder.exists():
        return {
            "status": "absent",
            "active_specs": 0,
            "cancel_markers": 0,
            "temporary_files": 0,
            "stale_files": 0,
            "scan_truncated": False,
            "names_exported": False,
        }
    counts = {".json": 0, ".cancel": 0, ".tmp": 0}
    stale = 0
    scanned = 0
    truncated = False
    cutoff = time.time() - (24 * 60 * 60)
    try:
        for path in folder.iterdir():
            if scanned >= max_entries:
                truncated = True
                break
            if not path.is_file() or path.suffix.lower() not in counts:
                continue
            scanned += 1
            counts[path.suffix.lower()] += 1
            try:
                if path.stat().st_mtime < cutoff:
                    stale += 1
            except OSError:
                continue
        return {
            "status": "ok",
            "active_specs": counts[".json"],
            "cancel_markers": counts[".cancel"],
            "temporary_files": counts[".tmp"],
            "stale_files": stale,
            "stale_after_seconds": 24 * 60 * 60,
            "scan_cap": max_entries,
            "scan_truncated": truncated,
            "names_exported": False,
            "contents_exported": False,
        }
    except OSError as exc:
        return {
            "status": "unavailable",
            "reason": redact_text(exc),
            "names_exported": False,
            "contents_exported": False,
        }


def resume_state_summary(settings: dict[str, Any], jobs_summary: dict[str, Any]) -> dict[str, Any]:
    statuses = jobs_summary.get("status_counts", {})
    remaining = sum(count for status, count in statuses.items() if status not in {"Done", "Skipped duplicate", "Cancelled", "Failed"})
    try:
        output_target = resolve_output_dir(settings.get("output_dir") or default_download_dir())
    except Exception:
        output_target = default_download_dir()
    diagnostic_settings = DownloadSettings(
        output_dir=output_target,
        mode=str(settings.get("mode") or "Video (best MP4)"),
        max_height=settings.get("max_height") if isinstance(settings.get("max_height"), int) else 1080,
        custom_format=str(settings.get("custom_format") or ""),
        include_playlist=bool(settings.get("include_playlist")),
        embed_metadata=bool(settings.get("embed_metadata", True)),
        write_subtitles=bool(settings.get("write_subtitles")),
        restrict_filenames=bool(settings.get("restrict_filenames", True)),
        use_archive=bool(settings.get("use_archive")),
        rate_limit_bytes=settings.get("rate_limit_bytes") if isinstance(settings.get("rate_limit_bytes"), int) else None,
        prefer_mp4=bool(settings.get("prefer_mp4", True)),
        ffmpeg_location=None,
        hide_media=bool(settings.get("hide_media", HIDE_MEDIA_DEFAULT)),
        smart_resilience=bool(settings.get("smart_resilience", SMART_RESILIENCE_DEFAULT)),
    )
    archive_path = redact_path(download_archive_path(diagnostic_settings)) if diagnostic_settings.use_archive else None
    return {
        "remaining_work_count": remaining,
        "output_dir_redacted": redact_path(output_target),
        "download_archive_redacted": archive_path,
        "download_archive_summary": download_archive_summary(diagnostic_settings),
        "media_index_summary": media_index_summary(),
        "site_tolerance_summary": site_tolerance_summary(),
        "partial_download_summary": output_recovery_artifact_summary(output_target),
        "queue_recovery": queue_recovery_diagnostic_summary(),
        "isolated_worker_controls": worker_control_summary(),
        "safe_resume_notes": "Unfinished GUI queue work is atomically journaled under state/queue-recovery.json and restored as Queued; .part files remain resumable; isolated worker specifications and cancel markers are short-lived, bounded, project-local, excluded from exports, and stale controls are pruned; duplicate protection combines canonical queue URLs, output-variant-scoped yt-dlp archive IDs, a verified local media index, and no-overwrite output handling; the privacy-minimized site-tolerance ledger keeps normal fragment concurrency at 3 or 5 and uses 1 only for recovery/manual rate caps.",
        "state_files_included": "summary/hash only; raw queue URLs, archive IDs, partial filenames, and state bytes are not included",
    }



def integrity_state_summary(jobs_summary: dict[str, Any], run_context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    run_context = run_context or {}
    lock_snapshot = run_context.get("instance_lock") or {"status": "not_applicable", "reason": "CLI does not acquire the GUI lock"}
    return {
        "single_instance": {"status": "implemented_for_gui", "lock": lock_snapshot, "second_launch_behavior": "clear rejection; stale dead or PID-reused owner can be recovered only after liveness/start-signature verification; live owner is never broken solely for heartbeat age"},
        "config_state_migration": {"status": "active", "current_schema_versions": {"queue_recovery": QUEUE_STATE_SCHEMA_VERSION, "diagnostic": DIAGNOSTIC_EXPORT_SCHEMA_VERSION}, "newer_schema_behavior": "read-only fail-safe; newer queue state is not overwritten", "rollback_path": "restore prior ZIP; queue journal can be retained for inspection or removed after backup"},
        "queue_backpressure": {"capacity": QUEUE_CAPACITY, "full_policy": "visible reject; no silent drop", "concurrency_limit": 1, "fragment_concurrency_policy": "normal site-aware cap=3 or 5; recovery/manual rate cap=1", "current_depth": jobs_summary.get("count", 0), "retry_policy": retry_policy_snapshot(), "shutdown_drain": f"signal isolated worker, force-stop its process tree after {CANCEL_GRACE_SECONDS:.1f}s if blocked, then poll GUI worker for up to {SHUTDOWN_GRACE_SECONDS:.0f}s; atomically preserve unfinished queue before exit"},
        "download_integrity": {"selected_format_check": True, "drm_fail_closed": True, "known_disk_guard": True, "abort_unavailable_fragments": True, "ffprobe_after_move": True, "duplicate_guard": "canonical queue key + output-variant-scoped yt-dlp archive + verified media index + no-overwrite", "non_destructive_failure": "failed media is retained for inspection"},
        "operational_reports": {"schema_version": EXPORT_SCHEMA_VERSION, "atomic_writes": True, "cli_checkpoint_policy": "initial, every job for <=10 jobs, every five jobs for larger queues, and final", "destination_collision_guard": "report and diagnostic files must differ", "integrity_ledger": True},
    }



def smoke_risk_summary(settings: dict[str, Any], dependencies: dict[str, Any], collector_failures: list[dict[str, str]]) -> dict[str, Any]:
    js = javascript_runtime_snapshot(execute_versions=False)
    return {
        "preflight_snapshot": {
            "yt_dlp_installed": safe_package_version("yt-dlp").get("installed", False),
            "ffmpeg_detected": bool(find_ffmpeg_location()),
            "ffprobe_detected": bool(find_executable("ffprobe")),
            "javascript_runtime_detected": bool(js.get("selected")),
            "tkinter_available": tk is not None and TK_IMPORT_ERROR is None,
            "format_selector": redact_text(settings.get("format_selector", "unavailable")),
            "collector_failures": collector_failures,
        },
        "export_reliability_checks": {
            "max_physical_files": DIAGNOSTIC_MAX_FILES,
            "allowlisted_plan": True,
            "self_exclusion": True,
            "offline_safe_read_only": True,
            "same_volume_temp_zip": True,
            "integrity_test_before_finalize": True,
            "atomic_finalize": True,
            "minimal_fallback_on_collector_failure": True,
            "normal_report_schema": EXPORT_SCHEMA_VERSION,
            "normal_report_integrity_ledger": True,
            "cli_atomic_checkpointing": True,
            "report_diagnostic_collision_guard": True,
            "cli_diagnostics_survive_missing_tkinter": True,
            "explicit_gui_dispatch": True,
            "gui_hidden_window_preflight": True,
            "gui_startup_failure_persistent_log": True,
            "asset_metadata_schema": ASSET_METADATA_SCHEMA_VERSION,
            "asset_metadata_reconciliation": True,
            "key_asset_header_check": True,
            "zip_comment_metadata": True,
            "no_per_file_sidecar_bloat": True,
        },
        "risk_tier": "low-to-moderate desktop utility downloading untrusted media from user-provided URLs",
        "update_impact": "cancellation, isolated worker lifecycle, shutdown, CLI interruption, diagnostics, tests, and docs; download formats, duplicate behavior, and persistent state schemas preserved",
        "runtime_safeguards": [
            "download and format-listing work runs in a separately owned worker process",
            "Stop uses cooperative cancellation followed by bounded escalation",
            "Force Stop terminates the owned worker tree while preserving resumable partial data",
            "duplicate checks, adaptive resilience, visible-media defaults, and final verification remain enabled",
        ],
        "verification_scope": {
            "offline_checks": ["source syntax", "safety unit tests", "diagnostic redaction and archive integrity"],
            "not_exercised": ["real third-party media download", "provider-specific extractor behavior"],
        },
        "distribution_safety": {
            "source_only": True,
            "bundled_executables": False,
            "obfuscation": False,
            "elevation_or_persistence": False,
            "silent_dependency_installation": False,
        },
        "implemented_controls": [
            "isolated yt-dlp worker process for downloads and format listing",
            "cooperative cancellation with bounded hard-stop escalation",
            "process-tree cleanup that preserves resumable partial data",
            "CLI interruption through the same worker boundary",
            "redacted local-only support diagnostics",
        ],
        "known_limits": [
            "No live provider/status/documentation checks during export",
            "Size estimates may be unavailable or approximate",
            "If ffprobe is absent, verification falls back to file existence/nonzero size",
        ],
    }



def collect_with_failure_isolation(name: str, collector: Callable[[], Any], failures: list[dict[str, str]]) -> Any:
    try:
        return collector()
    except Exception as exc:
        failures.append({"collector": name, "reason": redact_text(exc), "timestamp_utc": utc_now_iso()})
        return {"status": "unavailable", "collector": name, "reason": redact_text(exc)}


def build_diagnostic_snapshot(
    jobs: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    settings: dict[str, Any],
    dependencies: dict[str, Any],
    run_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a redacted, local-only support diagnostic snapshot."""
    generated_at = utc_now_iso()
    export_id = make_run_id("export")
    run_context = dict(run_context or {})
    run_context.setdefault("run_id", make_run_id("diagnostic"))
    run_context.setdefault("mode", "unknown")
    run_context.setdefault("started_at_utc", "unknown")
    run_context.setdefault("elapsed_seconds", None)
    collector_failures: list[dict[str, str]] = []
    sanitized_settings = redact_for_export(settings)
    sanitized_dependencies = redact_for_export(dependencies)
    jobs_summary = collect_with_failure_isolation("queue", lambda: sanitize_jobs_for_diagnostics(jobs), collector_failures)
    public_files = collect_with_failure_isolation("public_files", project_file_manifest, collector_failures)
    diagnostic_asset_metadata = {
        "metadata_schema": ASSET_METADATA_SCHEMA_VERSION,
        "asset_id": f"SVD-DIAGNOSTIC-{export_id.upper()}",
        "title": f"{APP_NAME} Diagnostic Export",
        "asset_class": "diagnostic",
        "role": "support-export",
        "project_slug": PROJECT_SLUG,
        "version": APP_VERSION,
        "status": "generated",
        "sensitivity": "redacted-support-data",
        "source_of_truth": False,
        "tags": ["safe-video-downloader", "diagnostic", "local-only"],
        "aliases": ["program diagnostics", "support export"],
        "lineage": "derived from cached/in-memory state and local read-only evidence; no live provider probe",
        "generated_at_utc": generated_at,
    }
    if isinstance(public_files, dict):
        public_files["diagnostic_export_asset"] = diagnostic_asset_metadata
    system = collect_with_failure_isolation("system", lambda: system_snapshot(settings if isinstance(settings, dict) else {}), collector_failures)
    portability = collect_with_failure_isolation("portability", lambda: path_portability_snapshot(settings if isinstance(settings, dict) else {}), collector_failures)
    compatibility = collect_with_failure_isolation("compatibility", lambda: compatibility_matrix(settings if isinstance(settings, dict) else {}), collector_failures)
    launcher = collect_with_failure_isolation("launcher", lambda: launcher_snapshot(run_context), collector_failures)
    dependency_provenance = collect_with_failure_isolation("dependency_provenance", dependency_provenance_snapshot, collector_failures)
    effective_inputs = collect_with_failure_isolation("effective_inputs", lambda: effective_input_snapshot(settings if isinstance(settings, dict) else {}, jobs_summary if isinstance(jobs_summary, dict) else {}), collector_failures)
    platform_api = collect_with_failure_isolation("platform_api", lambda: platform_api_snapshot(settings if isinstance(settings, dict) else {}), collector_failures)
    time_trace = collect_with_failure_isolation("time_trace", lambda: time_trace_summary(run_context, logs), collector_failures)
    settings_fingerprint = stable_fingerprint(effective_inputs) if isinstance(effective_inputs, dict) else stable_fingerprint(sanitized_settings)
    troubleshooting = collect_with_failure_isolation("troubleshooting", lambda: troubleshooting_evidence(run_context, settings_fingerprint, logs), collector_failures)
    health = collect_with_failure_isolation("health", lambda: run_history_health_summary(jobs_summary if isinstance(jobs_summary, dict) else {}, logs), collector_failures)
    resume = collect_with_failure_isolation("resume_state", lambda: resume_state_summary(settings if isinstance(settings, dict) else {}, jobs_summary if isinstance(jobs_summary, dict) else {}), collector_failures)
    integrity = collect_with_failure_isolation("integrity", lambda: integrity_state_summary(jobs_summary if isinstance(jobs_summary, dict) else {}, run_context), collector_failures)
    smoke = collect_with_failure_isolation("smoke_risk", lambda: smoke_risk_summary(settings if isinstance(settings, dict) else {}, sanitized_dependencies if isinstance(sanitized_dependencies, dict) else {}, collector_failures), collector_failures)
    privacy = {
        "classification": {"public": ["application name/version", "documentation filenames", "dependency package names"], "redacted_support_data": ["settings shape", "redacted paths", "format selector", "status counts"], "sensitive_minimized": ["queued URLs", "local paths", "errors/logs"], "secret_never_include": ["API keys", "passwords", "tokens", "cookies", "browser profiles", "local IP/MAC", "account IDs", "downloaded media"]},
        "redaction_policy": "URLs are replaced by host plus stable hash prefix; paths are shortened; common secrets and identifiers are removed.",
    }
    support_summary = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "diagnostic_schema_version": DIAGNOSTIC_EXPORT_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "current_state": "Diagnostic export created from in-memory GUI/CLI state and local metadata only.",
        "recent_issue_focus": "Cancellation: review per-job worker_process/cancellation telemetry, recent logs around Stop/Force Stop, queue recovery, partial-download summary, and worker-task cleanup evidence.",
        "first_recovery_step": "Run the offline tests, retry one permitted URL, and create a fresh redacted diagnostic export if the problem repeats.",
        "share_note": "Review before sharing; full queued URLs are intentionally not included.",
        "export_scope": support_export_scope_snapshot(),
    }
    return {
        "schema_version": DIAGNOSTIC_EXPORT_SCHEMA_VERSION,
        "max_physical_files": DIAGNOSTIC_MAX_FILES,
        "generated_at_utc": generated_at,
        "export_id": export_id,
        "diagnostic_asset_metadata": diagnostic_asset_metadata,
        "privacy": privacy,
        "support_summary": support_summary,
        "public_files": public_files,
        "release_notes": {"current_version": APP_VERSION, "rollback": "Use version control to restore a prior reviewed revision."},
        "effective_inputs": effective_inputs,
        "system_snapshot": system,
        "path_portability": portability,
        "compatibility_matrix": compatibility,
        "launcher_snapshot": launcher,
        "dependency_provenance": dependency_provenance,
        "platform_api_snapshot": platform_api,
        "recent_logs": sanitize_log_entries(logs),
        "queue_summary": jobs_summary,
        "time_trace": time_trace,
        "troubleshooting": troubleshooting,
        "run_history_health": health,
        "resume_state": resume,
        "integrity_state": integrity,
        "smoke_risk_summary": smoke,
        "collector_failures": collector_failures,
    }


def diagnostic_readme_text(snapshot: dict[str, Any]) -> str:
    plan_note = f"This archive is capped at {DIAGNOSTIC_MAX_FILES} files and was written with same-folder temp ZIP finalization plus integrity testing."
    return (
        f"{APP_NAME} program diagnostic export\n"
        f"Asset ID: {snapshot.get('diagnostic_asset_metadata', {}).get('asset_id', 'unavailable')}\n"
        f"Version/status: {APP_VERSION} / generated\n"
        f"Generated UTC: {snapshot.get('generated_at_utc')}\n"
        f"Schema: {snapshot.get('schema_version')} / metadata {ASSET_METADATA_SCHEMA_VERSION}\n\n"
        "Open 01-support-summary.md first, then 09-recent-log-tail.txt and 07-launcher-dependencies.json for common failures.\n"
        f"{plan_note}\n\n"
        "Privacy: full queued URLs, downloaded media, cookies, credentials, browser profiles, IP/MAC addresses, account IDs, and product/license keys are not intentionally included.\n"
    )


def diagnostic_markdown_summary(snapshot: dict[str, Any]) -> str:
    summary = snapshot.get("support_summary", {})
    jobs = snapshot.get("integrity_state", {}).get("queue_backpressure", {})
    health = snapshot.get("run_history_health", {})
    resume = snapshot.get("resume_state", {})
    system = snapshot.get("system_snapshot", {})
    portability = system.get("path_portability", {}) if isinstance(system, dict) else {}
    deps_root = snapshot.get("dependency_provenance", {})
    deps = deps_root.get("helper_binaries", {}) if isinstance(deps_root, dict) else {}
    packages = deps_root.get("python_packages", {}) if isinstance(deps_root, dict) else {}
    ffmpeg_present = deps.get("ffmpeg", {}).get("present") if isinstance(deps, dict) else None
    ffprobe_present = deps.get("ffprobe", {}).get("present") if isinstance(deps, dict) else None
    js = deps.get("javascript_runtimes", {}) if isinstance(deps, dict) else {}
    selected_js = js.get("selected") if isinstance(js, dict) else None
    if isinstance(selected_js, dict):
        javascript_runtime = f"{selected_js.get('name', 'unknown')} ({selected_js.get('status', 'unknown')})"
    else:
        javascript_runtime = "none"
    deno_status = next(
        (str(item.get("status", "unknown")) for item in js.get("candidates", []) if isinstance(item, dict) and item.get("name") == "deno"),
        "unknown",
    ) if isinstance(js, dict) else "unknown"
    yt_dlp_version = packages.get("yt-dlp", {}).get("version") if isinstance(packages, dict) else None
    runtime = system.get("runtime", {}) if isinstance(system, dict) else {}
    report_integrity = snapshot.get("integrity_state", {}).get("operational_reports", {})
    queue_recovery = resume.get("queue_recovery", {}) if isinstance(resume, dict) else {}
    collector_failures = snapshot.get("collector_failures", [])
    return (
        f"# {APP_NAME} diagnostic support summary\n\n"
        f"- App version: {summary.get('version', APP_VERSION)}\n"
        f"- Diagnostic schema: {snapshot.get('schema_version')}\n"
        f"- Generated UTC: {snapshot.get('generated_at_utc')}\n"
        f"- Export ID: {snapshot.get('export_id')}\n"
        f"- Current state: {summary.get('current_state', '')}\n"
        f"- Queue depth/capacity: {jobs.get('current_depth', 'unknown')}/{jobs.get('capacity', 'unknown')}\n"
        f"- Queue recovery: {queue_recovery.get('status', 'unknown')} ({queue_recovery.get('recoverable_job_count', 0)} recoverable)\n"
        f"- Health state: {health.get('health_state', 'unknown')}\n"
        f"- Path portability: {portability.get('status', 'unknown')} / stale findings {portability.get('stale_absolute_path_scan', {}).get('finding_count_returned', 'unknown')}\n"
        f"- Python: {runtime.get('python_version', 'unknown')}\n"
        f"- yt-dlp: {yt_dlp_version or 'not installed'}\n"
        f"- FFmpeg / FFprobe detected: {ffmpeg_present} / {ffprobe_present}\n"
        f"- JavaScript runtime selected: {javascript_runtime}; Deno status: {deno_status}\n"
        f"- Operational report schema/atomic writes: {report_integrity.get('schema_version', 'unknown')} / {report_integrity.get('atomic_writes', 'unknown')}\n"
        f"- Collector failures: {len(collector_failures) if isinstance(collector_failures, list) else 'unknown'}\n"
        f"- Export scope: {summary.get('export_scope', {}).get('status', 'unknown')}\n\n"
        "## Privacy\n\nQueued URLs are redacted to host plus hash. Local paths are shortened. Secrets, cookies, browser profiles, downloaded media, IP/MAC addresses, account IDs, and license/product keys are not intentionally included.\n\n"
        "## First recovery step\n\n"
        f"{summary.get('first_recovery_step', 'Review recent logs and dependency snapshot.')}\n"
    )


def diagnostic_known_good_text(snapshot: dict[str, Any]) -> str:
    release = snapshot.get("release_notes", {})
    return (
        "# Release and rollback notes\n\n"
        f"- Current version: {release.get('current_version', APP_VERSION)}\n"
        f"- Rollback path: {release.get('rollback', '')}\n"
        f"- Update impact: {snapshot.get('smoke_risk_summary', {}).get('update_impact', '')}\n"
    )


def build_diagnostic_archive_entries(snapshot: dict[str, Any]) -> list[tuple[str, bytes | str]]:
    redacted_log_text = logs_to_text(snapshot.get("recent_logs", [])) if snapshot.get("recent_logs") else "No in-memory log entries were captured.\n"
    persistent_tail = latest_persistent_log_tail()
    if persistent_tail:
        redacted_log_text += "\n--- Latest persistent run log tail (redacted) ---\n" + persistent_tail
    entries: list[tuple[str, bytes | str]] = [
        ("README-diagnostics.txt", diagnostic_readme_text(snapshot)),
        ("01-support-summary.md", diagnostic_markdown_summary(snapshot)),
        ("02-public-files.json", diagnostic_json(snapshot.get("public_files", {}))),
        ("03-release-notes.md", diagnostic_known_good_text(snapshot)),
        ("04-redacted-effective-config.json", diagnostic_json(snapshot.get("effective_inputs", {}))),
        ("05-system-snapshot.json", diagnostic_json(snapshot.get("system_snapshot", {}))),
        ("06-compatibility-matrix.json", diagnostic_json(snapshot.get("compatibility_matrix", {}))),
        ("07-launcher-dependencies.json", diagnostic_json({"launcher": snapshot.get("launcher_snapshot", {}), "dependencies": snapshot.get("dependency_provenance", {})})),
        ("08-platform-inputs.json", diagnostic_json(snapshot.get("platform_api_snapshot", {}))),
        ("09-recent-log-tail.txt", redacted_log_text),
        ("10-time-trace.json", diagnostic_json(snapshot.get("time_trace", {}))),
        ("11-troubleshooting-evidence.json", diagnostic_json(snapshot.get("troubleshooting", {}))),
        ("12-run-history-health.json", diagnostic_json(snapshot.get("run_history_health", {}))),
        ("13-resume-state.json", diagnostic_json({"resume_state": snapshot.get("resume_state", {}), "queue_summary": snapshot.get("queue_summary", {})})),
        ("14-instance-migration-queue.json", diagnostic_json(snapshot.get("integrity_state", {}))),
        ("15-smoke-risk-summary.json", diagnostic_json(snapshot.get("smoke_risk_summary", {}))),
    ]
    names_after_plan = [name for name, _payload in entries] + ["16-export-plan.json"]
    entry_integrity: list[dict[str, Any]] = []
    for entry_name, payload in entries:
        payload_bytes = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
        entry_integrity.append({
            "name": entry_name,
            "size_bytes": len(payload_bytes),
            "sha256": hashlib.sha256(payload_bytes).hexdigest(),
        })
    export_plan = {
        "max_physical_files": DIAGNOSTIC_MAX_FILES,
        "categories_are_logical_not_files": True,
        "allowlist_before_zip": True,
        "self_exclusion": "current temp/final archive, output/staging descendants, prior exports are not sourced into this archive",
        "offline_read_only": True,
        "collector_failure_isolation": True,
        "zip_finalization": "same-folder temp ZIP -> testzip integrity check -> entry count check -> atomic replace",
        "archive_hash_policy": "final ZIP hash is computed after finalization by the writer and is not stored inside itself",
        "entry_integrity": entry_integrity,
        "entry_integrity_note": "SHA-256 covers every payload except this export-plan file; the final ZIP hash is emitted after atomic finalization.",
        "final_entry_count": len(names_after_plan),
        "final_entries": names_after_plan,
        "collector_failures": snapshot.get("collector_failures", []),
        "asset_metadata": {
            "diagnostic_asset": snapshot.get("diagnostic_asset_metadata", {}),
            "public_file_reconciliation": snapshot.get("public_files", {}).get("metadata_reconciliation", {}),
            "policy": "diagnostics record live hashes for allowlisted project files and create no sidecar metadata",
        },
        "excluded_by_default": ["downloaded media", "prior exports", ".venv", "build", "dist", "__pycache__", "browser data", "cookies", "credentials", "raw queued URLs"],
    }
    entries.append(("16-export-plan.json", diagnostic_json(export_plan)))
    if len(entries) > DIAGNOSTIC_MAX_FILES:
        entries = entries[: DIAGNOSTIC_MAX_FILES - 1] + [("16-export-plan.json", diagnostic_json(export_plan))]
    return entries


def write_diagnostic_zip(path: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    path = path.expanduser()
    if path.suffix.lower() != ".zip":
        path = path.with_suffix(".zip")
    try:
        entries = build_diagnostic_archive_entries(snapshot)
    except Exception as exc:
        failure = {"collector": "archive_plan", "reason": redact_text(exc), "timestamp_utc": utc_now_iso()}
        entries = [
            ("README-diagnostics.txt", f"{APP_NAME} minimal diagnostic fallback\nGenerated UTC: {utc_now_iso()}\nAdvanced archive planning failed; recovery evidence was preserved where possible.\n"),
            ("01-support-summary.md", "# Minimal diagnostic fallback\n\nReview 02-public-files.json and 03-export-failure.json, then rerun the offline tests.\n"),
            ("02-public-files.json", safe_json_dumps(snapshot.get("public_files", {"app": APP_NAME, "version": APP_VERSION}))),
            ("03-export-failure.json", safe_json_dumps({"failure": failure, "collector_failures": snapshot.get("collector_failures", []), "privacy": snapshot.get("privacy", {})})),
        ]
    export_asset = snapshot.get("diagnostic_asset_metadata", {}) if isinstance(snapshot, dict) else {}
    return atomic_write_zip_entries(
        path,
        entries,
        max_files=DIAGNOSTIC_MAX_FILES,
        zip_comment=(
            f"asset_id={export_asset.get('asset_id', 'SVD-DIAGNOSTIC')};"
            f"project={PROJECT_SLUG};version={APP_VERSION};status=generated;"
            "tags=diagnostic,local-only;public-files=02-public-files.json"
        ),
    )


def build_ydl_options(
    settings: DownloadSettings,
    ui_queue: "queue.Queue[tuple[Any, ...]]",
    item_id: str,
    stop_event: threading.Event,
    *,
    resilience_profile: str = "normal",
    runtime_telemetry: Optional[dict[str, Any]] = None,
    normal_fragment_limit: Optional[int] = None,
) -> dict[str, Any]:
    """Build bounded, integrity-first yt-dlp API options."""
    output_dir = settings.output_dir
    postprocessors: list[dict[str, Any]] = []
    mode = settings.mode
    has_ffmpeg = bool(settings.ffmpeg_location)
    profile = resilience_profile_snapshot(settings, resilience_profile, normal_fragment_limit=normal_fragment_limit)
    retry_sleep = {
        "http": make_retry_sleep_function(1.0, 20.0),
        "fragment": make_retry_sleep_function(1.0, 20.0),
        "extractor": make_retry_sleep_function(1.0, 8.0),
        "file_access": make_retry_sleep_function(0.5, 4.0),
    }
    opts: dict[str, Any] = {
        "outtmpl": str(output_dir / DEFAULT_OUTPUT_TEMPLATE),
        "format": build_format_selector(settings),
        "noplaylist": not settings.include_playlist,
        "restrictfilenames": settings.restrict_filenames,
        "windowsfilenames": True,
        "continuedl": True,
        "overwrites": False,
        "nopart": False,
        "retries": HTTP_RETRIES,
        "fragment_retries": FRAGMENT_RETRIES,
        "extractor_retries": EXTRACTOR_RETRIES,
        "file_access_retries": FILE_ACCESS_RETRIES,
        "retry_sleep_functions": retry_sleep,
        "socket_timeout": int(profile["socket_timeout_seconds"]),
        "concurrent_fragment_downloads": int(profile["concurrent_fragments"]),
        "skip_unavailable_fragments": False,
        "check_formats": "selected",
        "progress_delta": PROGRESS_UPDATE_SECONDS,
        "cachedir": str(state_dir() / "yt-dlp-cache"),
        "no_color": True,
        "quiet": True,
        "no_warnings": False,
        "logger": QueueLogger(ui_queue),
    }
    def duplicate_match_filter(info: dict[str, Any], *, incomplete: bool = False) -> Optional[str]:
        if incomplete or not settings.use_archive:
            return None
        duplicate = detect_indexed_duplicate(info, settings)
        if runtime_telemetry is not None:
            runtime_telemetry["duplicate_detection"] = duplicate
        ui_queue.put(("job_result", item_id, {"duplicate_detection": duplicate}))
        if duplicate.get("status") == "duplicate":
            ui_queue.put(("log", "info", "Duplicate guard: verified matching media already exists; transfer skipped."))
            return "Duplicate guard: verified matching media already exists"
        if duplicate.get("status") == "stale_entry_repaired":
            ui_queue.put(("log", "warning", "Duplicate guard repaired a stale media-index entry and will download again."))
        return None

    opts["match_filter"] = duplicate_match_filter
    js = javascript_runtime_snapshot(execute_versions=True)
    selected_js = js.get("selected")
    if isinstance(selected_js, dict) and selected_js.get("path"):
        opts["js_runtimes"] = {str(selected_js.get("name")): {"path": str(selected_js.get("path"))}}
    if settings.prefer_mp4 and (mode.startswith("Video") or mode.startswith("Custom")):
        opts["format_sort"] = ["res", "fps", "hdr:12", "vcodec:h264", "acodec:aac"]
    if settings.ffmpeg_location:
        opts["ffmpeg_location"] = settings.ffmpeg_location
    if settings.rate_limit_bytes:
        opts["ratelimit"] = settings.rate_limit_bytes
    if profile.get("throttled_rate_bytes"):
        opts["throttledratelimit"] = int(profile["throttled_rate_bytes"])
    if profile.get("sleep_requests_seconds"):
        opts["sleep_interval_requests"] = float(profile["sleep_requests_seconds"])
    if profile.get("download_sleep_min_seconds"):
        opts["sleep_interval"] = float(profile["download_sleep_min_seconds"])
        opts["max_sleep_interval"] = float(profile["download_sleep_max_seconds"])
    if runtime_telemetry is not None:
        runtime_telemetry["active_profile"] = dict(profile)
    if settings.use_archive:
        archive_state = prepare_download_archive(settings)
        opts["download_archive"] = str(archive_state.get("path") or download_archive_path(settings))
        if runtime_telemetry is not None:
            runtime_telemetry["download_archive"] = {
                "status": archive_state.get("status"),
                "variant": duplicate_variant_key(settings),
                "path_redacted": redact_path(opts["download_archive"]),
            }
    if mode.startswith("Video"):
        if has_ffmpeg:
            opts["merge_output_format"] = "mp4/mkv"
        if settings.write_subtitles:
            opts.update({"writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["en.*", "en"]})
            if has_ffmpeg:
                opts["embedsubtitles"] = True
    elif mode.startswith("Custom"):
        if settings.prefer_mp4 and has_ffmpeg:
            opts["merge_output_format"] = "mp4/mkv"
    elif mode == "Audio (MP3)" and has_ffmpeg:
        postprocessors.append({"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"})
    if settings.embed_metadata and has_ffmpeg:
        postprocessors.append({"key": "FFmpegMetadata"})
    if postprocessors:
        opts["postprocessors"] = postprocessors

    last_status: Optional[str] = None
    observed_peak_speed = 0.0
    observed_ewma_speed: Optional[float] = None
    slow_samples = 0
    def progress_hook(data: dict[str, Any]) -> None:
        nonlocal last_status, observed_peak_speed, observed_ewma_speed, slow_samples
        if stop_event.is_set():
            raise DownloadCancelled("Cancelled by user")
        status = data.get("status")
        if status == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            percent = max(0.0, min(100.0, downloaded / total * 100.0)) if total else None
            raw_speed = data.get("speed")
            try:
                numeric_speed = float(raw_speed) if raw_speed is not None else None
            except (TypeError, ValueError):
                numeric_speed = None
            if numeric_speed is not None and numeric_speed >= 0:
                observed_peak_speed = max(observed_peak_speed, numeric_speed)
                observed_ewma_speed = numeric_speed if observed_ewma_speed is None else (0.25 * numeric_speed + 0.75 * observed_ewma_speed)
                throttle_floor = profile.get("throttled_rate_bytes")
                if throttle_floor and numeric_speed < float(throttle_floor):
                    slow_samples += 1
                else:
                    slow_samples = 0
                if runtime_telemetry is not None:
                    runtime_telemetry["network_observation"] = {
                        "last_speed_bytes_per_second": round(numeric_speed, 2),
                        "ewma_speed_bytes_per_second": round(observed_ewma_speed, 2),
                        "peak_speed_bytes_per_second": round(observed_peak_speed, 2),
                        "consecutive_below_throttle_floor_samples": slow_samples,
                        "throttle_floor_bytes_per_second": throttle_floor,
                    }
            speed = format_bytes(raw_speed) + "/s"
            eta = format_eta(data.get("eta"))
            fragment = data.get("fragment_index")
            fragment_count = data.get("fragment_count")
            extra = f" | fragment {fragment}/{fragment_count}" if fragment and fragment_count else ""
            text = f"Downloading {format_bytes(downloaded)} | {speed} | ETA {eta}{extra}" if percent is None else f"{percent:5.1f}% | {format_bytes(downloaded)} / {format_bytes(total)} | {speed} | ETA {eta}{extra}"
            ui_queue.put(("progress", percent, text))
            if last_status != "Downloading":
                ui_queue.put(("job_status", item_id, "Downloading"))
                last_status = "Downloading"
        elif status == "finished":
            filename = data.get("filename") or "downloaded file"
            safe_name = Path(str(filename)).name if filename else "downloaded file"
            ui_queue.put(("progress", 100.0, "Download finished. Post-processing and verification..."))
            ui_queue.put(("log", "info", f"Finished byte transfer: {redact_text(safe_name)}"))
            if last_status != "Processing":
                ui_queue.put(("job_status", item_id, "Processing"))
                last_status = "Processing"
        elif status == "error" and last_status != "Error":
            ui_queue.put(("job_status", item_id, "Error"))
            last_status = "Error"
    opts["progress_hooks"] = [progress_hook]
    return opts



def execute_download_job(
    yt_dlp_module: Any,
    url: str,
    settings: DownloadSettings,
    ui_queue: "queue.Queue[tuple[Any, ...]]",
    item_id: str,
    stop_event: threading.Event,
    telemetry: dict[str, Any],
    adaptive_state: Optional[AdaptiveRunState] = None,
    *,
    quiet: Optional[bool] = None,
) -> int:
    """Run one URL with a bounded session rebuild for transient failures.

    yt-dlp handles request/fragment retries inside each attempt. This wrapper
    adds exactly one fresh-session retry for network, rate-limit, or expired
    signed-URL failures. Existing .part files remain resumable.
    """
    state = adaptive_state or AdaptiveRunState(enabled=settings.smart_resilience)
    state.enabled = bool(settings.smart_resilience and state.enabled)
    maximum_attempts = SMART_OUTER_ATTEMPTS if state.enabled else 1
    profile = state.starting_profile()
    attempts: list[dict[str, Any]] = []
    tolerance = site_tolerance_decision(url, settings)
    normal_fragment_limit = int(tolerance.get("selected_fragment_limit") or FRAGMENT_CONCURRENCY_CONSERVATIVE)
    telemetry["site_tolerance"] = dict(tolerance)
    ui_queue.put((
        "log",
        "info",
        f"Segment tolerance: {normal_fragment_limit} concurrent fragment(s) selected ({tolerance.get('tier')}); normal mode is capped at 3 or 5 and recovery remains at 1.",
    ))
    stress_categories_seen: set[str] = set()
    telemetry["adaptive_resilience"] = {
        "enabled": state.enabled,
        "maximum_attempts": maximum_attempts,
        "initial_profile": profile,
        "attempts": attempts,
    }
    for attempt in range(1, maximum_attempts + 1):
        if stop_event.is_set():
            raise DownloadCancelled("Cancelled by user")
        attempt_started = time.monotonic()
        attempt_record: dict[str, Any] = {
            "attempt": attempt,
            "profile": profile,
            "started_at_utc": utc_now_iso(),
        }
        attempts.append(attempt_record)
        try:
            opts = build_ydl_options(
                settings,
                ui_queue,
                item_id,
                stop_event,
                resilience_profile=profile,
                runtime_telemetry=telemetry,
                normal_fragment_limit=normal_fragment_limit,
            )
            if quiet is not None:
                opts["quiet"] = bool(quiet)
            with yt_dlp_module.YoutubeDL(opts) as ydl:
                attach_safety_postprocessors(ydl, settings, ui_queue, item_id, stop_event, telemetry)
                result_code = int(ydl.download([url]))
            attempt_record.update({
                "outcome": "success" if result_code == 0 else "backend_exit",
                "exit_code": result_code,
                "elapsed_seconds": round(time.monotonic() - attempt_started, 3),
            })
            if result_code == 0 and "verification" not in telemetry and "duplicate_detection" not in telemetry:
                telemetry["duplicate_detection"] = {
                    "status": "archive_or_existing_output_skip",
                    "source": "yt-dlp_archive_or_no_overwrite",
                    "note": "No new final file was produced; yt-dlp download archive or existing-output protection may have skipped transfer.",
                }
            state.note_success(profile, attempt)
            new_media_verified = isinstance(telemetry.get("verification"), dict)
            preflight = telemetry.get("preflight") if isinstance(telemetry.get("preflight"), dict) else {}
            fragmented_transfer = bool(preflight.get("fragmented_transfer"))
            if result_code == 0 and new_media_verified and fragmented_transfer and settings.rate_limit_bytes is None:
                tolerance_event = "recovered_after_stress" if stress_categories_seen else "clean_success"
                tolerance_update = update_site_tolerance(url, tolerance_event, normal_fragment_limit)
                telemetry["site_tolerance"]["terminal_update"] = tolerance_update
            else:
                if settings.rate_limit_bytes is not None:
                    reason = "manual rate cap was active; capped transfers do not promote site tolerance"
                elif not new_media_verified:
                    reason = "no new verified media transfer completed"
                elif not fragmented_transfer:
                    reason = "selected protocol was not a segmented DASH/HLS/ISM transfer"
                else:
                    reason = "site-tolerance evidence was not applicable"
                telemetry["site_tolerance"]["terminal_update"] = {
                    "status": "not_updated",
                    "reason": reason,
                }
            telemetry["adaptive_resilience"].update({
                "terminal_profile": profile,
                "attempts_used": attempt,
                "recovered": attempt > 1,
                "run_state": state.snapshot(),
            })
            return result_code
        except (DownloadCancelled, KeyboardInterrupt):
            attempt_record.update({"outcome": "cancelled", "elapsed_seconds": round(time.monotonic() - attempt_started, 3)})
            raise
        except Exception as exc:
            category = classify_download_error(exc)
            attempt_record.update({
                "outcome": "failed",
                "error_category": category,
                "error": redact_text(exc),
                "elapsed_seconds": round(time.monotonic() - attempt_started, 3),
            })
            if category in {"network", "rate_limit", "stale_session"} and category not in stress_categories_seen:
                stress_categories_seen.add(category)
                tolerance_update = update_site_tolerance(url, category, normal_fragment_limit)
                telemetry["site_tolerance"]["stress_update"] = tolerance_update
                ui_queue.put((
                    "log",
                    "warning",
                    f"Site tolerance downgraded to the 3-fragment cap after {category.replace('_', ' ')} stress; recovery attempts use one fragment.",
                ))
            can_retry = state.enabled and is_adaptive_retryable(category) and attempt < maximum_attempts
            if not can_retry:
                telemetry["adaptive_resilience"].update({
                    "terminal_profile": profile,
                    "attempts_used": attempt,
                    "recovered": False,
                    "terminal_error_category": category,
                    "run_state": state.snapshot(),
                })
                raise
            next_profile = adaptive_retry_profile(category)
            delay = adaptive_retry_delay(category)
            state.note_retry(category, next_profile, delay)
            ui_queue.put((
                "log",
                "warning",
                f"Smart recovery: {category.replace('_', ' ')} detected. Rebuilding the network session in {delay:.0f}s with profile {next_profile}; resumable partial data will be reused.",
            ))
            ui_queue.put(("job_status", item_id, "Reconnecting"))
            if interruptible_wait(stop_event, delay):
                raise DownloadCancelled("Cancelled during reconnect cooldown")
            profile = next_profile
    raise RuntimeError("adaptive download loop exhausted without terminal result")


def worker_task_dir() -> Path:
    return state_dir() / "worker-tasks"


def prune_stale_worker_tasks(max_age_seconds: float = 24 * 60 * 60) -> None:
    """Remove only stale internal worker control files; never touch media partials."""
    folder = worker_task_dir()
    try:
        if not folder.exists():
            return
        cutoff = time.time() - max(60.0, float(max_age_seconds))
        for path in folder.iterdir():
            if not path.is_file() or path.suffix.lower() not in {".json", ".cancel", ".tmp"}:
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue
    except OSError:
        return


def worker_command(spec_path: Path) -> list[str]:
    """Return the same-runtime command for a hidden isolated worker."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker-job", str(spec_path)]
    return [sys.executable, str(Path(__file__).resolve()), "--worker-job", str(spec_path)]


def worker_process_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "cwd": str(app_base_dir()),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    if os.name == "nt":
        flags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        flags |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    return kwargs


def terminate_process_tree(proc: subprocess.Popen[Any]) -> dict[str, Any]:
    """Terminate a worker and its helper processes without touching the GUI."""
    result: dict[str, Any] = {
        "pid": getattr(proc, "pid", None),
        "requested": True,
        "method": None,
        "status": "already_exited" if proc.poll() is not None else "pending",
    }
    if proc.poll() is not None:
        return result
    if os.name == "nt":
        result["method"] = "taskkill_tree_force"
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=CANCEL_FORCE_WAIT_SECONDS,
            )
            result["taskkill_exit_code"] = completed.returncode
        except Exception as exc:
            result["taskkill_error"] = redact_text(exc)
            try:
                proc.kill()
                result["method"] = "process_kill_fallback"
            except Exception as fallback_exc:
                result["fallback_error"] = redact_text(fallback_exc)
    else:
        result["method"] = "process_group_term_kill"
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception as exc:
            result["term_error"] = redact_text(exc)
            try:
                proc.terminate()
            except Exception as fallback_exc:
                result["terminate_error"] = redact_text(fallback_exc)
        try:
            proc.wait(timeout=0.75)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception as exc:
                result["kill_error"] = redact_text(exc)
                try:
                    proc.kill()
                except Exception as fallback_exc:
                    result["kill_fallback_error"] = redact_text(fallback_exc)
    try:
        proc.wait(timeout=CANCEL_FORCE_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
    else:
        result["status"] = "stopped"
        result["exit_code"] = proc.returncode
    return result


class JsonLineEventSink:
    """Queue-compatible sink used by the isolated worker process."""

    def put(self, event: tuple[Any, ...]) -> None:
        payload = json.dumps(list(event), ensure_ascii=False, separators=(",", ":"), default=str)
        print(WORKER_EVENT_PREFIX + payload, flush=True)


def parse_worker_event_line(line: str) -> Optional[tuple[Any, ...]]:
    stripped = str(line).strip()
    if not stripped.startswith(WORKER_EVENT_PREFIX):
        return None
    try:
        payload = json.loads(stripped[len(WORKER_EVENT_PREFIX):])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list) or not payload:
        return None
    return tuple(payload)


def adaptive_state_from_snapshot(payload: Any) -> AdaptiveRunState:
    state = AdaptiveRunState()
    if not isinstance(payload, dict):
        return state
    for name in (
        "enabled", "caution_profile", "caution_jobs_remaining", "rate_limit_events",
        "network_events", "stale_session_events", "reconnect_attempts", "recovery_successes",
    ):
        if name in payload:
            try:
                setattr(state, name, payload[name])
            except Exception:
                pass
    history = payload.get("history")
    if isinstance(history, list):
        state.history = [dict(item) for item in history[-20:] if isinstance(item, dict)]
    return state


def update_adaptive_state_from_telemetry(state: AdaptiveRunState, telemetry: dict[str, Any]) -> None:
    adaptive = telemetry.get("adaptive_resilience")
    snapshot = adaptive.get("run_state") if isinstance(adaptive, dict) else None
    updated = adaptive_state_from_snapshot(snapshot)
    state.enabled = updated.enabled
    state.caution_profile = updated.caution_profile
    state.caution_jobs_remaining = updated.caution_jobs_remaining
    state.rate_limit_events = updated.rate_limit_events
    state.network_events = updated.network_events
    state.stale_session_events = updated.stale_session_events
    state.reconnect_attempts = updated.reconnect_attempts
    state.recovery_successes = updated.recovery_successes
    state.history = list(updated.history)


def _load_worker_spec(spec_path: Path) -> dict[str, Any]:
    resolved = spec_path.expanduser().resolve()
    expected_parent = worker_task_dir().resolve()
    if resolved.parent != expected_parent:
        raise ValueError("worker spec must be inside the project-local worker task folder")
    data = resolved.read_bytes()
    if len(data) > WORKER_SPEC_MAX_BYTES:
        raise ValueError("worker spec exceeds the bounded size limit")
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("worker spec root must be an object")
    if payload.get("schema_version") != WORKER_SPEC_SCHEMA_VERSION:
        raise ValueError("unsupported worker spec schema")
    if payload.get("app_version") != APP_VERSION:
        raise ValueError("worker spec application version does not match this executable")
    return payload


def _watch_cancel_marker(marker: Path, stop_event: threading.Event, done_event: threading.Event) -> None:
    while not done_event.wait(CANCEL_POLL_SECONDS):
        try:
            if marker.exists():
                stop_event.set()
                return
        except OSError:
            continue


def run_isolated_worker(spec_path: Path) -> int:
    """Hidden child-process entrypoint for interruptible network work."""
    prepend_tools_to_path()
    sink = JsonLineEventSink()
    done_event = threading.Event()
    watcher: Optional[threading.Thread] = None
    try:
        spec = _load_worker_spec(spec_path)
        task = str(spec.get("task") or "")
        url = str(spec.get("url") or "")
        item_id = str(spec.get("item_id") or "worker")
        if not URL_RE.match(url):
            raise ValueError("worker URL must use a supported network scheme")
        settings = settings_from_worker_payload(dict(spec.get("settings") or {}))
        cancel_marker = Path(str(spec.get("cancel_marker") or "")).expanduser().resolve()
        if cancel_marker.parent != worker_task_dir().resolve():
            raise ValueError("worker cancel marker must be project-local")
        stop_event = threading.Event()
        watcher = threading.Thread(
            target=_watch_cancel_marker,
            args=(cancel_marker, stop_event, done_event),
            daemon=True,
            name="worker-cancel-watcher",
        )
        watcher.start()
        import yt_dlp  # type: ignore

        if task == "download":
            telemetry: dict[str, Any] = {}
            adaptive_state = adaptive_state_from_snapshot(spec.get("adaptive_state"))
            code = execute_download_job(
                yt_dlp,
                url,
                settings,
                sink,  # type: ignore[arg-type]
                item_id,
                stop_event,
                telemetry,
                adaptive_state,
                quiet=True,
            )
            sink.put(("worker_terminal", {
                "outcome": "success",
                "exit_code": int(code),
                "telemetry": telemetry,
            }))
            return int(code)

        if task == "list_formats":
            opts: dict[str, Any] = {
                "listformats": True,
                "skip_download": True,
                "quiet": False,
                "no_color": True,
                "logger": QueueLogger(sink),  # type: ignore[arg-type]
                "noplaylist": not settings.include_playlist,
                "socket_timeout": SOCKET_TIMEOUT_SECONDS,
                "retries": HTTP_RETRIES,
                "extractor_retries": EXTRACTOR_RETRIES,
                "retry_sleep_functions": {
                    "http": make_retry_sleep_function(1, 20),
                    "extractor": make_retry_sleep_function(1, 8),
                },
                "progress_hooks": [lambda _data: (_ for _ in ()).throw(DownloadCancelled("Cancelled by user")) if stop_event.is_set() else None],
            }
            if settings.ffmpeg_location:
                opts["ffmpeg_location"] = settings.ffmpeg_location
            js = javascript_runtime_snapshot(execute_versions=True).get("selected")
            if isinstance(js, dict) and js.get("path"):
                opts["js_runtimes"] = {str(js.get("name")): {"path": str(js.get("path"))}}
            if stop_event.is_set():
                raise DownloadCancelled("Cancelled by user")
            with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[attr-defined]
                code = int(ydl.download([url]))
            if stop_event.is_set():
                raise DownloadCancelled("Cancelled by user")
            sink.put(("worker_terminal", {"outcome": "success", "exit_code": code, "telemetry": {}}))
            return code

        raise ValueError("unsupported worker task")
    except (DownloadCancelled, KeyboardInterrupt) as exc:
        sink.put(("worker_terminal", {
            "outcome": "cancelled",
            "exit_code": 130,
            "error_category": "cancelled",
            "error": redact_text(exc),
            "telemetry": {},
        }))
        return 130
    except Exception as exc:
        sink.put(("log", "error", redact_text(exc)))
        sink.put(("log", "debug", redact_text(traceback.format_exc())))
        sink.put(("worker_terminal", {
            "outcome": "failed",
            "exit_code": 1,
            "error_category": classify_download_error(exc),
            "error": redact_text(exc),
            "telemetry": {},
        }))
        return 1
    finally:
        done_event.set()
        if watcher is not None:
            watcher.join(timeout=0.25)


def execute_isolated_worker_task(
    task: str,
    url: str,
    settings: DownloadSettings,
    ui_queue: "queue.Queue[tuple[Any, ...]]",
    item_id: str,
    stop_event: threading.Event,
    telemetry: dict[str, Any],
    adaptive_state: Optional[AdaptiveRunState] = None,
    force_stop_event: Optional[threading.Event] = None,
) -> int:
    """Run yt-dlp in a killable child process while preserving resumable partials."""
    prune_stale_worker_tasks()
    folder = worker_task_dir()
    folder.mkdir(parents=True, exist_ok=True)
    token = f"{safe_filename_token(item_id, limit=24)}-{secrets.token_hex(6)}"
    spec_path = folder / f"{token}.json"
    cancel_marker = folder / f"{token}.cancel"
    spec = {
        "schema_version": WORKER_SPEC_SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "task": task,
        "url": url,
        "item_id": item_id,
        "settings": settings_to_worker_payload(settings),
        "adaptive_state": adaptive_state.snapshot() if adaptive_state is not None else None,
        "cancel_marker": str(cancel_marker),
        "created_at_utc": utc_now_iso(),
    }
    atomic_write_bytes(spec_path, json.dumps(spec, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    try:
        os.chmod(spec_path, 0o600)
    except OSError:
        pass

    proc: Optional[subprocess.Popen[Any]] = None
    reader_thread: Optional[threading.Thread] = None
    line_queue: "queue.Queue[Optional[str]]" = queue.Queue()
    reader_done = threading.Event()
    terminal: Optional[dict[str, Any]] = None
    cancellation_requested_at: Optional[float] = None
    hard_cancelled = False
    interrupted = False

    def reader() -> None:
        try:
            if proc is not None and proc.stdout is not None:
                for line in proc.stdout:
                    line_queue.put(line.rstrip("\r\n"))
        finally:
            reader_done.set()
            line_queue.put(None)

    try:
        proc = subprocess.Popen(worker_command(spec_path), **worker_process_kwargs())
        telemetry["worker_process"] = {
            "isolated": True,
            "pid": proc.pid,
            "task": task,
            "cancel_grace_seconds": CANCEL_GRACE_SECONDS,
            "partial_resume_policy": "yt-dlp .part files are preserved for a later resume",
        }
        reader_thread = threading.Thread(target=reader, daemon=True, name=f"{task}-worker-reader")
        reader_thread.start()

        while True:
            try:
                line = line_queue.get(timeout=CANCEL_POLL_SECONDS)
            except queue.Empty:
                line = ""
            if line:
                event = parse_worker_event_line(line)
                if event is None:
                    ui_queue.put(("log", "debug", redact_text(line)))
                elif event[0] == "worker_terminal" and len(event) > 1 and isinstance(event[1], dict):
                    terminal = dict(event[1])
                else:
                    ui_queue.put(event)

            if stop_event.is_set() and cancellation_requested_at is None:
                cancellation_requested_at = time.monotonic()
                try:
                    atomic_write_bytes(cancel_marker, b"cancel\n")
                except OSError as exc:
                    ui_queue.put(("log", "warning", f"Could not write the cooperative cancel marker: {redact_text(exc)}"))
                ui_queue.put(("job_status", item_id, "Cancelling"))
                ui_queue.put(("log", "warning", f"Cancellation signal sent to the isolated worker; a hard process-tree stop will follow after {CANCEL_GRACE_SECONDS:.1f}s if extraction remains blocked."))

            should_force = bool(force_stop_event and force_stop_event.is_set())
            if (
                proc.poll() is None
                and cancellation_requested_at is not None
                and (should_force or time.monotonic() - cancellation_requested_at >= CANCEL_GRACE_SECONDS)
            ):
                termination = terminate_process_tree(proc)
                hard_cancelled = True
                telemetry["worker_process"]["termination"] = termination
                ui_queue.put(("log", "warning", "The blocked worker process tree was force-stopped. Resumable partial data was preserved."))
                if force_stop_event is not None:
                    force_stop_event.set()

            if proc.poll() is not None and reader_done.is_set() and line_queue.empty():
                break
    except KeyboardInterrupt:
        interrupted = True
        stop_event.set()
        cancellation_requested_at = cancellation_requested_at or time.monotonic()
        if proc is not None and proc.poll() is None:
            telemetry.setdefault("worker_process", {})["termination"] = terminate_process_tree(proc)
            hard_cancelled = True
    finally:
        if proc is not None and proc.poll() is None:
            telemetry.setdefault("worker_process", {})["termination"] = terminate_process_tree(proc)
            hard_cancelled = True
        if reader_thread is not None:
            reader_thread.join(timeout=1.0)
        if proc is not None and proc.stdout is not None:
            try:
                proc.stdout.close()
            except OSError:
                pass
        try:
            spec_path.unlink(missing_ok=True)
            cancel_marker.unlink(missing_ok=True)
        except OSError:
            pass

    if stop_event.is_set() or interrupted or (terminal and terminal.get("outcome") == "cancelled"):
        latency = None
        if cancellation_requested_at is not None:
            latency = round(time.monotonic() - cancellation_requested_at, 3)
        telemetry["cancellation"] = {
            "requested": True,
            "mode": "hard_process_tree" if hard_cancelled else "cooperative",
            "latency_seconds": latency,
            "resumable_partial_preserved": True,
            "worker_exit_code": proc.returncode if proc is not None else None,
        }
        raise DownloadCancelled("Cancelled by user")

    if terminal is not None:
        child_telemetry = terminal.get("telemetry")
        if isinstance(child_telemetry, dict):
            telemetry.update(child_telemetry)
        if adaptive_state is not None:
            update_adaptive_state_from_telemetry(adaptive_state, telemetry)
        if terminal.get("outcome") == "success":
            return int(terminal.get("exit_code") or 0)
        raise RuntimeError(str(terminal.get("error") or "isolated worker failed"))

    exit_code = proc.returncode if proc is not None else 1
    raise RuntimeError(f"isolated worker exited without a terminal event (exit code {exit_code})")


class QueueLogger:
    """yt-dlp logger that forwards redacted messages to the Tk UI queue."""

    def __init__(self, ui_queue: "queue.Queue[tuple[Any, ...]]") -> None:
        self.ui_queue = ui_queue

    @staticmethod
    def _safe(msg: str) -> str:
        return redact_text(str(msg))

    def debug(self, msg: str) -> None:
        # yt-dlp sends many useful non-debug messages through debug() when quiet=True.
        if msg and not msg.startswith("[debug]"):
            self.ui_queue.put(("log", "info", self._safe(msg)))

    def info(self, msg: str) -> None:
        if msg:
            self.ui_queue.put(("log", "info", self._safe(msg)))

    def warning(self, msg: str) -> None:
        if msg:
            self.ui_queue.put(("log", "warning", f"WARNING: {self._safe(msg)}"))

    def error(self, msg: str) -> None:
        if msg:
            self.ui_queue.put(("log", "error", f"ERROR: {self._safe(msg)}"))


_TkBase = tk.Tk if tk is not None else object


class SafeMediaDownloaderApp(_TkBase):
    """Tkinter desktop UI."""

    MODES = ["Video (best MP4)", "Audio (MP3)", "Audio (original/best)", "Custom yt-dlp format"]
    HEIGHTS = ["Best", "2160", "1440", "1080", "720", "480", "360"]

    def __init__(self, run_id: Optional[str] = None, instance_guard: Optional[InstanceGuard] = None) -> None:
        prepend_tools_to_path()
        self.instance_guard = instance_guard
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1040x780")
        self.minsize(900, 640)

        self.ui_queue: "queue.Queue[tuple[Any, ...]]" = queue.Queue()
        self.stop_event = threading.Event()
        self.force_stop_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
        self.jobs: list[DownloadJob] = []
        self.log_entries: list[dict[str, str]] = []
        self._job_counter = 0
        self._closing = False
        self._shutdown_deadline_monotonic: Optional[float] = None
        self.run_id = run_id or make_run_id("gui")
        self.started_at_utc = datetime.now(timezone.utc).isoformat()
        self.started_monotonic = time.monotonic()
        self.log_path = default_run_log_path("gui", self.run_id)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        prune_old_logs()

        self.output_dir_var = tk.StringVar(value=str(default_download_dir()))
        self.mode_var = tk.StringVar(value=self.MODES[0])
        self.height_var = tk.StringVar(value="1080")
        self.custom_format_var = tk.StringVar(value="")
        self.include_playlist_var = tk.BooleanVar(value=False)
        self.embed_metadata_var = tk.BooleanVar(value=True)
        self.write_subtitles_var = tk.BooleanVar(value=False)
        self.restrict_filenames_var = tk.BooleanVar(value=True)
        self.use_archive_var = tk.BooleanVar(value=True)
        self.prefer_mp4_var = tk.BooleanVar(value=True)
        self.hide_media_var = tk.BooleanVar(value=HIDE_MEDIA_DEFAULT)
        self.smart_resilience_var = tk.BooleanVar(value=SMART_RESILIENCE_DEFAULT)
        self.rate_limit_var = tk.StringVar(value="")
        self.confirm_rights_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")
        self.dependency_status_var = tk.StringVar(value="")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_dependency_status()
        self._log("info", f"Application started. Run ID: {self.run_id}")
        self._log("info", f"Persistent log file: {self.log_path}")
        self._restore_recovery_state()
        self.after(100, self._poll_ui_queue)
        self.after(10_000, self._heartbeat_instance_lock)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        root.rowconfigure(5, weight=2)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_NAME, font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="For media you own, created, are licensed to download, public-domain, Creative Commons, or otherwise permitted. No DRM bypass.",
            foreground="#555555",
        ).grid(row=1, column=0, sticky="w", pady=(2, 8))
        ttk.Button(header, text="Help / README", command=self._open_readme).grid(row=0, column=1, rowspan=2, sticky="e")

        url_frame = ttk.LabelFrame(root, text="1) URLs")
        url_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        url_frame.columnconfigure(0, weight=1)
        self.url_text = tk.Text(url_frame, height=5, wrap="word", undo=True)
        self.url_text.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        url_scroll = ttk.Scrollbar(url_frame, orient="vertical", command=self.url_text.yview)
        url_scroll.grid(row=0, column=1, sticky="ns", pady=8)
        self.url_text.configure(yscrollcommand=url_scroll.set)

        url_buttons = ttk.Frame(url_frame)
        url_buttons.grid(row=0, column=2, sticky="ns", padx=(8, 8), pady=8)
        ttk.Button(url_buttons, text="Add to queue", command=self.add_urls).grid(row=0, column=0, sticky="ew", pady=(0, 5))
        ttk.Button(url_buttons, text="Paste", command=self.paste_urls).grid(row=1, column=0, sticky="ew", pady=(0, 5))
        ttk.Button(url_buttons, text="List formats", command=self.list_formats).grid(row=2, column=0, sticky="ew")

        queue_frame = ttk.LabelFrame(root, text="2) Queue")
        queue_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        queue_frame.rowconfigure(0, weight=1)
        queue_frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(queue_frame, columns=("url", "status"), show="headings", height=8)
        self.tree.heading("url", text="URL")
        self.tree.heading("status", text="Status")
        self.tree.column("url", minwidth=420, width=760, stretch=True)
        self.tree.column("status", minwidth=100, width=140, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        tree_scroll = ttk.Scrollbar(queue_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns", pady=8)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        queue_buttons = ttk.Frame(queue_frame)
        queue_buttons.grid(row=0, column=2, sticky="ns", padx=8, pady=8)
        ttk.Button(queue_buttons, text="Remove selected", command=self.remove_selected).grid(row=0, column=0, sticky="ew", pady=(0, 5))
        ttk.Button(queue_buttons, text="Clear queue", command=self.clear_queue).grid(row=1, column=0, sticky="ew", pady=(0, 5))
        ttk.Button(queue_buttons, text="Open output", command=self.open_output_folder).grid(row=2, column=0, sticky="ew", pady=(0, 5))
        ttk.Button(queue_buttons, text="Export report", command=self.export_report).grid(row=3, column=0, sticky="ew", pady=(0, 5))
        ttk.Button(queue_buttons, text="Export diagnostics", command=self.export_diagnostics).grid(row=4, column=0, sticky="ew")

        options_frame = ttk.LabelFrame(root, text="3) Options")
        options_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        for col in range(6):
            options_frame.columnconfigure(col, weight=1 if col in (1, 3, 5) else 0)

        ttk.Label(options_frame, text="Output folder:").grid(row=0, column=0, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(options_frame, textvariable=self.output_dir_var).grid(row=0, column=1, columnspan=4, sticky="ew", pady=6)
        ttk.Button(options_frame, text="Browse", command=self.browse_output_dir).grid(row=0, column=5, sticky="e", padx=8, pady=6)

        ttk.Label(options_frame, text="Mode:").grid(row=1, column=0, sticky="w", padx=(8, 4), pady=6)
        mode_box = ttk.Combobox(options_frame, textvariable=self.mode_var, values=self.MODES, state="readonly", width=24)
        mode_box.grid(row=1, column=1, sticky="ew", pady=6)
        mode_box.bind("<<ComboboxSelected>>", lambda _event: self._refresh_mode_state())

        ttk.Label(options_frame, text="Max height:").grid(row=1, column=2, sticky="w", padx=(16, 4), pady=6)
        self.height_box = ttk.Combobox(options_frame, textvariable=self.height_var, values=self.HEIGHTS, state="readonly", width=10)
        self.height_box.grid(row=1, column=3, sticky="w", pady=6)

        ttk.Label(options_frame, text="Rate limit:").grid(row=1, column=4, sticky="w", padx=(16, 4), pady=6)
        ttk.Entry(options_frame, textvariable=self.rate_limit_var, width=12).grid(row=1, column=5, sticky="w", padx=(0, 8), pady=6)

        ttk.Label(options_frame, text="Custom format:").grid(row=2, column=0, sticky="w", padx=(8, 4), pady=6)
        self.custom_entry = ttk.Entry(options_frame, textvariable=self.custom_format_var)
        self.custom_entry.grid(row=2, column=1, columnspan=5, sticky="ew", padx=(0, 8), pady=6)

        checks = ttk.Frame(options_frame)
        checks.grid(row=3, column=0, columnspan=6, sticky="ew", padx=8, pady=(4, 8))
        ttk.Checkbutton(checks, text="Prefer MP4/M4A", variable=self.prefer_mp4_var).grid(row=0, column=0, sticky="w", padx=(0, 16))
        ttk.Checkbutton(checks, text="Include playlist", variable=self.include_playlist_var).grid(row=0, column=1, sticky="w", padx=(0, 16))
        ttk.Checkbutton(checks, text="Embed metadata", variable=self.embed_metadata_var).grid(row=0, column=2, sticky="w", padx=(0, 16))
        ttk.Checkbutton(checks, text="English subtitles", variable=self.write_subtitles_var).grid(row=0, column=3, sticky="w", padx=(0, 16))
        ttk.Checkbutton(checks, text="Safe filenames", variable=self.restrict_filenames_var).grid(row=0, column=4, sticky="w", padx=(0, 16))
        ttk.Checkbutton(checks, text="Auto-detect completed duplicates", variable=self.use_archive_var).grid(row=0, column=5, sticky="w")
        ttk.Checkbutton(checks, text="Hide downloaded media in Windows", variable=self.hide_media_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(checks, text="Smart reconnect / adaptive throttle (recommended)", variable=self.smart_resilience_var).grid(row=1, column=3, columnspan=3, sticky="w", pady=(6, 0))

        confirm_frame = ttk.Frame(root)
        confirm_frame.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        ttk.Checkbutton(
            confirm_frame,
            variable=self.confirm_rights_var,
            text="I confirm I have the right to download these URLs and will not use this program to bypass DRM, access controls, or site terms.",
        ).grid(row=0, column=0, sticky="w")

        log_frame = ttk.LabelFrame(root, text="Log")
        log_frame.grid(row=5, column=0, sticky="nsew", pady=(0, 8))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=9, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns", pady=8)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        bottom = ttk.Frame(root)
        bottom.grid(row=6, column=0, sticky="ew")
        bottom.columnconfigure(1, weight=1)
        self.start_button = ttk.Button(bottom, text="Start downloads", command=self.start_downloads)
        self.start_button.grid(row=0, column=0, padx=(0, 8))
        self.progress = ttk.Progressbar(bottom, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.stop_button = ttk.Button(bottom, text="Stop", command=self.stop_downloads, state="disabled")
        self.stop_button.grid(row=0, column=2, padx=(0, 8))
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=3, sticky="e")
        ttk.Label(bottom, textvariable=self.dependency_status_var, foreground="#555555").grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        self._refresh_mode_state()

    def _refresh_mode_state(self) -> None:
        mode = self.mode_var.get()
        if mode.startswith("Video") or mode.startswith("Custom"):
            self.height_box.configure(state="readonly")
            if mode.startswith("Custom"):
                self.custom_entry.configure(state="normal")
            else:
                self.custom_entry.configure(state="disabled")
        else:
            self.height_box.configure(state="disabled")
            self.custom_entry.configure(state="disabled")

    def _refresh_dependency_status(self) -> None:
        ffmpeg = find_ffmpeg_location()
        js_runtime = find_js_runtime()
        ffmpeg_text = f"FFmpeg detected: {ffmpeg}" if ffmpeg else "FFmpeg not detected: using single-file fallback; MP3/embedding need FFmpeg."
        js_text = f"JS runtime detected: {js_runtime[0]}" if js_runtime else "JS runtime not detected: install Deno for best YouTube extraction."
        self.dependency_status_var.set(f"{ffmpeg_text} | {js_text}")

    def _raw_recovery_settings(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir_var.get(), "mode": self.mode_var.get(), "height": self.height_var.get(),
            "custom_format": self.custom_format_var.get(), "include_playlist": self.include_playlist_var.get(),
            "embed_metadata": self.embed_metadata_var.get(), "write_subtitles": self.write_subtitles_var.get(),
            "restrict_filenames": self.restrict_filenames_var.get(), "use_archive": self.use_archive_var.get(),
            "prefer_mp4": self.prefer_mp4_var.get(), "hide_media": self.hide_media_var.get(),
            "smart_resilience": self.smart_resilience_var.get(), "rate_limit": self.rate_limit_var.get(),
        }

    def _persist_recovery_state(self, reason: str) -> None:
        try:
            save_queue_recovery(self._jobs_for_export(), self._raw_recovery_settings(), reason=reason)
        except Exception as exc:
            self._log("warning", f"Queue recovery state could not be saved: {exc}")

    def _restore_recovery_state(self) -> None:
        recovered = load_queue_recovery()
        status = recovered.get("status")
        if status == "absent":
            return
        if status != "loaded":
            self._log("warning", f"Queue recovery state was not loaded: {status}. Existing file was left untouched.")
            return
        settings = recovered.get("settings") if isinstance(recovered.get("settings"), dict) else {}
        mode = str(settings.get("mode", ""))
        height = str(settings.get("height", ""))
        if settings.get("output_dir"):
            self.output_dir_var.set(str(settings.get("output_dir")))
        if mode in self.MODES:
            self.mode_var.set(mode)
        if height in self.HEIGHTS:
            self.height_var.set(height)
        self.custom_format_var.set(str(settings.get("custom_format", "")))
        for key, var in (("include_playlist", self.include_playlist_var), ("embed_metadata", self.embed_metadata_var), ("write_subtitles", self.write_subtitles_var), ("restrict_filenames", self.restrict_filenames_var), ("use_archive", self.use_archive_var), ("prefer_mp4", self.prefer_mp4_var), ("hide_media", self.hide_media_var), ("smart_resilience", self.smart_resilience_var)):
            if key in settings:
                var.set(bool(settings.get(key)))
        self.rate_limit_var.set(str(settings.get("rate_limit", "")))
        restored = 0
        existing = {canonical_url_key(job.url) for job in self.jobs}
        for item in recovered.get("jobs", [])[:QUEUE_CAPACITY]:
            url = str(item.get("url", ""))
            url_key = canonical_url_key(url)
            if not URL_RE.match(url) or url_key in existing:
                continue
            self._job_counter += 1
            item_id = f"job{self._job_counter}"
            job = DownloadJob(item_id=item_id, url=url, status="Queued", result=dict(item.get("result") or {}))
            self.jobs.append(job)
            self.tree.insert("", "end", iid=item_id, values=(url, "Queued"))
            existing.add(url_key)
            restored += 1
        self._refresh_mode_state()
        if restored:
            self._log("info", f"Restored {restored} unfinished queue item(s) from crash-safe local state.")

    def _open_readme(self) -> None:
        readme = app_base_dir() / "README.md"
        if readme.exists():
            if platform.system() == "Windows":
                os.startfile(str(readme))  # type: ignore[attr-defined]
            else:
                webbrowser.open(readme.as_uri())
        else:
            messagebox.showinfo(APP_NAME, "README.md is not next to the program file.")

    def _log(self, level: str, message: str) -> None:
        normalized_level = str(level or "info")
        entry = make_log_entry(self.run_id, normalized_level, str(message))
        self.log_entries.append(entry)
        if len(self.log_entries) > LOG_ENTRY_LIMIT:
            del self.log_entries[: len(self.log_entries) - LOG_ENTRY_LIMIT]

        prefix = {
            "info": "[info]",
            "warning": "[warn]",
            "error": "[error]",
            "debug": "[debug]",
        }.get(normalized_level, "[info]")
        timestamp = chicago_now().strftime("%H:%M:%S")
        append_persistent_log_entry(self.log_path, entry)
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{timestamp} {prefix} {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _heartbeat_instance_lock(self) -> None:
        if self.instance_guard:
            self.instance_guard.heartbeat()
        self.after(10_000, self._heartbeat_instance_lock)

    def _on_close(self) -> None:
        if self._closing:
            return
        if self.worker_thread and self.worker_thread.is_alive():
            if not self.stop_event.is_set() and not messagebox.askyesno(APP_NAME, "A download/listing worker is active. Stop it and close the app?"):
                return
            self._closing = True
            self.stop_event.set()
            self._persist_recovery_state("window_close_active_worker")
            self._shutdown_deadline_monotonic = time.monotonic() + SHUTDOWN_GRACE_SECONDS
            self.status_var.set("Stopping safely...")
            self._log("warning", f"Window close requested; worker stop signal sent with a {SHUTDOWN_GRACE_SECONDS:.0f}s bounded drain.")
            self.after(100, self._poll_shutdown)
            return
        self._finalize_close("normal_close")

    def _poll_shutdown(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive() and time.monotonic() < float(self._shutdown_deadline_monotonic or 0):
            self.after(100, self._poll_shutdown)
            return
        if self.worker_thread and self.worker_thread.is_alive():
            self._log("warning", "Bounded shutdown deadline reached; unfinished queue state is preserved and daemon worker will end with the process.")
            self._finalize_close("forced_after_bounded_drain")
        else:
            self._finalize_close("worker_stopped")

    def _finalize_close(self, reason: str) -> None:
        self._persist_recovery_state(reason)
        self._log("info", f"Application closing: {reason}; elapsed={time.monotonic() - self.started_monotonic:.2f}s")
        self.destroy()


    def paste_urls(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        if text:
            self.url_text.insert("end", text + ("\n" if not text.endswith("\n") else ""))

    def add_urls(self) -> None:
        text = self.url_text.get("1.0", "end")
        urls, pasted_duplicates = normalize_urls_with_stats(text)
        if not urls:
            messagebox.showinfo(APP_NAME, "Paste one or more URL lines first. Only http, https, and ftp URLs are accepted.")
            return
        existing = {canonical_url_key(job.url) for job in self.jobs}
        added = 0
        rejected = 0
        duplicate_skipped = pasted_duplicates
        for url in urls:
            url_key = canonical_url_key(url)
            if url_key in existing:
                duplicate_skipped += 1
                continue
            if len(self.jobs) >= QUEUE_CAPACITY:
                rejected += 1
                continue
            self._job_counter += 1
            item_id = f"job{self._job_counter}"
            job = DownloadJob(item_id=item_id, url=url)
            self.jobs.append(job)
            self.tree.insert("", "end", iid=item_id, values=(url, job.status))
            existing.add(url_key)
            added += 1
        self._log("info", f"Added {added} URL(s) to the queue; auto-skipped {duplicate_skipped} duplicate URL(s).")
        self._persist_recovery_state("queue_add")
        if rejected:
            self._log("warning", f"Queue capacity is {QUEUE_CAPACITY}; rejected {rejected} additional URL(s) without silently dropping active work.")
            messagebox.showwarning(APP_NAME, f"Queue capacity is {QUEUE_CAPACITY}. Rejected {rejected} additional URL(s).")


    def remove_selected(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning(APP_NAME, "Stop downloads before editing the queue.")
            return
        selected = set(self.tree.selection())
        if not selected:
            return
        self.jobs = [job for job in self.jobs if job.item_id not in selected]
        for item_id in selected:
            self.tree.delete(item_id)
        self._persist_recovery_state("queue_remove")


    def clear_queue(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning(APP_NAME, "Stop downloads before clearing the queue.")
            return
        self.jobs.clear()
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        self.progress.configure(value=0)
        self.status_var.set("Ready")
        self._persist_recovery_state("queue_clear")


    def browse_output_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.output_dir_var.get() or str(Path.home()))
        if chosen:
            self.output_dir_var.set(chosen)
            self._refresh_dependency_status()

    def open_output_folder(self) -> None:
        try:
            out_dir = resolve_output_dir(self.output_dir_var.get())
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        if platform.system() == "Windows":
            os.startfile(str(out_dir))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(out_dir)])
        else:
            subprocess.Popen(["xdg-open", str(out_dir)])

    def _selected_or_first_url(self) -> Optional[str]:
        selection = self.tree.selection()
        if selection:
            values = self.tree.item(selection[0], "values")
            if values:
                return str(values[0])
        urls = normalize_urls(self.url_text.get("1.0", "end"))
        return urls[0] if urls else None

    def _collect_settings(self, ensure_output_dir: bool = True) -> DownloadSettings:
        output_dir = resolve_output_dir(self.output_dir_var.get())
        if ensure_output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)

        max_height: Optional[int]
        height_text = self.height_var.get()
        if height_text == "Best":
            max_height = None
        else:
            max_height = int(height_text)

        rate_limit = parse_rate_limit(self.rate_limit_var.get())
        return DownloadSettings(
            output_dir=output_dir,
            mode=self.mode_var.get(),
            max_height=max_height,
            custom_format=self.custom_format_var.get(),
            include_playlist=self.include_playlist_var.get(),
            embed_metadata=self.embed_metadata_var.get(),
            write_subtitles=self.write_subtitles_var.get(),
            restrict_filenames=self.restrict_filenames_var.get(),
            use_archive=self.use_archive_var.get(),
            rate_limit_bytes=rate_limit,
            prefer_mp4=self.prefer_mp4_var.get(),
            ffmpeg_location=find_ffmpeg_location(),
            hide_media=self.hide_media_var.get(),
            smart_resilience=self.smart_resilience_var.get(),
        )

    def _jobs_for_export(self) -> list[dict[str, Any]]:
        return [{"item_id": job.item_id, "url": job.url, "status": job.status, "result": dict(job.result)} for job in self.jobs]


    def _build_export_snapshot(self) -> dict[str, Any]:
        try:
            settings = settings_to_export(self._collect_settings(ensure_output_dir=False))
        except Exception as exc:
            settings = {
                "error": str(exc),
                "raw_output_dir": self.output_dir_var.get(),
                "mode": self.mode_var.get(),
                "max_height": self.height_var.get(),
                "rate_limit": self.rate_limit_var.get(),
                "smart_resilience": self.smart_resilience_var.get(),
            }
        return build_export_snapshot(
            jobs=self._jobs_for_export(),
            logs=list(self.log_entries),
            settings=settings,
            dependencies=dependency_snapshot(),
        )

    def export_report(self) -> None:
        if not messagebox.askyesno(
            APP_NAME,
            "Export a general queue/report file?\n\nThis report may include full queued URLs, statuses, current settings, local dependency paths, and logs. It will not include downloaded media, cookies, passwords, or browser credentials. Use Export diagnostics for the redacted troubleshooting bundle.",
        ):
            return
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_name = f"SafeVideoDownloader-export-{timestamp}.zip"
        initial_dir = exports_dir()
        try:
            initial_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            try:
                initial_dir = Path(self.output_dir_var.get()).expanduser()
            except Exception:
                initial_dir = default_download_dir()
        if not initial_dir.exists():
            initial_dir = Path.home()
        chosen = filedialog.asksaveasfilename(
            title="Export report",
            initialdir=str(initial_dir),
            initialfile=default_name,
            defaultextension=".zip",
            filetypes=(
                ("Complete report ZIP", "*.zip"),
                ("Full report JSON", "*.json"),
                ("Queue CSV", "*.csv"),
                ("Log text", "*.txt"),
                ("All files", "*.*"),
            ),
        )
        if not chosen:
            return
        path = Path(chosen)
        if not path.suffix:
            path = path.with_suffix(".zip")
        snapshot = self._build_export_snapshot()
        try:
            result = write_export_by_suffix(path, snapshot)
            self._log("info", f"Exported report: {result.get('path')} ({result.get('type')}, sha256={str(result.get('sha256') or '')[:16]}...)")
            messagebox.showinfo(APP_NAME, f"Export complete:\n{result.get('path')}\n\nSHA-256: {result.get('sha256')}")
        except Exception as exc:
            self._log("error", f"Export failed: {exc}")
            self._log("debug", traceback.format_exc())
            messagebox.showerror(APP_NAME, f"Export failed:\n{exc}")

    def _build_diagnostic_snapshot(self) -> dict[str, Any]:
        try:
            settings = settings_to_export(self._collect_settings(ensure_output_dir=False))
        except Exception as exc:
            settings = {
                "error": str(exc),
                "raw_output_dir": self.output_dir_var.get(),
                "mode": self.mode_var.get(),
                "max_height": self.height_var.get(),
                "rate_limit": self.rate_limit_var.get(),
                "smart_resilience": self.smart_resilience_var.get(),
            }
        run_context = {
            "run_id": self.run_id,
            "mode": "gui",
            "started_at_utc": self.started_at_utc,
            "elapsed_seconds": round(time.monotonic() - self.started_monotonic, 3),
            "persistent_log_path": redact_path(self.log_path),
            "instance_lock": self.instance_guard.snapshot() if self.instance_guard else {"status": "not_acquired"},
        }
        return build_diagnostic_snapshot(self._jobs_for_export(), list(self.log_entries), settings, dependency_snapshot(), run_context)

    def export_diagnostics(self) -> None:
        if not messagebox.askyesno(
            APP_NAME,
            "Export a redacted support diagnostic ZIP?\n\nThe local-only bundle includes settings shape, dependency/system summaries, queue status, and a redacted log tail. It does not include downloaded media, full queued URLs, cookies, passwords, browser profiles, or credentials.",
        ):
            return
        default_name = f"SafeVideoDownloader-diagnostics-{windows_safe_timestamp()}.zip"
        initial_dir = diagnostics_dir()
        try:
            initial_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            initial_dir = Path.home()
        chosen = filedialog.asksaveasfilename(
            title="Export program diagnostics",
            initialdir=str(initial_dir),
            initialfile=default_name,
            defaultextension=".zip",
            filetypes=(("Diagnostic ZIP", "*.zip"), ("All files", "*.*")),
        )
        if not chosen:
            return
        path = Path(chosen)
        if not path.suffix:
            path = path.with_suffix(".zip")
        snapshot = self._build_diagnostic_snapshot()
        try:
            result = write_diagnostic_zip(path, snapshot)
            sha = str(result.get("sha256") or "")
            self._log("info", f"Exported diagnostics: {path} ({result.get('entry_count')} files, sha256={sha[:16]}...)")
            messagebox.showinfo(APP_NAME, f"Diagnostics export complete:\n{path}\n\nFiles: {result.get('entry_count')}\nSHA-256: {sha}")
        except Exception as exc:
            self._log("error", f"Diagnostics export failed: {exc}")
            self._log("debug", traceback.format_exc())
            messagebox.showerror(APP_NAME, f"Diagnostics export failed:\n{exc}")

    def start_downloads(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return
        if not self.confirm_rights_var.get():
            messagebox.showwarning(APP_NAME, "Please confirm you have the right to download these URLs and will not bypass DRM or access controls.")
            return
        if not self.jobs:
            self.add_urls()
        if not self.jobs:
            return
        try:
            settings = self._collect_settings()
            # Validate selector early.
            build_format_selector(settings)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return

        for warning in dependency_warnings(settings):
            self._log("warning", warning)

        jobs_snapshot = [DownloadJob(job.item_id, job.url, job.status, dict(job.result)) for job in self.jobs if job.status not in {"Done", "Skipped duplicate", "Cancelled"}]
        if not jobs_snapshot:
            messagebox.showinfo(APP_NAME, "No queued jobs to download.")
            return

        self.stop_event.clear()
        self.force_stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal", text="Stop")
        self.progress.configure(value=0)
        self.status_var.set("Starting...")
        self._log("info", f"Starting {len(jobs_snapshot)} job(s). Queue capacity: {QUEUE_CAPACITY}.")
        self._log("info", f"Output folder: {settings.output_dir}")
        self._log("info", f"Format selector: {build_format_selector(settings)}")
        self._log("info", f"Integrity mode: selected-format check, disk preflight, abort unavailable fragments, final media verification. Retry policy: {retry_policy_snapshot(bool(settings.rate_limit_bytes), settings.smart_resilience)}")
        self._persist_recovery_state("download_start")

        self.worker_thread = threading.Thread(
            target=self._download_worker,
            args=(jobs_snapshot, settings),
            daemon=True,
            name="download-worker",
        )
        self.worker_thread.start()

    def stop_downloads(self) -> None:
        if not self.stop_event.is_set():
            self.stop_event.set()
            self.status_var.set("Cancelling active worker...")
            self.stop_button.configure(text="Force Stop")
            self._persist_recovery_state("cancel_requested")
            self._log(
                "warning",
                f"Stop requested. Cooperative cancellation was signalled; if webpage extraction or network I/O remains blocked, the isolated worker will be force-stopped after {CANCEL_GRACE_SECONDS:.1f}s.",
            )
            return
        self.force_stop_event.set()
        self.status_var.set("Force stopping active worker...")
        self.stop_button.configure(state="disabled", text="Force stopping...")
        self._persist_recovery_state("force_cancel_requested")
        self._log("warning", "Force Stop requested. The active worker process tree will be terminated immediately; resumable .part data will be preserved.")

    def list_formats(self) -> None:
        url = self._selected_or_first_url()
        if not url:
            messagebox.showinfo(APP_NAME, "Select a queued URL or paste a URL first.")
            return
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning(APP_NAME, "Wait for the current task to finish first.")
            return
        try:
            settings = self._collect_settings()
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal", text="Stop")
        self.stop_event.clear()
        self.force_stop_event.clear()
        self.status_var.set("Listing formats...")
        self._log("info", f"Listing formats for {url_log_label(url)}")
        self.worker_thread = threading.Thread(
            target=self._list_formats_worker,
            args=(url, settings),
            daemon=True,
            name="format-list-worker",
        )
        self.worker_thread.start()

    def _download_worker(self, jobs: list[DownloadJob], settings: DownloadSettings) -> None:
        try:
            import yt_dlp  # type: ignore
        except Exception:
            self.ui_queue.put(("error_dialog", APP_NAME, "yt-dlp is not installed. Install requirements.txt in the project virtual environment first."))
            self.ui_queue.put(("run_complete",))
            return
        version = getattr(getattr(yt_dlp, "version", None), "__version__", "unknown")
        self.ui_queue.put(("log", "info", f"Using yt-dlp {version}"))
        adaptive_state = AdaptiveRunState(enabled=settings.smart_resilience)
        self.ui_queue.put(("log", "info", f"Smart reconnect/adaptive throttle: {'enabled' if settings.smart_resilience else 'disabled'}"))
        for index, job in enumerate(jobs, start=1):
            if self.stop_event.is_set():
                self.ui_queue.put(("job_status", job.item_id, "Cancelled"))
                continue
            started = time.monotonic()
            telemetry: dict[str, Any] = {}
            self.ui_queue.put(("job_status", job.item_id, "Starting"))
            self.ui_queue.put(("progress", 0.0, f"Job {index}/{len(jobs)} starting"))
            try:
                result_code = execute_isolated_worker_task(
                    "download",
                    job.url,
                    settings,
                    self.ui_queue,
                    job.item_id,
                    self.stop_event,
                    telemetry,
                    adaptive_state,
                    self.force_stop_event,
                )
                telemetry["elapsed_seconds"] = round(time.monotonic() - started, 3)
                self.ui_queue.put(("job_result", job.item_id, telemetry))
                if self.stop_event.is_set():
                    self.ui_queue.put(("job_status", job.item_id, "Cancelled"))
                    self.ui_queue.put(("log", "warning", f"Cancelled: {url_log_label(job.url)}"))
                elif result_code == 0:
                    verification = telemetry.get("verification") if isinstance(telemetry.get("verification"), dict) else None
                    if verification is None:
                        verification = {"status": "not_applicable", "method": "none", "reason": "No new final file was produced; download archive or an existing output may have skipped transfer."}
                        telemetry["verification"] = verification
                        self.ui_queue.put(("job_result", job.item_id, {"verification": verification}))
                    duplicate_state = telemetry.get("duplicate_detection") if isinstance(telemetry.get("duplicate_detection"), dict) else {}
                    duplicate_skipped = duplicate_state.get("status") in {"duplicate", "archive_or_existing_output_skip"}
                    self.ui_queue.put(("job_status", job.item_id, "Skipped duplicate" if duplicate_skipped else "Done"))
                    if duplicate_skipped:
                        self.ui_queue.put(("progress", 100.0, f"Job {index}/{len(jobs)} duplicate skipped"))
                        self.ui_queue.put(("log", "info", f"Duplicate already completed; skipped transfer: {url_log_label(job.url)}"))
                    elif verification.get("status") in {"verified", "warning", "basic_ok"}:
                        self.ui_queue.put(("progress", 100.0, f"Job {index}/{len(jobs)} verified and done"))
                        self.ui_queue.put(("log", "info", f"Completed with final-file verification: {url_log_label(job.url)}"))
                    else:
                        self.ui_queue.put(("progress", 100.0, f"Job {index}/{len(jobs)} complete (no new file to verify)"))
                        self.ui_queue.put(("log", "info", f"Completed without a new final file to verify: {url_log_label(job.url)}"))
                else:
                    telemetry["error_category"] = "backend_exit"
                    self.ui_queue.put(("job_result", job.item_id, telemetry))
                    self.ui_queue.put(("job_status", job.item_id, "Failed"))
                    self.ui_queue.put(("log", "error", f"yt-dlp returned {result_code} for {job.url}"))
            except DownloadCancelled as exc:
                telemetry.update({"error_category": "cancelled", "elapsed_seconds": round(time.monotonic() - started, 3), "error": str(exc)})
                self.ui_queue.put(("job_result", job.item_id, telemetry))
                self.ui_queue.put(("job_status", job.item_id, "Cancelled"))
                self.ui_queue.put(("log", "warning", f"Cancelled: {url_log_label(job.url)}"))
                break
            except Exception as exc:
                telemetry.update({"error_category": classify_download_error(exc), "elapsed_seconds": round(time.monotonic() - started, 3), "error": redact_text(exc)})
                self.ui_queue.put(("job_result", job.item_id, telemetry))
                self.ui_queue.put(("job_status", job.item_id, "Failed"))
                self.ui_queue.put(("log", "error", f"Failed: {url_log_label(job.url)}"))
                self.ui_queue.put(("log", "error", redact_text(exc)))
                self.ui_queue.put(("log", "debug", redact_text(traceback.format_exc())))
        self.ui_queue.put(("run_complete",))


    def _list_formats_worker(self, url: str, settings: DownloadSettings) -> None:
        try:
            import yt_dlp  # type: ignore
        except Exception:
            self.ui_queue.put(("error_dialog", APP_NAME, "yt-dlp is not installed. Install requirements.txt in the project virtual environment first."))
            self.ui_queue.put(("run_complete",))
            return
        try:
            telemetry: dict[str, Any] = {}
            code = execute_isolated_worker_task(
                "list_formats",
                url,
                settings,
                self.ui_queue,
                "format-list",
                self.stop_event,
                telemetry,
                None,
                self.force_stop_event,
            )
            if code == 0:
                self.ui_queue.put(("log", "info", "Finished listing formats."))
        except DownloadCancelled:
            self.ui_queue.put(("log", "warning", "Format listing cancelled."))
        except Exception as exc:
            self.ui_queue.put(("log", "error", redact_text(exc)))
            self.ui_queue.put(("log", "debug", redact_text(traceback.format_exc())))
        finally:
            self.ui_queue.put(("run_complete",))


    def _set_job_status(self, item_id: str, status: str) -> None:
        changed = False
        for job in self.jobs:
            if job.item_id == item_id:
                changed = job.status != status
                job.status = status
                break
        if self.tree.exists(item_id):
            values = list(self.tree.item(item_id, "values"))
            if len(values) < 2:
                values = [values[0] if values else "", status]
            else:
                values[1] = status
            self.tree.item(item_id, values=values)
        if changed:
            self._persist_recovery_state(f"job_status:{status}")

    def _set_job_result(self, item_id: str, updates: dict[str, Any]) -> None:
        for job in self.jobs:
            if job.item_id == item_id:
                job.result.update(dict(updates))
                break


    def _poll_ui_queue(self) -> None:
        try:
            while True:
                event = self.ui_queue.get_nowait()
                kind = event[0]
                if kind == "log":
                    _kind, level, msg = event
                    self._log(str(level), str(msg))
                elif kind == "job_status":
                    _kind, item_id, status = event
                    self._set_job_status(str(item_id), str(status))
                    self.status_var.set(str(status))
                elif kind == "job_result":
                    _kind, item_id, updates = event
                    self._set_job_result(str(item_id), dict(updates) if isinstance(updates, dict) else {})
                elif kind == "progress":
                    _kind, percent, text = event
                    if percent is None:
                        self.progress.configure(mode="indeterminate")
                        self.progress.start(12)
                    else:
                        if str(self.progress.cget("mode")) != "determinate":
                            self.progress.stop()
                            self.progress.configure(mode="determinate")
                        self.progress.configure(value=float(percent))
                    self.status_var.set(str(text))
                elif kind == "error_dialog":
                    _kind, title, msg = event
                    messagebox.showerror(str(title), str(msg))
                elif kind == "run_complete":
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled", text="Stop")
                    self.force_stop_event.clear()
                    self.status_var.set("Stopped" if self.stop_event.is_set() else "Ready")
                    self._refresh_dependency_status()
                    self._persist_recovery_state("run_complete")
                    if self._closing:
                        self._finalize_close("worker_reported_complete")
                        return
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll_ui_queue)



def run_gui() -> int:
    prepend_tools_to_path()
    run_id = make_run_id("gui")
    log_path = default_run_log_path("gui", run_id)
    prune_old_logs()

    def gui_log(level: str, message: str) -> None:
        append_persistent_log_entry(log_path, make_log_entry(run_id, level, message))

    gui_log("info", "GUI launch requested with explicit GUI mode.")
    import_check = gui_runtime_snapshot(create_window=False)
    if import_check.get("status") == "unavailable":
        message = (
            f"Tkinter GUI runtime is unavailable: {redact_text(import_check.get('tkinter_error') or 'unknown import failure')}. "
            "CLI path checks and diagnostics remain available; run --diagnostic-export auto."
        )
        gui_log("error", message)
        print(message, file=sys.stderr)
        return 5
    guard = InstanceGuard("gui", run_id)
    acquired, message = guard.acquire()
    if not acquired:
        gui_log("error", message)
        print(message, file=sys.stderr)
        return 3
    gui_log("info", "GUI instance lock acquired.")
    try:
        try:
            app = SafeMediaDownloaderApp(run_id=run_id, instance_guard=guard)
            gui_log("info", "GUI window created; entering main loop.")
            app.mainloop()
            gui_log("info", "GUI closed normally.")
            return 0
        except Exception as exc:
            message = (
                f"GUI startup failed: {redact_text(exc)}. "
                "Run --diagnostic-export auto for a redacted support bundle."
            )
            gui_log("error", message)
            gui_log("debug", redact_text(traceback.format_exc()))
            print(message, file=sys.stderr)
            return 5
    finally:
        guard.release()
        gui_log("info", "GUI instance lock released.")


def run_cli(argv: Optional[Iterable[str]] = None) -> int:
    """Lawful-use CLI with the same integrity/recovery policies as the GUI."""
    prepend_tools_to_path()
    parser = argparse.ArgumentParser(description=f"{APP_NAME} CLI wrapper around yt-dlp")
    parser.add_argument("url", nargs="*", help="URL(s) to download")
    parser.add_argument("-o", "--output-dir", default=str(default_download_dir()), help="Output folder")
    parser.add_argument("--mode", choices=["video", "mp3", "audio-original"], default="video")
    parser.add_argument("--max-height", type=int, default=1080, help="Video height limit; 0 for best")
    parser.add_argument("--playlist", action="store_true", help="Allow playlists")
    parser.add_argument("--rate-limit", default="", help="Optional hard ceiling like 500K or 2M")
    resilience = parser.add_mutually_exclusive_group()
    resilience.add_argument("--smart-resilience", dest="smart_resilience", action="store_true", help="Enable bounded reconnect and adaptive throttle (default)")
    resilience.add_argument("--no-smart-resilience", dest="smart_resilience", action="store_false", help="Disable outer reconnect/adaptive profiles; yt-dlp internal retries remain")
    parser.set_defaults(smart_resilience=SMART_RESILIENCE_DEFAULT)
    visibility = parser.add_mutually_exclusive_group()
    visibility.add_argument("--hide-media", dest="hide_media", action="store_true", help="Hide final downloaded media in Windows")
    visibility.add_argument("--show-media", dest="hide_media", action="store_false", help="Leave final downloaded media visible (default)")
    parser.set_defaults(hide_media=HIDE_MEDIA_DEFAULT)
    duplicate = parser.add_mutually_exclusive_group()
    duplicate.add_argument("--duplicate-check", dest="duplicate_check", action="store_true", help="Auto-detect completed duplicate media (default)")
    duplicate.add_argument("--no-duplicate-check", dest="duplicate_check", action="store_false", help="Disable archive and verified-media duplicate checks")
    parser.set_defaults(duplicate_check=True)
    parser.add_argument("--export-report", default="", help="Write an atomic JSON/ZIP/CSV/TXT report checkpoint before and during downloading")
    parser.add_argument("--diagnostic-export", nargs="?", const="auto", default="", help="Write a redacted local support ZIP")
    parser.add_argument("--diagnostics", nargs="?", const="auto", default="", help="Alias for --diagnostic-export and exit")
    parser.add_argument("--diagnostics-only", action="store_true", help="Create diagnostics and exit")
    parser.add_argument("--path-check", action="store_true", help="Print read-only path check and exit")
    parser.add_argument("--gui-check", action="store_true", help="Create and close a hidden Tk window, print GUI readiness, and exit")
    parser.add_argument("--i-have-rights", action="store_true", help="Required confirmation for downloads")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.diagnostics and not args.diagnostic_export:
        args.diagnostic_export, args.diagnostics_only = args.diagnostics, True
    if args.diagnostics_only and not args.diagnostic_export:
        args.diagnostic_export = "auto"
    mode_map = {"video": "Video (best MP4)", "mp3": "Audio (MP3)", "audio-original": "Audio (original/best)"}
    if args.max_height < 0:
        parser.error("--max-height must be 0 (best) or a positive integer")
    try:
        cli_output_dir = resolve_output_dir(args.output_dir)
        cli_rate_limit = parse_rate_limit(args.rate_limit)
    except ValueError as exc:
        parser.error(str(exc))
    settings = DownloadSettings(
        cli_output_dir,
        mode_map[args.mode],
        None if args.max_height == 0 else args.max_height,
        "",
        args.playlist,
        True,
        False,
        True,
        bool(args.duplicate_check),
        cli_rate_limit,
        True,
        find_ffmpeg_location(),
        bool(args.hide_media),
        bool(args.smart_resilience),
    )
    if args.path_check:
        print(safe_json_dumps(path_portability_snapshot(settings_to_export(settings))))
        return 0
    cli_start = datetime.now(timezone.utc)
    cli_start_monotonic = time.monotonic()
    cli_run_id = make_run_id("cli")
    cli_log_path = default_run_log_path("cli", cli_run_id)
    prune_old_logs()
    cli_log_entries: list[dict[str, str]] = []
    def cli_log(level: str, message: str) -> None:
        entry = make_log_entry(cli_run_id, level, message)
        cli_log_entries.append(entry)
        append_persistent_log_entry(cli_log_path, entry)
    cli_log("info", "CLI started.")
    if args.gui_check:
        snapshot = gui_runtime_snapshot(create_window=True)
        ok = snapshot.get("status") == "ok"
        cli_log("info" if ok else "error", f"GUI runtime preflight status: {snapshot.get('status')}")
        print(safe_json_dumps(snapshot))
        return 0 if ok else 5
    try:
        cli_urls = normalize_cli_urls(args.url)
    except ValueError as exc:
        parser.error(str(exc))
    if len(cli_urls) > QUEUE_CAPACITY:
        parser.error(f"too many URLs; maximum is {QUEUE_CAPACITY}")
    jobs: list[dict[str, Any]] = [{"item_id": f"cli{idx}", "url": url, "status": "Queued", "result": {}} for idx, url in enumerate(cli_urls, 1)]
    run_context = {"run_id": cli_run_id, "mode": "cli", "started_at_utc": cli_start.isoformat(), "elapsed_seconds": 0.0, "queue_capacity": QUEUE_CAPACITY, "persistent_log_path": redact_path(cli_log_path), "retry_policy": retry_policy_snapshot(bool(settings.rate_limit_bytes), settings.smart_resilience)}
    report_path: Optional[Path] = resolve_export_destination(args.export_report, exports_dir()) if args.export_report else None
    diagnostic_path: Optional[Path] = None
    if args.diagnostic_export:
        diagnostic_path = default_diagnostic_zip_path() if str(args.diagnostic_export).lower() == "auto" else resolve_export_destination(args.diagnostic_export, diagnostics_dir())
    if report_path is not None and diagnostic_path is not None and report_path.resolve() == diagnostic_path.resolve():
        parser.error("--export-report and --diagnostic-export must use different destination files")
    report_checkpoint_failed = False

    def write_cli_report_checkpoint(stage: str) -> dict[str, Any]:
        if report_path is None:
            return {}
        snapshot = build_export_snapshot(jobs, cli_log_entries, settings_to_export(settings), dependency_snapshot())
        snapshot["run_summary"]["checkpoint_stage"] = stage
        snapshot["run_summary"]["run_id"] = cli_run_id
        snapshot["run_summary"]["run_elapsed_seconds"] = round(time.monotonic() - cli_start_monotonic, 3)
        return write_export_by_suffix(report_path, snapshot)

    if report_path is not None:
        cli_log("info", f"Initializing atomic report checkpoint: {redact_path(report_path)}")
        try:
            report_result = write_cli_report_checkpoint("initial")
            cli_log("info", f"Initial report checkpoint created (sha256={str(report_result.get('sha256') or '')[:16]}...).")
        except Exception as exc:
            cli_log("error", f"Initial report export failed: {redact_text(exc)}")
            print(f"Report export failed before download: {redact_text(exc)}", file=sys.stderr)
            return 4
    if args.diagnostic_export:
        run_context["elapsed_seconds"] = round(time.monotonic() - cli_start_monotonic, 3)
        if diagnostic_path is None:
            parser.error("diagnostic destination could not be resolved")
        try:
            snapshot = build_diagnostic_snapshot(jobs, cli_log_entries, settings_to_export(settings), dependency_snapshot(), run_context)
            result = write_diagnostic_zip(diagnostic_path, snapshot)
        except Exception as exc:
            cli_log("error", f"Diagnostic export failed: {redact_text(exc)}")
            print(f"Diagnostic export failed: {redact_text(exc)}", file=sys.stderr)
            return 4
        cli_log("info", f"Diagnostics exported: {result['path']}")
        print(f"Diagnostics exported: {result['path']}\nFiles: {result['entry_count']}\nSHA-256: {result.get('sha256')}")
        if args.diagnostics_only or not cli_urls or not args.i_have_rights:
            return 0
    if not cli_urls:
        parser.error("at least one URL is required unless diagnostics are requested")
    if not args.i_have_rights:
        parser.error("add --i-have-rights after confirming lawful, non-DRM use")
    try:
        import yt_dlp  # type: ignore
    except Exception as exc:
        cli_log("error", f"yt-dlp is not installed: {exc}")
        print(f"yt-dlp is not installed: {redact_text(exc)}", file=sys.stderr)
        return 2
    try:
        settings.output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        cli_log("error", f"Output folder could not be created: {redact_text(exc)}")
        print(f"Output folder could not be created: {redact_text(exc)}", file=sys.stderr)
        return 3
    for warning in dependency_warnings(settings):
        cli_log("warning", warning)
        print(f"WARNING: {warning}", file=sys.stderr)
    stop_event = threading.Event()
    force_stop_event = threading.Event()
    overall = 0
    interrupted = False
    adaptive_state = AdaptiveRunState(enabled=settings.smart_resilience)
    cli_log("info", f"Smart reconnect/adaptive throttle: {'enabled' if settings.smart_resilience else 'disabled'}")
    cli_log("info", f"Duplicate guard: {'enabled' if settings.use_archive else 'disabled'}")
    for job_index, job in enumerate(jobs, 1):
        q: "queue.Queue[tuple[Any, ...]]" = queue.Queue()
        telemetry: dict[str, Any] = {}
        started = time.monotonic()
        try:
            code = execute_isolated_worker_task(
                "download",
                str(job["url"]),
                settings,
                q,
                str(job["item_id"]),
                stop_event,
                telemetry,
                adaptive_state,
                force_stop_event,
            )
            telemetry["elapsed_seconds"] = round(time.monotonic() - started, 3)
            if code == 0 and not isinstance(telemetry.get("verification"), dict):
                telemetry["verification"] = {"status": "not_applicable", "method": "none", "reason": "No new final file was produced; download archive or an existing output may have skipped transfer."}
            job["result"] = telemetry
            duplicate_state = telemetry.get("duplicate_detection") if isinstance(telemetry.get("duplicate_detection"), dict) else {}
            duplicate_skipped = duplicate_state.get("status") in {"duplicate", "archive_or_existing_output_skip"}
            job["status"] = "Skipped duplicate" if code == 0 and duplicate_skipped else ("Done" if code == 0 else "Failed")
            overall = max(overall, code)
        except (KeyboardInterrupt, DownloadCancelled):
            stop_event.set()
            interrupted = True
            telemetry.update({
                "error_category": "cancelled",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "error": "Interrupted by user",
            })
            job["result"] = telemetry
            job["status"] = "Cancelled"
            overall = 130
            cli_log("warning", f"Download interrupted by user for {url_log_label(str(job['url']))}.")
            for remaining_job in jobs[job_index:]:
                remaining_job["status"] = "Cancelled"
                remaining_job["result"] = {"error_category": "cancelled", "reason": "Not started after keyboard interrupt"}
        except Exception as exc:
            telemetry.update({"error_category": classify_download_error(exc), "elapsed_seconds": round(time.monotonic() - started, 3), "error": redact_text(exc)})
            job["result"] = telemetry
            job["status"] = "Failed"
            overall = 1
            cli_log("error", f"Download failed ({telemetry['error_category']}) for {url_log_label(str(job['url']))}: {redact_text(exc)}")
        while not q.empty():
            event = q.get_nowait()
            if event[0] == "log":
                cli_log(str(event[1]), str(event[2]))
        should_checkpoint = len(jobs) <= 10 or job_index % 5 == 0 or job_index == len(jobs)
        if report_path is not None and should_checkpoint:
            try:
                write_cli_report_checkpoint(f"job_{job_index}_of_{len(jobs)}_complete")
            except Exception as exc:
                report_checkpoint_failed = True
                cli_log("warning", f"Report checkpoint failed after {job['item_id']}: {redact_text(exc)}")
        if interrupted:
            break
    cli_log("info" if overall == 0 else "error", f"CLI finished with exit code {overall}; elapsed={time.monotonic() - cli_start_monotonic:.2f}s")
    if report_path is not None:
        try:
            final_report = write_cli_report_checkpoint("final")
            cli_log("info", f"Final report checkpoint completed (sha256={str(final_report.get('sha256') or '')[:16]}...).")
        except Exception as exc:
            report_checkpoint_failed = True
            cli_log("error", f"Final report export failed: {redact_text(exc)}")
            print(f"Final report export failed: {redact_text(exc)}", file=sys.stderr)
    if report_checkpoint_failed:
        overall = max(overall, 4)
    return overall



def main(argv: Optional[Iterable[str]] = None) -> int:
    """Select GUI for a no-argument launch and CLI for every explicit argument.

    This keeps double-click behavior unchanged while ensuring direct operational
    flags such as --diagnostic-export never fall through into Tk startup.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--worker-job":
        if len(args) != 2:
            print("--worker-job requires exactly one project-local worker spec", file=sys.stderr)
            return 2
        return run_isolated_worker(Path(args[1]))
    if not args:
        return run_gui()
    if args[0] == "--gui":
        if len(args) > 1:
            print("--gui does not accept additional arguments", file=sys.stderr)
            return 2
        return run_gui()
    if args[0] == "--cli":
        args = args[1:]
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
