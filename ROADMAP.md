# PocketDL Roadmap 🚀

This document outlines the future goals and development direction for PocketDL. The primary objective is to keep the application **minimal, lightweight, and single-purpose** while improving its reliability and user experience.

## 🎯 Core Principles
- **Minimalism**: No unnecessary features or complex dependencies.
- **Reliability**: It should "just work" for any supported URL.
- **Portability**: Keep it easy to deploy via Docker on any system.

## 🛠️ Planned Improvements

### 1. Smart Quality Fallback
Improve the download logic to handle errors more gracefully. If a 4K download fails or is restricted by the provider, the system should automatically fall back to 1080p or the next best available quality instead of returning an error.

### 2. ~~Enhanced Metadata & Embedding~~ ✅ Done
Thumbnails and metadata (artist, title, album) are now automatically embedded into downloaded MP3 and MP4 files via `--embed-thumbnail` and `--embed-metadata`.

### 3. ~~Multi-Platform Awareness~~ ✅ Done
README and UI now reflect support for 1000+ sites including YouTube, TikTok, Twitter/X, Instagram, and more.

### 4. Basic Authentication (Optional Security)
Add support for simple environment-based authentication (`APP_USERNAME` and `APP_PASSWORD`). This will allow users to securely expose the service to the internet without needing a full reverse proxy setup.

### 5. PWA & Mobile Share Target
Convert the web UI into a Progressive Web App (PWA) with Share Target support. This allows mobile users to share URLs directly from YouTube, TikTok, or any browser to PocketDL via the native share menu — no need to manually copy and paste URLs.

### 6. Improved Error Reporting
Refine the UI to catch specific `yt-dlp` errors (like age restrictions or region blocks) and display them in a user-friendly way, suggesting alternatives when a download is impossible.

## 🚫 What We ARE NOT Adding
To maintain the minimalist nature of PocketDL, we avoid:
- **Databases**: We will continue using the filesystem for history.
- **Complex User Management**: No multi-user accounts or registration systems.
- **Heavy Task Queues**: Current Python threading is sufficient for personal use.

---
*Last updated: March 2026*
