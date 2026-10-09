#!/usr/bin/env python3
import argparse
import getpass
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from common import password_hash,set_env
p=argparse.ArgumentParser();p.add_argument('--assistant',type=Path,default=Path(__file__).resolve().parent.parent/'assistant');args=p.parse_args()
if not (args.assistant/'.env').is_file():raise SystemExit('Assistant environment not found.')
pin=getpass.getpass('New phone PIN (6–10 digits): ')
if not pin.isascii() or not pin.isdigit() or not 6<=len(pin)<=10 or pin!=getpass.getpass('Repeat PIN: '):raise SystemExit('Invalid PIN or mismatch.')
salt,digest=password_hash(pin)
set_env(args.assistant/'.env',{'PHONE_PIN_SALT':salt,'PHONE_PIN_HASH':digest})
print('PIN hash updated locally. Recreate assistant with docker compose up -d --force-recreate assistant.')
