import json
from pathlib import Path
import tempfile
import unittest
import scenes
import video

class SceneTests(unittest.TestCase):
    def test_yaml_and_json_match(self):
        plan=scenes.load_plan(video.ROOT/'examples/happy_feet.scene.yaml')
        self.assertEqual(len(video.validate_plan(plan)['scenes']),4)
        self.assertEqual(sum(s['seconds'] for s in plan['scenes']),32)

    def test_missing_model_and_unknown_character_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scene.json'
            for plan in [dict(cast={},scenes=[dict(characters=['missing'])]),
                         dict(cast={'kid':dict(model='missing.glb',clip='Wave')},scenes=[dict(characters=['kid'])])]:
                path.write_text(json.dumps(plan))
                with self.assertRaises(ValueError): scenes.load_plan(path)

    def test_resolves_model_relative_to_scene_and_fingerprints_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); model=root/'kid.glb';model.write_bytes(b'fixture')
            path=root/'scene.json'
            path.write_text(json.dumps(dict(cast={'kid':dict(model='kid.glb',clip='Wave')},scenes=[dict(characters=['kid'])])))
            plan=scenes.load_plan(path)
            self.assertEqual(plan['scenes'][0]['characters'][0]['model'],str(model))
            score=video.ROOT/'examples/happy_feet.json'
            first=video.fingerprint(plan,score,None,True)
            model.write_bytes(b'changed fixture')
            self.assertNotEqual(first,video.fingerprint(plan,score,None,True))

    def test_caption_timing_skips_empty_and_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'captions.srt'
            self.assertEqual(scenes.write_captions([{'caption':'Hello'},{},{'caption':'Goodbye'}],[2,1,.5],path),2)
            self.assertIn('00:00:03,000 --> 00:00:03,500',path.read_text())
            self.assertNotIn('00:00:02,000 --> 00:00:03,000',path.read_text())
            with self.assertRaises(ValueError): scenes.write_captions([{'caption':'bad --> cue'}],[2],path)

if __name__=='__main__':unittest.main()
