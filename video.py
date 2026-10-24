"""Sequential, resumable Blender video runner; singing is imported, not synthesized."""
import argparse
import fcntl
import hashlib
import json
import math
import os
import resource
from pathlib import Path
import shutil
import subprocess
import sys
import time
import audio
import scenes as scene_files
import characters

ROOT = Path(__file__).resolve().parent
ACTIONS = {'waddle', 'hop', 'dance', 'wave', 'idle', 'walk', 'run', 'talk', 'sing'}
CAMERAS = {'dolly', 'arc', 'pullback', 'static'}

def validate_plan(plan):
    if not isinstance(plan, dict):
        raise ValueError('plan must be an object')
    if not isinstance(plan.get('scenes'), list) or not 1 <= len(plan['scenes']) <= 100:
        raise ValueError('plan needs 1 to 100 scenes')
    for scene in plan['scenes']:
        if not isinstance(scene, dict):
            raise ValueError('each scene must be an object')
        seconds = scene.get('seconds')
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not .5 <= seconds <= 60:
            raise ValueError('each scene needs 0.5 to 60 seconds')
        if not isinstance(scene.get('action'), str) or not isinstance(scene.get('camera'), str) or scene['action'] not in ACTIONS or scene['camera'] not in CAMERAS:
            raise ValueError('unknown action or camera preset')
        if 'original_characters' in scene:
            characters.select(scene['original_characters'])
        if scene.get('background', 'garden') != 'garden' or scene.get('expression', 'happy') != 'happy':
            raise ValueError('starter assets currently support garden backgrounds and happy expressions')
        if scene.get('transition', 'cut') not in ('cut', 'fade'):
            raise ValueError('transition must be cut or fade (fade through black)')
    if sum(s['seconds'] for s in plan['scenes']) > 600:
        raise ValueError('maximum video duration is 600 seconds')
    return plan

def run(command, log):
    # Keep the latest 1–2 MiB, including current output, without unbounded RAM/log growth.
    with Path(log).open('w+b') as stream:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
            while chunk := process.stdout.read1(65536):
                stream.write(chunk)
                if stream.tell() > 2*1024*1024:
                    stream.seek(-1024*1024, 2)
                    tail = stream.read()
                    stream.seek(0)
                    stream.truncate()
                    stream.write(tail)
                stream.flush()
            code = process.wait()
    if code:
        raise RuntimeError(f'Command failed ({code}); inspect {log}. Re-run the same command to resume.')

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

def fingerprint(plan, song, vocals, preview, soundtrack=None, settings=None):
    digest = hashlib.sha256()
    digest.update(json.dumps({'plan': plan, 'preview': preview, 'settings': settings}, sort_keys=True).encode())
    for path in [ROOT / 'video.py', ROOT / 'audio.py', ROOT / 'blender_scene.py', ROOT / 'scenes.py', ROOT / 'characters.py', ROOT / 'third_party/anim_studio/rig.py', song] + ([vocals] if vocals else []) + ([soundtrack] if soundtrack else []):
        digest.update(Path(path).read_bytes())
    for scene in plan.get('scenes', []):
        for character in scene.get('characters', []):
            with Path(character['model']).open('rb') as model:
                for chunk in iter(lambda: model.read(1024*1024), b''):
                    digest.update(chunk)
    return digest.hexdigest()


def render_settings(args, plan):
    mode = getattr(args, 'mode', 'legacy')
    orientation = getattr(args, 'orientation', None) or plan.get('orientation', 'portrait')
    if mode not in ('legacy', 'lite', 'quality') or orientation not in ('portrait', 'landscape'):
        raise ValueError('invalid rendering mode or orientation')
    engine = getattr(args, 'engine', 'cycles')
    if engine not in ('cycles', 'eevee'):
        raise ValueError('invalid render engine')
    fps = 12 if args.preview or mode == 'lite' else 24
    width, height = (256, 456) if args.preview else (360, 640) if mode == 'lite' else (1080, 1920) if mode == 'quality' else (540, 960)
    if orientation == 'landscape':
        width, height = height, width
    custom_width, custom_height = getattr(args, 'width', None), getattr(args, 'height', None)
    if (custom_width is None) != (custom_height is None):
        raise ValueError('Set both --width and --height.')
    if custom_width is not None:
        width, height = custom_width, custom_height
    if getattr(args, 'fps', None) is not None:
        fps = args.fps
    if any(type(n) is not int or n < 64 or n > 1920 or n % 2 for n in (width, height)) or width*height > 2073600:
        raise ValueError('Use even dimensions from 64 to 1920, up to 1080p pixels.')
    if type(fps) is not int or not 2 <= fps <= 30:
        raise ValueError('fps must be 2–30')
    if (orientation == 'portrait') != (width < height):
        raise ValueError('Dimensions must match the selected orientation.')
    tool_files = {}
    for name in (args.blender,'ffmpeg'):
        binary = shutil.which(name)
        if binary:
            stat = Path(binary).stat()
            tool_files[str(Path(binary).resolve())] = [stat.st_size,stat.st_mtime_ns]
    return dict(mode=mode, engine=engine, denoise=mode != 'lite', fps=fps, width=width, height=height,
                samples=8 if mode == 'lite' else 32 if args.preview else 64,
                blender=str(Path(shutil.which(args.blender) or args.blender).resolve()), tool_files=tool_files)

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
    # Cross-process guard also covers dashboard and queue workers using this runner.
    with Path(f'/tmp/toon-pilot-render-{os.getuid()}.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Another Toon Pilot render is active; retry after it finishes.') from exc
        return _create(args)


