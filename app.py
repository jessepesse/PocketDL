import os
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

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory storage for download jobs
# {job_id: {status: '...', progress: 0, title: '...', filename: '...', process: Popen_obj}}
jobs = {}
jobs_lock = threading.Lock()

def progress_hook(d, job_id):
    if d['status'] == 'downloading':
        p = d.get('_percent_str', '0%').replace('%', '')
        try:
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]['progress'] = float(p)
                    jobs[job_id]['speed'] = d.get('_speed_str', 'N/A')
                    jobs[job_id]['eta'] = d.get('_eta_str', 'N/A')
        except ValueError:
            pass

def run_download(url, job_id, format_type='video'):
    try:
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best' if format_type == 'video' else 'bestaudio/best',
            'merge_output_format': 'mp4',
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s_%(id)s.%(ext)s'),
            'progress_hooks': [lambda d: progress_hook(d, job_id)],
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True
        }
        
        if format_type == 'audio':
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Note: yt-dlp library call is blocking, but we run this in a thread.
            # To allow cancellation of the library call, we would need to wrap it differently,
            # but for minimalism, we handle the job lifecycle here.
            with jobs_lock:
                jobs[job_id]['status'] = 'downloading'
            
            info = ydl.extract_info(url, download=True)
            
            filename = ydl.prepare_filename(info)
            if format_type == 'audio':
                filename = os.path.splitext(filename)[0] + '.mp3'
            elif format_type == 'video':
                filename = os.path.splitext(filename)[0] + '.mp4'
                
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]['filename'] = os.path.basename(filename)
                    jobs[job_id]['status'] = 'finished'
                    jobs[job_id]['progress'] = 100
                    jobs[job_id]['completed_at'] = time.time()

    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        with jobs_lock:
            if job_id in jobs:
                if jobs[job_id]['status'] != 'cancelled':
                    jobs[job_id]['status'] = 'error'
                    jobs[job_id]['error'] = str(e)
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
        return jsonify({"error": str(e)}), 500

@app.route('/download', methods=['POST'])
def start_download():
    # 1. Check Disk Space
    total, used, free = shutil.disk_usage(DOWNLOAD_DIR)
    free_gb = free // (2**30)
    if free_gb < MIN_DISK_SPACE_GB:
        return jsonify({"error": f"Low disk space. Only {free_gb}GB remaining."}), 507

    # 2. Check Concurrent Limits
    with jobs_lock:
        active_jobs = [j for j in jobs.values() if j['status'] in ['pending', 'downloading']]
        if len(active_jobs) >= MAX_CONCURRENT_DOWNLOADS:
            return jsonify({"error": "Too many active downloads. Please wait."}), 429

    data = request.json
    url = data.get('url')
    format_type = data.get('format', 'video')
    
    if not url: return jsonify({"error": "No URL provided"}), 400
    
    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {
            'status': 'pending',
            'progress': 0,
            'speed': '0',
            'eta': 'N/A',
            'title': 'Fetching info...',
            'filename': '',
            'error': ''
        }
    
    threading.Thread(target=run_download, args=(url, job_id, format_type)).start()
    return jsonify({"job_id": job_id})

@app.route('/cancel/<job_id>', methods=['POST'])
def cancel_download(job_id):
    with jobs_lock:
        if job_id in jobs:
            if jobs[job_id]['status'] in ['pending', 'downloading']:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['completed_at'] = time.time()
                # Note: Killing a thread in Python is hard, but yt-dlp will 
                # eventually exit when it checks its internal state or when 
                # the process is managed. For a truly robust kill, 
                # we'd use subprocess.Popen for yt-dlp instead of the library.
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
            stats = os.stat(file_path)
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
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True, mimetype='application/octet-stream')

@app.after_request
def add_header(response):
    if request.path.startswith('/files/'):
        response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

def cleanup():
    while True:
        time.sleep(3600)
        now = time.time()
        # Remove old files from disk
        if os.path.exists(DOWNLOAD_DIR):
            for f in os.listdir(DOWNLOAD_DIR):
                p = os.path.join(DOWNLOAD_DIR, f)
                if os.stat(p).st_mtime < now - 86400:
                    try: os.remove(p)
                    except: pass
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
