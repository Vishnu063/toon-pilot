"""Contract tests with a local HTTP fixture, not a live ArcReel/model."""
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import arcreel


class ArcReelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.receipt = Path(self.temp.name)/'arcreel.json'
        self.calls = []
        self.failure = None
        self.expected_brief = 'Original brief — hello'
        outer = self
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def respond(self, value, status=200):
                self.send_response(status)
                self.send_header('Location', '/leak')
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())
            def do_GET(self):
                outer.calls.append(('GET', self.path))
                outer.assertEqual(self.headers['Authorization'], 'Bearer private-test-token')
                self.respond(dict(valid=True))
            def do_POST(self):
                outer.calls.append(('POST', self.path))
                raw = self.rfile.read(int(self.headers['Content-Length']))
                if outer.failure == 'create': return self.respond({}, 401)
                if outer.failure == 'redirect': return self.respond({}, 307)
                if self.path == '/api/v1/projects':
                    data = json.loads(raw)
                    outer.assertEqual(data['generation_mode'], 'storyboard')
                    outer.assertEqual(data['narration_delivery'], 'post_production')
                    self.respond(dict(success=True, name=data['name']))
                else:
                    message = BytesParser(policy=policy.default).parsebytes(
                        ('Content-Type: '+self.headers['Content-Type']+'\r\n\r\n').encode()+raw)
                    fields = {p.get_param('name', header='Content-Disposition'): p.get_payload(decode=True).decode()
                              for p in message.iter_parts()}
                    outer.fields = fields
                    if outer.expected_brief is not None:
                        outer.assertEqual(fields, dict(content=outer.expected_brief, generate_overview='false'))
                    if outer.failure == 'upload': return self.respond({}, 500)
                    if outer.failure == 'disconnect':
                        self.close_connection = True
                        self.connection.close()
                        return
                    self.respond(dict(success=True, filename='novel.txt', chars=len(fields['content'])))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        env = patch.dict(os.environ, ARCREEL_URL=f'http://127.0.0.1:{self.server.server_port}', ARCREEL_TOKEN='private-test-token')
        env.start(); self.addCleanup(env.stop)

    def send(self):
        return arcreel.Client().send(self.receipt, 'toon-fixture', 'Title', 'Original brief — hello')

    def test_transfer_flags_and_repeat_does_not_mutate(self):
        result = self.send()
        self.assertEqual(result['status'], 'sent')
        self.assertEqual(self.send(), result)
        self.assertEqual(self.calls, [('GET', '/api/v1/auth/verify'), ('POST', '/api/v1/projects'), ('POST', '/api/v1/projects/toon-fixture/source')])
        self.assertNotIn('private-test-token', self.receipt.read_text())

    def test_mutation_errors_and_lost_response_never_resubmit(self):
        for failure, phase in [('create','create_project'), ('upload','upload_source'), ('disconnect','upload_source'), ('redirect','create_project')]:
            with self.subTest(failure=failure):
                self.failure = failure
                self.receipt.unlink(missing_ok=True)
                self.calls.clear()
                with self.assertRaises(ValueError): self.send()
                receipt = json.loads(self.receipt.read_text())
                self.assertEqual(receipt['status'], 'uncertain')
                self.assertEqual(receipt['phase'], phase)
                count = len(self.calls)
                with self.assertRaisesRegex(ValueError, 'resubmission is blocked'): self.send()
                self.assertEqual(len(self.calls), count)
                self.assertFalse(any(path == '/leak' for _, path in self.calls))

    def test_optional_configuration_and_url_validation(self):
        with patch.dict(os.environ, ARCREEL_TOKEN=''):
            self.assertFalse(arcreel.Client().status()['configured'])
            with self.assertRaisesRegex(ValueError, 'ARCREEL_TOKEN'): self.send()
            self.assertFalse(self.receipt.exists())
        for url in ['http://remote.example', 'https://user:secret@example.com', 'https://example.com/path', 'https://example.com?token=bad']:
            with patch.dict(os.environ, ARCREEL_URL=url):
                with self.assertRaises(ValueError): arcreel.Client()

    def test_concurrent_attempt_is_blocked(self):
        import fcntl
        with self.receipt.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'already in progress'): self.send()
        self.assertEqual(self.calls, [])


class DashboardHandoffTests(ArcReelTests):
    # Inherit fixture setup only; base tests are not repeated by this class.
    test_transfer_flags_and_repeat_does_not_mutate = None
    test_mutation_errors_and_lost_response_never_resubmit = None
    test_optional_configuration_and_url_validation = None
    test_concurrent_attempt_is_blocked = None

    def test_dashboard_http_handoff_and_saved_receipt(self):
        import dashboard
        from urllib import request
        self.expected_brief = None
        studio = dashboard.Studio(Path(self.temp.name)/'studio')
        project = dict(title='A rhyme', lyrics='Hop hop little duck', prompt='Gentle singing',
                       duration=10, bpm=100, scenes=[dict(seconds=10, action='hop', camera='dolly', caption='Play')])
        detail = studio.create(project)
        server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.Handler)
        server.studio = studio
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/api/projects/{detail["id"]}/arcreel'
        req = request.Request(url, data=b'{}', headers={'X-Toon-Pilot':'1'})
        with request.urlopen(req) as response:
            self.assertEqual(json.load(response)['status'], 'sent')
        self.assertEqual(studio.detail(detail['id'])['arcreel']['name'], 'toon-'+detail['id'])
        self.assertIn(project['lyrics'], self.fields['content'])
        self.assertEqual(self.fields['generate_overview'], 'false')
        self.assertIsNone(studio.active)
        self.assertEqual(studio.detail(detail['id'])['state']['status'], 'ready')
