"""Local account management. Restart assistant after changes."""
import argparse,getpass,hashlib,json,os,re,secrets,tempfile
from pathlib import Path
VALID={'status','resources','logs','start','stop','restart'}
def main():
 p=argparse.ArgumentParser();p.add_argument('command',choices=['init','add','grant','disable']);p.add_argument('username',nargs='?');p.add_argument('--actions');p.add_argument('--servers');p.add_argument('--restart',action='store_true');args=p.parse_args()
 root=Path(__file__).resolve().parent;path=root/'users.json';users=json.loads(path.read_text()) if path.exists() else {};servers=json.loads((root/'servers.json').read_text())
 name=(args.username or ('owner' if args.command=='init' else '')).lower()
 if not re.fullmatch('[a-z0-9_-]{1,40}',name):raise SystemExit('Provide a valid username.')
 if args.command=='disable':
  if name not in users:raise SystemExit('Unknown account.')
  users[name]['disabled']=True
 else:
  if args.command=='add' and name in users:raise SystemExit('Account exists; use grant or disable.')
  if args.command=='grant' and name not in users:raise SystemExit('Unknown account.')
  if args.command=='init' and users:raise SystemExit('users.json is already populated.')
  actions=[x.strip() for x in args.actions.split(',')] if args.actions else users.get(name,{}).get('actions',['status','resources','logs'])
  if args.restart:actions=list(dict.fromkeys(actions+['restart']))
  if not actions or any(x not in VALID for x in actions):raise SystemExit('Unknown or empty actions.')
  if args.servers:allowed=[x.strip() for x in args.servers.split(',')]
  elif args.command=='add':
   print('Available aliases: '+', '.join(servers));allowed=[x.strip() for x in input('Allowed aliases, comma separated (* for all): ').split(',')]
  else:allowed=users.get(name,{}).get('servers',['*'])
  if not allowed or any(x!='*' and x not in servers for x in allowed):raise SystemExit('Unknown or empty server selection.')
  if args.command=='grant':users[name]['actions']=actions;users[name]['servers']=allowed
  else:
   if args.command=='init':
    env={}
    for line in (root/'.env').read_text().splitlines():
     if '=' in line and not line.lstrip().startswith('#'):
      key,value=line.split('=',1);env[key.strip()]=value.strip().strip("\"'")
    salt,digest=env['PASSWORD_SALT'],env['PASSWORD_HASH']
   else:
    password=getpass.getpass('New password (14+ characters): ')
    if len(password)<14 or password!=getpass.getpass('Repeat password: '):raise SystemExit('Passwords do not match or are too short.')
    salt=secrets.token_hex(16);digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
   users[name]={'salt':salt,'hash':digest,'servers':allowed,'actions':actions,'disabled':False}
 fd,tmp=tempfile.mkstemp(dir=root)
 try:
  with os.fdopen(fd,'w') as file:json.dump(users,file,indent=2);file.write('\n')
  os.chmod(tmp,0o644);os.replace(tmp,path)
 finally:Path(tmp).unlink(missing_ok=True)
 print('Saved users.json. Run docker compose restart assistant in '+str(root))
if __name__=='__main__':main()
