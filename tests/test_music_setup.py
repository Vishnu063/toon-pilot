"""Installer/launcher control-flow tests; never install packages or run a model."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MusicSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root/'ACE Step'
        (self.install/'.git').mkdir(parents=True)
        self.bin = self.root/'bin'
        self.bin.mkdir()
        revision = re.search(r'^revision=(\w+)', (ROOT/'scripts/install-music.sh').read_text(), re.M)[1]
        self.env = dict(os.environ, TOON_MUSIC_DIR=str(self.install), TEST_REV=revision,
                        PATH=str(self.bin)+os.pathsep+os.environ['PATH'])
        self.command('git', '''#!/bin/sh
case "$3" in
 remote) echo https://github.com/ace-step/ACE-Step-1.5.git ;;
 status) if [ "${TEST_DIRTY:-0}" = 1 ]; then echo ' M source.py'; fi ;;
 rev-parse) echo "$TEST_REV" ;;
 *) exit 90 ;;
esac
''')
        self.command('uv', '''#!/bin/sh
echo "$*" >> "$TOON_MUSIC_DIR/uv-calls"
if [ "${TEST_UV_FAIL:-0}" = 1 ]; then exit 42; fi
if [ "$1" = sync ]; then
 mkdir -p .venv/bin
 printf '#!/bin/sh\necho "$ACESTEP_DEVICE $ACESTEP_INIT_LLM $ACESTEP_API_HOST $ACESTEP_QUEUE_WORKERS" > started\n' > .venv/bin/acestep-api
 chmod +x .venv/bin/acestep-api
fi
''')
        # Deterministic disk preflight, independent of CI free space. This is a
        # fixture only: the production script uses real shutil.disk_usage.
        self.command('python3', '#!/bin/sh\ncat >/dev/null\nexit "${TEST_DISK_FAIL:-0}"\n')

    def command(self, name, source):
        path = self.bin/name
        path.write_text(source)
        path.chmod(0o755)

    def run_script(self, name, *args):
        return subprocess.run(['bash', str(ROOT/'scripts'/name), *args], env=self.env,
                              text=True, capture_output=True)

    def test_install_downloads_without_starting_then_cpu_launcher(self):
        result = self.run_script('install-music.sh', '--download-models')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.install/'.toon-pilot-installed').exists())
        calls = (self.install/'uv-calls').read_text()
        self.assertIn('sync --locked --python 3.12 --no-dev', calls)
        self.assertIn('run --no-sync acestep-download', calls)
        self.assertFalse((self.install/'started').exists())
        result = self.run_script('start-music.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.install/'started').read_text().strip(), 'cpu false 127.0.0.1 1')

    def test_dependency_failure_does_not_mark_install_complete(self):
        self.env['TEST_UV_FAIL'] = '1'
        result = self.run_script('install-music.sh')
        self.assertEqual(result.returncode, 42)
        self.assertFalse((self.install/'.toon-pilot-installed').exists())
        self.assertNotEqual(self.run_script('start-music.sh').returncode, 0)

    def test_dirty_source_and_low_disk_stop_before_dependency_download(self):
        self.env['TEST_DIRTY'] = '1'
        self.assertNotEqual(self.run_script('install-music.sh').returncode, 0)
        self.assertFalse((self.install/'uv-calls').exists())
        self.env['TEST_DIRTY'] = '0'
        self.env['TEST_DISK_FAIL'] = '1'
        self.assertNotEqual(self.run_script('install-music.sh').returncode, 0)
        self.assertFalse((self.install/'uv-calls').exists())

    def test_check_only_has_no_install_side_effects(self):
        self.assertEqual(self.run_script('install-music.sh', '--check').returncode, 0)
        self.assertFalse((self.install/'uv-calls').exists())
        self.assertFalse((self.install/'.toon-pilot-installed').exists())


if __name__ == '__main__':
    unittest.main()
