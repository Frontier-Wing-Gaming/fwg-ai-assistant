#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

def main():
    root=Path(__file__).resolve().parent.parent
    folder=root/'config/fwg-callshield'
    p=argparse.ArgumentParser();p.add_argument('--status',action='store_true');p.add_argument('--mode',choices=['report','block','off']);p.add_argument('--remove-cron',action='store_true');args=p.parse_args()
    if args.remove_cron:
        result=subprocess.run(['crontab','-l'],capture_output=True,text=True)
        if result.returncode and 'no crontab for' not in result.stderr.lower():raise SystemExit('Cannot read crontab; no changes made.')
        lines=[line for line in result.stdout.splitlines() if not line.endswith('# FWG_CALLSHIELD')]
        subprocess.run(['crontab','-'],input='\n'.join(lines)+'\n',text=True,check=True)
        print('CallShield updater schedule removed; other jobs retained.')
        if not args.mode and not args.status:return
    if args.mode:
        fd,name=tempfile.mkstemp(dir=folder)
        with os.fdopen(fd,'w') as f:json.dump({'mode':args.mode},f)
        os.chmod(name,0o644);os.replace(name,folder/'mode.json')
        print('Mode set to '+args.mode+'. Applies to subsequent calls; no restart needed.')
    if args.status or not args.mode:
        print('Mode:',json.loads((folder/'mode.json').read_text())['mode'])
        if (folder/'numbers.sqlite').exists():
            with sqlite3.connect('file:'+str(folder/'numbers.sqlite')+'?mode=ro',uri=True) as conn:
                print(json.dumps(dict(conn.execute('SELECT key,value FROM metadata')),indent=2))
        else:print('No verified database. Normal screening remains available.')
        if (folder/'update-status.json').exists():print((folder/'update-status.json').read_text())

if __name__=='__main__':main()
