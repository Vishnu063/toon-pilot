"""Small offline audio preparation tool. Does not synthesize singing."""
import argparse
import array
import json
import math
from pathlib import Path
import sys
import wave

RATE = 22050

def load_song(path):
    song = json.loads(Path(path).read_text(encoding='utf-8'))
    bpm = song['bpm']
    notes = song['notes']
    if isinstance(bpm, bool) or not isinstance(bpm, (int, float)) or not 40 <= bpm <= 240:
        raise ValueError('bpm must be between 40 and 240')
    if not notes:
        raise ValueError('song needs notes')
    for note in notes:
        if not isinstance(note['lyric'], str) or not note['lyric'] or any(c in note['lyric'] for c in '\r\n'):
            raise ValueError('each lyric must be a nonempty single line')
        if type(note['pitch']) is not int or not 0 <= note['pitch'] <= 127:
            raise ValueError('pitch must be a MIDI integer from 0 to 127')
        if type(note['ticks']) is not int or note['ticks'] <= 0:
            raise ValueError('ticks must be a positive integer')
    seconds = sum(n['ticks'] for n in notes) / 480 * 60 / bpm
    if seconds > 600:
        raise ValueError('maximum song duration is 600 seconds')
    return song, seconds

def write_wav(path, samples):
    if sys.byteorder != 'little':
        samples.byteswap()
    with wave.open(str(path), 'wb') as out:
        out.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        out.writeframes(samples.tobytes())

def prepare(song_path, output):
    song, seconds = load_song(song_path)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # UST 1.2 uses Shift-JIS; this starter deliberately accepts ASCII English lyrics.
    lines = ['[#VERSION]', 'UST Version1.2', '[#SETTING]', f"Tempo={song['bpm']}",
             'Tracks=1', 'ProjectName=Toon Pilot', 'Mode2=True']
    for i, note in enumerate(song['notes']):
        lines += [f'[#{i:04d}]', f"Length={note['ticks']}", f"Lyric={note['lyric']}",
                  f"NoteNum={note['pitch']}", 'Intensity=100', 'Modulation=0']
    lines += ['[#TRACKEND]']
    ust = ('\n'.join(lines) + '\n').encode('ascii')
    samples = array.array('h')
    # Quiet procedural bell-like backing; no downloaded music or model required.
    for i in range(round(seconds * RATE)):
        t = i / RATE
        beat = t * song['bpm'] / 60
        step = int(beat)
        phase = (beat - step) * 60 / song['bpm']
        pitch = [60, 64, 67, 64][step % 4]
        hz = 440 * 2 ** ((pitch - 69) / 12)
        envelope = min(1, phase / .01) * math.exp(-5 * phase)
        samples.append(round(2200 * envelope * math.sin(2 * math.pi * hz * phase)))
    (output / 'singing.ust').write_bytes(ust)
    write_wav(output / 'backing.wav', samples)
    (output / 'timing.json').write_text(json.dumps({'duration_seconds': seconds,
        'bpm': song['bpm'], 'status': 'prepared_not_sung'}, indent=2) + '\n')
    print(f'Prepared {seconds:.2f}s: singing.ust, backing.wav, timing.json. Vocals still required.')

def read_wav(path):
    with wave.open(str(path), 'rb') as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, 2, RATE, 'NONE'):
            raise ValueError('WAV must be mono, 16-bit PCM, 22050 Hz; see README conversion command')
        if source.getnframes() > RATE * 600:
            raise ValueError('maximum audio duration is 600 seconds')
        samples = array.array('h', source.readframes(source.getnframes()))
    if sys.byteorder != 'little':
        samples.byteswap()
    if not samples:
        raise ValueError('audio is empty')
    return samples

def mix(vocals, backing, output):
    if Path(output).resolve() in (Path(vocals).resolve(), Path(backing).resolve()):
        raise ValueError('output must differ from input files')
    voice, music = read_wav(vocals), read_wav(backing)
    if abs(len(voice) - len(music)) > RATE:
        raise ValueError('duration mismatch exceeds 1 second; align vocals to the song timeline')
    if not any(voice):
        raise ValueError('vocal file is silent')
    result = [int((voice[i] if i < len(voice) else 0) * .85 +
                  (music[i] if i < len(music) else 0) * .5)
              for i in range(max(len(voice), len(music)))]
    peak = max(abs(n) for n in result)
    gain = min(1, 30000 / max(1, peak))
    write_wav(output, array.array('h', (round(n * gain) for n in result)))
    print(f'Mixed {len(result) / RATE:.2f}s into {output}; listen before publishing.')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('song')
    prep.add_argument('--out', default='output/audio')
    mixer = commands.add_parser('mix')
    mixer.add_argument('--vocals', required=True)
    mixer.add_argument('--backing', required=True)
    mixer.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            prepare(args.song, args.out)
        else:
            mix(args.vocals, args.backing, args.out)
    except (ValueError, KeyError, OSError, UnicodeError, wave.Error, TypeError) as exc:
        parser.exit(1, f'Audio failed: {exc}\n')

if __name__ == '__main__':
    main()
