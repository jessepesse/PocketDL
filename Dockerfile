# Use a lightweight Python base image
FROM python:3.11-slim

# Install FFmpeg and Deno (JS runtime for yt-dlp-ejs)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl unzip && \
    curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh && \
    apt-get purge -y curl unzip && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir "yt-dlp[default,curl-cffi]" yt-dlp-ejs

# Copy application code
COPY . .

# Create non-root user and set permissions
RUN useradd -m appuser && \
    mkdir -p /app/downloads && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Port exposed by Flask
EXPOSE 5050

# Environment variables
ENV PORT=5050
ENV DOWNLOAD_DIR=/app/downloads

# Start the app with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--workers", "1", "--threads", "4", "app:app"]
