"""Inspect local resources; never download models or select a paid backend."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


def inspect():
    gpus = []
    if shutil.which('nvidia-smi'):
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=10, check=True)
            for line in result.stdout.splitlines():
                name, memory = line.rsplit(',', 1)
                gpus.append(dict(name=name.strip(), vram_mib=int(memory.strip())))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    memory = {}
    if Path('/proc/meminfo').exists():
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith(('MemTotal:', 'MemAvailable:')):
                key, value, *_ = line.split()
                memory[key.rstrip(':')+'_kib'] = int(value)
    return dict(cpu_count=os.cpu_count(), memory=memory, disk_free_bytes=shutil.disk_usage('.').free,
                gpus=gpus, ai_video='not_implemented', default_backend='blender-cpu',
                reason='Wan/FramePack/AnimateDiff/ComfyUI inference adapters are not installed or validated. Use Blender; no model is automatically downloaded.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(inspect(), indent=2))
