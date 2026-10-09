import asyncio, base64, hashlib, hmac, json, os, re, secrets, subprocess, sys, tempfile, time, wave
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ORIGIN=os.environ.get('APP_ORIGIN','http://localhost:8099').rstrip('/')
PANEL=os.environ.get('PTERO_URL','').rstrip('/')
KEY=os.environ.get('PTERO_CLIENT_KEY','')
OLLAMA=os.environ.get('OLLAMA_URL','http://ollama:11434')
VOICE_NAME=os.environ.get('PIPER_VOICE','en_US-ljspeech-high')
if not re.fullmatch(r'[A-Za-z0-9_-]+',VOICE_NAME): raise ValueError('Invalid PIPER_VOICE')
VOICE=Path('/cache/voices')/(VOICE_NAME+'.onnx')
sessions={}; attempts=[]; pending={}; busy=asyncio.Lock()
ready=False; startup_error=None

class PilotError(Exception): pass

from panel_tools import route as panel_route, execute_power

def validate_servers(data):
    if not isinstance(data,dict) or len(data)>30: raise ValueError('servers.json must be a map of at most 30 servers')
    for alias,item in data.items():
        if not re.fullmatch(r'[a-z0-9_-]{1,40}',alias): raise ValueError('Invalid server alias')
        if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not re.fullmatch(r'[A-Za-z0-9-]{8,36}',str(item.get('identifier',''))):
            raise ValueError('Replace every server identifier in servers.json; remove unused entries')
    return data

SERVERS=validate_servers(json.loads(Path('servers.json').read_text()))
USERS=json.loads(Path('users.json').read_text())
if not USERS: raise ValueError('Configure at least one user with accounts.py')

def same_origin(request):
    if request.headers.get('origin') != ORIGIN: raise HTTPException(403,'Browser origin does not match APP_ORIGIN')

def auth(request):
    token=request.cookies.get('fwg_session','')
    session=sessions.get(token)
    if not session or session['expires']<time.time():
        sessions.pop(token,None); raise HTTPException(401,'Sign in required')
    user=USERS.get(session['user'])
    if not user or user.get('disabled'): raise HTTPException(401,'Account disabled')
    return session['user'],user

def permitted(user,alias,action):
    return alias in SERVERS and (alias in user.get('servers',[]) or '*' in user.get('servers',[])) and action in user.get('actions',[])

