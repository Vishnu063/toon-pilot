"""Optional client for a separately installed, local ACE-Step 1.5 server."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import subprocess

ROOT = Path(__file__).resolve().parent

class LocalClient:
    def __init__(self, url):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != 'http' or parts.hostname not in {'127.0.0.1', 'localhost', '::1'} or parts.username or parts.password or parts.query or parts.fragment or parts.path not in {'', '/'}:
            raise ValueError('use a local HTTP server, e.g. http://127.0.0.1:8001; use an SSH tunnel for EC2')
        self.url = url.rstrip('/')
        # Ignore proxy settings for loopback. Refuse redirects away from the selected server.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise ValueError('server redirects are not supported')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def json(self, path, payload=None):
        request = urllib.request.Request(self.url + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type': 'application/json'})
        with self.opener.open(request, timeout=30) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('API response too large')
        result = json.loads(raw)
        if result.get('code', 200) != 200 or result.get('error'):
            raise ValueError('ACE-Step reported an API error; inspect its server logs')
        return result['data']

    def download(self, location, destination):
        url = urllib.parse.urljoin(self.url + '/', location)
        parts = urllib.parse.urlsplit(url)
        if (parts.scheme, parts.netloc) != (urllib.parse.urlsplit(self.url).scheme, urllib.parse.urlsplit(self.url).netloc) or parts.path != '/v1/audio':
            raise ValueError('audio URL must use /v1/audio on the same local server')
        with self.opener.open(url, timeout=60) as response, Path(destination).open('wb') as out:
            size = 0
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > 200_000_000:
                    raise ValueError('audio exceeds 200 MB download limit')
                out.write(chunk)

def payload_for(path):
    request = json.loads(Path(path).read_text(encoding='utf-8'))
    if not all(isinstance(request.get(k), str) and request[k].strip() for k in ('prompt','lyrics')):
        raise ValueError('song request needs a prompt and lyrics')
    seconds = request.get('audio_duration', 10)
    if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 10 <= seconds <= 120:
        raise ValueError('start with a 10 to 120 second song')
    bpm = request.get('bpm', 100)
    if type(bpm) is not int or not 30 <= bpm <= 300:
        raise ValueError('bpm must be an integer between 30 and 300')
    return dict(prompt=request['prompt'], lyrics=request['lyrics'], audio_duration=seconds,
        bpm=bpm, key_scale='C Major', time_signature='4', vocal_language='en',
        audio_format='wav', batch_size=1, inference_steps=8, thinking=False,
        sample_mode=False, use_format=False, use_cot_caption=False, use_cot_language=False,
        task_type='text2music', use_random_seed=False, seed=42)

def validate_audio(path, seconds):
    result = subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],
                            capture_output=True,text=True,check=True)
    info = json.loads(result.stdout)
    if not any(s['codec_type']=='audio' for s in info['streams']):
        raise ValueError('download contains no audio stream')
    if abs(float(info['format']['duration'])-seconds)>1:
        raise ValueError('generated duration differs by more than 1 second; inspect before using')
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-map','0:a:0','-f','null','-'],
                   capture_output=True,check=True)

def _generate(args):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('install FFmpeg and FFprobe first')
    payload = payload_for(args.request)
    client = LocalClient(args.url)
    destination = Path(args.out).resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    state_path = destination.with_suffix(destination.suffix+'.job.json')
    signature = hashlib.sha256(json.dumps({'url':client.url,'payload':payload},sort_keys=True).encode()).hexdigest()
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if state and state.get('fingerprint') != signature:
        raise ValueError('output belongs to a different request; choose another --out path')
    if destination.exists():
        if state.get('status') != 'downloaded_needs_listening_review':
            raise ValueError('output already exists; choose another --out path')
        validate_audio(destination,payload['audio_duration'])
        print(f'Reusing checked audio: {destination}. Singing quality still needs listening review.')
        return
    health = client.json('/health')
    if health.get('status') != 'ok':
        raise ValueError('ACE-Step health check failed')
    if not state.get('task_id'):
        # Do not retry task submission automatically: a lost response can mean the job was accepted.
        job = client.json('/release_task',payload)
        if not isinstance(job.get('task_id'),str) or not job['task_id']:
            raise ValueError('missing task_id in ACE-Step response')
        state = {'fingerprint':signature,'task_id':job['task_id'],'status':'submitted'}
        state_path.write_text(json.dumps(state,indent=2))
    print(f'Waiting for ACE-Step job {state["task_id"]}; re-run the same command to poll it again.',flush=True)
    deadline = time.monotonic()+args.timeout
    while time.monotonic()<deadline:
        records = client.json('/query_result',{'task_id_list':[state['task_id']]})
        record = next((r for r in records if r.get('task_id')==state['task_id']),None)
        if record is None:
            raise ValueError('task is not present on server; inspect ACE-Step before deleting the saved job record')
        status = int(record['status'])
        if status == 2:
            state['status']='failed'
            state_path.write_text(json.dumps(state,indent=2))
            raise ValueError('ACE-Step generation failed; inspect server logs, memory use, and model setup')
        if status == 1:
            entries = json.loads(record['result']) if isinstance(record['result'],str) else record['result']
            if not entries or int(entries[0].get('status',1))!=1:
                raise ValueError('task completed without a successful audio result')
            temporary = destination.with_suffix('.download.wav')
            try:
                client.download(entries[0]['file'],temporary)
                validate_audio(temporary,payload['audio_duration'])
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            state['status']='downloaded_needs_listening_review'
            state_path.write_text(json.dumps(state,indent=2))
            print(f'Saved: {destination}. File decoding and duration passed; vocals, lyrics, and musical quality are NOT verified.')
            return
        if status != 0:
            raise ValueError(f'unknown task status {status}')
        time.sleep(min(args.poll,max(0,deadline-time.monotonic())))
    raise ValueError(f'wait timed out; job ID is saved in {state_path}. Re-run the same command to continue polling, without submitting again.')

def generate(args):
    destination = Path(args.out).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.with_suffix(destination.suffix+'.lock')
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError(f'another client may be using this output: {lock}; remove only after confirming no client is running')
    os.close(descriptor)
    try:
        _generate(args)
    finally:
        lock.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',default=str(ROOT/'examples/ace_sample.json'))
    parser.add_argument('--url',default='http://127.0.0.1:8001')
    parser.add_argument('--out',default='output/music/sample.wav')
    parser.add_argument('--timeout',type=int,default=1800)
    parser.add_argument('--poll',type=int,default=5)
    args=parser.parse_args()
    if args.timeout<=0 or not 1<=args.poll<=60:
        parser.error('timeout must be positive and poll must be 1 to 60 seconds')
    try:
        generate(args)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError,urllib.error.URLError) as exc:
        parser.exit(1,f'Song generation failed: {exc}\n')
    except KeyboardInterrupt:
        parser.exit(130,'Stopped waiting. Any saved task ID can be polled again with the same command.\n')

if __name__=='__main__':
    main()
