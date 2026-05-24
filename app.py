import os
import re
import subprocess
import threading
import uuid
import time
import logging
import shutil
from collections import deque
from flask import Flask, request, jsonify, send_from_directory
import yt_dlp

# Configuration
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", os.path.join(os.path.dirname(__file__), "downloads"))
MIN_DISK_SPACE_GB = int(os.environ.get("MIN_DISK_SPACE_GB", 2))
MAX_CONCURRENT_DOWNLOADS = int(os.environ.get("MAX_CONCURRENT_DOWNLOADS", 3))
APP_VERSION = "1.6.1"

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory storage for download jobs
jobs = {}
jobs_lock = threading.Lock()
job_processes = {}  # {job_id: Popen} — separate dict to avoid JSON serialization issues

PROGRESS_RE = re.compile(r'\[download\]\s+([\d.]+)%.*?at\s+(\S+)\s+ETA\s+(\S+)')
PROGRESS_TEMPLATE_PREFIX = 'PDL_PROGRESS:'
PROGRESS_TEMPLATE = f'download:{PROGRESS_TEMPLATE_PREFIX}%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s'
ALLOWED_HISTORY_EXTENSIONS = {'.mp4', '.mp3'}
VIDEO_FORMATS = {
    'best': 'bestvideo+bestaudio/best',
    'ios': 'bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[ext=mp4]/best',
    'android': 'bestvideo+bestaudio/best',
}
VIDEO_QUALITIES = set(VIDEO_FORMATS) | {'custom'}
MAX_CUSTOM_FORMAT_LENGTH = 300


def is_allowed_history_filename(filename):
    _, ext = os.path.splitext(filename)
    return ext.lower() in ALLOWED_HISTORY_EXTENSIONS


def kill_process_safely(process):
    if not process:
        return
    try:
        process.kill()
    except (ProcessLookupError, OSError):
        pass

def resolve_video_format(quality='best', custom_format=''):
    if quality == 'custom':
        return custom_format
    return VIDEO_FORMATS.get(quality, VIDEO_FORMATS['best'])


def is_valid_custom_format(custom_format):
    return (
        isinstance(custom_format, str)
        and 0 < len(custom_format) <= MAX_CUSTOM_FORMAT_LENGTH
        and not any(ch in custom_format for ch in ('\x00', '\n', '\r'))
    )


def build_download_command(url, format_type='video', quality='best', custom_format='', fallback_video=False):
    cmd = [
        'yt-dlp',
        '--newline',
        '--no-playlist',
        '--print', 'TITLE:%(title)s',
        '--print', 'after_move:filepath',
        '--progress',
        '--progress-template', PROGRESS_TEMPLATE,
        '--progress-delta', '1',
        '--output', os.path.join(DOWNLOAD_DIR, '%(title)s_%(id)s.%(ext)s'),
        '--embed-thumbnail',
        '--embed-metadata',
    ]
    if format_type == 'video':
        if fallback_video:
            cmd += ['--format', 'best']
        else:
            cmd += ['--format', resolve_video_format(quality, custom_format), '--merge-output-format', 'mp4']
    else:
        cmd += ['--format', 'bestaudio/best', '--extract-audio',
                '--audio-format', 'mp3', '--audio-quality', '192K']
    cmd += ['--', url]
    return cmd


def parse_progress_line(line):
    if line.startswith(PROGRESS_TEMPLATE_PREFIX):
        parts = line[len(PROGRESS_TEMPLATE_PREFIX):].split('|', 2)
        if len(parts) != 3:
            return None
        percent_text, speed, eta = parts
        percent_match = re.search(r'([\d.]+)%', percent_text)
        if not percent_match:
            return None
        return float(percent_match.group(1)), speed.strip(), eta.strip()

    m = PROGRESS_RE.search(line)
    if m:
        return float(m.group(1)), m.group(2), m.group(3)

    return None