def audit(username,action,alias,result):
    record={'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'user':username,'action':action,'server':alias,'result':result}
    with open('/state/actions.jsonl','a') as f:
        f.write(json.dumps(record)+'\n'); f.flush(); os.fsync(f.fileno())


def initialize():
    global recognizer,speaker,ready,startup_error
    try:
        print('Downloading/loading local models...',flush=True)
        with httpx.Client(timeout=600) as client:
            for _ in range(60):
                try: client.get(OLLAMA+'/api/tags').raise_for_status(); break
                except Exception: time.sleep(2)
            else: raise PilotError('Ollama unavailable')
            r=client.post(OLLAMA+'/api/pull',json={'model':'qwen3:1.7b','stream':False}); r.raise_for_status()
            if r.json().get('error'): raise PilotError('Model download failed')
        VOICE.parent.mkdir(parents=True,exist_ok=True)
        if not VOICE.exists() or not Path(str(VOICE)+'.json').exists():
            subprocess.run([sys.executable,'-m','piper.download_voices',VOICE_NAME,'--data-dir',str(VOICE.parent)],check=True)
        from faster_whisper import WhisperModel
        from piper import PiperVoice
        recognizer=WhisperModel('base.en',device='cpu',compute_type='int8',cpu_threads=1,num_workers=1,download_root='/cache/whisper')
        speaker=PiperVoice.load(str(VOICE))
        with httpx.Client(timeout=180) as client:
            r=client.post(OLLAMA+'/api/chat',json={'model':'qwen3:1.7b','stream':False,'think':False,'keep_alive':'30m','messages':[{'role':'user','content':'Say hello.'}],'options':{'num_predict':20,'num_thread':4,'num_ctx':2048}}); r.raise_for_status()
        ready=True; print('Pilot ready',flush=True)
    except Exception as exc:
        startup_error=type(exc).__name__
        print('Model initialization failed: '+startup_error+'; check connectivity/cache and restart',flush=True)

@asynccontextmanager
async def lifespan(app):
    task=asyncio.create_task(asyncio.to_thread(initialize))
    yield
    if not task.done(): task.cancel()

app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
app.mount('/static',StaticFiles(directory='static'),name='static')

@app.middleware('http')
async def headers(request,call_next):
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'"
    return response

@app.get('/')
async def home(): return FileResponse('static/index.html')

@app.get('/health')
async def health(): return JSONResponse({'ready':ready},status_code=200 if ready else 503)

@app.post('/api/login')
async def login(request:Request):
    same_origin(request)
    now=time.time(); attempts[:]=[t for t in attempts if t>now-60]
    if len(attempts)>=5: raise HTTPException(429,'Too many login attempts; wait one minute')
    attempts.append(now)
    raw=await request.body()
    if len(raw)>2048: raise HTTPException(413,'Login too large')
    try:
        login_data=json.loads(raw); password=login_data.get('password',''); username=login_data.get('username','owner')
        if not isinstance(username,str): raise ValueError()
        username=username.lower().strip()
    except Exception: raise HTTPException(400,'Invalid login')
    if not isinstance(password,str): raise HTTPException(400,'Invalid login')
    user=USERS.get(username,{})
    salt=user.get('salt',os.environ['PASSWORD_SALT'])
    digest=await asyncio.to_thread(hashlib.pbkdf2_hmac,'sha256',password.encode(),bytes.fromhex(salt),600000)
    if not user or user.get('disabled') or not hmac.compare_digest(digest.hex(),user.get('hash','')): raise HTTPException(401,'Incorrect username or password')
    for token,expiry in list(sessions.items()):
        if expiry['expires']<now: sessions.pop(token,None)
    if len(sessions)>100: sessions.clear()
    token=secrets.token_urlsafe(32); sessions[token]={'expires':now+8*3600,'user':username}
    response=JSONResponse({'ok':True}); response.set_cookie('fwg_session',token,max_age=8*3600,httponly=True,secure=ORIGIN.startswith('https://'),samesite='strict')
    return response

@app.post('/api/logout')
async def logout(request:Request):
    same_origin(request); sessions.pop(request.cookies.get('fwg_session',''),None)
    response=JSONResponse({'ok':True}); response.delete_cookie('fwg_session'); return response

@app.get('/api/config')
async def config(request:Request):
    username,user=auth(request)
    return {'user':username,'ready':ready,'failed':bool(startup_error),'servers':{alias:item['name'] for alias,item in SERVERS.items() if permitted(user,alias,'status')},'actions':user.get('actions',[])}

def status_answer(alias):
    if alias not in SERVERS: raise PilotError('Choose a configured server')
    item=SERVERS[alias]
    if urlsplit(PANEL).scheme!='https' or not KEY: return 'The Pterodactyl connection is not configured.'
    try:
        with httpx.Client(timeout=15,follow_redirects=False) as client:
            r=client.get(PANEL+'/api/client/servers/'+item['identifier']+'/resources',headers={'Authorization':'Bearer '+KEY,'Accept':'application/json'})
            r.raise_for_status(); a=r.json()['attributes']; resources=a.get('resources',{})
        state=a.get('current_state')
        if state not in ['running','offline','starting','stopping']: return 'The panel returned an unfamiliar state. Please check the panel.'
        text=f"{item['name']} is {state}."
        if a.get('is_suspended'): text+=' The panel reports it is suspended.'
        memory=resources.get('memory_bytes'); cpu=resources.get('cpu_absolute')
        if isinstance(memory,(int,float)) and isinstance(cpu,(int,float)):
            text+=f' Memory use is {memory/1024**3:.2f} gigabytes. CPU use is {cpu:.1f} percent.'
        return text+' This is the latest status reported by the panel.'
    except Exception:
        return 'I could not verify the server status with Pterodactyl. Please check panel connectivity and account permissions.'

OPERATIONAL=re.compile(r'\b(server|servers|minecraft|zomboid|restart|reboot|shutdown|container|containers|disk|logs|pterodactyl)\b',re.I)

def answer(text,mode,alias):
    if mode=='status': return status_answer(alias)
    if OPERATIONAL.search(text) or any(alias.lower() in text.lower() for alias in SERVERS):
        return 'For verified server information, select Server status and choose a server. For power actions, say start, stop, or restart followed by a server name. You can also request resource usage or recent console logs.'
    with httpx.Client(timeout=180) as client:
        r=client.post(OLLAMA+'/api/chat',json={'model':'qwen3:1.7b','stream':False,'think':False,'keep_alive':'30m','messages':[{'role':'system','content':'You are the Frontier Wing Gaming voice assistant. Answer in one or two short sentences, under 35 words. You have no tools, server access, current operational facts, or telephone access. Never claim to perform actions or report infrastructure status. Do not include reasoning.'},{'role':'user','content':text}], 'options':{'num_predict':100,'num_ctx':2048,'num_thread':4,'temperature':0}})
        r.raise_for_status(); result=r.json().get('message',{}).get('content','').strip()
    if not result or '<think>' in result or '</think>' in result: raise PilotError('Model did not return a usable response')
    return result

def pick_server(text,user):
    matches=[]
    for alias,item in SERVERS.items():
        if not permitted(user,alias,'status'): continue
        phrases=[alias.replace('_',' ').replace('-',' '),item['name']]+item.get('voice_names',[])
        if any(re.search(r'(?<!\w)'+re.escape(phrase)+r'(?!\w)',text,re.I) for phrase in phrases): matches.append(alias)
    return matches[0] if len(matches)==1 else None

def prepare_turn(text,audio,mode,alias,username,user,session_token):
    timings={}; begin=time.perf_counter()
    if audio:
        with tempfile.TemporaryDirectory() as directory:
            incoming=Path(directory)/'input'; incoming.write_bytes(audio); wav=Path(directory)/'input.wav'
            subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-i',str(incoming),'-t','30','-ar','16000','-ac','1','-c:a','pcm_s16le',str(wav)],check=True,timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            segments,_=recognizer.transcribe(str(wav),language='en',beam_size=1,vad_filter=False)
            text=' '.join(seg.text.strip() for seg in segments).strip()
        timings['transcription_s']=time.perf_counter()-begin
    if mode=='chat' and not text: raise PilotError('No speech recognized')
    confirmation=None; t=time.perf_counter()
    # Explicit server mode ignores speech; voice routing in chat never defaults to a dropdown target.
    if mode=='status':
        if not permitted(user,alias,'status'): raise PilotError('Server access denied')
        reply=status_answer(alias); audit(username,'status',alias,'queried')
    elif (routed := panel_route(text,username,user,session_token,globals())) is not None:
        reply,confirmation=routed
    elif re.search(r'\b(status|online|offline|running|memory|cpu)\b',text,re.I) and pick_server(text,user):
        target=pick_server(text,user); reply=status_answer(target); audit(username,'status',target,'queried')
    else: reply=answer(text,'chat',alias)
    timings['answer_s']=time.perf_counter()-t
    return {'transcript':text,'answer':reply,'confirmation':confirmation,'timings':timings}

def audio_sentence(text):
    with tempfile.TemporaryDirectory() as directory:
        out=Path(directory)/'answer.wav'
        with wave.open(str(out),'wb') as wav: speaker.synthesize_wav(text,wav)
        return base64.b64encode(out.read_bytes()).decode()

async def protected_thread(fn,*args):
    task=asyncio.create_task(asyncio.to_thread(fn,*args))
    try: return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Keep the one-turn lock until the underlying CPU task actually stops.
        await task
        raise

@app.post('/api/turn')
async def turn(request:Request):
    same_origin(request); username,user=auth(request)
    if not ready: raise HTTPException(503,'Models are not ready')
    if busy.locked(): raise HTTPException(429,'Assistant is busy; try again shortly')
    await busy.acquire()
    try:
        chunks=[]; size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>8*1024*1024: raise HTTPException(413,'Recording too large')
            chunks.append(chunk)
        try:
            body=json.loads(b''.join(chunks)); mode=body.get('mode','chat'); alias=body.get('server',''); text=body.get('text','')
            if mode not in ['chat','status'] or not isinstance(text,str) or len(text)>2000: raise ValueError()
            if mode=='status' and not permitted(user,alias,'status'): raise HTTPException(403,'Server access denied')
            encoded=body.get('audio',''); audio=base64.b64decode(encoded,validate=True) if encoded else None
        except HTTPException: raise
        except Exception: raise HTTPException(400,'Invalid request')
        start=time.perf_counter()
        result=await protected_thread(prepare_turn,text,audio,mode,alias,username,user,request.cookies.get('fwg_session'))
    except BaseException:
        busy.release(); raise
    async def events():
        try:
            yield json.dumps({'type':'answer',**result})+'\n'
            # Sentence chunks begin playback before later chunks finish synthesis.
            sentences=re.split(r'(?<=[.!?])\s+',result['answer'])
            for i,sentence in enumerate(sentences):
                clip=await protected_thread(audio_sentence,sentence)
                yield json.dumps({'type':'audio','audio':clip})+'\n'
                if i==0: first=time.perf_counter()-start
            yield json.dumps({'type':'done','first_audio_ready_s':first,'all_audio_ready_s':time.perf_counter()-start})+'\n'
        except Exception:
            yield json.dumps({'type':'error','message':'Speech processing failed; use the displayed answer.'})+'\n'
        finally: busy.release()
    return StreamingResponse(events(),media_type='application/x-ndjson')

@app.post('/api/confirm')
async def confirm(request:Request):
    same_origin(request); username,user=auth(request)
    raw=await request.body()
    if len(raw)>2048: raise HTTPException(413,'Request too large')
    try: token=json.loads(raw)['token']
    except Exception: raise HTTPException(400,'Invalid confirmation')
    if not isinstance(token,str): raise HTTPException(400,'Invalid confirmation token')
    entry=pending.get(token)
    if not entry or entry['user']!=username or entry['session']!=request.cookies.get('fwg_session') or entry['expires']<time.time():
        raise HTTPException(403,'Confirmation expired or does not belong to this session')
    alias=entry['server']
    action=entry.get('action','restart')
    if action not in ('start','stop','restart') or not permitted(user,alias,action): raise HTTPException(403,'Power action permission denied')
    pending.pop(token,None)  # Single use before network I/O, including on failed requests.
    entry['action']=action
    result=await execute_power(entry,globals(),'web')
    if not result['accepted']: raise HTTPException(502,result['message'])
    return {'message':result['message']}

from phone_api import install_phone_routes
install_phone_routes(app, globals())
