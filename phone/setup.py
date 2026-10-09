"""Fresh LAN phone configuration with PIN authentication."""
import argparse, getpass, ipaddress, json, pathlib, secrets, socket, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from common import password_hash, private_write, set_env
p=argparse.ArgumentParser();p.add_argument('--assistant',required=True);p.add_argument('--ip',required=True);p.add_argument('--cidr',required=True);args=p.parse_args()
root=pathlib.Path(__file__).resolve().parent;target=pathlib.Path(args.assistant).resolve()
ip=ipaddress.ip_address(args.ip);network=ipaddress.ip_network(args.cidr,strict=False)
if ip.version!=4 or not ip.is_private or network.version!=4 or ip not in network or not network.is_private:
 raise SystemExit('Use a private LAN IPv4 and its private subnet CIDR.')
if (root/'config').exists():raise SystemExit('Phone config exists; keep existing credentials. No changes made.')
users=json.loads((target/'users.json').read_text())
user=input('Phone account [owner]: ').strip() or 'owner'
if user not in users or users[user].get('disabled'):raise SystemExit('An active assistant account is required.')
pin=getpass.getpass('New phone PIN (6–10 digits): ')
if not pin.isascii() or not pin.isdigit() or not 6<=len(pin)<=10 or pin!=getpass.getpass('Repeat PIN: '):raise SystemExit('Invalid PIN or mismatch.')
checks=[(socket.SOCK_DGRAM,5060,str(ip)),(socket.SOCK_STREAM,9092,'127.0.0.1')]
checks += [(socket.SOCK_DGRAM,port,'0.0.0.0') for port in range(10000,10020)]
for proto,port,address in checks:
 s=socket.socket(socket.AF_INET,proto)
 try:s.bind((address,port))
 except OSError:raise SystemExit('Port unavailable: '+str(port))
 finally:s.close()
token=secrets.token_hex(32);password=secrets.token_urlsafe(24)
config=root/'config';config.mkdir(mode=0o700)
def save(name,text):private_write(config/name,text,0o644)
save('pjsip.conf',f'''[transport-udp]
type=transport
protocol=udp
bind={ip}:5060

[1001]
type=endpoint
transport=transport-udp
context=fwg-internal
disallow=all
allow=ulaw,alaw
auth=1001-auth
aors=1001
callerid=FWG Owner <1001>
direct_media=no
force_rport=yes
rewrite_contact=yes
rtp_symmetric=yes
dtmf_mode=rfc4733
deny=0.0.0.0/0
permit={network}

[1001-auth]
type=auth
auth_type=userpass
username=1001
password={password}

[1001]
type=aor
max_contacts=1
remove_existing=yes
qualify_frequency=30
''')
save('extensions.conf','''[general]
static=yes
writeprotect=yes

[fwg-internal]
exten => 700,1,Answer()
 same => n,Wait(1)
 same => n,AudioSocket(550e8400-e29b-41d4-a716-446655440000,127.0.0.1:9092)
 same => n,Hangup()
''')
save('rtp.conf','[general]\nrtpstart=10000\nrtpend=10019\nstrictrtp=yes\nicesupport=no\n')
save('modules.conf','[modules]\nautoload=yes\nnoload=chan_sip.so\nnoload=chan_iax2.so\nnoload=chan_skinny.so\nnoload=chan_mgcp.so\nnoload=chan_unistim.so\n')
save('http.conf','[general]\nenabled=no\n')
save('manager.conf','[general]\nenabled=no\n')
save('logger.conf','[general]\n[logfiles]\nconsole => warning,error,notice\n')
set_env(root/'.env',{'PHONE_BRIDGE_TOKEN':token})
salt,digest=password_hash(pin)
set_env(target/'.env',{'PHONE_BRIDGE_TOKEN':token,'PHONE_USER':user,'PHONE_PIN_SALT':salt,'PHONE_PIN_HASH':digest})
private_write(root/'softphone-settings.txt',f'Username/authentication ID: 1001\nPassword: {password}\nDomain/SIP server: {ip}\nPort: 5060\nTransport: UDP\nProxy: none\nSTUN/ICE: disable for LAN\nDial: 700\nPhone account: {user} (PIN required)\n')
print('LAN phone configured. SIP settings are in phone/softphone-settings.txt; keep this file private.')
