import argparse
import array
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import audio
import characters
import narration
import planner
import production
import video
import youtube_upload
import stories


class PlanningTests(unittest.TestCase):
    def test_all_words_duration_format_and_character_identity(self):
        text = 'Milo waves hello. Pip hops along. Both dance and share a happy day.'
        for seconds in (30, 60, 120):
            plan = planner.plan('Hello', text, seconds, cast=['pip'], orientation='landscape')
            self.assertEqual(sum(s['seconds'] for s in plan['scenes']), seconds)
            self.assertEqual(' '.join(s['dialogue'] for s in plan['scenes']), text)
            self.assertTrue(all(s['original_characters'] == ['pip'] for s in plan['scenes']))
            self.assertEqual(plan['character_versions'], {'pip': 1})
            video.validate_plan(plan)

    def test_invalid_plans_and_character_inputs(self):
        for kwargs in (dict(duration=31), dict(duration=True), dict(language='xx'), dict(cast=[]), dict(cast=['milo','milo']), dict(cast=['unknown'])):
            with self.assertRaises(ValueError):
                planner.plan('Hello', 'Hello friend', **kwargs)
        copy = characters.select(['milo'])
        copy[0]['animations'].clear()
        self.assertTrue(characters.select(['milo'])[0]['animations'])

    def test_settings_and_cache_identity(self):
        args = argparse.Namespace(preview=False, blender='blender', mode='lite', orientation='landscape')
        settings = video.render_settings(args, {})
        self.assertEqual((settings['width'],settings['height']), (640,360))
        self.assertFalse(settings['denoise'])
        args.width, args.height = 181, 320
        with self.assertRaises(ValueError): video.render_settings(args,{})
        with tempfile.TemporaryDirectory() as folder:
            score = Path(folder)/'score'
            score.write_text('test')
            self.assertNotEqual(video.fingerprint({},score,None,True,settings={'mode':'lite'}),
                                video.fingerprint({},score,None,True,settings={'mode':'quality'}))

    def test_original_daily_templates_are_repeatable_and_explicitly_finite(self):
        first = stories.for_day('2026-10-24')
        self.assertEqual(first,stories.for_day('2026-10-24'))
        self.assertNotEqual(first['text'],stories.for_day('2026-10-25')['text'])
        self.assertEqual(first['text'],stories.for_day('2026-10-27')['text'])
        self.assertEqual(stories.for_day('2026-10-24','hi')['language'],'hi')


class NarrationTests(unittest.TestCase):
    def test_missing_engine_and_language_mismatch_never_create_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'voice.wav'
            plan = planner.plan('Hello','Hello friend.')
            with self.assertRaises(ValueError): narration.synthesize(plan,target,executable='missing-toon-speech-engine')
            with self.assertRaises(ValueError): narration.synthesize(plan,target,voice='hi-boy')
            self.assertFalse(target.exists())

    @unittest.skipUnless(shutil.which('espeak-ng'), 'requires installed eSpeak NG')
    def test_real_english_and_hindi_speech_and_overflow(self):
        with tempfile.TemporaryDirectory() as folder:
            for lang, text in [('en','Hello Milo. Hello Pip.'), ('hi','नमस्ते। हम साथ खेलते हैं।')]:
                plan = planner.plan('Hello',text,language=lang)
                target = Path(folder)/(lang+'.wav')
                report = narration.synthesize(plan,target,voice=lang+'-boy')
                self.assertEqual(report['kind'], 'spoken_narration_not_singing')
                self.assertAlmostEqual(report['seconds'],30,places=3)
                self.assertGreater(report['rms'],10)
                self.assertLess(report['peak'],32767)
                self.assertTrue(all(s['speech_seconds']>0 for s in report['segments']))
                with self.assertRaises(ValueError): narration.synthesize(plan,target,voice=lang+'-boy')
            dense = dict(language='en',scenes=[dict(seconds=.5,dialogue='A long sentence cannot fit into half a second without cutting off the words.')])
            with self.assertRaisesRegex(ValueError,'shorten'):
                narration.synthesize(dense,Path(folder)/'overflow.wav')
            self.assertFalse((Path(folder)/'overflow.wav').exists())


