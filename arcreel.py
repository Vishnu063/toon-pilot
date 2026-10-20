"""Optional ArcReel brief handoff; never submits media/model generation."""
import fcntl
import json
import os
from pathlib import Path
import re
from urllib import error, parse, request
import uuid


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, timeout=15):
        self.url = os.environ.get('ARCREEL_URL', 'http://127.0.0.1:1241').rstrip('/')
        parts = parse.urlsplit(self.url)
        if (parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment or parts.path
                or (parts.scheme == 'http' and parts.hostname not in {'localhost', '127.0.0.1', '::1'})):
            raise ValueError('ARCREEL_URL must be an origin: loopback HTTP or HTTPS, without credentials, path or query.')
        self.token = os.environ.get('ARCREEL_TOKEN', '').strip()
        if any(ord(c) < 32 or ord(c) > 126 for c in self.token):
            raise ValueError('ARCREEL_TOKEN must be a plain bearer token.')
        self.timeout = timeout
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())

    def status(self):
        return dict(configured=bool(self.token), url=self.url)

    def call(self, path, data=None, content_type='application/json'):
        if not self.token:
            raise ValueError('Set ARCREEL_TOKEN in the worker environment, then restart it.')
        req = request.Request(self.url+'/api/v1'+path, data=data, headers={
            'Authorization': 'Bearer '+self.token, 'Content-Type': content_type})
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read(1024*1024+1)
                if len(raw) > 1024*1024:
                    raise ValueError('ArcReel response exceeded the size limit.')
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError('ArcReel returned an invalid response.')
                return result
        except error.HTTPError as exc:
            # Do not expose upstream bodies, URLs or credentials in local logs/UI.
            raise ValueError(f'ArcReel HTTP {exc.code}. Check authentication, API version and project in ArcReel.') from None
        except (OSError, error.URLError, ValueError):
            raise ValueError('ArcReel connection or response failed. Check the saved handoff receipt before trying again.') from None

    def send(self, receipt_path, name, title, brief, aspect='9:16', style=''):
        """One durable attempt per project. Ambiguous mutations require manual inspection."""
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', name):
            raise ValueError('Invalid ArcReel project name.')
        if not isinstance(brief, str) or not 1 <= len(brief) <= 200000:
            raise ValueError('ArcReel brief must contain 1–200000 characters.')
        receipt_path = Path(receipt_path)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        with receipt_path.with_suffix('.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('An ArcReel handoff is already in progress.') from None
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text())
                if receipt['status'] == 'sent':
                    return receipt
                raise ValueError('ArcReel handoff is incomplete or uncertain. Inspect arcreel.json and the named project in ArcReel; automatic resubmission is blocked.')
            if self.call('/auth/verify').get('valid') is not True:
                raise ValueError('ArcReel rejected the bearer token.')
            receipt = dict(status='uncertain', phase='create_project', name=name, url=self.url)
            def save():
                temp = receipt_path.with_suffix('.tmp')
                temp.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
                temp.replace(receipt_path)
            # Checkpoint BEFORE each remote mutation. A crash must never invite retry.
            save()
            result = self.call('/projects', json.dumps(dict(name=name, title=title,
                style=style, aspect_ratio=aspect, content_mode='narration',
                generation_mode='storyboard', narration_delivery='post_production')).encode())
            if result.get('success') is not True or result.get('name') != name:
                raise ValueError('ArcReel project creation was not confirmed. Inspect the receipt and remote project.')
            receipt['phase'] = 'upload_source'
            save()
            boundary = 'brief-'+uuid.uuid4().hex
            fields = dict(content=brief, generate_overview='false')
            body = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
                           for key, value in fields.items())+f'--{boundary}--\r\n'
            result = self.call('/projects/'+name+'/source', body.encode('utf-8'), 'multipart/form-data; boundary='+boundary)
            if result.get('success') is not True or result.get('filename') != 'novel.txt' or result.get('chars') != len(brief):
                raise ValueError('ArcReel source upload was not confirmed. Inspect the receipt and remote source.')
            receipt.update(status='sent', phase='complete', source='novel.txt')
            save()
            return receipt
