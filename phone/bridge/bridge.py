import asyncio, audioop, base64, io, json, logging, os, struct, subprocess, urllib.request, wave
TOKEN=os.environ.get('PHONE_BRIDGE_TOKEN','')
URL='http://127.0.0.1:8099/internal/phone-turn'
active=asyncio.Lock()
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')

def ask(action,call,**fields):
    req=urllib.request.Request('http://127.0.0.1:8099/internal/phone-control',data=json.dumps({'action':action,'call':call,**fields}).encode(),headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=180) as r: result=json.load(r)
    if result.get('audio'):
        wav=base64.b64decode(result['audio'],validate=True)
        result['pcm']=subprocess.run(['ffmpeg','-v','error','-nostdin','-i','pipe:0','-ar','8000','-ac','1','-f','s16le','pipe:1'],input=wav,capture_output=True,check=True,timeout=20).stdout
    return result

async def frame(reader):
    header=await asyncio.wait_for(reader.readexactly(3),timeout=45)
    kind,length=struct.unpack('!BH',header)
    if length>8192: raise ValueError('Oversized AudioSocket frame')
    return kind,await reader.readexactly(length)

async def play(writer,pcm):
    clock=asyncio.get_running_loop().time()
    for offset in range(0,len(pcm),320):
        chunk=pcm[offset:offset+320]
        if len(chunk)<320: chunk+=b'\x00'*(320-len(chunk))
        writer.write(struct.pack('!BH',0x10,len(chunk))+chunk);await writer.drain()
        clock+=0.02
        await asyncio.sleep(max(0,clock-asyncio.get_running_loop().time()))

async def handle(reader,writer):
    import secrets
    acquired=False;task=None;cid=secrets.token_urlsafe(32)
    try:
        kind,payload=await frame(reader)
        if kind!=1 or len(payload)!=16:raise ValueError('Missing UUID')
        if active.locked():return
        await active.acquire();acquired=True
        processing=True;authenticated=False;pending=False;pin='';pcm=bytearray();quiet=0;voiced=0
        async def respond(action,**fields):
            nonlocal processing,authenticated,pending,pcm,quiet,voiced
            processing=True
            try:
                result=await asyncio.to_thread(ask,action,cid,**fields)
                if result.get('pcm'):await play(writer,result['pcm'])
                if 'authenticated' in result:authenticated=result['authenticated']
                if 'pending' in result:pending=result['pending']
                if action in ('cancel','confirm'):pending=False
                if pending:await asyncio.to_thread(ask,'arm',cid)
            except Exception as exc:
                logging.warning('Phone control failed: %s',type(exc).__name__)
                writer.close()
            finally:
                pcm=bytearray();quiet=0;voiced=0;processing=False
        task=asyncio.create_task(respond('begin'))
        deadline=asyncio.get_running_loop().time()+600
        while asyncio.get_running_loop().time()<deadline:
            kind,payload=await frame(reader)
            if kind in (0,255):break
            if processing:continue
            if kind==3 and len(payload)==1:
                digit=payload.decode('ascii',errors='ignore')
                if not authenticated:
                    if digit=='*':pin=''
                    elif digit.isdigit() and len(pin)<10:pin+=digit
                    elif digit=='#':
                        submitted=pin;pin='';processing=True
                        task=asyncio.create_task(respond('auth',pin=submitted))
                elif pending and digit in ('1','2'):
                    processing=True;task=asyncio.create_task(respond('confirm' if digit=='1' else 'cancel'))
                continue
            if kind!=16 or not authenticated or pending or not payload or len(payload)%2:continue
            duration=len(payload)/16000;loud=audioop.rms(payload,2)>=int(os.environ.get('VOICE_RMS','350'))
            if loud:voiced+=duration;quiet=0
            elif not pcm:continue
            else:quiet+=duration
            pcm.extend(payload)
            if (quiet>=1 and voiced>=0.24) or len(pcm)>=480000:
                out=io.BytesIO()
                with wave.open(out,'wb') as w:
                    w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(bytes(pcm))
                processing=True;task=asyncio.create_task(respond('turn',audio=base64.b64encode(out.getvalue()).decode()))
            elif quiet>=1:pcm.clear();quiet=0;voiced=0
    except (asyncio.IncompleteReadError,TimeoutError,ConnectionError):pass
    except Exception as exc:logging.warning('Call ended: %s',type(exc).__name__)
    finally:
        if task and not task.done():
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
        if acquired:
            try:await asyncio.to_thread(ask,'end',cid)
            except Exception:pass
            active.release()
        writer.close()
        try:await writer.wait_closed()
        except Exception:pass

async def main():
    if len(TOKEN)<40: raise RuntimeError('Run setup.py first')
    server=await asyncio.start_server(handle,'127.0.0.1',9092)
    logging.info('AudioSocket ready on loopback:9092')
    async with server: await server.serve_forever()
if __name__=='__main__': asyncio.run(main())
