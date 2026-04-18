import os
import time
import tempfile
import threading
from unittest.mock import patch, MagicMock
import pytest
import app as app_module


@pytest.fixture(autouse=True)
def isolated_app(tmp_path):
    """Give each test its own download dir and clean job state."""
    original_dir = app_module.DOWNLOAD_DIR
    app_module.DOWNLOAD_DIR = str(tmp_path)
    app_module.app.config['TESTING'] = True

    with app_module.jobs_lock:
        app_module.jobs.clear()
        app_module.job_processes.clear()

    yield app_module.app.test_client()

    app_module.DOWNLOAD_DIR = original_dir


# --- /version ---

def test_version_returns_app_and_ytdlp(isolated_app):
    resp = isolated_app.get('/version')
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['app'] == app_module.APP_VERSION
    assert 'ytdlp' in data and len(data['ytdlp']) > 0


# --- / ---

def test_index_serves_html(isolated_app):
    resp = isolated_app.get('/')
    assert resp.status_code == 200
    assert b'html' in resp.data.lower()


# --- /info ---

def test_info_missing_url(isolated_app):
    resp = isolated_app.get('/info')
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_info_invalid_url(isolated_app):
    resp = isolated_app.get('/info?url=not-a-real-url')
    assert resp.status_code == 500
    assert 'error' in resp.get_json()


# --- /download validation ---

def test_download_missing_url(isolated_app):
    resp = isolated_app.post('/download', json={})
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_download_invalid_json(isolated_app):
    resp = isolated_app.post('/download', data='not-json', content_type='text/plain')
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_download_low_disk_space(isolated_app):
    fake_usage = os.statvfs_result((0, 0, 0, 0, 0, 0, 0, 0, 0, 0)) if hasattr(os, 'statvfs_result') else None
    with patch('shutil.disk_usage', return_value=(100 * 2**30, 99 * 2**30, 0)):
        resp = isolated_app.post('/download', json={'url': 'https://example.com'})
    assert resp.status_code == 507
    assert 'disk space' in resp.get_json()['error'].lower()


def test_download_concurrent_limit(isolated_app):
    with app_module.jobs_lock:
        for i in range(app_module.MAX_CONCURRENT_DOWNLOADS):
            app_module.jobs[f'fake-{i}'] = {'status': 'downloading', 'url': f'https://example.com/{i}'}

    resp = isolated_app.post('/download', json={'url': 'https://example.com'})
    assert resp.status_code == 429
    assert 'too many' in resp.get_json()['error'].lower()


def test_download_duplicate_url_rejected(isolated_app):
    with app_module.jobs_lock:
        app_module.jobs['existing'] = {'status': 'downloading', 'url': 'https://example.com/video'}

    resp = isolated_app.post('/download', json={'url': 'https://example.com/video'})
    assert resp.status_code == 409
    assert 'already' in resp.get_json()['error'].lower()


def test_download_returns_job_id(isolated_app):
    with patch('subprocess.Popen') as mock_popen:
        proc = MagicMock()
        proc.stdout = iter([])
        proc.wait.return_value = None
        proc.returncode = 1
        mock_popen.return_value = proc

        resp = isolated_app.post('/download', json={'url': 'https://example.com'})
        assert resp.status_code == 200
        assert 'job_id' in resp.get_json()


# --- /status ---

def test_status_unknown_job(isolated_app):
    resp = isolated_app.get('/status/nonexistent-id')
    assert resp.status_code == 404


def test_status_returns_job_data(isolated_app):
    with app_module.jobs_lock:
        app_module.jobs['test-job'] = {
            'status': 'downloading', 'progress': 42,
            'speed': '1MiB/s', 'eta': '00:10',
            'title': 'Test', 'filename': '', 'error': ''
        }
    resp = isolated_app.get('/status/test-job')
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['status'] == 'downloading'
    assert data['progress'] == 42


# --- /cancel ---

def test_cancel_unknown_job(isolated_app):
    resp = isolated_app.post('/cancel/nonexistent-id')
    assert resp.status_code == 404


def test_cancel_active_job(isolated_app):
    mock_proc = MagicMock()
    with app_module.jobs_lock:
        app_module.jobs['cancel-me'] = {'status': 'downloading'}
        app_module.job_processes['cancel-me'] = mock_proc

    resp = isolated_app.post('/cancel/cancel-me')
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'cancelled'
    mock_proc.kill.assert_called_once()

    with app_module.jobs_lock:
        assert app_module.jobs['cancel-me']['status'] == 'cancelled'


