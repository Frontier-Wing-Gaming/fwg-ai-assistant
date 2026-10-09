import asyncio,base64,hashlib,hmac,json,os,secrets,time
from fastapi import HTTPException,Request
import httpx

def install_phone_routes(app,ns):
    calls={};attempts=[]
    async def speech(text):return {'audio':await ns['protected_thread'](ns['audio_sentence'],text)}
    @app.post('/internal/phone-control')
    async def control(request:Request):
        token=os.environ.get('PHONE_BRIDGE_TOKEN','')
        if len(token)<40 or not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+token):raise HTTPException(401,'Unauthorized')
        if not ns['ready']:raise HTTPException(503,'Models loading')
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>750000:raise HTTPException(413,'Request too large')
        try:
            body=json.loads(raw);cid=body['call'];action=body['action']
            if not isinstance(cid,str) or not 30<=len(cid)<=80:raise ValueError()
        except Exception:raise HTTPException(400,'Invalid request')
        now=time.time()
        for old,c in list(calls.items()):
            if c['expires']<now:calls.pop(old,None)
        if action=='end':
            calls.pop(cid,None)
            for key,p in list(ns['pending'].items()):
                if p['session']=='phone:'+cid:ns['pending'].pop(key,None)
            return {}
        if ns['busy'].locked():raise HTTPException(429,'Assistant busy')
        async with ns['busy']:
            if action=='begin':
                if calls:raise HTTPException(429,'Phone already in use')
                calls[cid]={'expires':now+600,'authenticated':False,'attempts':0,'pending':None,'armed':False}
                return await speech('Welcome to Frontier Wing Gaming. Enter your phone PIN, then press pound.')
            c=calls.get(cid)
            if not c:raise HTTPException(403,'Call expired')
            username=os.environ.get('PHONE_USER','owner');user=ns['USERS'].get(username)
            if not user or user.get('disabled'):raise HTTPException(403,'Account disabled')
            if action=='auth':
                attempts[:]=[t for t in attempts if now-t<300]
                if c['attempts']>=3 or len(attempts)>=5:raise HTTPException(429,'PIN attempts exhausted')
                pin=body.get('pin','');salt=os.environ.get('PHONE_PIN_SALT','');digest=os.environ.get('PHONE_PIN_HASH','')
                if not isinstance(pin,str) or not pin.isdigit() or not 6<=len(pin)<=10 or not salt or not digest:
                    correct=False
                else:
                    hashed=await ns['protected_thread'](hashlib.pbkdf2_hmac,'sha256',pin.encode(),bytes.fromhex(salt),600000)
                    correct=hmac.compare_digest(hashed.hex(),digest)
                c['attempts']+=1
                if not correct:attempts.append(now)
                if correct:
                    c['authenticated']=True
                    return {**await speech('Authenticated. You can ask for server status, resource usage, console logs, or request an authorized power action.'),'authenticated':True}
                return {**await speech('Incorrect PIN. Try again, then press pound.'),'authenticated':False}
            if not c['authenticated']:raise HTTPException(403,'PIN required')
            if action=='turn':
                if c['pending']:ns['pending'].pop(c['pending'],None)
                c['pending']=None;c['armed']=False
                try:audio=base64.b64decode(body['audio'],validate=True)
                except Exception:raise HTTPException(400,'Invalid audio')
                result=await ns['protected_thread'](ns['prepare_turn'],'',audio,'chat','',username,user,'phone:'+cid)
                confirmation=result.get('confirmation')
                if confirmation:
                    c['pending']=confirmation['token']
                    text=confirmation['action'].capitalize()+' requested for '+confirmation['server']+'. After this message, press one to confirm, or two to cancel. No action has been taken.'
                else:text=result['answer']
                return {**await speech(text),'pending':bool(confirmation)}
            if action=='arm':
                p=ns['pending'].get(c['pending'])
                if not p or p['expires']<now:raise HTTPException(403,'Confirmation expired')
                c['armed']=True;return {}
            if action=='cancel':
                ns['pending'].pop(c['pending'],None);c['pending']=None;c['armed']=False
                return await speech('Power action cancelled. No action was taken.')
            if action=='confirm':
                key=c['pending'];p=ns['pending'].get(key)
                if not c['armed'] or not p or p['session']!='phone:'+cid or p['user']!=username or p['expires']<now:
                    raise HTTPException(403,'Confirmation unavailable')
                alias=p['server']
                power=p.get('action','restart')
                if power not in ('start','stop','restart') or not ns['permitted'](user,alias,power):raise HTTPException(403,'Power action denied')
                ns['pending'].pop(key,None);c['pending']=None;c['armed']=False
                p['action']=power
                result=await ns['execute_power'](p,ns,'phone')
                return await speech(result['message'])
            raise HTTPException(400,'Unknown action')
