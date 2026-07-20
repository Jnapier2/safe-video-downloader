# Security Policy

## Supported version

Security fixes target the current version on the default branch.

## Reporting a vulnerability

Please use GitHub's private vulnerability-reporting or security-advisory feature for this repository. Do not include real credentials, private URLs, downloaded media, browser profiles, or personal diagnostic bundles in an issue.

Include the affected version, a minimal reproduction using synthetic or public-domain inputs, expected and observed behavior, and the security impact. Please allow time for confirmation before public disclosure.

## Intended security boundary

Safe Video Downloader accepts public URL input for authorized, non-DRM media. GUI and CLI inputs are limited to `http`, `https`, and `ftp`; URLs with embedded credentials, local hostnames, or direct or DNS-resolved non-public addresses are rejected before queueing and checked again by the isolated worker. It intentionally does not read browser cookies, automate login, bypass access controls, execute downloaded files, or interpolate URLs into shell commands. Reports intended for troubleshooting are redacted, but users should still review every artifact before sharing it.

The URL check is a defense-in-depth preflight, not complete SSRF containment. Redirects, extractor-discovered subresources, and DNS changes can occur after validation inside upstream networking code. Run the application without access to sensitive internal services and report any path that reaches a non-public target.
