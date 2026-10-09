#!/usr/bin/env python3
"""Read-only host checks. All credentials stay in local files."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent

def save(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, indent=2)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def request(url, headers=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=8) as r:
        return json.load(r)

def panel_settings(folder):
    values = {}
    for line in (Path(folder)/'.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('\"\'')
    return values

def checks(config):
    result = {}
    def check(key, fn):
        try: result[key] = fn()
        except Exception as e: result[key] = (False, 'Check failed: '+type(e).__name__)
    def container(name):
        p = subprocess.run(['docker', 'inspect', name], capture_output=True, text=True, timeout=10)
        if p.returncode: return False, 'Unavailable or Docker inaccessible'
        s = json.loads(p.stdout)[0]['State']
        health = s.get('Health', {}).get('Status')
        return s['Running'] and health in (None, 'healthy'), s['Status'] + (('/'+health) if health else '')
    for name in config['containers']:
        check('Docker: '+name, lambda name=name: container(name))
    def website(url):
        with urllib.request.urlopen(url, timeout=8) as r:
            return 200 <= r.status < 400, 'HTTP '+str(r.status)
    for url in config['websites']:
        check('Website: '+url, lambda url=url: website(url))
    def disk():
        usage = shutil.disk_usage(config['disk_path'])
        percent = usage.used / usage.total * 100
        return percent < config['disk_percent'], f'{percent:.1f}% used'
    check('Host: disk', disk)
    def memory():
        values = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
        percent = (1-values['MemAvailable']/values['MemTotal'])*100
        return percent < config['memory_percent'], f'{percent:.1f}% used'
    check('Host: memory', memory)
    def game(alias):
        folder = Path(config['assistant_path'])
        env = panel_settings(folder)
        server = json.loads((folder/'servers.json').read_text())[alias]['identifier']
        base = env['PTERO_URL'].rstrip('/')
        if not base.startswith('https://'): raise ValueError('HTTPS required')
        response = request(base+'/api/client/servers/'+server+'/resources',
                           {'Authorization': 'Bearer '+env['PTERO_CLIENT_KEY'], 'Accept': 'application/json'})
        status = response['attributes']['current_state']
        return status == 'running', status
    for alias in config['games']:
        check('Game: '+alias, lambda alias=alias: game(alias))
    return result

def send(webhook, content):
    payload = json.dumps({'content': content[:1900], 'allowed_mentions': {'parse': []}}).encode()
    req = urllib.request.Request(webhook, data=payload, headers={'Content-Type': 'application/json', 'User-Agent': 'FWG-Monitor/1.0'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return 200 <= r.status < 300

def update(state, results):
    events = []
    for key, (ok, detail) in results.items():
        item = state.setdefault('checks', {}).setdefault(key, {'bad': 0, 'good': 0, 'alerted': False})
        item['bad'] = 0 if ok else item['bad'] + 1
        item['good'] = item['good'] + 1 if ok else 0
        item.update(ok=ok, detail=detail)
        if item['bad'] >= 3 and not item['alerted']:
            events.append((key, True, '⚠️ Problem: '+key+' — '+detail))
        elif item['good'] >= 2 and item['alerted']:
            events.append((key, False, '✅ Recovered: '+key+' — '+detail))
    return events

def run(config, state, notifier=send, now=None):
    results = checks(config)
    events = update(state, results)
    for key, alerted, message in events:
        try:
            if notifier(config['webhook'], message): state['checks'][key]['alerted'] = alerted
        except Exception: print('Discord delivery failed; will retry. No credentials logged.')
    now = now or dt.datetime.now(ZoneInfo(config['timezone']))
    today = now.date().isoformat()
    if now.hour >= config['summary_hour'] and state.get('last_summary') != today:
        rows = [f'{"OK" if ok else "PROBLEM"}: {key} — {detail}' for key, (ok, detail) in results.items()]
        summary = 'FWG daily health summary ('+today+')\n'+'\n'.join(rows)
        try:
            if notifier(config['webhook'], summary): state['last_summary'] = today
        except Exception: print('Discord summary delivery failed; will retry.')
    state['checked_at'] = now.isoformat()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-webhook', action='store_true')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    config_path, state_path = ROOT/'config.json', ROOT/'state.json'
    if args.status:
        print(state_path.read_text() if state_path.exists() else 'No checks run yet.')
        return
    try:
        os.chmod(config_path, 0o600)
        config = json.loads(config_path.read_text())
        if args.test_webhook:
            if send(config['webhook'], '✅ FWG monitor test. Discord alerts are connected.'):
                print('Discord test delivered.')
            return
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        run(config, state)
        save(state_path, state)
    except Exception as e:
        print('Monitor failed: '+type(e).__name__+'. Check local setup; credentials are not logged.')
        raise SystemExit(1)

if __name__ == '__main__': main()
