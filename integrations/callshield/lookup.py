#!/usr/bin/python3
"""Bounded offline AGI lookup. No network, secrets or free-form commands."""
import datetime as dt
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT=Path(__file__).resolve().parent

def lookup(number,folder=ROOT,today=None):
    if not re.fullmatch(r'1[2-9][0-9]{2}[2-9][0-9]{6}',number):return 'CLEAR'
    try:
        config=json.loads((folder/'mode.json').read_text())
        mode=config['mode']
        if mode not in ('report','block','off'):return 'UNAVAILABLE'
        if mode=='off':return 'CLEAR'
        with sqlite3.connect('file:'+str(folder/'numbers.sqlite')+'?mode=ro',uri=True,timeout=0.2) as conn:
            metadata=dict(conn.execute('SELECT key,value FROM metadata'))
            date=dt.date.fromisoformat(metadata['updated'])
            age=((today or dt.date.today())-date).days
            if age>90 or age < -1:return 'UNAVAILABLE'
            match=conn.execute('SELECT 1 FROM numbers WHERE number=?',(number,)).fetchone()
        if not match:return 'CLEAR'
        return 'BLOCK' if mode=='block' else 'REPORT'
    except Exception:return 'UNAVAILABLE'

def main():
    # AGI environment, followed by an empty line. Parse only the bounded argv number.
    for _ in range(200):
        line=sys.stdin.readline()
        if not line or line in ('\n','\r\n'):break
    result=lookup(sys.argv[1] if len(sys.argv)>1 else '')
    print('SET VARIABLE FWG_CS_RESULT "'+result+'"',flush=True)
    sys.stdin.readline()

if __name__=='__main__':main()
