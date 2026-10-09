"""Fresh setup only. Existing users and credentials are never overwritten."""
import getpass
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import password_hash, private_write, set_env

def main():
    root = Path(__file__).resolve().parent
    if any((root/name).exists() for name in ['.env', 'users.json', 'servers.json']):
        raise SystemExit('Configuration exists. Use deploy.py update; setup does not overwrite it.')
    origin = input('Browser origin [http://localhost:8099]: ').strip().rstrip('/') or 'http://localhost:8099'
    panel = input('Pterodactyl panel HTTPS origin: ').strip().rstrip('/')
    for value in [origin, panel]:
        u = urlsplit(value)
        if u.scheme not in ('http', 'https') or not u.netloc or u.path or u.query or u.fragment or u.username:
            raise SystemExit('Use an origin URL with no path, query or credentials.')
    if not panel.startswith('https://'):
        raise SystemExit('The panel must use HTTPS.')
    key = getpass.getpass('Restricted Pterodactyl CLIENT API key (hidden): ').strip()
    if not key: raise SystemExit('A client API key is required.')
    password = getpass.getpass('Owner web password (14+ characters): ')
    if len(password) < 14 or password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords do not match or are too short.')
    servers = {}
    print('Add panel servers. Enter a blank alias when finished.')
    while True:
        alias = input('Server alias (for example minecraft): ').strip().lower()
        if not alias: break
        if not re.fullmatch(r'[a-z0-9_-]{1,40}', alias) or alias in servers or len(servers) >= 30:
            print('Invalid, duplicate or excessive alias.'); continue
        name = input('Display name: ').strip()
        identifier = input('Panel server identifier (from its URL): ').strip()
        if not name or not re.fullmatch(r'[A-Za-z0-9-]{8,36}', identifier):
            print('Invalid name or identifier.'); continue
        servers[alias] = {'name': name, 'identifier': identifier}
    if not servers: raise SystemExit('Add at least one server.')
    actions = ['status', 'resources', 'logs']
    if input('Allow owner to confirm start/stop/restart? [y/N]: ').strip().lower() == 'y':
        actions += ['start', 'stop', 'restart']
    salt, digest = password_hash(password)
    set_env(root/'.env', {'APP_ORIGIN': origin, 'PTERO_URL': panel, 'PTERO_CLIENT_KEY': key,
                         'PASSWORD_SALT': salt, 'PASSWORD_HASH': digest, 'PIPER_VOICE': 'en_US-ljspeech-high'})
    private_write(root/'servers.json', json.dumps(servers, indent=2)+'\n', 0o644)
    private_write(root/'users.json', json.dumps({'owner': {'salt': salt, 'hash': digest, 'servers': ['*'],
                            'actions': actions, 'disabled': False}}, indent=2)+'\n', 0o644)
    root.chmod(0o700)
    print('Configured owner and server allowlist. No plaintext web password saved.')

if __name__ == '__main__': main()
