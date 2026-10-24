"""Persistent, single-worker offline production queue around the existing runner."""
import argparse
import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace

import narration
import audio
import planner
import video


class Queue:
    def __init__(self, root='output/production'):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root/'queue.sqlite3', timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL, error TEXT, updated REAL NOT NULL)')
        self.db.commit()

    def close(self):
        self.db.close()

    def enqueue(self, request, key=None):
        # Validate before leaving a durable pending job.
        if not isinstance(request, dict):
            raise ValueError('Production request must be an object.')
        planned = planner.plan(request['title'], request['text'], request.get('duration', 30),
                     request.get('language', 'en'), request.get('characters'), request.get('orientation', 'portrait'))
        if any(type(request.get(name,False)) is not bool for name in ('preview','upload_private')):
            raise ValueError('preview and upload_private must be booleans.')
        voice = request.get('voice',request.get('language','en')+'-boy')
        if voice not in narration.VOICES or narration.VOICES[voice]['language'] != planned['language']:
            raise ValueError('Choose a known narration voice matching the story language.')
        video.render_settings(SimpleNamespace(preview=request.get('preview',False), blender='blender',
            mode=request.get('mode','lite'), orientation=planned['orientation'],
            width=request.get('width'), height=request.get('height'), fps=request.get('fps')), planned)
        raw = json.dumps(request, sort_keys=True, ensure_ascii=False)
        identifier = hashlib.sha256((key or raw).encode()).hexdigest()[:24]
        existing = self.db.execute('SELECT request FROM jobs WHERE id=?', (identifier,)).fetchone()
        if existing and existing['request'] != raw:
            raise ValueError('That schedule key already names a different request.')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO jobs VALUES (?, ?, ?, ?, NULL, ?)',
                            (identifier, raw, 'pending', 'plan', time.time()))
        return identifier

    def rows(self):
        return [dict(row) for row in self.db.execute('SELECT id,status,stage,error,updated FROM jobs ORDER BY updated DESC')]

    def update(self, identifier, status, stage, error=None):
        with self.db:
            self.db.execute('UPDATE jobs SET status=?,stage=?,error=?,updated=? WHERE id=?',
                            (status, stage, error, time.time(), identifier))

    def retry(self, identifier):
        with self.db:
            changed = self.db.execute("UPDATE jobs SET status='pending', error=NULL WHERE id=? AND status='failed'", (identifier,)).rowcount
        if not changed:
            raise ValueError('Only a failed job can be retried.')

    def worker(self, blender='blender', speech=None, allow_private_upload=False, token='output/private/youtube-token.json'):
        with (self.root/'worker.lock').open('w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError('Another queue worker is active.') from exc
            # A process crash releases flock; retain completed stage artifacts.
            with self.db:
                self.db.execute("UPDATE jobs SET status='pending' WHERE status='running'")
            rows = list(self.db.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY updated"))
            failed = 0
            for row in rows:
                folder = self.root/row['id']
                folder.mkdir(exist_ok=True)
                request = json.loads(row['request'])
                stage = 'plan'
                try:
                    self.update(row['id'], 'running', stage)
                    plan = planner.plan(request['title'], request['text'], request.get('duration', 30),
                                        request.get('language', 'en'), request.get('characters'), request.get('orientation', 'portrait'))
                    for name, value in [('plan.json', plan), ('score.json', dict(bpm=60, notes=[dict(lyric='R', pitch=60, ticks=request.get('duration',30)*480)]))]:
                        (folder/name).write_text(json.dumps(value, ensure_ascii=False, indent=2))
                    stage = 'narration'
                    self.update(row['id'], 'running', stage)
                    spoken = folder/'narration.wav'
                    if not spoken.exists():
                        narration.synthesize(plan, spoken, voice=request.get('voice', request.get('language','en')+'-boy'), executable=speech)
                    else:
                        narration.check_audio(spoken)
                        import song
                        song.validate_audio(spoken, request.get('duration',30))
                    soundtrack = folder/'soundtrack.wav'
                    if not soundtrack.exists():
                        audio.prepare(folder/'score.json', folder/'backing')
                        temporary_soundtrack = folder/'soundtrack.pending.wav'
                        audio.mix(spoken, folder/'backing/backing.wav', temporary_soundtrack)
                        temporary_soundtrack.replace(soundtrack)
                    stage = 'render'
                    self.update(row['id'], 'running', stage)
                    args = SimpleNamespace(plan=str(folder/'plan.json'), song=str(folder/'score.json'), out=str(folder/'render'),
                        vocals=None, soundtrack=str(soundtrack), instrumental=False, preview=request.get('preview',False),
                        blender=blender, threads=2, mode=request.get('mode','lite'), engine='cycles', orientation=plan['orientation'],
                        width=request.get('width'), height=request.get('height'), fps=request.get('fps'))
                    # Use the actual runner result, including its exact output path, rather
                    # than recomputing a key if source files change while rendering.
                    manifest = video.create(args)
                    if manifest['status'] != 'verified_media_needs_human_review':
                        raise ValueError('Runner did not verify this job.')
                    (folder/'result.json').write_text(json.dumps(dict(manifest, audio_kind='spoken_narration_not_singing'), indent=2))
                    if request.get('upload_private'):
                        stage = 'upload'
                        if not allow_private_upload:
                            self.update(row['id'], 'needs_review', stage, 'Private upload is disabled. Review media and enable it explicitly.')
                            continue
                        self.update(row['id'], 'running', stage)
                        import youtube_upload
                        youtube_upload.upload(manifest['output'], folder/'youtube.json', token, request['title'], request['text'].encode('utf-8')[:4500].decode('utf-8',errors='ignore'))
                        self.update(row['id'], 'uploaded_private', 'complete')
                        continue
                    self.update(row['id'], 'needs_review', 'complete')
                except Exception as exc:
                    failed += 1
                    self.update(row['id'], 'failed', stage, str(exc)[:2000])
            return failed


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', default='output/production')
    sub = p.add_subparsers(dest='command', required=True)
    enqueue = sub.add_parser('enqueue')
    enqueue.add_argument('--request', required=True)
    daily = sub.add_parser('daily', help='Enqueue one opted-in 30-second story for today; no background daemon or upload')
    daily.add_argument('--request', help='Optional original script; otherwise rotate three built-in story templates')
    daily.add_argument('--language', choices=['en','hi'], default='en')
    daily.add_argument('--timezone', default='Asia/Kolkata')
    worker = sub.add_parser('worker', help='Drain pending jobs once; failed jobs require explicit retry')
    worker.add_argument('--blender', default='blender')
    worker.add_argument('--speech', help='Path to espeak-ng executable')
    worker.add_argument('--allow-private-upload', action='store_true', help='Explicitly permit requests marked upload_private, after OAuth and quota setup')
    worker.add_argument('--youtube-token', default='output/private/youtube-token.json')
    retry = sub.add_parser('retry')
    retry.add_argument('id')
    sub.add_parser('list')
    args = p.parse_args()
    queue = Queue(args.root)
    try:
        if args.command in ('enqueue', 'daily'):
            if args.request:
                request = json.loads(Path(args.request).read_text())
            else:
                from stories import for_day
                from zoneinfo import ZoneInfo
                request = for_day(datetime.datetime.now(ZoneInfo(args.timezone)).date(),args.language)
            key = None
            if args.command == 'daily':
                from zoneinfo import ZoneInfo
                if request.get('duration',30) != 30:
                    raise ValueError('Daily mode requires a 30-second request.')
                key = 'daily:'+str(datetime.datetime.now(ZoneInfo(args.timezone)).date())
            print(queue.enqueue(request, key))
        elif args.command == 'worker':
            return 1 if queue.worker(args.blender, args.speech, args.allow_private_upload, args.youtube_token) else 0
        elif args.command == 'retry':
            queue.retry(args.id)
        else:
            print(json.dumps(queue.rows(), indent=2))
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(f'Production: {exc}', file=sys.stderr)
        return 1
    finally:
        queue.close()


if __name__ == '__main__':
    sys.exit(main())
