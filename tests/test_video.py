import argparse
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import video

class VideoTests(unittest.TestCase):
    def test_plan_rejects_unknown_actions_and_invalid_lengths(self):
        for scene in [dict(seconds=0, action='dance', camera='arc'),
                      dict(seconds=8, action='fly', camera='arc'),
                      dict(seconds=float('nan'), action='dance', camera='arc')]:
            with self.assertRaises(ValueError):
                video.validate_plan({'scenes': [scene]})
        self.assertEqual(len(video.validate_plan(json.loads((video.ROOT/'examples/video.json').read_text()))['scenes']), 4)

    def test_fingerprint_changes_for_audio_and_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            song = Path(folder)/'song.json'
            song.write_text('one')
            first = video.fingerprint({}, song, None, True)
            song.write_text('two')
            self.assertNotEqual(first, video.fingerprint({}, song, None, True))
            self.assertNotEqual(first, video.fingerprint({'scenes': []}, song, None, True))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires ffmpeg/ffprobe')
    def test_real_media_pipeline_failure_resume_and_reuse_with_fixture_renderer(self):
        # This checks actual FFmpeg assembly/decoding, not Blender's visual quality.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            launcher = root/'fixture-blender'
            launcher.write_text('''#!/usr/bin/env python3
import json, pathlib, struct, sys, zlib
config=json.loads(pathlib.Path(sys.argv[-1]).read_text())
directory=pathlib.Path(config['directory'])
marker=directory/'attempts'
count=int(marker.read_text())+1 if marker.exists() else 1
marker.write_text(str(count))
w,h=config['width'],config['height']
def chunk(tag,data):
    return struct.pack('!I',len(data))+tag+data+struct.pack('!I',zlib.crc32(tag+data)&0xffffffff)
png=b'\\x89PNG\\r\\n\\x1a\\n'+chunk(b'IHDR',struct.pack('!2I5B',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\\0'+bytes([120,180,100])*w)*h))+chunk(b'IEND',b'')
for i in range(1,config['frames']+1):
    path=directory/f'{i:05d}.png'
    if not path.exists(): path.write_bytes(png)
    if count==1: sys.exit(7)
''')
            launcher.chmod(0o755)
            args=argparse.Namespace(plan=str(video.ROOT/'examples/video.json'),song=str(video.ROOT/'examples/happy_feet.json'),
                out=str(root/'output'), preview=True, vocals=None, instrumental=False, blender=str(launcher), threads=1)
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    video.create(args)
                statuses=list((root/'output').rglob('status.json'))
                self.assertEqual(json.loads(statuses[0].read_text())['status'], 'failed')
                self.assertFalse(list((root/'output').rglob('.running')))
                video.create(args)
                output=list((root/'output').rglob('preview.mp4'))[0]
                self.assertEqual({s['codec_type'] for s in video.probe(output)['streams']}, {'video','audio'})
                self.assertAlmostEqual(float(video.probe(output)['format']['duration']),2,delta=.15)
                video.create(args)
                self.assertTrue(json.loads(statuses[0].read_text())['scenes'][0]['reused'])
                self.assertEqual(list((root/'output').rglob('attempts'))[0].read_text(),'2')

if __name__ == '__main__':
    unittest.main()
