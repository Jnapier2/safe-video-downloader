from __future__ import annotations

import queue
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import safe_media_downloader as svd


TEST_WATCHDOG_SECONDS = 1.0


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
            with mock.patch.object(svd, "worker_task_dir", return_value=root / "worker"), mock.patch.object(svd, "worker_command", return_value=[sys.executable, "-c", "import time; time.sleep(30)"]), mock.patch.object(svd, "DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS", TEST_WATCHDOG_SECONDS):
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
            with mock.patch.object(svd, "worker_task_dir", return_value=root / "worker"), mock.patch.object(svd, "worker_command", return_value=[sys.executable, "-c", script]), mock.patch.object(svd, "DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS", TEST_WATCHDOG_SECONDS):
                result = svd.execute_isolated_worker_task("download", "https://example.com/video", make_settings(root / "output"), queue.Queue(), "activity-probe", threading.Event(), {}, svd.AdaptiveRunState(), threading.Event())
        self.assertEqual(result, 0)

    def test_processing_event_disarms_watchdog(self) -> None:
        script = "import json,time; print('SVD_EVENT:'+json.dumps(['job_status','job1','Processing']),flush=True); time.sleep(1.25); print('SVD_EVENT:'+json.dumps(['worker_terminal',{'outcome':'success','exit_code':0,'telemetry':{}}]),flush=True)"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with mock.patch.object(svd, "worker_task_dir", return_value=root / "worker"), mock.patch.object(svd, "worker_command", return_value=[sys.executable, "-c", script]), mock.patch.object(svd, "DOWNLOAD_NO_PROGRESS_TIMEOUT_SECONDS", TEST_WATCHDOG_SECONDS):
                result = svd.execute_isolated_worker_task("download", "https://example.com/video", make_settings(root / "output"), queue.Queue(), "processing-probe", threading.Event(), {}, svd.AdaptiveRunState(), threading.Event())
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
