const el=id=>document.getElementById(id);
let recorder,stream,timer,running=false,pendingToken=null,audioQueue=[],playing=false,audioUrl;
const message=text=>{el('message').textContent=text;};
async function api(path,body){
 const r=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
 const d=await r.json();if(!r.ok){if(r.status===401){el('login').hidden=false;el('workspace').hidden=true;}throw new Error(d.detail||'Request failed');}return d;
}
async function config(){
 const c=await api('/api/config');el('login').hidden=true;el('workspace').hidden=false;
 el('readiness').textContent=c.ready?'Ready · signed in as '+c.user:c.failed?'Model setup failed; check logs':'Models loading…';
 const selected=el('server').value;el('server').replaceChildren();
 for(const [alias,name] of Object.entries(c.servers)){const o=document.createElement('option');o.value=alias;o.textContent=name;el('server').append(o);}
 if(selected&&[...el('server').options].some(o=>o.value===selected))el('server').value=selected;
 el('send').disabled=!c.ready||running;el('record').disabled=!c.ready||running;
}
function nextAudio(){
 if(playing||!audioQueue.length)return;
 playing=true;if(audioUrl)URL.revokeObjectURL(audioUrl);
 const binary=atob(audioQueue.shift());audioUrl=URL.createObjectURL(new Blob([Uint8Array.from(binary,c=>c.charCodeAt(0))],{type:'audio/wav'}));
 el('audio').src=audioUrl;el('audio').play().catch(()=>message('Press Play to hear the reply.'));
}
el('audio').onended=()=>{playing=false;nextAudio();};
async function turn(audio=''){
 running=true;el('send').disabled=true;el('record').disabled=true;pendingToken=null;el('confirmation').hidden=true;
 el('audio').pause();playing=false;audioQueue=[];message('Processing…');
 try{
  const r=await fetch('/api/turn',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:el('mode').value,server:el('server').value,text:el('text').value,audio})});
  if(!r.ok){const d=await r.json();throw new Error(d.detail||'Request failed');}
  const reader=r.body.getReader(),decoder=new TextDecoder();let buffer='';
  function event(e){
   if(e.type==='answer'){
    el('transcript').textContent=e.transcript;el('answer').textContent=e.answer;
    if(e.confirmation){pendingToken=e.confirmation.token;const action=e.confirmation.action||'restart';el('confirm-description').textContent=action+' '+e.confirmation.server+'? Confirmation expires in 90 seconds.';el('confirm-button').textContent='Confirm '+action;el('confirmation').hidden=false;}
   }else if(e.type==='audio'){audioQueue.push(e.audio);nextAudio();}
   else if(e.type==='done'){el('timings').textContent='First sentence audio ready: '+e.first_audio_ready_s.toFixed(2)+'s · all audio ready: '+e.all_audio_ready_s.toFixed(2)+'s';message('Reply ready.');}
   else if(e.type==='error')message(e.message);
  }
  while(true){const {value,done}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});let split;while((split=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,split);buffer=buffer.slice(split+1);if(line)event(JSON.parse(line));}if(done)break;}
 }catch(error){message(error.message);}finally{running=false;try{await config();}catch{}}
}
el('signin').onclick=async()=>{try{await api('/api/login',{username:el('username').value,password:el('password').value});el('password').value='';await config();message('Signed in.');}catch(e){message(e.message);}};
el('send').onclick=()=>turn();
el('logout').onclick=async()=>{await api('/api/logout',{});location.reload();};
el('confirm-button').onclick=async()=>{
 if(!pendingToken)return;const token=pendingToken;pendingToken=null;el('confirmation').hidden=true;
 try{const d=await api('/api/confirm',{token});message(d.message);}catch(e){message(e.message);}
};
el('cancel-button').onclick=()=>{pendingToken=null;el('confirmation').hidden=true;message('Cancelled in this browser. No restart sent.');};
el('record').onclick=async()=>{
 if(!navigator.mediaDevices||!window.MediaRecorder){message('Microphone requires HTTPS or localhost and a supported browser.');return;}
 try{
  el('audio').pause();audioQueue=[];playing=false;stream=await navigator.mediaDevices.getUserMedia({audio:true});recorder=new MediaRecorder(stream);const chunks=[];
  recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
  recorder.onstop=()=>{clearTimeout(timer);stream.getTracks().forEach(t=>t.stop());el('stop').disabled=true;const reader=new FileReader();reader.onload=()=>turn(String(reader.result).split(',')[1]);reader.readAsDataURL(new Blob(chunks,{type:recorder.mimeType}));};
  recorder.start();el('record').disabled=true;el('send').disabled=true;el('stop').disabled=false;message('Recording; stop when finished.');timer=setTimeout(()=>{if(recorder.state==='recording')recorder.stop();},30000);
 }catch(e){if(stream)stream.getTracks().forEach(t=>t.stop());message(e.message);}
};
el('stop').onclick=()=>{if(recorder?.state==='recording')recorder.stop();};
config().catch(()=>{});setInterval(()=>{if(!el('workspace').hidden&&!running&&recorder?.state!=='recording')config().catch(e=>message(e.message));},15000);
