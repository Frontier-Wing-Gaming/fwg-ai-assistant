#!/usr/bin/env python3
"""Conservative checks on tracked source files; not a complete secret scanner."""
from pathlib import Path
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parent.parent
paths=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
patterns=[r'https://(?:discord(?:app)?\.com)/api/webhooks/[0-9]+/[A-Za-z0-9_-]+',
          r'\bgh[pousr]_[A-Za-z0-9]{20,}',r'\bgithub_pat_[A-Za-z0-9_]{20,}',
          r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'\bAKIA[A-Z0-9]{16}\b',
          r'\bptlc_[A-Za-z0-9]{20,}']
bad=[]
for name in paths:
    if not name:continue
    path=ROOT/name
    if path.is_symlink():bad.append((name,'symlink'));continue
    if (path.name.startswith('.env') and path.name!='.env.example') or path.name in {'users.json','servers.json','config.json','state.json','softphone-settings.txt'}:
        bad.append((name,'runtime configuration'));continue
    if path.suffix in {'.wav','.sqlite','.onnx','.zip','.pyc','.jsonl'} or any(part in {'backups','__pycache__','.venv'} for part in path.parts):
        bad.append((name,'runtime/binary artifact'));continue
    text=path.read_text()
    if any(re.search(pattern,text) for pattern in patterns):bad.append((name,'possible credential'))
if bad:
    for name,reason in bad:print(name+': '+reason)
    raise SystemExit(1)
print('Tracked-source checks passed. Review unknown secrets manually before publication.')
