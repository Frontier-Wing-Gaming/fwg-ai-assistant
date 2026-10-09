#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import venv

SOURCE=Path(__file__).resolve().parent
TAG='# FWG_CALLSHIELD'
HOOK=''' ; FWG CALLSHIELD BEGIN
 same => n,AGI(/etc/asterisk/fwg-callshield/lookup.py,${FWG_CID})
 same => n,ExecIf($["${FWG_CS_RESULT}"="REPORT"]?Log(NOTICE,FWG CallShield report caller=${FWG_CID}))
 same => n,ExecIf($["${FWG_CS_RESULT}"="BLOCK"]?Log(NOTICE,FWG CallShield blocked caller=${FWG_CID}))
 same => n,ExecIf($["${FWG_CS_RESULT}"="UNAVAILABLE"]?Log(NOTICE,FWG CallShield unavailable - normal screening retained))
 same => n,GotoIf($["${FWG_CS_RESULT}"="BLOCK"]?blocked)
 ; FWG CALLSHIELD END
'''

def patch_dialplan(text):
    if 'FWG CALLSHIELD BEGIN' in text:raise ValueError('CallShield hook already installed')
    if '[fwg-public-main]' not in text:raise ValueError('Install public phone routing first')
    before,body=text.split('[fwg-public-main]',1)
    if '\n[' in body:raise ValueError('Unexpected extra contexts after incoming route')
    needle=' same => n,Answer()'
    if body.count(needle)!=1 or '?admin)' not in body or 'Read(FWG_SCREEN,' not in body:
        raise ValueError('Unexpected incoming route; no changes made')
    if body.index('?admin)')>body.index(needle):raise ValueError('Whitelist must run before the lookup')
    return before+'[fwg-public-main]'+body.replace(needle,HOOK+needle,1)

def crontab():
    p=subprocess.run(['crontab','-l'],capture_output=True,text=True)
    if p.returncode and 'no crontab for' not in p.stderr.lower():raise ValueError('Unable to read existing crontab')
    return p.stdout

def main():
    p=argparse.ArgumentParser();p.add_argument('--pilot',default=str(Path(__file__).resolve().parents[2]/'phone'));args=p.parse_args()
    root=Path(args.pilot).resolve();ext=root/'config/extensions.conf'
    compose=root/'compose.yaml'
    if not compose.exists():compose=root/'compose.yml'
    old_ext=ext.read_text();old_compose=compose.read_text()
    try:new_ext=patch_dialplan(old_ext)
    except ValueError as e:raise SystemExit(str(e))
    for command in ['docker','crontab','flock']:
        if not shutil.which(command):raise SystemExit('Required command missing: '+command)
    needle='      - ./config/rtp.conf:/etc/asterisk/rtp.conf:ro'
    if needle not in old_compose:raise SystemExit('Unexpected Compose mounts. No configuration changed.')
    old_cron=crontab()
    folder=root/'config/fwg-callshield';folder.mkdir(mode=0o755,exist_ok=True)
    host=root/'callshield';host.mkdir(mode=0o755,exist_ok=True)
    for name in ['update.py','manage.py']:shutil.copy2(SOURCE/name,host/name)
    shutil.copy2(SOURCE/'lookup.py',folder/'lookup.py');os.chmod(folder/'lookup.py',0o755)
    (folder/'mode.json').write_text(json.dumps({'mode':'block'})+'\n');os.chmod(folder/'mode.json',0o644)
    interpreter=host/'.venv/bin/python'
    if not interpreter.exists():
        try:venv.create(host/'.venv',with_pip=True)
        except Exception:raise SystemExit('Install venv support: sudo apt install python3-venv. Then rerun setup. Incoming routing has not changed.')
    subprocess.run([str(interpreter),'-m','pip','install','cryptography>=44,<47'],check=True)
    result=subprocess.run([str(interpreter),str(host/'update.py'),'--data-dir',str(folder)])
    if result.returncode:raise SystemExit('Initial signed download failed; incoming route was not changed. Rerun after connectivity/feed verification is resolved.')
    command=' '.join(shlex.quote(x) for x in ['flock','-n',str(host/'cron.lock'),str(interpreter),str(host/'update.py'),'--data-dir',str(folder)])
    if '%' in command:raise SystemExit('Install path must not contain percent signs')
    lines=[line for line in old_cron.splitlines() if not line.endswith(TAG)]
    lines.append('5 4 * * * '+command+' >> '+shlex.quote(str(host/'update.log'))+' 2>&1 '+TAG)
    new_cron='\n'.join(lines)+'\n'
    new_compose=old_compose.replace(needle,needle+'\n      - ./config/fwg-callshield:/etc/asterisk/fwg-callshield:ro',1)
    backup=root.parent/('fwg-pre-callshield-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir(mode=0o700)
    shutil.copy2(ext,backup/ext.name);shutil.copy2(compose,backup/compose.name)
    try:
        ext.write_text(new_ext);compose.write_text(new_compose)
        if subprocess.run(['docker','compose','config','--quiet'],cwd=root,capture_output=True).returncode:
            raise ValueError('Compose validation failed')
        subprocess.run(['crontab','-'],input=new_cron,text=True,check=True)
        subprocess.run(['docker','compose','up','-d','--no-deps','asterisk'],cwd=root,check=True)
    except (Exception,KeyboardInterrupt):
        ext.write_text(old_ext);compose.write_text(old_compose)
        subprocess.run(['crontab','-'],input=old_cron,text=True)
        print('Original route and Compose files restored. If the container was replaced, recreate Asterisk using the restored files.')
        raise SystemExit(1)
    print('Installed in BLOCK mode. Matching non-whitelisted callers are rejected before answering or forwarding.')
    print('Backup: '+str(backup))
    print('Status: python3 '+str(host/'manage.py')+' --status')

if __name__=='__main__':main()
