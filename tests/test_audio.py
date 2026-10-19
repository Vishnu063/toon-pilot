import array
import json
from pathlib import Path
import tempfile
import unittest
import wave
import audio

class AudioTests(unittest.TestCase):
    def test_sample_duration_and_ust(self):
        with tempfile.TemporaryDirectory() as folder:
            audio.prepare('examples/happy_feet.json', folder)
            with wave.open(str(Path(folder) / 'backing.wav')) as wav:
                self.assertEqual(wav.getnframes(), 32 * audio.RATE)
            ust = (Path(folder) / 'singing.ust').read_text()
            self.assertIn('[#TRACKEND]', ust)
            self.assertEqual(ust.count('Lyric='), 32)

    def test_invalid_tempo_and_injected_lyric(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'song.json'
            for bpm, lyric in [(0, 'hi'), (60, 'hi\n[#SETTING]')]:
                path.write_text(json.dumps({'bpm': bpm, 'notes': [{'lyric': lyric, 'pitch': 60, 'ticks': 480}]}))
                with self.assertRaises(ValueError):
                    audio.load_song(path)

    def test_mismatch_silence_and_format_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            v, b, out = [Path(folder) / n for n in ('v.wav', 'b.wav', 'out.wav')]
            audio.write_wav(v, array.array('h', [100] * audio.RATE))
            audio.write_wav(b, array.array('h', [100] * (audio.RATE * 3)))
            with self.assertRaisesRegex(ValueError, 'duration mismatch'):
                audio.mix(v, b, out)
            audio.write_wav(v, array.array('h', [0] * (audio.RATE * 3)))
            with self.assertRaisesRegex(ValueError, 'silent'):
                audio.mix(v, b, out)
            with wave.open(str(v), 'wb') as wav:
                wav.setparams((2, 2, audio.RATE, 0, 'NONE', ''))
                wav.writeframes(b'\x00' * 8)
            with self.assertRaisesRegex(ValueError, 'mono'):
                audio.read_wav(v)

    def test_mix_limits_peak_and_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            v, b, out = [Path(folder) / n for n in ('v.wav', 'b.wav', 'out.wav')]
            for path in (v, b):
                audio.write_wav(path, array.array('h', [32767, -32768] * 100))
            before = v.read_bytes()
            audio.mix(v, b, out)
            self.assertLessEqual(max(abs(x) for x in audio.read_wav(out)), 30000)
            self.assertEqual(v.read_bytes(), before)
            with self.assertRaises(ValueError):
                audio.mix(v, b, v)

if __name__ == '__main__':
    unittest.main()