def run_download(url, job_id, format_type='video', quality='best', custom_format=''):
    attempts = [False, True] if format_type == 'video' else [False]

    try:
        for idx, fallback_video in enumerate(attempts, start=1):
            cmd = build_download_command(url, format_type, quality=quality, custom_format=custom_format, fallback_video=fallback_video)
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            with jobs_lock:
                # FIX: Check if already cancelled before overwriting status
                if job_id not in jobs or jobs[job_id]['status'] == 'cancelled':
                    kill_process_safely(process)
                    process.wait()
                    return
                jobs[job_id]['status'] = 'downloading'
                job_processes[job_id] = process

            final_path = None
            last_error = None
            output_tail = deque(maxlen=25)

            for line in process.stdout:
                line = line.rstrip()
                if line:
                    output_tail.append(line)
                progress = parse_progress_line(line)
                if progress:
                    percent, speed, eta = progress
                    with jobs_lock:
                        if job_id in jobs:
                            jobs[job_id]['progress'] = percent
                            jobs[job_id]['speed'] = speed
                            jobs[job_id]['eta'] = eta
                elif line.startswith('TITLE:'):
                    # FIX: Update title from yt-dlp output
                    with jobs_lock:
                        if job_id in jobs:
                            jobs[job_id]['title'] = line[6:]
                elif line.startswith(DOWNLOAD_DIR):
                    final_path = line
                elif re.search(r'\berror\b', line, re.IGNORECASE):
                    last_error = line

                cancelled = False
                with jobs_lock:
                    if job_id in jobs and jobs[job_id]['status'] == 'cancelled':
                        job_processes.pop(job_id, None)  # FIX: clean up dict
                        cancelled = True
                if cancelled:
                    kill_process_safely(process)
                    process.wait()  # FIX: reap zombie, outside lock to avoid blocking
                    return

            process.wait()

            with jobs_lock:
                job_processes.pop(job_id, None)
                if job_id not in jobs or jobs[job_id]['status'] == 'cancelled':
                    return
                if process.returncode == 0 and final_path:
                    jobs[job_id]['filename'] = os.path.basename(final_path)
                    try:
                        jobs[job_id]['filesize_mb'] = round(os.path.getsize(final_path) / (1024 * 1024), 2)
                    except OSError:
                        jobs[job_id]['filesize_mb'] = None
                    jobs[job_id]['status'] = 'finished'
                    jobs[job_id]['progress'] = 100
                    jobs[job_id]['completed_at'] = time.time()
                    return

            output_tail_text = " | ".join(output_tail) if output_tail else "<no output>"
            logger.warning(
                "yt-dlp attempt failed (job_id=%s attempt=%s/%s fallback=%s rc=%s url=%s tail=%s)",
                job_id, idx, len(attempts), fallback_video, process.returncode, url, output_tail_text
            )
            if idx < len(attempts):
                continue

            with jobs_lock:
                if job_id in jobs and jobs[job_id]['status'] != 'cancelled':
                    jobs[job_id]['status'] = 'error'
                    jobs[job_id]['error'] = last_error or (output_tail[-1] if output_tail else 'Download failed')
                    jobs[job_id]['completed_at'] = time.time()
            return

    except Exception as e:
        logger.error(f"Download error for job {job_id}: {str(e)}")
        with jobs_lock:
            job_processes.pop(job_id, None)
            if job_id in jobs and jobs[job_id]['status'] != 'cancelled':
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = 'Download failed'  # FIX: don't expose internals
                jobs[job_id]['completed_at'] = time.time()

@app.route('/download', methods=['POST'])
def start_download():
    # 1. Check Disk Space
    total, used, free = shutil.disk_usage(DOWNLOAD_DIR)
    free_gb = free // (2**30)
    if free_gb < MIN_DISK_SPACE_GB:
        return jsonify({"error": f"Low disk space. Only {free_gb}GB remaining."}), 507

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid or missing JSON body"}), 400
    url = data.get('url')
    format_type = data.get('format', 'video')
    quality = data.get('quality', 'best')
    custom_format = data.get('custom_format', '').strip()

    if not url: return jsonify({"error": "No URL provided"}), 400
    if format_type not in ('video', 'audio'):
        return jsonify({"error": "Invalid format. Use 'video' or 'audio'."}), 400
    if quality not in VIDEO_QUALITIES:
        return jsonify({"error": "Invalid quality. Use 'best', 'ios', 'android', or 'custom'."}), 400
    if format_type == 'video' and quality == 'custom' and not is_valid_custom_format(custom_format):
        return jsonify({"error": "Invalid custom format selector."}), 400

    # Check concurrent limits and register job atomically
    job_id = str(uuid.uuid4())
    with jobs_lock:
        active_jobs = [j for j in jobs.values() if j['status'] in ['pending', 'downloading']]
        if len(active_jobs) >= MAX_CONCURRENT_DOWNLOADS:
            return jsonify({"error": "Too many active downloads. Please wait."}), 429
        # FIX: Reject duplicate URL already being downloaded
        if any(j.get('url') == url for j in active_jobs):
            return jsonify({"error": "This URL is already being downloaded."}), 409
        jobs[job_id] = {
            'status': 'pending',
            'url': url,
            'progress': 0,
            'speed': '0',
            'eta': 'N/A',
            'title': 'Fetching info...',
            'filename': '',
            'error': ''
        }
    
    threading.Thread(target=run_download, args=(url, job_id, format_type, quality, custom_format), daemon=True).start()
    return jsonify({"job_id": job_id})

