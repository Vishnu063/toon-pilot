"""Opt-in official YouTube OAuth and private-only, duplicate-protected uploads."""
import argparse
import hashlib
import json
import os
from pathlib import Path

SCOPE = ['https://www.googleapis.com/auth/youtube.upload']


def private_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd,0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream, indent=2)
    temporary.replace(path)


def service(token):
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from google_auth_httplib2 import AuthorizedHttp
        import httplib2
    except ImportError as exc:
        raise ValueError('Install requirements-upload.txt for optional YouTube support.') from exc
    if not Path(token).is_file():
        raise ValueError('YouTube is disconnected. Run the explicit connect command with your own OAuth desktop client.')
    credentials = Credentials.from_authorized_user_file(str(token), SCOPE)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        private_json(token, json.loads(credentials.to_json()))
    if not credentials.valid:
        raise ValueError('YouTube OAuth expired or was revoked; reconnect explicitly.')
    # httplib2 does not use requests' CA environment automatically. Preserve the
    # cloud proxy CA bundle explicitly; leave its normal proxy selection intact.
    trust = os.environ.get('SSL_CERT_FILE') or os.environ.get('REQUESTS_CA_BUNDLE')
    transport = httplib2.Http(ca_certs=trust, timeout=60)
    return build('youtube', 'v3', http=AuthorizedHttp(credentials,http=transport), cache_discovery=False)


def upload(movie, receipt, token, title, description, api=None, media_factory=None):
    """An ambiguous attempt blocks resubmission. Never accept a visibility argument."""
    import fcntl
    movie, receipt = Path(movie), Path(receipt)
    if not movie.is_file() or movie.suffix.lower() != '.mp4':
        raise ValueError('Select a completed MP4.')
    if not isinstance(title, str) or not title.strip() or len(title) > 100:
        raise ValueError('Upload title must contain 1–100 characters.')
    if not isinstance(description, str) or len(description.encode('utf-8')) > 5000:
        raise ValueError('Description is too long.')
    digest = hashlib.sha256()
    with movie.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    signature = digest.hexdigest()
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.with_suffix('.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('An upload is already active.') from exc
        if receipt.exists():
            state = json.loads(receipt.read_text())
            if state.get('sha256') != signature:
                raise ValueError('Upload receipt belongs to different media.')
            if state.get('status') == 'uploaded_private':
                return state
            raise ValueError('Previous upload outcome is uncertain. Inspect YouTube Studio before any manual resubmission; automatic retry is blocked.')
        # Validate prerequisites before recording an attempt.
        if api is None:
            api = service(token)
        if media_factory is None:
            from googleapiclient.http import MediaFileUpload
            media_factory = MediaFileUpload
        import video
        info = video.probe(movie)
        if not {'video', 'audio'} <= {s['codec_type'] for s in info['streams']}:
            raise ValueError('YouTube upload requires video and audio.')
        video.verify_video(movie, float(info['format']['duration']), 12, receipt.with_suffix('.verify.log'))
        body = dict(snippet=dict(title=title.strip(), description=description,
                    tags=['original animation', 'children story'], categoryId='1'),
                    status=dict(privacyStatus='private', selfDeclaredMadeForKids=True))
        state = dict(status='upload_started_outcome_uncertain', sha256=signature, visibility='private')
        private_json(receipt, state)
        try:
            request = api.videos().insert(part='snippet,status', body=body,
                media_body=media_factory(str(movie), mimetype='video/mp4', chunksize=8*1024*1024, resumable=True))
            response = None
            while response is None:
                _, response = request.next_chunk(num_retries=0)
            if not isinstance(response.get('id'), str) or not response['id']:
                raise ValueError('YouTube returned no video ID.')
            state.update(status='uploaded_private', video_id=response['id'])
            private_json(receipt, state)
        except Exception:
            # Do not log API error bodies or token-bearing resumable URLs.
            raise ValueError('Upload failed or its response was lost. Receipt blocks duplicate uploads; inspect YouTube Studio.') from None
        return state


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    connect = sub.add_parser('connect')
    connect.add_argument('--client', required=True, help='Private OAuth Desktop client JSON, outside Git')
    connect.add_argument('--token', default='output/private/youtube-token.json')
    send = sub.add_parser('upload')
    send.add_argument('--video', required=True)
    send.add_argument('--receipt', required=True)
    send.add_argument('--token', default='output/private/youtube-token.json')
    send.add_argument('--title', required=True)
    send.add_argument('--description', default='An original Toon Pilot animation. Spoken narration; not singing.')
    args = p.parse_args()
    try:
        if args.command == 'connect':
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(args.client, SCOPE)
            credentials = flow.run_local_server(host='127.0.0.1', port=8769, open_browser=False)
            private_json(args.token, json.loads(credentials.to_json()))
            print('YouTube connected. Uploads remain opt-in and private.')
        else:
            print(json.dumps(upload(args.video, args.receipt, args.token, args.title, args.description)))
    except (ValueError, OSError, ImportError) as exc:
        p.exit(1, f'YouTube: {exc}\n')


if __name__ == '__main__':
    main()
