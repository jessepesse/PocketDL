import os
import threading
import uuid
import time
import logging
from flask import Flask, request, jsonify, send_from_directory, send_file
import yt_dlp

# Configuration
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", os.path.join(os.path.dirname(__file__), "downloads"))
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory storage for download jobs
# {job_id: {status: 'pending/downloading/finished/error', progress: 0, title: '', filename: '', error: ''}}
jobs = {}

def progress_hook(d, job_id):
    if d['status'] == 'downloading':
        p = d.get('_percent_str', '0%').replace('%', '')
        try:
            jobs[job_id]['progress'] = float(p)
        except ValueError:
            pass
    elif d['status'] == 'finished':
        jobs[job_id]['progress'] = 100
        jobs[job_id]['status'] = 'finished'
        # Get filename correctly from the info dict
        filename = d.get('filename') or d.get('info_dict', {}).get('_filename')
        if filename:
            jobs[job_id]['filename'] = os.path.basename(filename)

def run_download(url, job_id, format_type='video'):
    try:
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best' if format_type == 'video' else 'bestaudio/best',
            'merge_output_format': 'mp4', # Merge best quality into MP4 container
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s_%(id)s.%(ext)s'),
            'progress_hooks': [lambda d: progress_hook(d, job_id)],
            'noplaylist': True,
        }
        
        if format_type == 'audio':
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            jobs[job_id]['status'] = 'downloading'
            info = ydl.extract_info(url, download=True)
            jobs[job_id]['title'] = info.get('title', 'Unknown Title')
            
            # Adjust filename based on post-processing (mp3 or merged mp4)
            filename = ydl.prepare_filename(info)
            if format_type == 'audio':
                filename = os.path.splitext(filename)[0] + '.mp3'
            elif format_type == 'video':
                filename = os.path.splitext(filename)[0] + '.mp4'
                
            jobs[job_id]['filename'] = os.path.basename(filename)
            jobs[job_id]['status'] = 'finished'
            jobs[job_id]['progress'] = 100
            
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)

@app.route('/info')
def get_info():
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({
                "title": info.get('title'),
                "thumbnail": info.get('thumbnail'),
                "duration": info.get('duration'),
                "formats": [{"id": f['format_id'], "ext": f['ext'], "resolution": f.get('resolution')} for f in info.get('formats', []) if f.get('vcodec') != 'none']
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download', methods=['POST'])
def start_download():
    data = request.json
    url = data.get('url')
    format_type = data.get('format', 'video') # 'video' or 'audio'
    
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        'status': 'pending',
        'progress': 0,
        'title': '',
        'filename': '',
        'error': ''
    }
    
    threading.Thread(target=run_download, args=(url, job_id, format_type)).start()
    return jsonify({"job_id": job_id})

@app.route('/status/<job_id>')
def get_status(job_id):
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(jobs[job_id])

@app.route('/history')
def get_history():
    files = []
    if not os.path.exists(DOWNLOAD_DIR):
        return jsonify([])
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
    # Sort newest first
    files.sort(key=lambda x: x['mtime'], reverse=True)
    return jsonify(files)

@app.route('/update-log')
def get_update_log():
    log_path = os.path.join(DOWNLOAD_DIR, "update.log")
    if not os.path.exists(log_path):
        return "No updates performed yet."
    with open(log_path, 'r') as f:
        return f.read(), 200, {'Content-Type': 'text/plain'}

@app.route('/files/<job_id>/<path:filename>')
def serve_file(job_id, filename):
    # Security: send_from_directory prevents Path Traversal attacks (e.g., ../../etc/passwd)
    # It ensures the file is served only from the DOWNLOAD_DIR
    try:
        return send_from_directory(
            DOWNLOAD_DIR, 
            filename, 
            as_attachment=True, 
            mimetype='application/octet-stream'
        )
    except FileNotFoundError:
        return "File not found", 404

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

# Cleanup thread to remove old files
def cleanup():
    while True:
        time.sleep(3600) # Every hour
        now = time.time()
        for f in os.listdir(DOWNLOAD_DIR):
            file_path = os.path.join(DOWNLOAD_DIR, f)
            if os.stat(file_path).st_mtime < now - 3600 * 24: # 24 hours old
                try: os.remove(file_path)
                except: pass

# Background thread for automatic yt-dlp updates
def update_ytdlp_loop():
    log_path = os.path.join(DOWNLOAD_DIR, "update.log")
    while True:
        try:
            logger.info("Starting automatic yt-dlp update...")
            # Run update as the current non-root user
            import subprocess
            result = subprocess.run(["pip", "install", "-U", "yt-dlp"], capture_output=True, text=True)
            with open(log_path, 'a') as f:
                f.write(f"\n--- Update at {time.ctime()} ---\n")
                f.write(result.stdout)
                if result.stderr:
                    f.write("\nErrors:\n" + result.stderr)
            logger.info("yt-dlp update completed.")
        except Exception as e:
            logger.error(f"Failed to update yt-dlp: {str(e)}")
        
        # Wait 24 hours (86400 seconds)
        time.sleep(86400)

threading.Thread(target=update_ytdlp_loop, daemon=True).start()
threading.Thread(target=cleanup, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5050)), debug=True)
