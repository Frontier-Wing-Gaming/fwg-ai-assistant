import ast
import asyncio
import importlib.util
import json
from pathlib import Path
import re
import sys
import time
import types
import unittest
from unittest.mock import patch
import panel_tools as tools

class HTTPException(Exception):
    def __init__(self,status_code,detail): self.status_code=status_code;self.detail=detail

class Request:
    def __init__(self,body,cookie='web',token=None):
        self.data=json.dumps(body).encode();self.cookies={'fwg_session':cookie}
        self.headers={'authorization':'Bearer '+token} if token else {}
    async def body(self):return self.data
    async def stream(self):yield self.data

def functions():
    names={'permitted','pick_server','prepare_turn','confirm'}
    tree=ast.parse(Path('app.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    for n in nodes:n.decorator_list=[]
    ns={'re':re,'time':time,'json':json,'HTTPException':HTTPException,'Request':Request,'panel_route':tools.route,
        'execute_power':tools.execute_power}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'app.py','exec'),ns)
    ns['SERVERS']={'minecraft':{'name':'FWG Minecraft','identifier':'12345678'},'zomboid':{'name':'FWG Zomboid','identifier':'87654321'}}
    ns['user']={'servers':['minecraft'],'actions':['status','restart','start','stop','resources','logs']}
    ns['pending']={};ns['audit_records']=[]
    ns['audit']=lambda *args:ns['audit_records'].append(args)
    ns['status_answer']=lambda a:'verified status'
    ns['answer']=lambda *args:'No operational action.'
    ns['same_origin']=lambda r:None
    ns['auth']=lambda r:('owner',ns['user'])
    async def thread(fn,*args):return fn(*args)
    ns['protected_thread']=thread
    ns.update(PANEL='https://panel.example',KEY='fake-test-key',USERS={'owner':ns['user']},ready=True,busy=asyncio.Lock())
    return ns

class AsyncClient:
    posts=[];status=204;fail=False
    def __init__(self,**kwargs):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def post(self,url,**kwargs):
        self.posts.append((url,kwargs))
        if self.fail:raise TimeoutError()
        return types.SimpleNamespace(status_code=self.status)

class Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns=functions();self.ns['httpx']=types.SimpleNamespace(AsyncClient=AsyncClient)
        AsyncClient.posts=[];AsyncClient.status=204;AsyncClient.fail=False
    def turn(self,text):return self.ns['prepare_turn'](text,None,'chat','zomboid','owner',self.ns['user'],'web')

    def test_strict_intent_and_allowlist(self):
        for text in ['Do not stop Minecraft','Can you restart Minecraft?','Stop Minecraft and start Zomboid','Restart Zomboid','Stop Minecraft then delete backups','Kill Minecraft']:
            result=self.turn(text);self.assertIsNone(result['confirmation'],text)
        for verb in ['Start','Stop','Restart']:
            c=self.turn(verb+' Minecraft')['confirmation'];self.assertEqual(c['action'],verb.lower())
        self.assertEqual(AsyncClient.posts,[])

    async def test_web_replay_wrong_session_expiry_permission(self):
        c=self.turn('Stop Minecraft')['confirmation'];r=Request({'token':c['token']})
        with self.assertRaises(HTTPException):await self.ns['confirm'](Request({'token':c['token']},cookie='other'))
        self.ns['user']['actions'].remove('stop')
        with self.assertRaises(HTTPException):await self.ns['confirm'](r)
        self.assertEqual(AsyncClient.posts,[])
        self.ns['user']['actions'].append('stop')
        self.ns['pending'][c['token']]['expires']=time.time()-1
        with self.assertRaises(HTTPException):await self.ns['confirm'](r)
        c=self.turn('Stop Minecraft')['confirmation'];r=Request({'token':c['token']})
        await self.ns['confirm'](r)
        with self.assertRaises(HTTPException):await self.ns['confirm'](r)
        self.assertEqual(len(AsyncClient.posts),1)
        self.assertEqual(AsyncClient.posts[0][1]['json'],{'signal':'stop'})

    async def test_failure_consumes_confirmation_without_retry(self):
        for status,fail in [(403,False),(204,True)]:
            AsyncClient.status=status;AsyncClient.fail=fail
            c=self.turn('Start Minecraft')['confirmation'];r=Request({'token':c['token']})
            with self.assertRaises(HTTPException):await self.ns['confirm'](r)
            self.assertNotIn(c['token'],self.ns['pending'])
        self.assertEqual(len(AsyncClient.posts),2)
        self.assertTrue(any(x[-1]=='web_outcome_unknown' for x in self.ns['audit_records']))

    def test_resource_and_log_permissions(self):
        self.ns['user']['actions']=['status']
        with patch.object(tools,'console_answer') as logs,patch.object(tools,'resource_answer') as stats:
            self.turn('Minecraft console logs');self.turn('Minecraft resource usage')
            logs.assert_not_called();stats.assert_not_called()

    def test_console_redaction(self):
        line=tools.clean_line('\x1b[31msecret=abc password=xyz fake-test-key\x1b[0m',self.ns)
        for value in ['abc','xyz','fake-test-key','\x1b']:self.assertNotIn(value,line)

    def test_console_reads_only_and_closes(self):
        class Socket:
            sent=[];closed=False
            messages=[{'event':'auth success','args':[]}, {'event':'console output','args':['first\nsecond\nthird\nfourth']}]
            def __enter__(ws):return ws
            def __exit__(ws,*args):ws.closed=True
            def send(ws,value):ws.sent.append(json.loads(value))
            def recv(ws,**kwargs):
                if ws.messages:return json.dumps(ws.messages.pop(0))
                raise TimeoutError()
        ws=Socket()
        with patch.object(tools,'panel_get',return_value={'data':{'socket':'wss://node.example/api/servers/id/ws','token':'fake-ws-token'}}), patch('websockets.sync.client.connect',return_value=ws):
            answer=tools.console_answer('minecraft',self.ns)
        self.assertEqual([x['event'] for x in ws.sent],['auth','send logs'])
        self.assertTrue(ws.closed)
        self.assertNotIn('first',answer);self.assertIn('fourth',answer)
        self.assertNotIn('fake-ws-token',answer)

    async def test_phone_pin_arm_confirm_cancel(self):
        import hashlib
        fake=types.ModuleType('fastapi');fake.HTTPException=HTTPException;fake.Request=Request
        fake_http=types.ModuleType('httpx')
        with patch.dict(sys.modules,{'fastapi':fake,'httpx':fake_http}):
            spec=importlib.util.spec_from_file_location('phone_under_test','phone_api.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        class App:
            def post(app,path):
                def decorate(fn):app.control=fn;return fn
                return decorate
        app=App();self.ns['audio_sentence']=lambda text:text
        # Real routing, with transcription bypassed to isolate phone authentication.
        self.ns['prepare_turn']=lambda *args:self.turn('Start Minecraft')
        # Correct session binding is supplied by the phone handler to prepare_turn.
        self.ns['prepare_turn']=lambda text,audio,mode,alias,user,permissions,session: {'answer':'', 'confirmation':tools.route('Start Minecraft',user,permissions,session,self.ns)[1]}
        module.install_phone_routes(app,self.ns)
        cid='a'*32;token='b'*64;salt='11'*16;pin='123456'
        env={'PHONE_BRIDGE_TOKEN':token,'PHONE_USER':'owner','PHONE_PIN_SALT':salt,
             'PHONE_PIN_HASH':hashlib.pbkdf2_hmac('sha256',pin.encode(),bytes.fromhex(salt),600000).hex()}
        async def call(action,**kw):return await app.control(Request({'call':cid,'action':action,**kw},token=token))
        with patch.dict(module.os.environ,env):
            await call('begin')
            with self.assertRaises(HTTPException):await call('turn',audio='YQ==')
            self.assertTrue((await call('auth',pin=pin))['authenticated'])
            await call('turn',audio='YQ==')
            with self.assertRaises(HTTPException):await call('confirm')
            await call('arm');await call('cancel')
            self.assertEqual(AsyncClient.posts,[])
            await call('turn',audio='YQ==');await call('arm');await call('confirm')
            self.assertEqual(AsyncClient.posts[0][1]['json'],{'signal':'start'})
            with self.assertRaises(HTTPException):await call('confirm')

if __name__=='__main__':unittest.main()