def _create(args):
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
    settings = render_settings(args, plan)
    job_key = fingerprint(plan, Path(args.song), Path(args.vocals) if args.vocals else None, args.preview, soundtrack_input, settings)
    folder = Path(args.out).resolve() / ('preview' if args.preview else 'full') / job_key[:16]
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / '.running'
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError(f'Job lock exists: {lock}. If no render is running, remove this lock and retry.')
    os.close(descriptor)
    manifest_path = folder / 'status.json'
    started = time.monotonic()
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
        fps, width, height, samples = (settings[k] for k in ('fps', 'width', 'height', 'samples'))
        scenes = [dict(plan['scenes'][0], seconds=min(2, plan['scenes'][0]['seconds']))] if args.preview else plan['scenes']
        durations = [round(s['seconds'] * fps) / fps for s in scenes]
        caption_count = scene_files.write_captions(scenes, durations, folder / 'captions.srt')
        for index, (scene, seconds) in enumerate(zip(scenes, durations)):
            work = folder / f'scene-{index:02d}'
            work.mkdir(exist_ok=True)
            clip = work / 'clip.mp4'
            frames = round(seconds * fps)
            config = dict(scene, frames=frames, fps=fps, width=width, height=height, samples=samples,
                          directory=str(work), threads=args.threads, engine=settings['engine'], denoise=settings['denoise'])
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
                fade = ['-vf', f'fade=t=in:st=0:d=0.2,fade=t=out:st={max(0, seconds-.2)}:d=0.2'] if scene.get('transition') == 'fade' else []
                run(['ffmpeg', '-y', '-v', 'error', '-xerror', '-framerate', str(fps), '-i', str(work / '%05d.png'),
                     '-frames:v', str(frames), *fade, '-c:v', 'libx264', '-threads', str(args.threads), '-pix_fmt', 'yuv420p', str(clip)], work / 'encode.log')
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
        final_streams = probe(temporary)['streams']
        picture = next(s for s in final_streams if s['codec_type'] == 'video')
        if (picture['width'], picture['height'], picture['codec_name']) != (width, height, 'h264'):
            raise ValueError('unexpected final dimensions or video codec')
        run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(temporary), '-map', '0:a:0', '-f', 'null', '-'], folder/'verify-audio.log')
        temporary.replace(destination)
        run(['ffmpeg', '-y', '-v', 'error', '-i', str(destination), '-frames:v', '1', str(folder/'thumbnail.jpg')], folder/'thumbnail.log')
        manifest.update(status='verified_media_needs_human_review', output=str(destination),
                        seconds=sum(durations), captions=caption_count, finished=time.time(),
                        settings=settings, elapsed_seconds=time.monotonic()-started,
                        max_child_peak_rss_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f'Created: {destination}\nAudio: {"imported complete song; vocals unverified" if soundtrack_input else "imported vocals" if args.vocals else "instrumental only, no singing"}. Review animation and sound before publishing.')
        return manifest
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
    new.add_argument('--mode', choices=['legacy', 'lite', 'quality'], default='legacy')
    new.add_argument('--engine', choices=['cycles', 'eevee'], default='cycles', help='Eevee requires a working graphics/EGL driver; no automatic fallback')
    new.add_argument('--orientation', choices=['portrait', 'landscape'])
    new.add_argument('--width', type=int)
    new.add_argument('--height', type=int)
    new.add_argument('--fps', type=int)
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