def test_cancel_handles_already_exited_process(isolated_app):
    mock_proc = MagicMock()
    mock_proc.kill.side_effect = ProcessLookupError("gone")
    with app_module.jobs_lock:
        app_module.jobs['cancel-race'] = {'status': 'downloading'}
        app_module.job_processes['cancel-race'] = mock_proc

    resp = isolated_app.post('/cancel/cancel-race')
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'cancelled'
    mock_proc.kill.assert_called_once()

    with app_module.jobs_lock:
        assert app_module.jobs['cancel-race']['status'] == 'cancelled'
        assert 'cancel-race' not in app_module.job_processes


def test_cancel_finished_job_fails(isolated_app):
    with app_module.jobs_lock:
        app_module.jobs['done'] = {'status': 'finished'}

    resp = isolated_app.post('/cancel/done')
    assert resp.status_code == 404


# --- /history ---

def test_history_empty(isolated_app):
    resp = isolated_app.get('/history')
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_history_lists_media_files(isolated_app, tmp_path):
    (tmp_path / 'video_abc.mp4').write_bytes(b'\x00' * 1024)
    (tmp_path / 'song_xyz.mp3').write_bytes(b'\x00' * 512)
    (tmp_path / 'readme.txt').write_text('ignored')

    resp = isolated_app.get('/history')
    data = resp.get_json()
    assert len(data) == 2
    filenames = {f['filename'] for f in data}
    assert 'video_abc.mp4' in filenames
    assert 'song_xyz.mp3' in filenames
    assert all(f['format'] in ('video', 'audio') for f in data)


def test_history_sorted_newest_first(isolated_app, tmp_path):
    old = tmp_path / 'old_1.mp4'
    old.write_bytes(b'\x00')
    os.utime(old, (1000, 1000))

    new = tmp_path / 'new_2.mp4'
    new.write_bytes(b'\x00')

    resp = isolated_app.get('/history')
    data = resp.get_json()
    assert data[0]['filename'] == 'new_2.mp4'
    assert data[1]['filename'] == 'old_1.mp4'


# --- DELETE /files/history ---

def test_delete_file(isolated_app, tmp_path):
    (tmp_path / 'delete_me.mp4').write_bytes(b'\x00')
    resp = isolated_app.delete('/files/history/delete_me.mp4')
    assert resp.status_code == 200
    assert not (tmp_path / 'delete_me.mp4').exists()


def test_delete_nonexistent_file(isolated_app):
    resp = isolated_app.delete('/files/history/ghost.mp4')
    assert resp.status_code == 404


def test_history_get_file(isolated_app, tmp_path):
    (tmp_path / 'test_vid.mp4').write_bytes(b'fakevideo')
    resp = isolated_app.get('/files/history/test_vid.mp4')
    assert resp.status_code == 200
    assert resp.data == b'fakevideo'


def test_history_get_disallows_part_file(isolated_app, tmp_path):
    (tmp_path / 'partial_video.mp4.part').write_bytes(b'partial')
    resp = isolated_app.get('/files/history/partial_video.mp4.part')
    assert resp.status_code == 404


def test_delete_disallows_part_file(isolated_app, tmp_path):
    temp_file = tmp_path / 'partial_video.mp4.part'
    temp_file.write_bytes(b'partial')
    resp = isolated_app.delete('/files/history/partial_video.mp4.part')
    assert resp.status_code == 404
    assert temp_file.exists()


def test_healthz_ok(isolated_app):
    resp = isolated_app.get('/healthz')
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'ok'


def test_cancel_only_removes_own_temp_files(isolated_app, tmp_path):
    # Other job's temp file should survive cancellation of job A
    other_temp = tmp_path / '_job_other-job_video.mp4.part'
    other_temp.write_bytes(b'other')

    mock_proc = MagicMock()
    with app_module.jobs_lock:
        app_module.jobs['cancel-me'] = {'status': 'downloading'}
        app_module.job_processes['cancel-me'] = mock_proc

    isolated_app.post('/cancel/cancel-me')
    assert other_temp.exists(), "Cancel should not delete other jobs' temp files"


def test_delete_path_traversal_blocked(isolated_app, tmp_path):
    resp = isolated_app.delete('/files/history/../../etc/passwd')
    assert resp.status_code == 400
    assert 'invalid' in resp.get_json()['error'].lower()


# --- /files/ serving ---

