#!/usr/bin/env python3
"""One entry point for configuration, deployment and in-place code updates."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from common import read_env, set_env, private_write

ROOT = Path(__file__).resolve().parent

def run(*args, cwd=None):
    subprocess.run([str(x) for x in args], cwd=cwd, check=True)

def compose(folder, *args): run('docker', 'compose', *args, cwd=folder)

def script(path, *args): run(sys.executable, ROOT/path, *args, cwd=(ROOT/path).parent)

def yes(prompt): return input(prompt+' [y/N]: ').strip().lower() == 'y'

def preflight():
    if not shutil.which('docker'): raise SystemExit('Install Docker Engine and its Compose plugin first.')
    run('docker', 'compose', 'version')
    run('docker', 'info', '--format', '{{.ServerVersion}}')

def wait_ready(folder, seconds=900):
    print('Waiting for model initialization (first download can take several minutes)...', flush=True)
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8099/health', timeout=5) as response:
                if json.load(response).get('ready'): return
        except (OSError, ValueError, urllib.error.URLError): pass
        time.sleep(5)
    raise SystemExit('Assistant did not become ready. Inspect: docker compose logs assistant (in '+str(folder)+'). Rerun install to resume.')

def install():
    preflight()
    assistant, phone = ROOT/'assistant', ROOT/'phone'
    if not (assistant/'.env').exists():
        script('assistant/setup.py')
        if yes('Connect assistant to an existing Nginx Proxy Manager Docker network?'):
            network = input('Existing NPM Docker network name: ').strip()
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', network): raise SystemExit('Invalid network name.')
            run('docker', 'network', 'inspect', network)
            text = (assistant/'compose.proxy.example.yaml').read_text().replace('REPLACE_WITH_NPM_DOCKER_NETWORK', network)
            private_write(assistant/'compose.override.yaml', text, 0o644)
            print('In NPM: forward your HTTPS host to fwg-ai-assistant, HTTP port 8000. APP_ORIGIN must match that host.')
    for name in ['users.json', 'servers.json']:
        if not (assistant/name).is_file(): raise SystemExit('Incomplete setup: '+name+' missing. Resolve before starting.')
    compose(assistant, 'config', '--quiet')
    compose(assistant, 'up', '-d', '--build')
    wait_ready(assistant)
    print('Web assistant ready. Log in as owner at '+read_env(assistant/'.env')['APP_ORIGIN'])
    if (phone/'config').exists() or yes('Enable LAN phone access with Asterisk and PIN authentication?'):
        if not (phone/'config').exists():
            ip = input('This server LAN IPv4: ').strip()
            cidr = input('Allowed LAN subnet CIDR (for example 192.168.50.0/24): ').strip()
            script('phone/setup.py', '--assistant', assistant, '--ip', ip, '--cidr', cidr)
            compose(assistant, 'up', '-d', '--force-recreate', 'assistant')
            wait_ready(assistant)
        compose(phone, 'config', '--quiet')
        compose(phone, 'up', '-d', '--build')
        print('Use the private softphone-settings.txt file and call extension 700 to test your PIN and server status.')
        print('When the LAN test works, run: python3 deploy.py provider')
    if (ROOT/'monitor/config.json').exists() or yes('Enable Discord monitoring?'):
        monitor_setup()
    print('Deployment complete. Use python3 deploy.py status. See docs/DEPLOYMENT.md for the phone stages.')

def monitor_setup():
    for command in ['crontab', 'flock']:
        if not shutil.which(command): raise SystemExit('Install cron support: sudo apt install cron')
    if not (ROOT/'monitor/config.json').exists(): script('monitor/setup.py')
    script('monitor/setup.py', '--install-cron')
    print('Discord checks scheduled every two minutes. Test delivery: python3 monitor/monitor.py --test-webhook')

def provider():
    preflight()
    phone = ROOT/'phone'
    sip = phone/'config/pjsip.conf'
    if not sip.exists(): raise SystemExit('Run install and finish the LAN phone test first.')
    text = sip.read_text()
    if '[fwg-provider-registration]' not in text:
        match = re.search(r'(?m)^bind=([0-9.]+):5060$', text)
        if not match: raise SystemExit('LAN transport bind not found.')
        cidr = re.search(r'(?m)^permit=([0-9./]+)$', text)
        if not cidr: raise SystemExit('LAN subnet ACL not found.')
        script('integrations/voipms/setup.py', '--pilot', phone, '--lan-ip', match[1], '--cidr', cidr[1])
    compose(phone, 'up', '-d', '--force-recreate', 'asterisk')
    compose(phone, 'exec', '-T', 'asterisk', 'asterisk', '-rx', 'pjsip show registrations')
    print('Confirm Registered and that the DID routes to the same encrypted subaccount/Chicago1 POP.')
    print('Then run: python3 deploy.py public-phone')

def public_phone():
    preflight()
    phone = ROOT/'phone'
    result = subprocess.run(['docker','compose','exec','-T','asterisk','asterisk','-rx','pjsip show registrations'],
                            cwd=phone, capture_output=True, text=True, check=True)
    if not re.search(r'fwg-provider-registration/.*\bRegistered\b', result.stdout):
        raise SystemExit('Provider registration is not Registered. Resolve registration before enabling incoming calls.')
    script('integrations/public-phone/setup.py', '--pilot', phone, '--assistant', ROOT/'assistant')
    compose(phone, 'up', '-d', '--no-deps', 'asterisk')
    print('Route configured. Apply the restricted RTP forwarding in docs/PHONE.md and test incoming audio.')
    if yes('Enable CallShield exact-number spam rejection now?'): callshield()

def callshield():
    script('integrations/callshield/install.py', '--pilot', ROOT/'phone')

def code_update(assistant, phone, monitor):
    preflight()
    if not all((assistant/name).is_file() for name in ['.env','users.json','servers.json','compose.yaml']):
        raise SystemExit('Assistant deployment/configuration not found; no files changed.')
    # Deliberately retain deployment Compose project names and named volumes.
    files = [(ROOT/'assistant'/name, assistant/name) for name in
             ['app.py','phone_api.py','panel_tools.py','Dockerfile','accounts.py']]
    files += [(path,assistant/'static'/path.name) for path in (ROOT/'assistant/static').iterdir() if path.is_file()]
    if (phone/'compose.yaml').exists():
        files += [(ROOT/'phone/bridge'/name,phone/'bridge'/name) for name in ['bridge.py','Dockerfile']]
        files += [(ROOT/'phone/asterisk/Dockerfile',phone/'asterisk/Dockerfile')]
    if (monitor/'config.json').exists(): files += [(ROOT/'monitor/monitor.py',monitor/'monitor.py')]
    files = [(source,target) for source,target in files if source.resolve()!=target.resolve()]
    backup = ROOT/'backups'/dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup.mkdir(parents=True,mode=0o700)
    (ROOT/'backups').chmod(0o700)
    manifest = []
    old_env = (assistant/'.env').read_text()
    env_backup = backup/'assistant.env'; private_write(env_backup, old_env)
    try:
        for index,(source,target) in enumerate(files):
            saved = backup/str(index)
            if target.exists(): shutil.copy2(target,saved)
            manifest.append({'target':str(target),'saved':str(saved) if saved.exists() else None})
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
        private_write(backup/'restore.json',json.dumps(manifest,indent=2)+'\n')
        if 'PIPER_VOICE' not in read_env(assistant/'.env'):
            set_env(assistant/'.env',{'PIPER_VOICE':'en_US-lessac-medium'})
        compose(assistant,'config','--quiet')
        if (phone/'compose.yaml').exists(): compose(phone,'config','--quiet')
        compose(assistant,'up','-d','--build','--force-recreate','assistant')
        wait_ready(assistant)
        if (phone/'compose.yaml').exists(): compose(phone,'up','-d','--build')
    except BaseException:
        for item in reversed(manifest):
            target = Path(item['target'])
            if item['saved']: shutil.copy2(item['saved'],target)
            else: target.unlink(missing_ok=True)
        # Restore the original private environment if a default was added.
        private_write(assistant/'.env',old_env)
        print('Previous files restored. Containers may still use the new image. Rebuild/recreate from restored files to roll back runtime.')
        raise
    print('Updated code. Credentials, accounts, routing, Compose overrides and volumes retained. Private rollback files: '+str(backup))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['install','update','status','provider','public-phone','callshield','monitor'])
    parser.add_argument('--assistant',type=Path,default=ROOT/'assistant',help='Existing deployment path for update/status')
    parser.add_argument('--phone',type=Path,default=ROOT/'phone',help='Existing phone deployment path for update/status')
    parser.add_argument('--monitor',type=Path,default=ROOT/'monitor',help='Existing monitor path for update/status')
    args = parser.parse_args()
    if args.command == 'install': install()
    elif args.command == 'update': code_update(args.assistant.resolve(),args.phone.resolve(),args.monitor.resolve())
    elif args.command == 'status':
        for folder in [args.assistant,args.phone]:
            if (folder/'compose.yaml').exists() and (folder/'.env').exists(): compose(folder,'ps')
        if (args.monitor/'config.json').exists(): run(sys.executable,args.monitor/'monitor.py','--status')
    elif args.command == 'provider': provider()
    elif args.command == 'public-phone': public_phone()
    elif args.command == 'callshield': callshield()
    elif args.command == 'monitor': monitor_setup()

if __name__ == '__main__':
    try: main()
    except subprocess.CalledProcessError as error:
        raise SystemExit('Command failed (exit '+str(error.returncode)+'). Resolve the reported error and rerun the same step.')
