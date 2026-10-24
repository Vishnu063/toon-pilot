"""Offline eSpeak NG/Piper narration, explicitly separate from singing."""
import argparse
import array
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave

import audio

VOICES = {f'{lang}-{style}': dict(language=lang, espeak=f'{lang}+{variant}')
          for lang in ('en', 'hi') for style, variant in (('boy', 'm3'), ('girl', 'f3'))}


def check_audio(path):
    samples = audio.read_wav(path)
    peak = max(abs(n) for n in samples)
    if peak < 100:
        raise ValueError('Narration is silent or too quiet.')
    if peak >= 32767:
        raise ValueError('Narration is clipped.')
    return dict(seconds=len(samples)/audio.RATE, peak=peak,
                rms=(sum(n*n for n in samples)/len(samples))**.5)


def synthesize(plan, destination, voice='en-boy', engine='espeak-ng', model=None, executable=None):
    if voice not in VOICES or engine not in ('espeak-ng', 'piper'):
        raise ValueError('Unknown narration voice or engine.')
    if VOICES[voice]['language'] != plan.get('language', 'en'):
        raise ValueError('Voice language must match the story language.')
    executable = executable or engine
    if not shutil.which(executable):
        raise ValueError(f'{engine} is missing; install it first. No instrumental substitute will be used.')
    if engine == 'piper' and (not model or not Path(model).is_file() or not Path(str(model)+'.json').is_file()):
        raise ValueError('Piper needs a licensed local .onnx model and its .onnx.json config. No models are downloaded automatically.')
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Narration output already exists; choose a new output or reuse its checkpoint.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = array.array('h')
    segments = []
    with tempfile.TemporaryDirectory(prefix='toon-narration-') as temp:
        temp = Path(temp)
        for i, scene in enumerate(plan['scenes']):
            text = scene.get('dialogue', scene.get('caption', ''))
            if not isinstance(text, str) or not text.strip() or len(text) > 1000 or '\x00' in text:
                raise ValueError('Each scene needs spoken text of 1–1000 characters.')
            raw, normalized = temp/'raw.wav', temp/'normalized.wav'
            if engine == 'espeak-ng':
                # Stable character variants; voice names describe synthetic timbres, not real children.
                selected = voice
                if scene.get('speaker') == 'pip':
                    selected = VOICES[voice]['language']+'-girl'
                elif scene.get('speaker') == 'milo':
                    selected = VOICES[voice]['language']+'-boy'
                command = [executable, '-v', VOICES[selected]['espeak'], '-s', '145', '-w', str(raw), '--stdin']
            else:
                command = [executable, '--model', str(model), '--output_file', str(raw)]
            subprocess.run(command, input=text+'\n', text=True, check=True, capture_output=True, timeout=120)
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(raw), '-ar', str(audio.RATE), '-ac', '1',
                '-af', 'alimiter=limit=0.9:level=false', '-c:a', 'pcm_s16le', str(normalized)],
                check=True, capture_output=True, timeout=120)
            measured = check_audio(normalized)
            samples = audio.read_wav(normalized)
            available = round(scene['seconds']*audio.RATE)
            # Never truncate words or silently speed up speech to fit a dense script.
            if len(samples) > available - round(.15*audio.RATE):
                raise ValueError(f'Scene {i+1} narration takes {measured["seconds"]:.2f}s; shorten the text or increase scene duration ({scene["seconds"]}s).')
            segments.append(dict(scene=i, speech_seconds=measured['seconds'], timeline_start=len(result)/audio.RATE))
            result.extend(samples)
            result.extend(array.array('h', [0])*(available-len(samples)))
        temporary = temp/'final.wav'
        audio.write_wav(temporary, result)
        quality = check_audio(temporary)
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.narration-', suffix='.wav', delete=False) as local:
            local_path = Path(local.name)
        try:
            shutil.copyfile(temporary, local_path)
            local_path.replace(destination)
        finally:
            local_path.unlink(missing_ok=True)
    report = dict(kind='spoken_narration_not_singing', engine=engine, voice=voice,
                  segments=segments, **quality)
    destination.with_suffix('.audio.json').write_text(json.dumps(report, indent=2))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--voice', choices=VOICES, default='en-boy')
    p.add_argument('--engine', choices=['espeak-ng', 'piper'], default='espeak-ng')
    p.add_argument('--model')
    p.add_argument('--executable')
    args = p.parse_args()
    try:
        print(json.dumps(synthesize(json.loads(Path(args.plan).read_text()), args.out, args.voice,
                                    args.engine, args.model, args.executable), indent=2))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        p.exit(1, f'Narration failed: {exc}\n')


if __name__ == '__main__':
    main()