class QueueTests(unittest.TestCase):
    def test_scheduled_private_upload_requires_both_opt_ins(self):
        with tempfile.TemporaryDirectory() as folder:
            queue=production.Queue(folder)
            self.addCleanup(queue.close)
            request=dict(title='Hello',text='Hello Milo. Hello Pip.',duration=30,upload_private=True)
            queue.enqueue(request)
            def voice(plan,destination,**kwargs):
                audio.write_wav(destination,array.array('h',[300,-300])*(15*audio.RATE))
            result=dict(status='verified_media_needs_human_review',output=str(Path(folder)/'fixture.mp4'))
            with patch('production.narration.synthesize',side_effect=voice), patch('production.video.create',return_value=result), patch('youtube_upload.upload') as upload:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(queue.worker(),0)
                    self.assertEqual(queue.rows()[0]['stage'],'upload')
                    upload.assert_not_called()
                    queue.enqueue(dict(request,text='A different story.'))
                    self.assertEqual(queue.worker(allow_private_upload=True),0)
                self.assertEqual(upload.call_count,1)
                self.assertIn('uploaded_private',[r['status'] for r in queue.rows()])

    def test_durable_enqueue_failure_retry_and_completed_audio_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = production.Queue(folder)
            request = dict(title='Hello', text='Hello Milo. Hello Pip.',duration=30)
            identifier = queue.enqueue(request)
            self.assertEqual(identifier, queue.enqueue(request))
            queue.close()
            queue = production.Queue(folder)
            self.addCleanup(queue.close)
            def voice(plan,destination,**kwargs):
                audio.write_wav(destination,array.array('h',[300,-300])*(15*audio.RATE))
            with patch('production.narration.synthesize', side_effect=voice) as speech, patch('production.video.create', side_effect=RuntimeError('render fixture failure')):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(queue.worker(),1)
                    self.assertEqual(queue.rows()[0]['stage'],'render')
                    self.assertEqual(queue.rows()[0]['status'],'failed')
                    self.assertEqual(queue.worker(),0)  # failed jobs do not loop
                    queue.retry(identifier)
                    self.assertEqual(queue.worker(),1)
                self.assertEqual(speech.call_count,1)
            with self.assertRaises(ValueError): queue.retry('unknown')
            queue.enqueue(request,key='daily:2026-10-24')
            with self.assertRaises(ValueError): queue.enqueue(dict(request,title='Different'),key='daily:2026-10-24')


class YouTubeTests(unittest.TestCase):
    def fixture(self, folder, lost=False):
        movie=Path(folder)/'video.mp4';movie.write_bytes(b'fixture-media-not-a-real-mp4')
        class Request:
            def next_chunk(self,**kwargs):
                if lost: raise OSError('fixture lost response')
                return None, {'id':'fixture-video-id'}
        class API:
            calls=0
            body=None
            def videos(self): return self
            def insert(self,**kwargs):
                self.calls+=1;self.body=kwargs['body'];return Request()
        return movie, API()

    def test_private_upload_and_repeat_do_not_resubmit(self):
        with tempfile.TemporaryDirectory() as folder:
            movie,api=self.fixture(folder)
            receipt=Path(folder)/'receipt.json'
            with patch('video.probe',return_value={'format':{'duration':'2'},'streams':[{'codec_type':'video'},{'codec_type':'audio'}]}), patch('video.verify_video'):
                first=youtube_upload.upload(movie,receipt,'unused','Hello','Original story',api=api,media_factory=lambda *a,**k:object())
                self.assertEqual(api.body['status'],dict(privacyStatus='private',selfDeclaredMadeForKids=True))
                again=youtube_upload.upload(movie,receipt,'unused','Hello','Original story',api=api)
                self.assertEqual(first,again)
                self.assertEqual(api.calls,1)
                self.assertEqual(receipt.stat().st_mode & 0o777,0o600)

    def test_lost_response_blocks_duplicate_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            movie,api=self.fixture(folder,lost=True)
            receipt=Path(folder)/'receipt.json'
            with patch('video.probe',return_value={'format':{'duration':'2'},'streams':[{'codec_type':'video'},{'codec_type':'audio'}]}), patch('video.verify_video'):
                with self.assertRaisesRegex(ValueError,'failed'):
                    youtube_upload.upload(movie,receipt,'unused','Hello','Original',api=api,media_factory=lambda *a,**k:object())
                with self.assertRaisesRegex(ValueError,'uncertain'):
                    youtube_upload.upload(movie,receipt,'unused','Hello','Original',api=api)
                self.assertEqual(api.calls,1)


if __name__ == '__main__':
    unittest.main()
