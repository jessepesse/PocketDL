# PocketDL Roadmap 🚀

This document outlines the future goals and development direction for PocketDL. The primary objective is to keep the application **minimal, lightweight, and single-purpose** while improving its reliability and user experience.

## 🎯 Core Principles
- **Minimalism**: No unnecessary features or complex dependencies.
- **Reliability**: It should "just work" for any supported URL.
- **Portability**: Keep it easy to deploy via Docker on any system.

## 🛠️ Planned Improvements

### 1. Smart Quality Fallback
Improve the download logic to handle errors more gracefully. If a 4K download fails or is restricted by the provider, the system should automatically fall back to 1080p or the next best available quality instead of returning an error.

### 2. Enhanced Metadata & Embedding
Utilize `yt-dlp` capabilities to embed thumbnails and metadata (artist, title, album) directly into the downloaded files. This ensures MP3s and MP4s look professional in mobile media players.

### 3. Multi-Platform Awareness
Officially support and document more platforms beyond YouTube. Since `yt-dlp` supports hundreds of sites (TikTok, Twitter/X, Instagram, SoundCloud, etc.), the UI should reflect that it is a universal media downloader.

### 4. Basic Authentication (Optional Security)
Add support for simple environment-based authentication (`APP_USERNAME` and `APP_PASSWORD`). This will allow users to securely expose the service to the internet without needing a full reverse proxy setup.

### 5. Improved Error Reporting
Refine the UI to catch specific `yt-dlp` errors (like age restrictions or region blocks) and display them in a user-friendly way, suggesting alternatives when a download is impossible.

## 🚫 What We ARE NOT Adding
To maintain the minimalist nature of PocketDL, we avoid:
- **Databases**: We will continue using the filesystem for history.
- **Complex User Management**: No multi-user accounts or registration systems.
- **Heavy Task Queues**: Current Python threading is sufficient for personal use.

---
*Last updated: February 2026*
