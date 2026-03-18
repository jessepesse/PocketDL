import os
import re
import subprocess
import threading
import uuid
import time
import logging
import shutil
from flask import Flask, request, jsonify, send_from_directory, send_file
import yt_dlp

# Configuration
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", os.path.join(os.path.dirname(__file__), "downloads"))
MIN_DISK_SPACE_GB = int(os.environ.get("MIN_DISK_SPACE_GB", 2))
MAX_CONCURRENT_DOWNLOADS = int(os.environ.get("MAX_CONCURRENT_DOWNLOADS", 3))
APP_VERSION = "1.3.0"

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

def run_download(url, job_id, format_type='video'):
    job_output_template = os.path.join(DOWNLOAD_DIR, f'%(title)s_%(id)s.%(ext)s')
    job_temp_prefix = os.path.join(DOWNLOAD_DIR, f'_job_{job_id}_')
    cmd = [
        'yt-dlp',
        '--newline',
        '--no-playlist',
        '--print', 'TITLE:%(title)s',
        '--print', 'after_move:filepath',
        '--output', job_output_template,
        '--temp-filename-prefix', f'_job_{job_id}_',
        '--embed-thumbnail',
        '--embed-metadata',
    ]
    if format_type == 'video':
        cmd += ['--format', 'bestvideo+bestaudio/best', '--merge-output-format', 'mp4']
    else:
        cmd += ['--format', 'bestaudio/best', '--extract-audio',
                '--audio-format', 'mp3', '--audio-quality', '192K']
    cmd += ['--', url]

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        with jobs_lock:
            # FIX: Check if already cancelled before overwriting status
            if job_id not in jobs or jobs[job_id]['status'] == 'cancelled':
                process.kill()
                process.wait()
                return
            jobs[job_id]['status'] = 'downloading'
            job_processes[job_id] = process

        final_path = None
        last_error = None

        for line in process.stdout:
            line = line.rstrip()
            m = PROGRESS_RE.search(line)
            if m:
                with jobs_lock:
                    if job_id in jobs:
                        jobs[job_id]['progress'] = float(m.group(1))
                        jobs[job_id]['speed'] = m.group(2)
                        jobs[job_id]['eta'] = m.group(3)
            elif line.startswith('TITLE:'):
                # FIX: Update title from yt-dlp output
                with jobs_lock:
                    if job_id in jobs:
                        jobs[job_id]['title'] = line[6:]
            elif line.startswith(DOWNLOAD_DIR):
                final_path = line
            elif 'ERROR' in line:
                last_error = line

            cancelled = False
            with jobs_lock:
                if job_id in jobs and jobs[job_id]['status'] == 'cancelled':
                    job_processes.pop(job_id, None)  # FIX: clean up dict
                    cancelled = True
            if cancelled:
                process.kill()
                process.wait()  # FIX: reap zombie, outside lock to avoid blocking
                for f in os.listdir(DOWNLOAD_DIR):
                    if f.startswith(f'_job_{job_id}_'):
                        try: os.remove(os.path.join(DOWNLOAD_DIR, f))
                        except: pass
                return

        process.wait()

        with jobs_lock:
            job_processes.pop(job_id, None)
            if job_id not in jobs or jobs[job_id]['status'] == 'cancelled':
                return
            if process.returncode == 0 and final_path:
                jobs[job_id]['filename'] = os.path.basename(final_path)
                jobs[job_id]['status'] = 'finished'
                jobs[job_id]['progress'] = 100
                jobs[job_id]['completed_at'] = time.time()
            else:
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = last_error or 'Download failed'
                jobs[job_id]['completed_at'] = time.time()

    except Exception as e:
        logger.error(f"Download error for job {job_id}: {str(e)}")
        with jobs_lock:
            job_processes.pop(job_id, None)
            if job_id in jobs and jobs[job_id]['status'] != 'cancelled':
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = 'Download failed'  # FIX: don't expose internals
                jobs[job_id]['completed_at'] = time.time()

@app.route('/info')
def get_info():
    url = request.args.get('url')
    if not url: return jsonify({"error": "No URL provided"}), 400
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({"title": info.get('title'), "thumbnail": info.get('thumbnail')})
    except Exception as e:
        logger.error(f"Info fetch error for {url}: {str(e)}")
        return jsonify({"error": "Failed to fetch video info"}), 500

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

    if not url: return jsonify({"error": "No URL provided"}), 400

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
    
    threading.Thread(target=run_download, args=(url, job_id, format_type), daemon=True).start()
    return jsonify({"job_id": job_id})

@app.route('/cancel/<job_id>', methods=['POST'])
def cancel_download(job_id):
    with jobs_lock:
        if job_id in jobs:
            if jobs[job_id]['status'] in ['pending', 'downloading']:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['completed_at'] = time.time()
                process = job_processes.get(job_id)
                if process:
                    process.kill()
                return jsonify({"status": "cancelled"})
    return jsonify({"error": "Job not found or already finished"}), 404

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
        if filename.endswith(('.mp4', '.mp3')):
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
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True, mimetype='application/octet-stream')

@app.route('/files/history/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    file_path = os.path.realpath(os.path.join(DOWNLOAD_DIR, filename))
    if not file_path.startswith(os.path.realpath(DOWNLOAD_DIR) + os.sep):
        return jsonify({"error": "Invalid filename"}), 400
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
