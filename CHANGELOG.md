# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.6.1] - 2026-05-24

### Fixed
- Restored live download progress updates when using `yt-dlp --print` by enabling progress output explicitly
- Switched progress parsing to a stable `yt-dlp --progress-template` line while keeping legacy progress output support

## [1.6.0] - 2026-05-18

### Added
- Added `AGENTS.md` contributor guidelines for repository structure, development commands, testing, and release expectations
- Added a `Custom` video quality option for advanced `yt-dlp` format selectors
- Added backend validation for custom format selectors
- Added completed download file size metadata for UI decisions

### Changed
- Android quality now uses the same best available video format as the default `Best` option
- `Save to Photos` is hidden for videos larger than 150 MB to avoid loading large files into mobile browser memory
- Improved the iOS share fallback message when sharing is cancelled or blocked

## [1.5.0] - 2026-05-17

### Added
- Added a video quality selector with `Best`, `iPhone`, and `Android` options
- Automatically defaults the quality selector to `iPhone` on iOS, `Android` on Android, and `Best` elsewhere
- Added backend validation and `yt-dlp` format handling for the new `quality` download field

### Changed
- `Save to Photos` now restores the button state after opening the native share sheet, even if iOS keeps the share promise pending
- iPhone quality downloads now prefer iOS-compatible MP4/H.264 video with M4A audio

## [1.4.2] - 2026-05-17

### Fixed
- Let iOS attempt `Save to Photos` over HTTP instead of blocking before calling Web Share
- Moved the HTTPS guidance into the fallback error message shown only after sharing fails

## [1.4.1] - 2026-05-17

### Fixed
- Relaxed mobile `Save to Photos` button detection so it is shown on iPhone even when Web Share support cannot be confirmed before tapping
- Added `Save to Photos` support for MP4 files in download history
- Improved the iOS/HTTPS error message when Web Share file sharing is unavailable

## [1.4.0] - 2026-05-17

### Added
- Added a mobile-only `Save to Photos` action for completed MP4 downloads using the Web Share API

### Changed
- Consolidated `yt-dlp` dependencies into `requirements.txt` so local, CI, and Docker installs use the same dependency list
- Docker builds now install dependencies from `requirements.txt` only

### Removed
- Removed the unused `/info` endpoint and related tests
- Removed obsolete cancel-time cleanup for the old `_job_<id>_` temporary filename prefix
- Removed unused `send_file` import

### CI
- Added a pytest gate before Docker image build and push in the release workflow

## [1.3.2] - 2026-05-05

### Fixed
- Removed unsupported `yt-dlp` option `--temp-filename-prefix` that caused immediate download failures on newer `yt-dlp` versions
- Improved download error diagnostics by logging failed attempt return code and recent output lines
- Download status error message now falls back to the latest downloader output line when no explicit `ERROR:` line exists

### Added
- Input validation for `/download` `format` value; only `video` and `audio` are accepted
- Video download fallback: if `bestvideo+bestaudio/best` fails, PocketDL retries once with `best`

## [1.3.1] - 2026-04-18

### Fixed
- Frontend polling now handles status endpoint errors gracefully and clears stale UI state
- Video title is now updated during active polling
- Job cancellation handles already-exited subprocesses safely (prevents race-condition crash)
- Cancelling a job now removes its process handle from in-memory tracking
- History file endpoints now reject partial files (e.g. `.part`) with 404

### Tests
- Added regression test for cancelling a job after process exit
- Added tests to ensure `.part` files are blocked from history download/delete routes

## [1.3.0] - 2026-03-17

### Fixed
- Cancel job now only removes its own temp files (per-job `--temp-filename-prefix`)
- History download button now works via dedicated `GET /files/history/<filename>` route
- Race condition in `/history` when file is deleted between listing and stat
- Malformed JSON body now returns 400 instead of crashing
- Download threads are now daemon threads (no longer block app shutdown)
- Path traversal attack prevented on `DELETE /files/history/<filename>`

### Added
- `/healthz` endpoint for container health monitoring
- `HEALTHCHECK` instruction in Dockerfile using `/healthz`
- `PYTHONDONTWRITEBYTECODE` and `PYTHONUNBUFFERED` env vars in Dockerfile
- Full pytest test suite (30 tests covering all API endpoints)

### Changed
- Deno pinned to v2.7.5 for reproducible builds (was installing latest)
- GitHub Actions updated to Node.js 24 compatible versions

### CI
- Fixed weekly scheduled build failing due to missing git tag
- Separated semver release tag from `latest` tag in CI workflow

## [1.2.0] - 2025-01-26

### Added
- gunicorn as production WSGI server (replaces Flask dev server)
- `yt-dlp-ejs` and Deno runtime for improved YouTube support
- `curl_cffi` for better TLS impersonation and site compatibility
- `--embed-thumbnail` and `--embed-metadata` flags for all downloads

## [1.1.5] and earlier

See git history for changes prior to v1.2.0.

[Unreleased]: https://github.com/jessepesse/PocketDL/compare/v1.6.1...HEAD
[1.6.1]: https://github.com/jessepesse/PocketDL/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/jessepesse/PocketDL/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/jessepesse/PocketDL/compare/v1.4.2...v1.5.0
[1.4.2]: https://github.com/jessepesse/PocketDL/compare/v1.4.1...v1.4.2
[1.4.1]: https://github.com/jessepesse/PocketDL/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/jessepesse/PocketDL/compare/v1.3.2...v1.4.0
[1.3.2]: https://github.com/jessepesse/PocketDL/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/jessepesse/PocketDL/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/jessepesse/PocketDL/compare/v1.2.1...v1.3.0
[1.2.0]: https://github.com/jessepesse/PocketDL/compare/v1.1.5...v1.2.0
