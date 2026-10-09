"""Prepare TLS registration only. No public AI route or outbound dialing."""
import argparse,datetime,getpass,ipaddress,pathlib,re,shutil,socket
SERVER='chicago1.voip.ms'
MARKER='; FWG VOIPMS REGISTRATION ONLY'

def make_config(username,password,lan_ip,public_ip,lan_cidr=None):
    if not re.fullmatch(r'[0-9]{6}_[A-Za-z0-9_-]{1,12}',username):
        raise ValueError('Enter the complete dedicated subaccount username, including the six-digit prefix and underscore.')
    if not 8<=len(password)<=50 or not re.fullmatch(r'[A-Za-z0-9_!@#$%^&*()+={}\[\]:,.?/-]+',password):
        raise ValueError('Password must be 8–50 safe ASCII characters, with no spaces, quotes, semicolons or backslashes. Use a strong alphanumeric/URL-safe provider password if needed.')
    lan=ipaddress.ip_address(lan_ip);public=ipaddress.ip_address(public_ip)
    if lan.version!=4 or not lan.is_private or public.version!=4 or not public.is_global:
        raise ValueError('Use a private LAN IPv4 and a public WAN IPv4.')
    network=ipaddress.ip_network(lan_cidr or str(lan)+'/24',strict=False)
    if network.version!=4 or not network.is_private or lan not in network:raise ValueError('Invalid private LAN subnet')
    return f'''
{MARKER}
[fwg-provider-tls]
type=transport
protocol=tls
bind={lan}:5061
method=tlsv1_2
ca_list_file=/etc/ssl/certs/ca-certificates.crt
verify_server=yes
verify_client=no
require_client_cert=no
allow_wildcard_certs=yes
local_net={network}
external_signaling_address={public}
external_media_address={public}

[fwg-provider-auth]
type=auth
auth_type=userpass
username={username}
password={password}

[fwg-provider-registration]
type=registration
transport=fwg-provider-tls
outbound_auth=fwg-provider-auth
server_uri=sip:{SERVER}:5061\\;transport=tls
client_uri=sip:{username}@{SERVER}:5061\\;transport=tls
contact_user=fwg-disabled
expiration=300
retry_interval=60
forbidden_retry_interval=600
fatal_retry_interval=600
max_retries=5
line=yes
endpoint=fwg-provider-disabled

[fwg-provider-disabled]
type=endpoint
transport=fwg-provider-tls
context=fwg-provider-disabled
disallow=all
allow=ulaw
media_encryption=sdes
media_encryption_optimistic=no
direct_media=no
allow_transfer=no
rtp_symmetric=yes
force_rport=yes
rewrite_contact=yes
'''

DIALPLAN='''
; FWG VOIPMS REGISTRATION ONLY
[fwg-provider-disabled]
exten => _.,1,Hangup(21)
'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pilot',default=str(Path(__file__).resolve().parents[2]/'phone'));parser.add_argument('--lan-ip',required=True);parser.add_argument('--cidr');args=parser.parse_args()
    root=pathlib.Path(args.pilot);sip=root/'config/pjsip.conf';dial=root/'config/extensions.conf'
    old_sip=sip.read_text();old_dial=dial.read_text()
    if MARKER in old_sip or '[fwg-provider-disabled]' in old_dial:raise SystemExit('Registration setup already present; no changes made.')
    if '[1001]' not in old_sip or 'AudioSocket(' not in old_dial:raise SystemExit('Working LAN phone pilot not found.')
    username=input('Full VoIP.ms AI subaccount SIP username: ').strip()
    password=getpass.getpass('VoIP.ms SIP subaccount password (hidden): ')
    public=input('Current public/WAN IPv4 (enter locally): ').strip()
    try:new=make_config(username,password,args.lan_ip,public,args.cidr)
    except ValueError as e:raise SystemExit(str(e)+' No changes made.')
    check=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:check.bind((args.lan_ip,5061))
    except OSError:raise SystemExit('TCP 5061 unavailable; no changes made.')
    finally:check.close()
    backup=root.parent/('fwg-pre-voipms-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir(mode=0o700)
    shutil.copy2(sip,backup/'pjsip.conf');shutil.copy2(dial,backup/'extensions.conf')
    # Preserve mounted file inodes. Existing bind mounts remain valid.
    sip.write_text(old_sip.rstrip()+'\n'+new);dial.write_text(old_dial.rstrip()+'\n'+DIALPLAN)
    print('Prepared TLS registration to '+SERVER+'. Backup: '+str(backup))
    print('Existing extension 700 is unchanged. Public calls remain disabled.')
    print('Enable Encrypted SIP Traffic for this VoIP.ms subaccount, then recreate Asterisk per README.')
if __name__=='__main__':main()
