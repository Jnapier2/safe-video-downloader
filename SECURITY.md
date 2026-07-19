# Security Policy

## Supported version

Security fixes target the current version on the default branch.

## Reporting a vulnerability

Please use GitHub's private vulnerability-reporting or security-advisory feature for this repository. Do not include real credentials, private URLs, downloaded media, browser profiles, or personal diagnostic bundles in an issue.

Include the affected version, a minimal reproduction using synthetic or public-domain inputs, expected and observed behavior, and the security impact. Please allow time for confirmation before public disclosure.

## Intended security boundary

Safe Video Downloader accepts public URL input for authorized, non-DRM media. It intentionally does not read browser cookies, automate login, bypass access controls, execute downloaded files, or interpolate URLs into shell commands. Reports intended for troubleshooting are redacted, but users should still review every artifact before sharing it.
