# Use a lightweight Python base image
FROM python:3.11-slim

# Install FFmpeg and CRON
RUN apt-get update && \
    apt-get install -y ffmpeg cron && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user and set permissions
RUN useradd -m appuser && \
    mkdir -p /app/downloads && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Set up Cron job for automatic yt-dlp updates (every night at 03:00)
# Note: In a container, it's safer to have cron run via an entrypoint if needed,
# or simply use a simple loop in the app. For now, we'll keep it via pip.

# Port exposed by Flask
EXPOSE 5050

# Environment variables
ENV PORT=5050
ENV DOWNLOAD_DIR=/app/downloads

# Start the Flask app
CMD ["python", "app.py"]
