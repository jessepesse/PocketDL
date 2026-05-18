# Repository Guidelines

## Project Structure & Module Organization

PocketDL is a small Flask application with a static browser UI.

- `app.py` contains the Flask routes, download job state, `yt-dlp` command construction, cleanup loop, and health/version endpoints.
- `static/index.html` contains all frontend HTML, CSS, and JavaScript.
- `test_app.py` contains the pytest suite for API behavior, download flow, cancellation, history, and security regressions.
- `Dockerfile` and `docker-compose.yml` define the production container setup.
- `.github/workflows/release.yml` runs tests, builds/pushes the Docker image, and creates releases.
- `CHANGELOG.md` is the source for GitHub release notes.

Generated downloads live in `downloads/` and must not be committed.

## Build, Test, and Development Commands

Install dependencies:

```bash
pip install -r requirements.txt pytest
```

Run locally:

```bash
python app.py
```

The app listens on `http://localhost:5050` by default.

Run tests:

```bash
pytest -q
```

Run with Docker Compose:

```bash
docker compose up -d --build
```

Check service health:

```bash
curl http://localhost:5050/healthz
```

## Coding Style & Naming Conventions

Use Python 3.11-compatible code. Keep the backend simple and explicit; this project intentionally avoids a database, task queue, or frontend build system. Use four-space indentation in Python and existing vanilla JavaScript style in `static/index.html`.

Route handlers should return JSON errors with appropriate HTTP status codes. Keep helper names descriptive, for example `build_download_command`, `run_download`, and `is_allowed_history_filename`.

## Testing Guidelines

Tests use pytest and Flask’s test client. Add or update tests for route changes, download command changes, cancellation behavior, path handling, and security-sensitive logic.

Name tests with `test_...` and keep them focused on one behavior. Mock external processes and network-dependent downloader behavior; do not require live media downloads in the test suite.

## Commit & Pull Request Guidelines

Recent history uses concise messages such as `fix: ...`, `ci: ...`, `feat: ...`, and release commits like `Release vX.Y.Z`. Prefer this style for normal changes.

Pull requests should include:

- A short summary of user-visible behavior.
- Test results, usually `pytest -q`.
- Screenshots or mobile notes for UI changes.
- Changelog updates for release-worthy changes.

## Security & Configuration Tips

PocketDL accepts user-provided URLs and runs `yt-dlp`, so treat it as a private-network tool unless protected by a reverse proxy, VPN, or authentication layer. Keep `MAX_CONCURRENT_DOWNLOADS` and `MIN_DISK_SPACE_GB` configured for the host. Gunicorn should run with one worker unless job state is moved out of process memory.
