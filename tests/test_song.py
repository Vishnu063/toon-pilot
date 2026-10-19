import argparse
import array
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
import audio
import song

class SongTests(unittest.TestCase):
    def test_request_disables_lm_and_uses_one_song(self):
        data=song.payload_for(song.ROOT/'examples/ace_sample.json')
        self.assertEqual(data['batch_size'],1)
        for key in ['thinking','use_format','sample_mode','use_cot_caption','use_cot_language']:
            self.assertFalse(data[key])
        with self.assertRaises(ValueError):
            song.LocalClient('https://example.com')
        with self.assertRaises(ValueError):
            song.LocalClient('http://127.0.0.1:8001').download('https://example.com/song.wav','unused')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'requires media tools')
    def test_local_http_job_timeout_resume_download_and_cache(self):
        self.exercise('success')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'requires media tools')
    def test_failed_job_creates_no_output(self):
        self.exercise('failure')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'requires media tools')
    def test_invalid_download_creates_no_output(self):
        self.exercise('invalid_audio')

    def exercise(self,mode):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            fixture=root/'fixture.wav'
            # Synthetic alternating samples, not an AI singing sample.
            audio.write_wav(fixture,array.array('h',[500,-500]*(audio.RATE*5)))
            counts={'submit':0,'queries':0}
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*args): pass
                def respond(self,value):
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps({'code':200,'data':value,'error':None}).encode())
                def do_GET(self):
                    if self.path=='/health': self.respond({'status':'ok'})
                    else:
                        self.send_response(200); self.end_headers()
                        self.wfile.write(b'bad audio' if mode=='invalid_audio' else fixture.read_bytes())
                def do_POST(self):
                    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if self.path=='/release_task':
                        counts['submit']+=1
                        self.respond({'task_id':'test-job'})
                    else:
                        counts['queries']+=1
                        self.respond([{'task_id':'test-job','status':0 if counts['queries']==1 else 2 if mode=='failure' else 1,
                                       'result':json.dumps([{'status':1,'file':'/v1/audio?path=fixture.wav'}])}])
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            args=argparse.Namespace(request=str(song.ROOT/'examples/ace_sample.json'),url=f'http://127.0.0.1:{server.server_port}',
                out=str(root/'song.wav'),timeout=.001,poll=.001)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(ValueError,'timed out'):
                        song.generate(args)
                    self.assertTrue((root/'song.wav.job.json').exists())
                    args.timeout=10
                    if mode=='failure':
                        with self.assertRaisesRegex(ValueError,'generation failed'): song.generate(args)
                        self.assertFalse((root/'song.wav').exists())
                    elif mode=='invalid_audio':
                        with self.assertRaises(Exception): song.generate(args)
                        self.assertFalse((root/'song.wav').exists())
                        self.assertFalse((root/'song.download.wav').exists())
                    else:
                        song.generate(args)
                        self.assertEqual((root/'song.wav').read_bytes(),fixture.read_bytes())
                        song.generate(args)
                        self.assertEqual(json.loads((root/'song.wav.job.json').read_text())['status'],'downloaded_needs_listening_review')
                    self.assertEqual(counts['submit'],1)
            finally:
                server.shutdown();server.server_close();worker.join()

if __name__=='__main__': unittest.main()
