#!/usr/bin/env python3
"""Apply the reviewed Safe Video Downloader 1.14.2 watchdog patch once.

Copyright © 2026 Gateway Information Group LLC. All rights reserved.
"""
from __future__ import annotations

from pathlib import Path

SOURCE_PATH = Path("safe_media_downloader.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = SOURCE_PATH.read_text(encoding="utf-8")
    text = replace_once(text, 'APP_VERSION = "1.14.1"', 'APP_VERSION = "1.14.2"', "app version")
    text = replace_once(
        text,
        'DIAGNOSTIC_EXPORT_SCHEMA_VERSION = "1.14.1"',
        'DIAGNOSTIC_EXPORT_SCHEMA_VERSION = "1.14.2"',
        "diagnostic version",
    )
    text = replace_once(
        text,
        'CANCEL_FORCE_WAIT_SECONDS = 3.0\nWORKER_EVENT_PREFIX = "SVD_EVENT:"',
        'CANCEL_FORCE_WAIT_SECONDS = 3.0\nDOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS = 5.0\nWORKER_EVENT_PREFIX = "SVD_EVENT:"',
        "watchdog constant",
    )
    text = replace_once(
        text,
        'class DownloadCancelled(Exception):\n    """Raised inside yt-dlp hooks when the user presses Stop."""\n\n\n@dataclass(frozen=True)',
        'class DownloadCancelled(Exception):\n    """Raised inside yt-dlp hooks when the user presses Stop."""\n\n\nclass DownloadNoProgressTimeout(Exception):\n    """Raised when an isolated download worker produces no activity for the configured timeout."""\n\n\n@dataclass(frozen=True)',
        "watchdog exception",
    )
    text = replace_once(
        text,
        '        "cancellation": {\n            "isolated_worker_process": True,\n            "cooperative_marker": True,\n            "automatic_hard_stop_after_seconds": CANCEL_GRACE_SECONDS,\n            "second_click_force_stop": True,\n            "process_tree_termination": True,\n            "partial_resume_preserved": True,\n        },\n        "smart_resilience": {',
        '        "cancellation": {\n            "isolated_worker_process": True,\n            "cooperative_marker": True,\n            "automatic_hard_stop_after_seconds": CANCEL_GRACE_SECONDS,\n            "second_click_force_stop": True,\n            "process_tree_termination": True,\n            "partial_resume_preserved": True,\n        },\n        "no_progress_timeout": {\n            "enabled": DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS > 0,\n            "seconds": DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS,\n            "scope": "download worker activity only; disabled during post-processing",\n            "action": "terminate worker process tree and preserve resumable .part files",\n        },\n        "smart_resilience": {',
        "retry policy",
    )
    text = replace_once(
        text,
        'def classify_download_error(exc: BaseException) -> str:\n    text = str(exc).lower()\n    if isinstance(exc, DownloadCancelled) or "cancel" in text:',
        'def classify_download_error(exc: BaseException) -> str:\n    text = str(exc).lower()\n    if isinstance(exc, DownloadNoProgressTimeout):\n        return "no_progress_timeout"\n    if isinstance(exc, DownloadCancelled) or "cancel" in text:',
        "error classification",
    )
    text = replace_once(
        text,
        '        "smart_resilience": settings.smart_resilience,\n        "format_selector": build_format_selector(settings),',
        '        "smart_resilience": settings.smart_resilience,\n        "download_no_progress_timeout_seconds": DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS,\n        "format_selector": build_format_selector(settings),',
        "settings export",
    )
    text = replace_once(
        text,
        '    hard_cancelled = False\n    interrupted = False\n\n    def reader() -> None:',
        '    hard_cancelled = False\n    interrupted = False\n    timeout_triggered = False\n    timeout_triggered_at: Optional[float] = None\n    last_activity_at = time.monotonic()\n    last_activity_kind = "worker_start"\n    activity_events = 0\n    watchdog_armed = task == "download" and DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS > 0\n\n    def reader() -> None:',
        "watchdog state",
    )
    text = replace_once(
        text,
        '            "cancel_grace_seconds": CANCEL_GRACE_SECONDS,\n            "partial_resume_policy": "yt-dlp .part files are preserved for a later resume",\n        }',
        '            "cancel_grace_seconds": CANCEL_GRACE_SECONDS,\n            "partial_resume_policy": "yt-dlp .part files are preserved for a later resume",\n            "no_progress_timeout_seconds": DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS if task == "download" else None,\n            "no_progress_timeout_scope": "disabled after byte transfer enters post-processing",\n        }',
        "worker telemetry",
    )
    text = replace_once(
        text,
        '            if line:\n                event = parse_worker_event_line(line)\n                if event is None:\n                    ui_queue.put(("log", "debug", redact_text(line)))\n                elif event[0] == "worker_terminal" and len(event) > 1 and isinstance(event[1], dict):\n                    terminal = dict(event[1])\n                else:\n                    ui_queue.put(event)\n\n            if stop_event.is_set() and cancellation_requested_at is None:',
        '            if line:\n                now_activity = time.monotonic()\n                last_activity_at = now_activity\n                activity_events += 1\n                event = parse_worker_event_line(line)\n                if event is None:\n                    last_activity_kind = "worker_output"\n                    ui_queue.put(("log", "debug", redact_text(line)))\n                elif event[0] == "worker_terminal" and len(event) > 1 and isinstance(event[1], dict):\n                    last_activity_kind = "worker_terminal"\n                    terminal = dict(event[1])\n                else:\n                    last_activity_kind = str(event[0])\n                    if event[0] == "job_status" and len(event) > 2 and str(event[2]).lower() == "processing":\n                        watchdog_armed = False\n                    elif event[0] == "progress" and len(event) > 2 and "post-processing" in str(event[2]).lower():\n                        watchdog_armed = False\n                    ui_queue.put(event)\n\n            if (\n                watchdog_armed\n                and not timeout_triggered\n                and cancellation_requested_at is None\n                and proc.poll() is None\n                and time.monotonic() - last_activity_at >= DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS\n            ):\n                timeout_triggered = True\n                timeout_triggered_at = time.monotonic()\n                idle_seconds = round(timeout_triggered_at - last_activity_at, 3)\n                termination = terminate_process_tree(proc)\n                telemetry.setdefault("worker_process", {})["termination"] = termination\n                telemetry["download_timeout"] = {\n                    "triggered": True,\n                    "mode": "no_progress",\n                    "threshold_seconds": DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS,\n                    "idle_seconds": idle_seconds,\n                    "last_activity_kind": last_activity_kind,\n                    "activity_events_seen": activity_events,\n                    "resumable_partial_preserved": True,\n                    "post_processing_excluded": True,\n                    "termination": termination,\n                }\n                ui_queue.put(("job_status", item_id, "Timed out"))\n                ui_queue.put(("log", "warning", f"Download timed out after {DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS:.0f}s without worker activity. The worker process tree was stopped and resumable partial data was preserved."))\n\n            if stop_event.is_set() and cancellation_requested_at is None:',
        "worker event loop",
    )
    text = replace_once(
        text,
        '    if stop_event.is_set() or interrupted or (terminal and terminal.get("outcome") == "cancelled"):',
        '    if timeout_triggered:\n        timeout_record = telemetry.setdefault("download_timeout", {})\n        timeout_record["worker_exit_code"] = proc.returncode if proc is not None else None\n        timeout_record["elapsed_after_trigger_seconds"] = round(time.monotonic() - timeout_triggered_at, 3) if timeout_triggered_at is not None else None\n        raise DownloadNoProgressTimeout(\n            f"Download made no worker progress for {DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS:.0f} seconds"\n        )\n\n    if stop_event.is_set() or interrupted or (terminal and terminal.get("outcome") == "cancelled"):',
        "watchdog terminal result",
    )
    SOURCE_PATH.write_text(text, encoding="utf-8", newline="\n")

    readme_path = Path("README.md")
    readme = readme_path.read_text(encoding="utf-8")
    marker = "- Downloads run in an isolated worker process so stop and force-stop actions remain predictable.\n"
    addition = marker + "- A five-second no-progress watchdog terminates a silent download worker, preserves resumable partial files, and disarms when post-processing begins.\n"
    if readme.count(marker) != 1:
        raise SystemExit("README watchdog insertion point is not unique")
    readme_path.write_text(readme.replace(marker, addition, 1), encoding="utf-8", newline="\n")

    Path("tests/test_no_progress_timeout.py").write_text(
        '''from __future__ import annotations

import queue
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import safe_media_downloader as svd


def make_settings(output_dir: Path) -> svd.DownloadSettings:
    return svd.DownloadSettings(output_dir=output_dir, mode="Video (best MP4)", max_height=1080, custom_format="", include_playlist=False, embed_metadata=False, write_subtitles=False, restrict_filenames=True, use_archive=True, rate_limit_bytes=None, prefer_mp4=True, ffmpeg_location=None, hide_media=False, smart_resilience=True)


class NoProgressWatchdogTests(unittest.TestCase):
    def test_policy_and_export_expose_five_second_timeout(self) -> None:
        self.assertEqual(svd.APP_VERSION, "1.14.2")
        self.assertEqual(svd.DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS, 5.0)
        self.assertEqual(svd.retry_policy_snapshot()["no_progress_timeout"]["seconds"], 5.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(svd.settings_to_export(make_settings(Path(tmpdir)))["download_no_progress_timeout_seconds"], 5.0)

    def test_silent_download_worker_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            telemetry: dict[str, object] = {}
            with mock.patch.object(svd, "worker_task_dir", return_value=root / "worker"), mock.patch.object(svd, "worker_command", return_value=[sys.executable, "-c", "import time; time.sleep(30)"]), mock.patch.object(svd, "DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS", 0.25):
                started = time.monotonic()
                with self.assertRaises(svd.DownloadNoProgressTimeout):
                    svd.execute_isolated_worker_task("download", "https://example.com/video", make_settings(root / "output"), queue.Queue(), "timeout-probe", threading.Event(), telemetry, svd.AdaptiveRunState(), threading.Event())
            self.assertLess(time.monotonic() - started, 4.0)
            self.assertTrue(telemetry["download_timeout"]["triggered"])
            self.assertTrue(telemetry["download_timeout"]["resumable_partial_preserved"])

    def test_worker_activity_resets_timeout(self) -> None:
        script = "import json,time; [(print('SVD_EVENT:'+json.dumps(['progress',1.0,'tick']),flush=True),time.sleep(0.10)) for _ in range(5)]; print('SVD_EVENT:'+json.dumps(['worker_terminal',{'outcome':'success','exit_code':0,'telemetry':{}}]),flush=True)"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with mock.patch.object(svd, "worker_task_dir", return_value=root / "worker"), mock.patch.object(svd, "worker_command", return_value=[sys.executable, "-c", script]), mock.patch.object(svd, "DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS", 0.25):
                result = svd.execute_isolated_worker_task("download", "https://example.com/video", make_settings(root / "output"), queue.Queue(), "activity-probe", threading.Event(), {}, svd.AdaptiveRunState(), threading.Event())
        self.assertEqual(result, 0)

    def test_processing_event_disarms_watchdog(self) -> None:
        script = "import json,time; print('SVD_EVENT:'+json.dumps(['job_status','job1','Processing']),flush=True); time.sleep(0.50); print('SVD_EVENT:'+json.dumps(['worker_terminal',{'outcome':'success','exit_code':0,'telemetry':{}}]),flush=True)"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with mock.patch.object(svd, "worker_task_dir", return_value=root / "worker"), mock.patch.object(svd, "worker_command", return_value=[sys.executable, "-c", script]), mock.patch.object(svd, "DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS", 0.25):
                result = svd.execute_isolated_worker_task("download", "https://example.com/video", make_settings(root / "output"), queue.Queue(), "processing-probe", threading.Event(), {}, svd.AdaptiveRunState(), threading.Event())
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
