from __future__ import annotations

import unittest
import sys
import types
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

# Helper tests do not need a display. A tiny module stub keeps test discovery
# deterministic on headless Windows runners and minimal Python distributions.
tk_stub = types.ModuleType("tkinter")
tk_stub.Tk = object
tk_stub.filedialog = types.ModuleType("tkinter.filedialog")
tk_stub.messagebox = types.ModuleType("tkinter.messagebox")
tk_stub.ttk = types.ModuleType("tkinter.ttk")
sys.modules["tkinter"] = tk_stub
sys.modules["tkinter.filedialog"] = tk_stub.filedialog
sys.modules["tkinter.messagebox"] = tk_stub.messagebox
sys.modules["tkinter.ttk"] = tk_stub.ttk

from safe_media_downloader import (
    DownloadSettings,
    HIDE_MEDIA_DEFAULT,
    build_diagnostic_snapshot,
    canonical_url_key,
    download_archive_summary,
    prepare_download_archive,
    normalize_cli_urls,
    normalize_urls_with_stats,
    parse_rate_limit,
    redact_text,
    write_diagnostic_zip,
)


class PublicBehaviorTests(unittest.TestCase):
    @staticmethod
    def default_video_settings(output_dir: Path) -> DownloadSettings:
        return DownloadSettings(
            output_dir=output_dir,
            mode="Video",
            max_height=1080,
            custom_format="",
            include_playlist=False,
            embed_metadata=True,
            write_subtitles=False,
            restrict_filenames=True,
            use_archive=True,
            rate_limit_bytes=None,
            prefer_mp4=True,
            ffmpeg_location=None,
            hide_media=False,
        )

    def test_downloaded_media_is_visible_by_default(self) -> None:
        self.assertFalse(HIDE_MEDIA_DEFAULT)

    def test_equivalent_youtube_urls_share_an_identity(self) -> None:
        short = "https://youtu.be/abc123XYZ00?si=tracking"
        full = "https://www.youtube.com/watch?v=abc123XYZ00&utm_source=test"
        self.assertEqual(canonical_url_key(short), canonical_url_key(full))

    def test_url_list_collapses_tracking_only_duplicates(self) -> None:
        urls, duplicates = normalize_urls_with_stats(
            "https://example.org/video?id=7&utm_source=a\n"
            "https://example.org/video?utm_medium=b&id=7\n"
        )
        self.assertEqual(len(urls), 1)
        self.assertEqual(duplicates, 1)

    def test_cli_rejects_local_file_schemes(self) -> None:
        with self.assertRaises(ValueError):
            normalize_cli_urls(["file:///private/video.mp4"])

    def test_rate_limit_parser_is_bounded_to_positive_values(self) -> None:
        self.assertEqual(parse_rate_limit("1.5M"), int(1.5 * 1024**2))
        with self.assertRaises(ValueError):
            parse_rate_limit("0")

    def test_redaction_removes_credentials_and_user_details(self) -> None:
        synthetic_user_path = "C:" + r"\Users\Example\Downloads"
        redacted = redact_text(
            f"token=SECRET https://example.org/private?id=7 {synthetic_user_path} person@example.org"
        )
        self.assertNotIn("SECRET", redacted)
        self.assertNotIn("Example", redacted)
        self.assertNotIn("person@example.org", redacted)

    def test_redaction_removes_ipv6_addresses(self) -> None:
        address = "2001:0db8:85a3::8a2e:0370:7334"
        redacted = redact_text(f"peer={address}")
        self.assertNotIn(address, redacted)
        self.assertIn("<redacted-ip>", redacted)

    def test_default_variant_imports_the_bounded_legacy_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "downloads"
            output_dir.mkdir()
            legacy = output_dir / "download-archive.txt"
            legacy.write_text("youtube abc\nyoutube def\n", encoding="utf-8")
            state = root / "state"
            with patch("safe_media_downloader.state_dir", return_value=state):
                result = prepare_download_archive(self.default_video_settings(output_dir))
            self.assertEqual(result["status"], "legacy_default_imported")
            self.assertEqual(Path(result["path"]).read_bytes(), legacy.read_bytes())

    def test_legacy_archive_summary_contract_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            (output_dir / "download-archive.txt").write_text("one\ntwo\n", encoding="utf-8")
            summary = download_archive_summary(output_dir, True)
            self.assertEqual(summary["status"], "ok")
            self.assertEqual(summary["variant"], "legacy-global")
            self.assertEqual(summary["entries"], 2)

    def test_diagnostic_snapshot_and_zip_are_public_and_local_only(self) -> None:
        blocked_labels = (
            "chat" + "gpt",
            "drive_" + "vault",
            "command " + "center",
            "export" + "20",
            "project-" + "internal",
            "parameter_" + "bundle",
            "transfer_" + "summary",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = {
                "output_dir": tmpdir,
                "mode": "video",
                "hide_media": HIDE_MEDIA_DEFAULT,
                "smart_resilience": True,
            }
            snapshot = build_diagnostic_snapshot(
                jobs=[],
                logs=[],
                settings=settings,
                dependencies={},
                run_context={"mode": "cli", "run_id": "synthetic-test"},
            )
            serialized = json.dumps(snapshot, sort_keys=True).lower()
            self.assertIn("support_summary", snapshot)
            self.assertIn("public_files", snapshot)
            self.assertEqual(snapshot["support_summary"]["export_scope"]["status"], "local_only")
            for label in blocked_labels:
                self.assertNotIn(label, serialized)

            destination = Path(tmpdir) / "support-diagnostics.zip"
            result = write_diagnostic_zip(destination, snapshot)
            self.assertTrue(destination.is_file(), result)
            with zipfile.ZipFile(destination, "r") as archive:
                names = archive.namelist()
            self.assertIn("01-support-summary.md", names)
            self.assertIn("02-public-files.json", names)

    def test_public_source_has_no_legacy_private_integration_labels(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "safe_media_downloader.py").read_text(encoding="utf-8").lower()
        blocked_labels = (
            "chat" + "gpt",
            "google " + "drive",
            "drive_" + "vault",
            "command " + "center",
            "export" + "20",
            "project-" + "internal",
            "parameter_" + "bundle",
            "transfer_" + "summary",
            "full_batch_" + "output",
            "mani" + "fest.json",
            "mani" + "fest.csv",
        )
        for label in blocked_labels:
            self.assertNotIn(label, source)

if __name__ == "__main__":
    unittest.main()
