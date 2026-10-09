import base64
import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
import update
import lookup
from install import patch_dialplan

class Tests(unittest.TestCase):
    def setUp(self):
        self.key=ec.generate_private_key(ec.SECP256R1())
        self.keys=[base64.b64encode(self.key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).decode()]
        self.today=dt.date(2026,10,9)
    def feed(self,version=1,date='2026-10-09',count=1200):
        data=(f'# CallShield spam numbers, database version {version} (updated {date})\n'+
              '\n'.join('+1248555'+f'{i:04d}' for i in range(count))+'\n').encode()
        sig=base64.b64encode(self.key.sign(data,ec.ECDSA(hashes.SHA256())))
        return data,sig
    def test_signature_tampering_rejected(self):
        data,sig=self.feed()
        update.verify(data,sig,self.keys)
        with self.assertRaises(Exception):update.verify(data+b'\n',sig,self.keys)
        with self.assertRaises(Exception):update.verify(data,b'invalid-signature',self.keys)
    def test_failed_update_retains_previous_database(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);data,sig=self.feed(version=2)
            update.import_feed(folder,data,sig,self.keys,self.today)
            before=(folder/'numbers.sqlite').read_bytes()
            data,sig=self.feed(version=1)
            with self.assertRaises(ValueError):update.import_feed(folder,data,sig,self.keys,self.today)
            data,sig=self.feed(version=3,date='2026-01-01')
            with self.assertRaises(ValueError):update.import_feed(folder,data,sig,self.keys,self.today)
            self.assertEqual((folder/'numbers.sqlite').read_bytes(),before)
    def test_report_block_off_and_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);data,sig=self.feed();update.import_feed(folder,data,sig,self.keys,self.today)
            for mode,expected in [('report','REPORT'),('block','BLOCK'),('off','CLEAR')]:
                (folder/'mode.json').write_text(json.dumps({'mode':mode}))
                self.assertEqual(lookup.lookup('12485550001',folder,self.today),expected)
                self.assertEqual(lookup.lookup('12125550123',folder,self.today),'CLEAR')
            (folder/'mode.json').write_text('{invalid')
            self.assertEqual(lookup.lookup('12485550001',folder,self.today),'UNAVAILABLE')
            self.assertEqual(lookup.lookup('12485550001;DROP TABLE numbers',folder,self.today),'CLEAR')
            (folder/'mode.json').write_text('{"mode":"block"}')
            self.assertEqual(lookup.lookup('12485550001',folder,dt.date(2027,2,1)),'UNAVAILABLE')
    def test_hook_after_whitelist_before_screening_and_no_duplication(self):
        before='[fwg-internal]\nexten => 700,1,AudioSocket(test,127.0.0.1:9092)\n\n'
        body='[fwg-public-main]\nexten => s,1,NoOp()\n same => n,GotoIf($["${FWG_CID}"="12485550123"]?admin)\n same => n,Answer()\n same => n,Read(FWG_SCREEN,test,1,,1,8)\n same => n(admin),Goto(fwg-internal,700,1)\n same => n(blocked),Hangup(21)\n'
        result=patch_dialplan(before+body)
        self.assertTrue(result.startswith(before))
        self.assertLess(result.index('?admin)'),result.index('AGI('))
        self.assertLess(result.index('AGI('),result.index('Read(FWG_SCREEN'))
        self.assertIn('"${FWG_CS_RESULT}"="BLOCK"]?blocked',result)
        with self.assertRaises(ValueError):patch_dialplan(result)
        with self.assertRaises(ValueError):patch_dialplan(before)

if __name__=='__main__':unittest.main()