def test_serve_file(isolated_app, tmp_path):
    (tmp_path / 'test_vid.mp4').write_bytes(b'fakevideo')
    with app_module.jobs_lock:
        app_module.jobs['some-job-id'] = {'status': 'finished', 'filename': 'test_vid.mp4'}
    resp = isolated_app.get('/files/some-job-id/test_vid.mp4')
    assert resp.status_code == 200
    assert resp.data == b'fakevideo'
    assert resp.headers.get('Cache-Control') == 'no-cache'


def test_serve_file_wrong_job(isolated_app, tmp_path):
    (tmp_path / 'test_vid.mp4').write_bytes(b'fakevideo')
    with app_module.jobs_lock:
        app_module.jobs['job-a'] = {'status': 'finished', 'filename': 'other_vid.mp4'}
    resp = isolated_app.get('/files/job-a/test_vid.mp4')
    assert resp.status_code == 404


def test_serve_nonexistent_file(isolated_app):
    resp = isolated_app.get('/files/some-job-id/nope.mp4')
    assert resp.status_code == 404


# --- Download flow with mocked subprocess ---

def test_successful_download_sets_finished(isolated_app, tmp_path):
    final_file = tmp_path / 'My Video_abc123.mp4'
    final_file.write_bytes(b'fakevideo')

    output_lines = [
        'TITLE:My Video\n',
        '[download]  50.0% of 10MiB at 2MiB/s ETA 00:05\n',
        f'{final_file}\n',
    ]

    with patch('subprocess.Popen') as mock_popen:
        proc = MagicMock()
        proc.stdout = iter(output_lines)
        proc.wait.return_value = None
        proc.returncode = 0
        mock_popen.return_value = proc

        resp = isolated_app.post('/download', json={'url': 'https://example.com/video'})
        job_id = resp.get_json()['job_id']

        # Wait for the download thread to finish
        time.sleep(0.5)

        resp = isolated_app.get(f'/status/{job_id}')
        data = resp.get_json()
        assert data['status'] == 'finished'
        assert data['filename'] == 'My Video_abc123.mp4'
        assert data['progress'] == 100
        assert data['title'] == 'My Video'


def test_failed_download_sets_error(isolated_app):
    output_lines = [
        'ERROR: Video unavailable\n',
    ]

    with patch('subprocess.Popen') as mock_popen:
        proc = MagicMock()
        proc.stdout = iter(output_lines)
        proc.wait.return_value = None
        proc.returncode = 1
        mock_popen.return_value = proc

        resp = isolated_app.post('/download', json={'url': 'https://example.com/bad'})
        job_id = resp.get_json()['job_id']

        time.sleep(0.5)

        resp = isolated_app.get(f'/status/{job_id}')
        data = resp.get_json()
        assert data['status'] == 'error'
        assert 'ERROR' in data['error']


def test_download_builds_correct_video_command(isolated_app):
    with patch('subprocess.Popen') as mock_popen:
        proc = MagicMock()
        proc.stdout = iter([])
        proc.wait.return_value = None
        proc.returncode = 1
        mock_popen.return_value = proc

        isolated_app.post('/download', json={'url': 'https://example.com', 'format': 'video'})
        time.sleep(0.3)

        cmd = mock_popen.call_args[0][0]
        assert '--embed-thumbnail' in cmd
        assert '--embed-metadata' in cmd
        assert '--merge-output-format' in cmd
        assert 'mp4' in cmd
        # URL must come after -- separator to prevent argument injection
        separator_idx = cmd.index('--')
        assert cmd[separator_idx + 1] == 'https://example.com'


def test_download_builds_correct_audio_command(isolated_app):
    with patch('subprocess.Popen') as mock_popen:
        proc = MagicMock()
        proc.stdout = iter([])
        proc.wait.return_value = None
        proc.returncode = 1
        mock_popen.return_value = proc

        isolated_app.post('/download', json={'url': 'https://example.com', 'format': 'audio'})
        time.sleep(0.3)

        cmd = mock_popen.call_args[0][0]
        assert '--embed-thumbnail' in cmd
        assert '--embed-metadata' in cmd
        assert '--extract-audio' in cmd
        assert '--audio-format' in cmd
        assert 'mp3' in cmd
        separator_idx = cmd.index('--')
        assert cmd[separator_idx + 1] == 'https://example.com'


# --- Progress parsing ---

def test_progress_regex():
    line = '[download]  75.3% of 100MiB at 5.2MiB/s ETA 00:03'
    m = app_module.PROGRESS_RE.search(line)
    assert m is not None
    assert m.group(1) == '75.3'
    assert m.group(2) == '5.2MiB/s'
    assert m.group(3) == '00:03'
