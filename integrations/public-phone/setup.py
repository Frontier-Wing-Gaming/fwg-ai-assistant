#!/usr/bin/env python3
"""Local incoming-call setup, retaining all credentials and LAN phone behavior."""
import argparse
import base64
import datetime
import getpass
import ipaddress
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys

MARKER='; FWG VOIPMS REGISTRATION ONLY'
POP='chicago1.voip.ms'

def number(value):
    digits=re.sub(r'[\s()+.-]', '', value)
    if re.fullmatch(r'[2-9][0-9]{2}[2-9][0-9]{6}',digits): digits='1'+digits
    if not re.fullmatch(r'1[2-9][0-9]{2}[2-9][0-9]{6}',digits):
        raise ValueError('Use a 10-digit US/Canadian number, optionally prefixed by +1.')
    return digits

def section(text,name):
    match=re.search(r'(?ms)^\['+re.escape(name)+r'\]\s*\n(.*?)(?=^\[|\Z)',text)
    if not match: raise ValueError('Expected configuration section missing: '+name)
    return match.group(1)

def get(body,key):
    match=re.search(r'(?m)^'+re.escape(key)+r'\s*=\s*(.*?)\s*$',body)
    if not match: raise ValueError('Missing configuration setting: '+key)
    return match.group(1)

def patch_section(text,name,values):
    body=section(text,name)
    changed=body
    for key,value in values.items():
        pattern=r'(?m)^'+re.escape(key)+r'\s*=.*$'
        if re.search(pattern,changed): changed=re.sub(pattern,lambda m:key+'='+value,changed)
        else: changed=changed.rstrip()+'\n'+key+'='+value+'\n'
    pattern=r'(?ms)(^\['+re.escape(name)+r'\]\s*\n).*?(?=^\[|\Z)'
    return re.sub(pattern,lambda m:m.group(1)+changed.rstrip()+'\n\n',text,count=1)

def dialplan(did,cell,admins,blocked):
    # Only literal locally validated digits enter the dialplan.
    lines=['; FWG PUBLIC PHONE ROUTING', '[fwg-public]',
           'exten => fwg-disabled,1,Goto(fwg-public-main,s,1)',
           f'exten => {did[1:]},1,Goto(fwg-public-main,s,1)',
           f'exten => {did},1,Goto(fwg-public-main,s,1)',
           f'exten => +{did},1,Goto(fwg-public-main,s,1)',
           'exten => s,1,Goto(fwg-public-main,s,1)', '', '[fwg-public-main]',
           'exten => s,1,Set(FWG_CID=${FILTER(0-9,${CALLERID(num)})})',
           ' same => n,ExecIf($[${LEN(${FWG_CID})}=10]?Set(FWG_CID=1${FWG_CID}))']
    for caller in blocked: lines.append(f' same => n,GotoIf($["${{FWG_CID}}"="{caller}"]?blocked)')
    lines+=[' same => n,Set(GROUP(fwg-public)=incoming)',
            ' same => n,GotoIf($[${GROUP_COUNT(incoming@fwg-public)}>1]?blocked)',
            ' same => n,Set(TIMEOUT(absolute)=600)']
    for caller in admins:lines.append(f' same => n,GotoIf($["${{FWG_CID}}"="{caller}"]?admin)')
    lines+=[' same => n,Answer()',
            ' same => n,Read(FWG_SCREEN,/etc/asterisk/fwg-sounds/screen,1,,1,8)',
            ' same => n,GotoIf($["${FWG_SCREEN}"="5"]?forward:blocked)',
            f' same => n(forward),Set(CALLERID(num)={did[1:]})',
            ' same => n,Set(CALLERID(name)=FWG NETWORK)',
            # i ignores callee-requested redirection; one fixed destination, ten-minute bound.
            f' same => n,Dial(PJSIP/{cell}@fwg-provider-disabled,30,iL(600000))',
            ' same => n,Hangup()',
            ' same => n(admin),Goto(fwg-internal,700,1)',
            ' same => n(blocked),Hangup(21)', '']
    return '\n'.join(lines)

