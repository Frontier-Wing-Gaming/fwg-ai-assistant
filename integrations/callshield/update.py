#!/usr/bin/env python3
"""Daily signed feed import; no caller numbers leave the homelab."""
import argparse
import base64
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import urllib.request
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT=Path(__file__).resolve().parent
URL='https://raw.githubusercontent.com/SysAdminDoc/CallShield/master/data/spam_numbers.txt'
# Pinned from upstream FeedSignature.kt, inspected 2026-10-09. Never refreshed automatically.
KEYS=[
 'MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAESGK0kjIAEM7FP2RBLbWctHhYVP7LcNVJmWiuh6k6hkBGHfVXaqw+TOaSVQtbZLZeN5OThnqd0WTEF/CkBJ2gdA==',
 'MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE3eBrWqtgDaKc2HFC6EPtENrh8nlCH/bZ5PstgPpIJBVL8ZEf35UfwtbqWKJ/fQDi1pYKLmvMv/0OC3KSug/fxg=='
]

def download(url,limit):
    req=urllib.request.Request(url,headers={'User-Agent':'FWG-CallShield/1.0'})
    with urllib.request.urlopen(req,timeout=20) as response:
        if not response.geturl().startswith('https://raw.githubusercontent.com/'):
            raise ValueError('Unexpected download redirect')
        data=response.read(limit+1)
    if len(data)>limit:raise ValueError('Feed exceeds size limit')
    return data

def verify(data,sig,keys=KEYS):
    signature=base64.b64decode(sig.strip(),validate=True)
    for encoded in keys:
        key=serialization.load_der_public_key(base64.b64decode(encoded))
        try:
            key.verify(signature,data,ec.ECDSA(hashes.SHA256()))
            return
        except InvalidSignature:pass
    raise ValueError('CallShield signature does not verify')

def parse(data,today=None):
    text=data.decode('utf-8');today=today or dt.date.today()
    header=re.search(r'^# CallShield spam numbers, database version (\d+) \(updated (\d{4}-\d{2}-\d{2})\)$',text,re.M)
    if not header:raise ValueError('Unrecognized signed feed header')
    version=int(header[1]);updated=dt.date.fromisoformat(header[2])
    age=(today-updated).days
    if age < -1 or age>90:raise ValueError('Feed date is outside supported freshness window')
    numbers=set()
    for line in text.splitlines():
        if not line or line.startswith('#'):continue
        if not re.fullmatch(r'\+[1-9][0-9]{6,14}',line):raise ValueError('Unexpected feed entry')
        # Exact NANP numbers only. No prefix or geographic wildcard rules.
        if re.fullmatch(r'\+1[2-9][0-9]{2}[2-9][0-9]{6}',line):numbers.add(line[1:])
    if not 1000<=len(numbers)<=250000:raise ValueError('Unexpected usable feed count')
    return numbers,version,updated.isoformat()

def import_feed(folder,data,sig,keys=KEYS,today=None):
    verify(data,sig,keys);numbers,version,updated=parse(data,today)
    database=folder/'numbers.sqlite'
    previous={}
    if database.exists():
        with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as conn:
            previous=dict(conn.execute('SELECT key,value FROM metadata'))
        if version<int(previous['version']):raise ValueError('Refusing a feed version rollback')
        if len(numbers)<int(previous['count'])/2:raise ValueError('Feed shrank by more than half; retain existing list pending review')
    digest=hashlib.sha256(data).hexdigest()
    if previous.get('sha256')==digest:return int(previous['count']),False
    if previous and version==int(previous['version']):raise ValueError('Same version has different content')
    fd,name=tempfile.mkstemp(dir=folder,suffix='.sqlite');os.close(fd)
    try:
        with sqlite3.connect(name) as conn:
            conn.execute('CREATE TABLE numbers(number TEXT PRIMARY KEY) WITHOUT ROWID')
            conn.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)')
            conn.executemany('INSERT INTO numbers VALUES (?)',((n,) for n in sorted(numbers)))
            metadata={'version':str(version),'updated':updated,'count':str(len(numbers)),'sha256':digest,
                      'imported_at':dt.datetime.now(dt.timezone.utc).isoformat()}
            conn.executemany('INSERT INTO metadata VALUES (?,?)',metadata.items())
        os.chmod(name,0o644);os.replace(name,database)
    finally:
        if os.path.exists(name):os.unlink(name)
    return len(numbers),True

def main():
    p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,default=ROOT/'data');args=p.parse_args()
    args.data_dir.mkdir(parents=True,exist_ok=True)
    with (args.data_dir/'update.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        try:
            data=download(URL,4*1024*1024);sig=download(URL+'.sig',512)
            count,changed=import_feed(args.data_dir,data,sig)
            message=f'Signed feed verified: {count} exact NANP entries; '+('updated.' if changed else 'unchanged.')
            print(message)
            (args.data_dir/'update-status.json').write_text(json.dumps({'ok':True,'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'message':message})+'\n')
        except Exception as e:
            message='Update rejected or unavailable: '+type(e).__name__+'. Previous valid database retained.'
            print(message)
            (args.data_dir/'update-status.json').write_text(json.dumps({'ok':False,'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'message':message})+'\n')
            raise SystemExit(1)

if __name__=='__main__':main()
