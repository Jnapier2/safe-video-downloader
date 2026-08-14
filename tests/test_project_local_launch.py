from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import safe_media_downloader as app


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = PACKAGE_ROOT / "run_safe_video_downloader.bat"
SOURCE = PACKAGE_ROOT / "safe_media_downloader.py"


class ProjectLocalLaunchTests(unittest.TestCase):
    def test_default_download_directory_is_project_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            with patch.object(app, "app_base_dir", return_value=root):
                self.assertEqual(app.default_download_dir(), root / "downloads")
                self.assertEqual(app.resolve_output_dir("relative-output"), root / "relative-output")

    def test_launcher_is_root_relative_and_forwards_cli_arguments(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8").lower()
        self.assertIn('cd /d "%~dp0"', text)
        self.assertIn(r".venv\scripts\python.exe", text)
        self.assertIn('"%svd_script%" --gui', text)
        self.assertIn('"%svd_script%" %*', text)
        self.assertNotIn("executionpolicy bypass", text)
        root_launchers = sorted(
            path.name
            for path in PACKAGE_ROOT.iterdir()
            if path.is_file() and path.suffix.lower() in {".bat", ".cmd"}
        )
        self.assertEqual(root_launchers, ["run_safe_video_downloader.bat"])

    def test_export_dialogs_do_not_fall_back_to_user_home(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn('return Path.home() / "Downloads" / APP_NAME.replace(" ", "")', source)
        self.assertNotIn("initial_dir = Path.home()", source)


if __name__ == "__main__":
    unittest.main()
