"""Local rhyme studio. Reuses song.py/video.py; no model is loaded by the UI."""
import argparse
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import urllib.parse
import uuid

import arcreel
import song
import video
import characters
import narration
import planner

ROOT = Path(__file__).resolve().parent
MAX_UPLOAD = 64 * 1024 * 1024


def save_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def validate_project(data):
    if not isinstance(data, dict):
        raise ValueError('Project must be an object.')
    result = {}
    for name, limit in [('title', 100), ('lyrics', 8000), ('prompt', 1500)]:
        value = data.get(name)
        if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
            raise ValueError(f'{name.capitalize()} is required (maximum {limit} characters).')
        result[name] = value.strip()
    duration = data.get('duration')
    if type(duration) not in (float, int) or not math.isfinite(duration) or not 10 <= duration <= 120 or duration*2 != round(duration*2):
        raise ValueError('Duration must be 10–120 seconds in half-second steps.')
    bpm = data.get('bpm')
    if type(bpm) is not int or not 30 <= bpm <= 300:
        raise ValueError('Tempo must be a whole number from 30 to 300.')
    raw = data.get('scenes')
    if not isinstance(raw, list) or not 1 <= len(raw) <= 16:
        raise ValueError('Add 1–16 scenes.')
    scenes = []
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError('Invalid scene.')
        caption = row.get('caption', '')
        if not isinstance(row.get('action'), str) or not isinstance(row.get('camera'), str):
            raise ValueError('Choose a movement and camera for each scene.')
        if not isinstance(caption, str) or len(caption) > 500 or '-->' in caption or '\x00' in caption:
            raise ValueError('Scene captions must be plain text, up to 500 characters.')
        seconds = row.get('seconds')
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds*2 != round(seconds*2):
            raise ValueError('Use half-second steps for scene timings.')
        extra = {key: row[key] for key in ('original_characters', 'dialogue', 'speaker', 'background', 'expression', 'transition') if key in row}
        if 'dialogue' in extra and (not isinstance(extra['dialogue'], str) or len(extra['dialogue']) > 1000):
            raise ValueError('Dialogue must be text up to 1000 characters.')
        scenes.append(dict(seconds=seconds, action=row.get('action'), camera=row.get('camera'), caption=caption, **extra))
    video.validate_plan({'scenes': scenes})
    if abs(sum(row['seconds'] for row in scenes)-duration) > .001:
        raise ValueError('Scene durations must add up to the song duration.')
    language = data.get('language', 'en')
    orientation = data.get('orientation', 'portrait')
    mode = data.get('mode', 'legacy')
    if language not in ('en', 'hi') or orientation not in ('portrait', 'landscape') or mode not in ('lite', 'quality', 'legacy'):
        raise ValueError('Invalid language, orientation or render mode.')
    voice = data.get('narrator', language+'-boy')
    if not isinstance(voice, str) or voice not in narration.VOICES or narration.VOICES[voice]['language'] != language:
        raise ValueError('Choose a narration voice matching the language.')
    members = data.get('characters', ['milo', 'pip'])
    characters.select(members)
    for row in scenes:
        row.setdefault('original_characters', members)
    return dict(result, duration=duration, bpm=bpm, scenes=scenes, language=language, orientation=orientation,
                mode=mode, narrator=voice, characters=members)


class BusyError(ValueError):
    pass


