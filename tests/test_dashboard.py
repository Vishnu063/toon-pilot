import array
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

import audio
import dashboard
import song


def project():
    return dict(title='A happy rhyme', lyrics='Little duck, hop and play', prompt='Warm original nursery singing',
                duration=10, bpm=100, scenes=[dict(seconds=10, action='hop', camera='dolly', caption='Hop and play')])


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.studio = dashboard.Studio(self.temp.name)

    def test_timings_and_malformed_inputs(self):
        bad = project()
        bad['duration'] = 11
        with self.assertRaisesRegex(ValueError, 'add up'):
            self.studio.create(bad)
        for key, value in [('duration', True), ('bpm', 3.5), ('lyrics', ''), ('duration', float('nan'))]:
            bad = project(); bad[key] = value
            with self.assertRaises(ValueError): self.studio.create(bad)
        bad = project(); bad['scenes'][0]['action'] = []
        with self.assertRaises(ValueError): self.studio.create(bad)
        detail = self.studio.create(project())
        folder = self.studio.folder(detail['id'])
        _, seconds = audio.load_song(folder/'score.json')
        self.assertEqual(seconds, 10)
        self.assertEqual(song.payload_for(folder/'request.json')['lyrics'], project()['lyrics'])

    def test_failure_is_persisted_and_releases_worker(self):
        detail = self.studio.create(project())
        with patch('dashboard.subprocess.Popen', side_effect=OSError('fixture engine unavailable')):
            self.studio.start(detail['id'], 'song')
            self.studio.worker.join(5)
        state = self.studio.detail(detail['id'])['state']
        self.assertEqual(state['status'], 'failed')
        self.assertIn('engine unavailable', state['message'])
        self.assertIsNone(self.studio.active)
        self.assertFalse(self.studio.detail(detail['id'])['media'])

    def test_busy_and_render_without_audio_fail(self):
        detail = self.studio.create(project())
        self.studio.reserve(detail['id'])
        with self.assertRaises(dashboard.BusyError): self.studio.start(detail['id'], 'song')
        self.studio.release()
        with self.assertRaisesRegex(ValueError, 'confirm'):
            self.studio.start(detail['id'], 'preview')
        with patch('dashboard.socket.create_connection', side_effect=OSError('not running')):
            with self.assertRaisesRegex(ValueError, 'upload a song'):
                self.studio.start(detail['id'], 'full', True)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires media tools')
    def test_actual_audio_upload_and_bad_duration_cleanup(self):
        detail = self.studio.create(project())
        fixture = Path(self.temp.name)/'fixture.wav'
        audio.write_wav(fixture, array.array('h', [500, -500]*(audio.RATE*5)))
        self.studio.upload(detail['id'], io.BytesIO(fixture.read_bytes()), fixture.stat().st_size)
        self.assertIn('song.wav', self.studio.detail(detail['id'])['media'])
        self.assertEqual(self.studio.detail(detail['id'])['state']['status'], 'needs_review')
        other = self.studio.create(project())
        audio.write_wav(fixture, array.array('h', [500, -500]*100))
        with self.assertRaisesRegex(ValueError, 'duration'):
            self.studio.upload(other['id'], io.BytesIO(fixture.read_bytes()), fixture.stat().st_size)
        self.assertFalse(self.studio.detail(other['id'])['media'])
        self.assertFalse((self.studio.folder(other['id'])/'upload.tmp').exists())
        self.assertIsNone(self.studio.active)

    def test_http_origin_paths_ranges_and_restart_state(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.Handler)
        server.studio = self.studio
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        def post(headers):
            return urllib.request.urlopen(urllib.request.Request(base+'/api/projects', data=json.dumps(project()).encode(), headers=headers))
        with self.assertRaises(urllib.error.HTTPError) as error:
            post({'X-Toon-Pilot': '1', 'Origin': 'https://other.example'})
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError): post({})
        with post({'X-Toon-Pilot': '1'}) as response: detail = json.load(response)
        folder = self.studio.folder(detail['id'])
        (folder/'song.wav').write_bytes(b'0123456789')
        request = urllib.request.Request(base+f'/media/{detail["id"]}/song.wav', headers={'Range': 'bytes=2-5'})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b'2345')
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(base+'/media/../../etc/passwd')
        dashboard.save_json(folder/'state.json', dict(status='running'))
        reopened = dashboard.Studio(self.temp.name)
        self.assertEqual(reopened.detail(detail['id'])['state']['status'], 'interrupted')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires media tools')
    def test_actual_song_client_subprocess_with_fixture_engine(self):
        fixture = Path(self.temp.name)/'engine.wav'
        audio.write_wav(fixture, array.array('h', [500, -500]*(audio.RATE*5)))
        class Engine(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def reply(self, data):
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps(dict(code=200, data=data)).encode())
            def do_GET(self):
                if self.path == '/health': self.reply(dict(status='ok'))
                else:
                    self.send_response(200); self.end_headers()
                    self.wfile.write(fixture.read_bytes())
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                if self.path == '/release_task': self.reply(dict(task_id='fixture'))
                else: self.reply([dict(task_id='fixture', status=1, result=[dict(file='/v1/audio?path=fixture')])])
        engine = ThreadingHTTPServer(('127.0.0.1', 0), Engine)
        threading.Thread(target=engine.serve_forever, daemon=True).start()
        self.addCleanup(engine.server_close)
        self.addCleanup(engine.shutdown)
        studio = dashboard.Studio(Path(self.temp.name)/'songs', music_url=f'http://127.0.0.1:{engine.server_port}')
        detail = studio.create(project())
        with self.assertRaisesRegex(ValueError, 'still active'):
            studio.start(detail['id'], 'preview', True)
        studio.start(detail['id'], 'song')
        studio.worker.join(15)
        self.assertFalse(studio.worker.is_alive())
        detail = studio.detail(detail['id'])
        self.assertEqual(detail['state']['status'], 'needs_review', detail['state'])
        self.assertIn('song.wav', detail['media'])
        self.assertEqual(detail['state']['audio_task'], 'downloaded_needs_listening_review')


if __name__ == '__main__':
    unittest.main()
