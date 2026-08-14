from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "safe_media_downloader.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''def default_download_dir() -> Path:\n    return Path.home() / "Downloads" / APP_NAME.replace(" ", "")\n''',
        '''def default_download_dir() -> Path:\n    """Return the project-local default media destination."""\n    return app_base_dir() / "downloads"\n''',
        "project-local default downloads",
    )

    text = replace_once(
        text,
        '''        initial_dir = exports_dir()\n        try:\n            initial_dir.mkdir(parents=True, exist_ok=True)\n        except Exception:\n            try:\n                initial_dir = Path(self.output_dir_var.get()).expanduser()\n            except Exception:\n                initial_dir = default_download_dir()\n        if not initial_dir.exists():\n            initial_dir = Path.home()\n''',
        '''        initial_dir = exports_dir()\n        try:\n            initial_dir.mkdir(parents=True, exist_ok=True)\n        except Exception as exc:\n            self._log("error", f"Project-local export folder is unavailable: {exc}")\n            messagebox.showerror(APP_NAME, f"Project-local export folder is unavailable:\\n{exc}")\n            return\n''',
        "report export fallback",
    )

    text = replace_once(
        text,
        '''        initial_dir = diagnostics_dir()\n        try:\n            initial_dir.mkdir(parents=True, exist_ok=True)\n        except Exception:\n            initial_dir = Path.home()\n''',
        '''        initial_dir = diagnostics_dir()\n        try:\n            initial_dir.mkdir(parents=True, exist_ok=True)\n        except Exception as exc:\n            self._log("error", f"Project-local diagnostics folder is unavailable: {exc}")\n            messagebox.showerror(APP_NAME, f"Project-local diagnostics folder is unavailable:\\n{exc}")\n            return\n''',
        "diagnostics export fallback",
    )

    text = replace_once(
        text,
        '''    "tests/test_safety_behavior.py",\n)\n''',
        '''    "tests/test_safety_behavior.py",\n    "tests/test_no_progress_timeout.py",\n    "tests/test_project_local_launch.py",\n)\n''',
        "portability scan inventory",
    )

    text = replace_once(
        text,
        '''    {"asset_id": "SVD-TESTS", "path": "tests/test_safety_behavior.py", "title": "Safety behavior tests", "purpose": "Offline safety and parsing regression tests", "asset_class": "test", "role": "verification", "format": "py", "status": "current", "sensitivity": "public", "source_of_truth": False, "tags": ["tests"], "aliases": [], "metadata_depth": "file"},\n)\n''',
        '''    {"asset_id": "SVD-TESTS", "path": "tests/test_safety_behavior.py", "title": "Safety behavior tests", "purpose": "Offline safety and parsing regression tests", "asset_class": "test", "role": "verification", "format": "py", "status": "current", "sensitivity": "public", "source_of_truth": False, "tags": ["tests"], "aliases": [], "metadata_depth": "file"},\n    {"asset_id": "SVD-WATCHDOG-TESTS", "path": "tests/test_no_progress_timeout.py", "title": "Worker watchdog tests", "purpose": "No-progress timeout and post-processing regression tests", "asset_class": "test", "role": "verification", "format": "py", "status": "current", "sensitivity": "public", "source_of_truth": False, "tags": ["tests", "watchdog"], "aliases": [], "metadata_depth": "file"},\n    {"asset_id": "SVD-LAUNCH-TESTS", "path": "tests/test_project_local_launch.py", "title": "Project-local launch tests", "purpose": "Canonical launcher and project-local output regression tests", "asset_class": "test", "role": "verification", "format": "py", "status": "current", "sensitivity": "public", "source_of_truth": False, "tags": ["tests", "launcher", "portability"], "aliases": [], "metadata_depth": "file"},\n)\n''',
        "asset inventory",
    )

    SOURCE.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
