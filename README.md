# Safe Video Downloader

[![CI](https://github.com/Jnapier2/safe-video-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/Jnapier2/safe-video-downloader/actions/workflows/ci.yml)

A controlled Windows desktop and command-line workflow for retrieving media the user is authorized to retain. Shared planning across both interfaces, explicit rights confirmation, duplicate controls, isolated workers, bounded recovery, and post-download verification make repeated operations more predictable without exposing browser credentials or shelling out user-supplied URLs.

The shared planner is the control point: regardless of interface, the same format, capacity, duplicate, and verification decisions govern each job. This keeps desktop and scripted use aligned as recovery behavior evolves.

## Operational controls

The workflow is designed to keep authorized retrieval predictable and reviewable:

- require the user to confirm download rights;
- reject unsupported URL schemes and avoid browser credential or cookie access;
- keep completed media visible by default;
- prevent repeat work through a download archive and media index;
- atomically preserve only unfinished queue work for interruption recovery;
- validate completed output and record useful, redacted diagnostics;
- stop active work responsively, including a bounded force-stop path.

The tool does **not** bypass DRM, authentication, paywalls, access controls, or site policy. It is intended for owned, public-domain, Creative Commons, and otherwise authorized media only.

## Safety model

- GUI and CLI entry points share the same download planning and verification path.
- User-provided URLs are passed to the `yt-dlp` Python API, not interpolated into a shell command.
- Adaptive retry profiles respond to transient network, stale-session, and rate-limit conditions with bounded backoff.
- Downloads run in an isolated worker process so stop and force-stop actions remain predictable.
- Duplicate detection normalizes harmless tracking differences while preserving the original requested URL.
- Diagnostic exports redact URLs, credentials, email addresses, user paths, and local network details.

## Quick start

Requirements: Windows 10/11 and Python 3.11 or newer. FFmpeg is optional but recommended for format merging.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python safe_media_downloader.py --gui
```

The included `run_safe_video_downloader.bat` launches the GUI with an existing project virtual environment or a compatible Python installation. It never installs packages silently.

For a CLI download, add the explicit rights acknowledgement:

```powershell
python safe_media_downloader.py --i-have-rights --output-dir downloads "https://example.org/authorized-media"
```

Downloaded media is visible by default. `--hide-media` is an explicit Windows-only opt-in. Run `python safe_media_downloader.py --help` for the complete interface.

## Verification

```powershell
python -m compileall -q safe_media_downloader.py tests
python -m unittest discover -s tests -v
```

Tests cover URL identity, rate-limit parsing, redaction, and explicit visible-output defaults without downloading external media.

## Boundaries

- Extractor behavior depends on upstream sites and the installed `yt-dlp` version.
- This project does not guarantee that a URL is lawful to download; the user must verify rights and applicable terms.
- No downloaded media, browser profile, cookies, credentials, executable build, or private diagnostic bundle is included in this repository.
- The source remains copyright-protected; see [LICENSE.md](LICENSE.md).
