#!/usr/bin/env python3
import argparse
import getpass
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from monitor import ROOT, save

TAG = '# FWG_DISCORD_MONITOR'

def cron(remove=False):
    if not shutil.which('crontab') or not shutil.which('flock'):
        raise SystemExit('Install cron first: sudo apt install cron')
    old = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    if old.returncode and 'no crontab for' not in old.stderr.lower():
        raise SystemExit('Could not read crontab; existing jobs were not changed.')
    lines = [line for line in old.stdout.splitlines() if not line.endswith(TAG)]
    if not remove:
        if not (ROOT/'config.json').exists(): raise SystemExit('Run setup.py first.')
        command = ' '.join(shlex.quote(x) for x in ['flock', '-n', str(ROOT/'monitor.lock'), sys.executable, str(ROOT/'monitor.py')])
        if '%' in command: raise SystemExit('Install path must not contain percent signs.')
        lines.append('*/2 * * * * '+command+' > /dev/null 2>&1 '+TAG)
    subprocess.run(['crontab', '-'], input='\n'.join(lines)+'\n', text=True, check=True)
    print('Monitor schedule '+('removed.' if remove else 'installed: every two minutes.'))

def configure():
    webhook = getpass.getpass('New Discord webhook URL (hidden): ').strip()
    if not re.fullmatch(r'https://discord\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+', webhook):
        raise SystemExit('Expected a Discord webhook URL. Nothing saved.')
    p = subprocess.run(['docker', 'ps', '--format', '{{.Names}}'], capture_output=True, text=True)
    if p.returncode: raise SystemExit('Docker unavailable for this user. Check docker ps before setup.')
    print('Running containers:\n'+p.stdout)
    print('Choose containers that should always run. Blank skips container checks.')
    containers = [x.strip() for x in input('Container names, comma separated: ').split(',') if x.strip()]
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', x) for x in containers):
        raise SystemExit('Invalid container name.')
    websites = [x.strip() for x in input('Public website URLs, comma separated (blank skips): ').split(',') if x.strip()]
    if any(not x.startswith('https://') for x in websites): raise SystemExit('Use HTTPS website URLs.')
    default = ROOT.parent/'assistant'
    folder = Path(input(f'Assistant folder [{default}]: ').strip() or str(default))
    available = []
    if (folder/'servers.json').exists():
        available = list(json.loads((folder/'servers.json').read_text()))
        print('Game aliases: '+', '.join(available))
    games = [x.strip() for x in input('Games expected to stay running, comma separated (blank skips): ').split(',') if x.strip()]
    if any(x not in available for x in games): raise SystemExit('Unknown game alias.')
    if games and not (folder/'.env').exists(): raise SystemExit('Assistant .env missing.')
    disk = input(f'Disk path [{ROOT.parent}]: ').strip() or str(ROOT.parent)
    if not Path(disk).exists(): raise SystemExit('Disk path does not exist.')
    save(ROOT/'config.json', dict(webhook=webhook, containers=containers, websites=websites,
        assistant_path=str(folder), games=games, disk_path=disk, disk_percent=90,
        memory_percent=90, timezone='America/New_York', summary_hour=9))
    # Discard previous counters when targets change.
    (ROOT/'state.json').unlink(missing_ok=True)
    print('Private local configuration saved. Next: python3 monitor.py --test-webhook')

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--install-cron', action='store_true')
    p.add_argument('--remove-cron', action='store_true')
    args = p.parse_args()
    if args.install_cron or args.remove_cron: cron(args.remove_cron)
    else: configure()