class Studio:
    def __init__(self, directory, blender='blender', music_url='http://127.0.0.1:8001'):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.blender = blender
        self.music_url = song.LocalClient(music_url).url
        self.guard = threading.Lock()
        self.active = None
        self.process = None
        self.worker = None
        self.closing = False
        for path in self.root.glob('*/state.json'):
            state = json.loads(path.read_text())
            if state.get('status') == 'running':
                state.update(status='interrupted', message='Dashboard stopped during this job. Check existing processes and job locks before retrying.')
                save_json(path, state)

    def folder(self, identifier):
        if not re.fullmatch(r'[a-f0-9]{32}', identifier):
            raise ValueError('Invalid project ID.')
        folder = self.root/identifier
        if not (folder/'project.json').is_file():
            raise ValueError('Project not found.')
        return folder

    def create(self, data):
        data = validate_project(data)
        identifier = uuid.uuid4().hex
        folder = self.root/identifier
        folder.mkdir()
        save_json(folder/'project.json', data)
        save_json(folder/'request.json', dict(prompt=data['prompt'], lyrics=data['lyrics'], audio_duration=data['duration'], bpm=data['bpm']))
        plan = dict(title=data['title'], language=data['language'], orientation=data['orientation'], scenes=data['scenes'])
        words = data['lyrics'].split()
        for i, scene in enumerate(plan['scenes']):
            scene.setdefault('dialogue', ' '.join(words[i*len(words)//len(plan['scenes']):(i+1)*len(words)//len(plan['scenes'])]))
        save_json(folder/'plan.json', plan)
        # A rest-only timing score satisfies the existing runner's timeline check.
        # The complete uploaded/generated soundtrack supplies the actual music.
        save_json(folder/'score.json', dict(bpm=60, notes=[dict(lyric='R', pitch=60, ticks=round(data['duration']*480))]))
        save_json(folder/'state.json', dict(status='ready', message='Saved. Generate or upload a song, or make an instrumental preview.'))
        return self.detail(identifier)

    def detail(self, identifier):
        folder = self.folder(identifier)
        state = json.loads((folder/'state.json').read_text())
        data = json.loads((folder/'project.json').read_text())
        media = {}
        for name in ('song.wav', 'preview.mp4', 'video.mp4'):
            if (folder/name).is_file():
                media[name] = f'/media/{identifier}/{name}'
        state_file = folder/'song.wav.job.json'
        if state_file.exists():
            state['audio_task'] = json.loads(state_file.read_text()).get('status')
        log = folder/'job.log'
        if log.exists():
            with log.open('rb') as stream:
                stream.seek(max(0, log.stat().st_size-6000))
                state['log'] = stream.read().decode('utf-8', errors='replace')
        if state.get('status') == 'running' and state.get('action') in ('preview', 'full'):
            manifests = list((folder/'render').rglob('status.json'))
            if manifests:
                try:
                    state['render'] = json.loads(max(manifests, key=lambda p: p.stat().st_mtime).read_text()).get('scenes', [])
                except (OSError, ValueError):
                    pass
        return dict(id=identifier, project=data, state=state, media=media,
                    youtube=json.loads((folder/'youtube.json').read_text()) if (folder/'youtube.json').exists() else None,
                    arcreel=json.loads((folder/'arcreel.json').read_text()) if (folder/'arcreel.json').exists() else None)

    def send_arcreel(self, identifier):
        folder = self.folder(identifier)
        self.reserve(identifier)
        try:
            data = json.loads((folder/'project.json').read_text())
            brief = ('TOON PILOT — ORIGINAL SONG AND SCENE BRIEF\n'
                     'Preserve the supplied lyrics and scene timing. Milo is a yellow duck; '
                     'Pip is a bunny. Both appear together. This is a brief, not a generated script. '
                     'Singing, lip sync and character matching require separate review.\n\n'
                     + json.dumps(data, ensure_ascii=False, indent=2))
            return arcreel.Client().send(folder/'arcreel.json', 'toon-'+identifier,
                                        data['title'], brief, aspect='16:9',
                                        style='Colourful 3D nursery animation')
        finally:
            self.release()

    def list_projects(self):
        return [dict(id=p.parent.name, title=json.loads(p.read_text())['title'])
                for p in sorted(self.root.glob('*/project.json'), key=lambda p: p.stat().st_mtime, reverse=True)]

    def reserve(self, identifier):
        with self.guard:
            if self.active or self.closing:
                raise BusyError('Another job or upload is running. Wait for it to finish.')
            self.active = identifier

    def release(self):
        with self.guard:
            self.active = None

    def start(self, identifier, action, server_stopped=False):
        folder = self.folder(identifier)
        if action not in ('song', 'narration', 'preview', 'full', 'youtube'):
            raise ValueError('Unknown action.')
        if action in ('preview', 'full') and not server_stopped:
            raise ValueError('Stop the ACE-Step server first, then confirm it is stopped before rendering.')
        if action in ('preview', 'full'):
            try:
                parts = urllib.parse.urlsplit(self.music_url)
                connection = socket.create_connection((parts.hostname, parts.port or 80), timeout=.3)
            except OSError:
                pass
            else:
                connection.close()
                raise ValueError('The audio server port is still active. Stop ACE-Step before rendering.')
        if action == 'full' and not (folder/'song.wav').exists():
            raise ValueError('Generate or upload a song before creating the full video.')
        if action == 'narration' and ((folder/'song.wav').exists() or (folder/'song.wav.job.json').exists()):
            raise ValueError('Audio already exists. Save a new project to create narration.')
        if action == 'youtube' and not (folder/'video.mp4').exists():
            raise ValueError('Create and review a full video before uploading privately.')
        self.reserve(identifier)
        try:
            message = {'song':'Waiting for the audio engine…', 'narration':'Creating offline spoken narration…',
                       'youtube':'Uploading privately to YouTube…'}.get(action,'Rendering on CPU…')
            save_json(folder/'state.json', dict(status='running', action=action, message=message))
            self.worker = threading.Thread(target=self.run, args=(identifier, action), daemon=True)
            self.worker.start()
        except BaseException:
            self.release()
            raise

    def run(self, identifier, action):
        folder = self.folder(identifier)
        try:
            project = json.loads((folder/'project.json').read_text())
            if action == 'song':
                if (folder/'song.wav').exists() and not (folder/'song.wav.job.json').exists():
                    raise ValueError('This project already has uploaded audio. Save a new project to generate an alternative.')
                command = [sys.executable, '-u', str(ROOT/'song.py'), '--request', str(folder/'request.json'), '--out', str(folder/'song.wav'), '--url', self.music_url]
            elif action == 'narration':
                command = [sys.executable, '-u', str(ROOT/'narration.py'), '--plan', str(folder/'plan.json'),
                           '--out', str(folder/'song.wav'), '--voice', project.get('narrator', 'en-boy')]
            elif action == 'youtube':
                command = [sys.executable, '-u', str(ROOT/'youtube_upload.py'), 'upload', '--video', str(folder/'video.mp4'),
                    '--receipt', str(folder/'youtube.json'), '--token', str(ROOT/'output/private/youtube-token.json'),
                    '--title', project['title'], '--description', project['lyrics'].encode('utf-8')[:4500].decode('utf-8',errors='ignore')]
            else:
                command = [sys.executable, '-u', str(ROOT/'video.py'), 'create', '--plan', str(folder/'plan.json'),
                           '--song', str(folder/'score.json'), '--out', str(folder/'render'), '--blender', self.blender,
                           '--mode', project.get('mode', 'legacy'), '--orientation', project.get('orientation', 'portrait')]
                if action == 'preview':
                    command.append('--preview')
                command += ['--soundtrack', str(folder/'song.wav')] if (folder/'song.wav').exists() else ['--instrumental']
            with (folder/'job.log').open('w') as stream:
                with self.guard:
                    if self.closing:
                        raise RuntimeError('Dashboard is stopping.')
                    self.process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                code = self.process.wait()
            if code:
                raise RuntimeError(f'Job stopped (exit {code}). See the details below. Retry uses the same saved job; a client timeout does not cancel generation on ACE-Step.')
            if action in ('preview', 'full'):
                candidates = list((folder/'render'/('preview' if action == 'preview' else 'full')).rglob('preview.mp4' if action == 'preview' else 'video.mp4'))
                if not candidates:
                    raise ValueError('Renderer completed without an output video.')
                temporary = folder/'video-copy.tmp'
                shutil.copyfile(max(candidates, key=lambda p: p.stat().st_mtime), temporary)
                temporary.replace(folder/('preview.mp4' if action == 'preview' else 'video.mp4'))
            elif action in ('song', 'narration') and not (folder/'song.wav').exists():
                raise ValueError('Audio engine completed without an audio file.')
            save_json(folder/'state.json', dict(status='needs_review', action=action,
                message='Private YouTube upload completed; see youtube.json for its ID.' if action == 'youtube' else
                    'Spoken narration created, not singing. Listen for pronunciation and timing.' if action == 'narration' else
                    'File checks passed. Listen and review lyrics, timing and quality before using.' if action == 'song' else
                    'Video created. Review movement, camera and audio before publishing.'))
        except Exception as exc:
            save_json(folder/'state.json', dict(status='failed', action=action, message=str(exc)))
        finally:
            self.process = None
            self.release()

    def upload(self, identifier, stream, length):
        folder = self.folder(identifier)
        if not 0 < length <= MAX_UPLOAD:
            raise ValueError('Upload must be 1 byte to 64 MiB.')
        self.reserve(identifier)
        temporary = folder/'upload.tmp'
        try:
            if (folder/'song.wav').exists() or (folder/'song.wav.job.json').exists():
                raise ValueError('Audio or a generation task already exists. Save a new project for different audio.')
            with temporary.open('wb') as target:
                remaining = length
                while remaining:
                    chunk = stream.read(min(65536, remaining))
                    if not chunk:
                        raise ValueError('Upload was interrupted.')
                    target.write(chunk)
                    remaining -= len(chunk)
            duration = json.loads((folder/'project.json').read_text())['duration']
            song.validate_audio(temporary, duration)
            # Convert complete audio to an actual WAV, preserving sample rate/channels.
            output = folder/'upload.wav'
            try:
                subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(temporary), '-map', '0:a:0', '-c:a', 'pcm_s16le', str(output)], check=True, capture_output=True)
                output.replace(folder/'song.wav')
            finally:
                output.unlink(missing_ok=True)
            save_json(folder/'state.json', dict(status='needs_review', message='Uploaded audio passed decoding and duration checks. Listen before rendering.'))
        finally:
            temporary.unlink(missing_ok=True)
            self.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, value):
        raw = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)

    def trusted(self):
        # SSH tunnels may use a different local port. Still require a literal
        # loopback hostname; arbitrary Host names cannot access this service.
        host = urllib.parse.urlsplit('http://'+self.headers.get('Host', '')).hostname
        if host not in {'127.0.0.1', 'localhost'}:
            raise PermissionError('Use localhost through your SSH tunnel.')
        origin = self.headers.get('Origin')
        if origin and origin != 'http://'+self.headers.get('Host'):
            raise PermissionError('Cross-origin requests are disabled.')

    def do_GET(self):
        try:
            self.trusted()
            path = urllib.parse.urlsplit(self.path).path
            studio = self.server.studio
            if path == '/':
                raw = (ROOT/'dashboard.html').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(raw)
            elif path == '/api/projects':
                self.reply(200, studio.list_projects())
            elif path.startswith('/api/projects/'):
                self.reply(200, studio.detail(path.rsplit('/', 1)[-1]))
            elif path == '/api/arcreel':
                self.reply(200, arcreel.Client().status())
            elif path == '/api/tools':
                self.reply(200, dict(blender=bool(shutil.which(studio.blender)), ffmpeg=bool(shutil.which('ffmpeg')), ffprobe=bool(shutil.which('ffprobe'))))
            elif path == '/api/production':
                import production
                queue = production.Queue(studio.root/'queue')
                try:
                    self.reply(200, dict(jobs=queue.rows(), speech=bool(shutil.which('espeak-ng')),
                        youtube=(ROOT/'output/private/youtube-token.json').is_file()))
                finally:
                    queue.close()
            elif path.startswith('/media/'):
                _, _, identifier, name = path.split('/')
                if name not in {'song.wav', 'preview.mp4', 'video.mp4'}:
                    raise ValueError('Unknown media file.')
                file = studio.folder(identifier)/name
                size = file.stat().st_size
                start, end = 0, size-1
                ranged = self.headers.get('Range')
                if ranged:
                    match = re.fullmatch(r'bytes=(\d+)-(\d*)', ranged)
                    if not match:
                        return self.reply(416, dict(error='Unsupported byte range.'))
                    start, end = int(match[1]), min(int(match[2]) if match[2] else size-1, size-1)
                    if start > end:
                        return self.reply(416, dict(error='Range outside file.'))
                self.send_response(206 if ranged else 200)
                self.send_header('Content-Type', 'audio/wav' if name.endswith('.wav') else 'video/mp4')
                self.send_header('Content-Length', str(end-start+1))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Content-Disposition', f'inline; filename="{name}"')
                if ranged:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.end_headers()
                with file.open('rb') as stream:
                    stream.seek(start)
                    remaining = end-start+1
                    while remaining:
                        chunk = stream.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            else:
                self.reply(404, dict(error='Not found.'))
        except PermissionError as exc:
            self.reply(403, dict(error=str(exc)))
        except (ValueError, OSError, KeyError) as exc:
            self.reply(400, dict(error=str(exc)))

    def do_POST(self):
        try:
            self.trusted()
            if self.headers.get('X-Toon-Pilot') != '1':
                raise PermissionError('Open the dashboard to use this action.')
            path = urllib.parse.urlsplit(self.path).path
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_UPLOAD:
                raise ValueError('Missing or oversized request body.')
            studio = self.server.studio
            if re.fullmatch(r'/api/projects/[a-f0-9]{32}/upload', path):
                identifier = path.split('/')[3]
                studio.upload(identifier, self.rfile, length)
                return self.reply(200, studio.detail(identifier))
            if length > 64000:
                raise ValueError('Project request is too large.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Request must be an object.')
            if path == '/api/projects':
                self.reply(201, studio.create(data))
            elif path == '/api/plan':
                self.reply(200, planner.plan(data.get('title'), data.get('lyrics'), data.get('duration',30),
                    data.get('language','en'), data.get('characters'), data.get('orientation','portrait')))
            elif re.fullmatch(r'/api/projects/[a-f0-9]{32}/arcreel', path):
                self.reply(200, studio.send_arcreel(path.split('/')[3]))
            elif re.fullmatch(r'/api/projects/[a-f0-9]{32}/run', path):
                identifier = path.split('/')[3]
                if not isinstance(data, dict):
                    raise ValueError('Action must be an object.')
                studio.start(identifier, data.get('action'), data.get('server_stopped') is True)
                self.reply(202, dict(status='running'))
            else:
                self.reply(404, dict(error='Not found.'))
        except PermissionError as exc:
            self.reply(403, dict(error=str(exc)))
        except BusyError as exc:
            self.reply(409, dict(error=str(exc)))
        except (ValueError, OSError, KeyError, IndexError, subprocess.SubprocessError) as exc:
            self.reply(400, dict(error=str(exc)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8768)
    parser.add_argument('--out', default=str(ROOT/'output/dashboard'))
    parser.add_argument('--blender', default='blender')
    parser.add_argument('--music-url', default='http://127.0.0.1:8001')
    args = parser.parse_args()
    output = Path(args.out).resolve()
    output.mkdir(parents=True, exist_ok=True)
    # One dashboard instance per output directory, including separate terminals.
    lock = (output/'.dashboard.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.exit(1, 'This dashboard output directory is already in use.\n')
    studio = Studio(output, args.blender, args.music_url)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.studio = studio
    print(f'Rhyme Studio: http://127.0.0.1:{args.port}', flush=True)
    print('Music generation needs the separate ACE-Step server. Use an SSH tunnel on EC2.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with studio.guard:
            studio.closing = True
            process = studio.process
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        server.server_close()
        lock.close()


if __name__ == '__main__':
    main()