def sound(assistant):
    script=r'''import base64,os,subprocess,tempfile,wave
from pathlib import Path
from piper import PiperVoice
voice=PiperVoice.load('/cache/voices/'+os.environ.get('PIPER_VOICE','en_US-ljspeech-high')+'.onnx')
with tempfile.TemporaryDirectory() as d:
    source=Path(d)/'source.wav'; output=Path(d)/'screen.wav'
    with wave.open(str(source),'wb') as f:
        voice.synthesize_wav('Welcome to Frontier Wing Gaming. To connect to the owner, press five now.',f)
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-ar','8000','-ac','1','-c:a','pcm_s16le',str(output)],check=True)
    print(base64.b64encode(output.read_bytes()).decode())
'''
    p=subprocess.run(['docker','compose','exec','-T','assistant','python','-c',script],cwd=assistant,
                     capture_output=True,text=True,timeout=90)
    if p.returncode:raise ValueError('Unable to generate screening prompt. Ensure the assistant is running and its voice model is cached.')
    try: data=base64.b64decode(p.stdout.strip(),validate=True)
    except Exception:raise ValueError('Unexpected screening audio output; no configuration changed.')
    if not data.startswith(b'RIFF') or len(data)>2_000_000:raise ValueError('Invalid screening WAV; no configuration changed.')
    return data

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pilot',default=str(pathlib.Path(__file__).resolve().parents[2]/'phone'))
    p.add_argument('--assistant',default=str(Path(__file__).resolve().parents[2]/'assistant'))
    args=p.parse_args();root=Path(args.pilot);assistant=Path(args.assistant)
    sip=root/'config/pjsip.conf';ext=root/'config/extensions.conf'
    old_sip=sip.read_text();old_ext=ext.read_text()
    if '[fwg-public]' in old_ext or '[fwg-provider-aor]' in old_sip:raise SystemExit('Public routing already installed. No changes made.')
    if MARKER not in old_ext or section(old_ext,'fwg-provider-disabled').strip()!='exten => _.,1,Hangup(21)':
        raise SystemExit('Incoming dialplan differs from the registration-only version. No changes made.')
    if 'AudioSocket(' not in section(old_ext,'fwg-internal'):raise SystemExit('Working LAN extension not found.')
    username=get(section(old_sip,'fwg-provider-auth'),'username')
    registration=section(old_sip,'fwg-provider-registration')
    if POP not in get(registration,'server_uri'):raise SystemExit('Expected Chicago1 registration. No changes made.')
    for key,value in [('media_encryption','sdes'),('media_encryption_optimistic','no')]:
        if get(section(old_sip,'fwg-provider-disabled'),key)!=value:raise SystemExit('Expected encrypted endpoint settings. No changes made.')
    env={}
    for line in (assistant/'.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key,value=line.split('=',1);env[key.strip()]=value.strip().strip('\"\'')
    if not env.get('PHONE_PIN_HASH') or not env.get('PHONE_PIN_SALT'):raise SystemExit('Phone PIN authentication is not configured. No changes made.')
    try:
        did=number(input('Assigned VoIP.ms DID: ').strip())
        cell=number(getpass.getpass('Personal cellphone to forward other callers to (hidden): ').strip())
        print('Include your cellphone in the admin whitelist to avoid forwarding loops.')
        raw=getpass.getpass('Admin caller numbers, comma separated (hidden): ')
        admins=list(dict.fromkeys(number(x.strip()) for x in raw.split(',') if x.strip()))
        raw=getpass.getpass('Known blocked numbers, comma separated (hidden; blank for none): ')
        blocked=list(dict.fromkeys(number(x.strip()) for x in raw.split(',') if x.strip()))
        if not admins or cell not in admins:raise ValueError('Forwarding cellphone must be in the admin whitelist.')
        if did==cell or did in admins or set(admins)&set(blocked):raise ValueError('Conflicting DID, whitelist, forwarding or blocked entries.')
        if len(admins)>30 or len(blocked)>100:raise ValueError('Maximum 30 admins and 100 blocked numbers.')
        current=input('Current public/WAN IPv4 (confirm against router WAN): ').strip()
        if not ipaddress.ip_address(current).is_global or ipaddress.ip_address(current).version!=4:raise ValueError('A public IPv4 is required.')
        provider_ip=socket.gethostbyname(POP)
        if not ipaddress.ip_address(provider_ip).is_global:raise ValueError('Unexpected provider DNS address.')
        audio=sound(assistant)
    except ValueError as e:raise SystemExit(str(e)+' No changes made.')
    changed=patch_section(old_sip,'fwg-provider-disabled',{'context':'fwg-public','outbound_auth':'fwg-provider-auth',
        'aors':'fwg-provider-aor','from_user':username,'from_domain':POP,'send_rpid':'yes','dtmf_mode':'rfc4733'})
    changed=patch_section(changed,'fwg-provider-tls',{'external_signaling_address':current,'external_media_address':current})
    changed+=f'\n[fwg-provider-aor]\ntype=aor\ncontact=sip:{POP}:5061\\;transport=tls\n\n[fwg-provider-identify]\ntype=identify\nendpoint=fwg-provider-disabled\nmatch={provider_ip}\n'
    prefix=old_ext.split(MARKER,1)[0].rstrip()
    # Ensure no unknown contexts were appended to the registration-only dialplan.
    if len(re.findall(r'(?m)^\[',old_ext.split(MARKER,1)[1]))!=1:raise SystemExit('Unexpected appended dialplan; no changes made.')
    compose=root/'compose.yaml'
    if not compose.exists():compose=root/'compose.yml'
    old_compose=compose.read_text()
    needle='      - ./config/rtp.conf:/etc/asterisk/rtp.conf:ro'
    if needle not in old_compose:raise SystemExit('Unexpected Compose volume layout. No changes made.')
    new_compose=old_compose.replace(needle,needle+'\n      - ./config/fwg-sounds:/etc/asterisk/fwg-sounds:ro',1)
    backup=root.parent/('fwg-pre-public-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(mode=0o700)
    for path in [sip,ext,compose]:shutil.copy2(path,backup/path.name)
    prompts=root/'config/fwg-sounds';prompts.mkdir(mode=0o755,exist_ok=True)
    (prompts/'screen.wav').write_bytes(audio)
    try:
        # Preserve bind-mount inodes so rollback/reloads see new content.
        sip.write_text(changed);ext.write_text(prefix+'\n\n'+dialplan(did,cell,admins,blocked));compose.write_text(new_compose)
        result=subprocess.run(['docker','compose','config','--quiet'],cwd=root,capture_output=True)
        if result.returncode:raise ValueError('Compose validation failed')
    except Exception:
        sip.write_text(old_sip);ext.write_text(old_ext);compose.write_text(old_compose)
        raise SystemExit('Validation failed. Original configuration restored; no restart performed.')
    print('Prepared incoming routing. Credentials retained. Private backup: '+str(backup))
    print('Whitelist callers use the existing PHONE_USER account and PIN; no individual phone identities are added.')
    print('Next: read README, apply restricted UDP media forwarding, then docker compose up -d --no-deps asterisk')
    print('Provider media IP to verify against VoIP.ms guidance: '+provider_ip)

if __name__=='__main__':main()
