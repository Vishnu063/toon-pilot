"""Sequential, resumable Blender video runner; singing is imported, not synthesized."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import audio
import scenes as scene_files

ROOT = Path(__file__).resolve().parent
ACTIONS = {'waddle', 'hop', 'dance', 'wave'}
CAMERAS = {'dolly', 'arc', 'pullback', 'static'}

def validate_plan(plan):
    if not isinstance(plan.get('scenes'), list) or not 1 <= len(plan['scenes']) <= 100:
        raise ValueError('plan needs 1 to 100 scenes')
    for scene in plan['scenes']:
        seconds = scene.get('seconds')
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not .5 <= seconds <= 60:
            raise ValueError('each scene needs 0.5 to 60 seconds')
        if scene.get('action') not in ACTIONS or scene.get('camera') not in CAMERAS:
            raise ValueError('unknown action or camera preset')
    if sum(s['seconds'] for s in plan['scenes']) > 600:
        raise ValueError('maximum video duration is 600 seconds')
    return plan

def run(command, log):
    with Path(log).open('w') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}); inspect {log}. Re-run the same command to resume.')

def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)

def verify_video(path, seconds, fps, log):
    data = probe(path)
    streams = [s for s in data['streams'] if s['codec_type'] == 'video']
    if not streams or abs(float(data['format']['duration']) - seconds) > max(.15, 2 / fps):
        raise ValueError(f'invalid video duration: {path}')
    run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-map', '0:v:0', '-f', 'null', '-'], log)

def fingerprint(plan, song, vocals, preview, soundtrack=None):
    digest = hashlib.sha256()
    digest.update(json.dumps({'plan': plan, 'preview': preview}, sort_keys=True).encode())
    for path in [ROOT / 'video.py', ROOT / 'audio.py', ROOT / 'blender_scene.py', ROOT / 'scenes.py', ROOT / 'third_party/anim_studio/rig.py', song] + ([vocals] if vocals else []) + ([soundtrack] if soundtrack else []):
        digest.update(Path(path).read_bytes())
    for scene in plan.get('scenes', []):
        for character in scene.get('characters', []):
            with Path(character['model']).open('rb') as model:
                for chunk in iter(lambda: model.read(1024*1024), b''):
                    digest.update(chunk)
    return digest.hexdigest()

def doctor(args):
    missing = []
    for name, executable in [('Blender', args.blender), ('FFmpeg', 'ffmpeg'), ('FFprobe', 'ffprobe')]:
        found = shutil.which(executable)
        print(f'{name}: {found or "MISSING"}')
        if not found:
            missing.append(name)
    if args.voicebank:
        bank = Path(args.voicebank)
        configs = [p for p in bank.rglob('*') if p.name.lower() in {'character.txt', 'dsconfig.yaml', 'oto.ini'}] if bank.is_dir() else []
        print('Voicebank files: ' + (', '.join(str(p.relative_to(bank)) for p in configs[:8]) or 'NOT FOUND'))
        if not configs:
            missing.append('voicebank files')
    else:
        print('Voicebank: not supplied. OpenUtau needs an English singer; ACE-Step uses the separate song.py path.')
    print('Phonemizer: ' + (args.phonemizer or 'not supplied; select the one required by the singer in OpenUtau'))
    print('Renderer: select the renderer required by the singer in OpenUtau (WORLDLINE-R or DiffSinger, for example).')
    print('File presence does not verify a voicebank license, phonemizer compatibility, or audible output.')
    if missing:
        print('Fix: install missing tools; see README. Use --blender /path/to/blender for a custom location.')
    return 1 if missing else 0

def create(args):
    plan = validate_plan(scene_files.load_plan(args.plan))
    song, song_seconds = audio.load_song(args.song)
    total = sum(s['seconds'] for s in plan['scenes'])
    if abs(total - song_seconds) > .05:
        raise ValueError('song and video plan durations must match')
    for name in (args.blender, 'ffmpeg', 'ffprobe'):
        if not shutil.which(name):
            raise ValueError(f'{name} is missing. Run: python3 video.py doctor')
    soundtrack_input = getattr(args, 'soundtrack', None)
    if soundtrack_input and (args.vocals or args.instrumental):
        raise ValueError('--soundtrack is a complete song; do not combine it with --vocals or --instrumental')
    if soundtrack_input:
        import song as song_client
        song_client.validate_audio(soundtrack_input, total)
    if not args.preview and not args.vocals and not args.instrumental and not soundtrack_input:
        raise ValueError('supply --soundtrack song.wav, --vocals vocals.wav, or explicitly choose --instrumental')
    job_key = fingerprint(plan, Path(args.song), Path(args.vocals) if args.vocals else None, args.preview, soundtrack_input)
    folder = Path(args.out).resolve() / ('preview' if args.preview else 'full') / job_key[:16]
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / '.running'
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError(f'Job lock exists: {lock}. If no render is running, remove this lock and retry.')
    os.close(descriptor)
    manifest_path = folder / 'status.json'
    try:
        manifest = {'fingerprint': job_key, 'status': 'running', 'scenes': [], 'vocals': bool(args.vocals), 'soundtrack': bool(soundtrack_input)}
        manifest_path.write_text(json.dumps(manifest, indent=2))
        audio.prepare(args.song, folder)
        soundtrack = folder / 'backing.wav'
        if args.vocals:
            audio.mix(args.vocals, soundtrack, folder / 'song.wav')
            soundtrack = folder / 'song.wav'
        if soundtrack_input:
            soundtrack = Path(soundtrack_input).resolve()
        fps, width, height, samples = (12, 256, 456, 4) if args.preview else (24, 540, 960, 8)
        scenes = [dict(plan['scenes'][0], seconds=min(2, plan['scenes'][0]['seconds']))] if args.preview else plan['scenes']
        durations = [round(s['seconds'] * fps) / fps for s in scenes]
        caption_count = scene_files.write_captions(scenes, durations, folder / 'captions.srt')
        for index, (scene, seconds) in enumerate(zip(scenes, durations)):
            work = folder / f'scene-{index:02d}'
            work.mkdir(exist_ok=True)
            clip = work / 'clip.mp4'
            frames = round(seconds * fps)
            config = dict(scene, frames=frames, fps=fps, width=width, height=height, samples=samples,
                          directory=str(work), threads=args.threads)
            config_path = work / 'config.json'
            config_path.write_text(json.dumps(config))
            good = False
            if clip.exists():
                try:
                    verify_video(clip, seconds, fps, work / 'verify.log')
                    good = True
                except (ValueError, RuntimeError, subprocess.SubprocessError, KeyError):
                    pass
            if not good:
                print(f'Rendering scene {index+1}/{len(scenes)} ({seconds}s), CPU threads={args.threads}', flush=True)
                run([args.blender, '--background', '--factory-startup', '--python-exit-code', '1',
                     '--python', str(ROOT / 'blender_scene.py'), '--', str(config_path)], work / 'render.log')
                # Decode each PNG before encoding; an interrupted partial file must not count as complete.
                for frame in range(1, frames + 1):
                    image = work / f'{frame:05d}.png'
                    if not image.exists() or image.stat().st_size < 100:
                        raise ValueError(f'missing frame {image}; rerun to resume')
                run(['ffmpeg', '-y', '-v', 'error', '-xerror', '-framerate', str(fps), '-i', str(work / '%05d.png'),
                     '-frames:v', str(frames), '-c:v', 'libx264', '-threads', str(args.threads), '-pix_fmt', 'yuv420p', str(clip)], work / 'encode.log')
                verify_video(clip, seconds, fps, work / 'verify.log')
            manifest['scenes'].append({'index': index, 'status': 'verified', 'reused': good})
            manifest_path.write_text(json.dumps(manifest, indent=2))
        # Relative, tool-generated paths avoid concat quoting issues with arbitrary output directory names.
        (folder / 'clips.txt').write_text(''.join(f"file 'scene-{i:02d}/clip.mp4'\n" for i in range(len(scenes))))
        destination = folder / ('preview.mp4' if args.preview else 'video.mp4')
        temporary = folder / 'assembling.mp4'
        run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '1', '-i', str(folder / 'clips.txt'),
             '-i', str(soundtrack), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
             '-t', str(sum(durations)), '-movflags', '+faststart', str(temporary)], folder / 'assemble.log')
        if caption_count:
            captioned = folder / 'captioned.mp4'
            run(['ffmpeg', '-y', '-v', 'error', '-i', str(temporary), '-i', str(folder / 'captions.srt'),
                 '-map', '0:v:0', '-map', '0:a:0', '-map', '1:0', '-c', 'copy', '-c:s', 'mov_text',
                 '-metadata:s:s:0', 'language=eng', '-movflags', '+faststart', str(captioned)], folder / 'captions.log')
            captioned.replace(temporary)
        verify_video(temporary, sum(durations), fps, folder / 'verify-final.log')
        if not any(s['codec_type'] == 'audio' for s in probe(temporary)['streams']):
            raise ValueError('final video is missing audio')
        temporary.replace(destination)
        manifest.update(status='verified_media_needs_human_review', output=str(destination),
                        seconds=sum(durations), captions=caption_count, finished=time.time())
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f'Created: {destination}\nAudio: {"imported complete song; vocals unverified" if soundtrack_input else "imported vocals" if args.vocals else "instrumental only, no singing"}. Review animation and sound before publishing.')
    except BaseException as exc:
        if 'manifest' in locals():
            manifest.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', error=str(exc))
            manifest_path.write_text(json.dumps(manifest, indent=2))
        raise
    finally:
        lock.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    doc = commands.add_parser('doctor')
    doc.add_argument('--blender', default='blender')
    doc.add_argument('--voicebank')
    doc.add_argument('--phonemizer')
    new = commands.add_parser('create')
    new.add_argument('--plan', default=str(ROOT / 'examples/video.json'))
    new.add_argument('--song', default=str(ROOT / 'examples/happy_feet.json'))
    new.add_argument('--out', default='output/video')
    new.add_argument('--vocals')
    new.add_argument('--soundtrack', help='Complete song with music; bypasses procedural backing and vocal mixing')
    new.add_argument('--instrumental', action='store_true')
    new.add_argument('--preview', action='store_true')
    new.add_argument('--blender', default='blender')
    new.add_argument('--threads', type=int, choices=range(1, 5), default=2)
    args = parser.parse_args()
    try:
        if args.command == 'doctor':
            return doctor(args)
        create(args)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'Video failed: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Stopped. Run the same command to resume.', file=sys.stderr)
        return 130

if __name__ == '__main__':
    sys.exit(main())
