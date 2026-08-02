# Safe Video Downloader

[![CI](https://github.com/Jnapier2/safe-video-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/Jnapier2/safe-video-downloader/actions/workflows/ci.yml)

A controlled Windows desktop and command-line workflow for retrieving media the user is authorized to retain. Shared planning across both interfaces, explicit rights confirmation, duplicate controls, isolated workers, bounded recovery, and post-download verification make repeated operations more predictable without exposing browser credentials or passing user-supplied URLs through a command shell.

GUI and CLI jobs use the same planning and verification path. Format, capacity, duplicate, and final validation decisions stay consistent between desktop and scripted use.

## Operational controls

The workflow is designed to keep authorized retrieval predictable and reviewable:

- require the user to confirm download rights;
- accept only public `http`, `https`, and `ftp` targets, with hostname and resolved-address checks before media retrieval;
- keep completed media visible by default;
- prevent repeat work through a download archive and media index;
- atomically preserve only unfinished queue work for interruption recovery;
- validate completed output and record useful, redacted diagnostics;
- stop active work responsively, including a bounded force-stop path.

The tool does **not** bypass DRM, authentication, paywalls, access controls, or site policy. It is intended for owned, public-domain, Creative Commons, and otherwise authorized media only.

## Safety model

- GUI and CLI entry points share the same download planning and verification path.
- Public-network preflight rejects embedded credentials, local hostnames, and direct or DNS-resolved non-public addresses; the isolated worker checks the boundary again before retrieval.
- User-provided URLs are passed to the `yt-dlp` Python API, not interpolated into a shell command.
- Adaptive retry profiles respond to transient network, stale-session, and rate-limit conditions with bounded backoff.
- Downloads run in an isolated worker process so stop and force-stop actions remain predictable.
- A five-second no-progress watchdog terminates a silent download worker, preserves resumable partial files, and disarms when post-processing begins.
- Duplicate detection normalizes harmless tracking differences while preserving the original requested URL.
- Diagnostic exports redact URLs, credentials, email addresses, user paths, and local network details.

## Quick start

Requirements: Windows 10/11 and Python 3.11–3.13. FFmpeg is optional but recommended for format merging.

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

Tests cover the offline public-URL boundary, URL identity, rate-limit parsing, redaction, media-signature fallback, batch exit policy, and explicit visible-output defaults without downloading external media.

## Boundaries

- Extractor behavior depends on upstream sites and the installed `yt-dlp` version.
- Public-network preflight is a defense-in-depth check of submitted targets. Redirects, extractor-discovered subresources, and DNS changes occur after validation, so the application should run without access to sensitive internal services.
- This project does not guarantee that a URL is lawful to download; the user must verify rights and applicable terms.
- No downloaded media, browser profile, cookies, credentials, executable build, or private diagnostic bundle is included in this repository.
- Source and documentation terms are defined in [LICENSE.md](LICENSE.md).

## Portfolio and rights

[Portfolio](https://jerry-napier-portfolio.netlify.app/) · [GitHub profile](https://github.com/Jnapier2)

Copyright © 2026 Gateway Information Group LLC. All rights reserved. Third-party components and services retain their own rights and terms.