@app.route('/cancel/<job_id>', methods=['POST'])
def cancel_download(job_id):
    process = None
    with jobs_lock:
        if job_id in jobs:
            if jobs[job_id]['status'] in ['pending', 'downloading']:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['completed_at'] = time.time()
                process = job_processes.pop(job_id, None)
            else:
                return jsonify({"error": "Job not found or already finished"}), 404
        else:
            return jsonify({"error": "Job not found or already finished"}), 404
    kill_process_safely(process)
    return jsonify({"status": "cancelled"})

@app.route('/status/<job_id>')
def get_status(job_id):
    with jobs_lock:
        if job_id not in jobs:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(jobs[job_id])

@app.route('/history')
def get_history():
    files = []
    if not os.path.exists(DOWNLOAD_DIR): return jsonify([])
    for filename in os.listdir(DOWNLOAD_DIR):
        if is_allowed_history_filename(filename):
            file_path = os.path.join(DOWNLOAD_DIR, filename)
            try:
                stats = os.stat(file_path)
            except FileNotFoundError:
                continue
            files.append({
                "filename": filename,
                "size": round(stats.st_size / (1024 * 1024), 2),
                "mtime": stats.st_mtime,
                "format": "video" if filename.endswith('.mp4') else "audio"
            })
    files.sort(key=lambda x: x['mtime'], reverse=True)
    return jsonify(files)

@app.route('/files/<job_id>/<path:filename>')
def serve_file(job_id, filename):
    # FIX: Validate that filename belongs to this job
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or job.get('filename') != filename:
            return jsonify({"error": "File not found"}), 404
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True, mimetype='application/octet-stream')

@app.route('/files/history/<path:filename>', methods=['GET'])
def serve_history_file(filename):
    file_path = os.path.realpath(os.path.join(DOWNLOAD_DIR, filename))
    if not file_path.startswith(os.path.realpath(DOWNLOAD_DIR) + os.sep):
        return jsonify({"error": "Invalid filename"}), 400
    if not is_allowed_history_filename(filename):
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True, mimetype='application/octet-stream')

@app.route('/files/history/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    file_path = os.path.realpath(os.path.join(DOWNLOAD_DIR, filename))
    if not file_path.startswith(os.path.realpath(DOWNLOAD_DIR) + os.sep):
        return jsonify({"error": "Invalid filename"}), 400
    if not is_allowed_history_filename(filename):
        return jsonify({"error": "File not found"}), 404
    try:
        os.remove(file_path)
        return jsonify({"status": "deleted"})
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        logger.error(f"Delete error for {filename}: {str(e)}")
        return jsonify({"error": "Failed to delete file"}), 500

@app.after_request
def add_header(response):
    if request.path.startswith('/files/'):
        response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/healthz')
def healthz():
    ok = os.path.isdir(DOWNLOAD_DIR)
    return jsonify({"status": "ok" if ok else "error", "download_dir": ok}), 200 if ok else 500

@app.route('/version')
def version():
    return jsonify({"app": APP_VERSION, "ytdlp": yt_dlp.version.__version__})

def cleanup():
    while True:
        time.sleep(3600)
        now = time.time()
        # Remove old files from disk
        if os.path.exists(DOWNLOAD_DIR):
            for entry in os.scandir(DOWNLOAD_DIR):
                try:
                    if entry.stat().st_mtime < now - 86400:
                        os.remove(entry.path)
                except (FileNotFoundError, OSError):
                    pass
        # Remove completed/failed jobs older than 1 hour from memory
        with jobs_lock:
            stale = [jid for jid, j in jobs.items()
                     if j['status'] in ('finished', 'error', 'cancelled')
                     and now - j.get('completed_at', now) > 3600]
            for jid in stale:
                del jobs[jid]

threading.Thread(target=cleanup, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5050)), debug=False)
