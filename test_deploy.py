import json
from pathlib import Path
import tempfile
import unittest
import runpy
import shutil
import sys
from unittest.mock import patch
import common
import deploy

class DeploymentTests(unittest.TestCase):
    def test_fresh_setup_creates_owner_and_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)/'assistant';folder.mkdir()
            shutil.copy2(deploy.ROOT/'assistant/setup.py',folder/'setup.py')
            answers=['https://ai.example.com','https://panel.example.com','minecraft','Minecraft','1234abcd','','y']
            with patch('builtins.input',side_effect=answers),patch('getpass.getpass',side_effect=['test-key-only','a-test-password-123','a-test-password-123']):
                runpy.run_path(str(folder/'setup.py'),run_name='__main__')
            users=json.loads((folder/'users.json').read_text())
            self.assertIn('restart',users['owner']['actions'])
            self.assertEqual(users['owner']['servers'],['*'])
            self.assertNotIn('a-test-password-123',(folder/'users.json').read_text())
            self.assertEqual((folder/'.env').stat().st_mode & 0o777,0o600)
            self.assertEqual(folder.stat().st_mode & 0o777,0o700)
            original=(folder/'.env').read_text()
            with self.assertRaises(SystemExit):runpy.run_path(str(folder/'setup.py'),run_name='__main__')
            self.assertEqual((folder/'.env').read_text(),original)

    def test_fresh_phone_connects_same_token_and_hashes_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);phone=root/'phone';assistant=root/'assistant'
            phone.mkdir();assistant.mkdir()
            shutil.copy2(deploy.ROOT/'phone/setup.py',phone/'setup.py')
            (assistant/'.env').write_text("PTERO_CLIENT_KEY='test-key-only'\n")
            (assistant/'users.json').write_text('{"owner":{"disabled":false}}')
            argv=['setup.py','--assistant',str(assistant),'--ip','192.168.50.10','--cidr','192.168.50.0/24']
            with patch.object(sys,'argv',argv),patch('builtins.input',return_value=''),patch('getpass.getpass',return_value='123456'),patch('socket.socket'):
                runpy.run_path(str(phone/'setup.py'),run_name='__main__')
            a=common.read_env(assistant/'.env');b=common.read_env(phone/'.env')
            self.assertEqual(a['PHONE_BRIDGE_TOKEN'],b['PHONE_BRIDGE_TOKEN'])
            self.assertEqual(len(a['PHONE_BRIDGE_TOKEN']),64)
            self.assertNotIn('123456',(assistant/'.env').read_text())
            self.assertIn('permit=192.168.50.0/24',(phone/'config/pjsip.conf').read_text())
            self.assertEqual((phone/'softphone-settings.txt').stat().st_mode & 0o777,0o600)

    def test_env_update_preserves_unrelated_values_and_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory)/'.env'
            env.write_text("# retained\nSECRET='existing'\nPIPER_VOICE='old'\n")
            common.set_env(env,{'PIPER_VOICE':'new'})
            self.assertEqual(common.read_env(env),{'SECRET':'existing','PIPER_VOICE':'new'})
            self.assertEqual(env.stat().st_mode & 0o777,0o600)
            with self.assertRaises(ValueError): common.set_env(env,{'BAD':'value\nINJECTED=yes'})
            self.assertEqual(common.read_env(env)['SECRET'],'existing')

    def fixture(self, directory):
        root=Path(directory);source=root/'release';target=root/'live'
        (source/'assistant/static').mkdir(parents=True);(target/'static').mkdir(parents=True)
        for name in ['app.py','phone_api.py','panel_tools.py','Dockerfile','accounts.py']:
            (source/'assistant'/name).write_text('new '+name)
            (target/name).write_text('old '+name)
        (source/'assistant/static/app.js').write_text('new ui');(target/'static/app.js').write_text('old ui')
        originals={'.env':"SECRET='test-only'\n",'users.json':'{"owner":{}}','servers.json':'{}','compose.yaml':'existing volume names'}
        for name,text in originals.items():(target/name).write_text(text)
        return root,source,target,originals

    def test_failed_update_restores_code_credentials_and_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root,source,target,originals=self.fixture(directory)
            def fail_build(folder,*args):
                if args and args[0]=='up':raise RuntimeError('simulated build failure')
            with patch.object(deploy,'ROOT',source),patch.object(deploy,'preflight'),patch.object(deploy,'compose',side_effect=fail_build):
                with self.assertRaises(RuntimeError):deploy.code_update(target,root/'no-phone',root/'no-monitor')
            for name,text in originals.items():self.assertEqual((target/name).read_text(),text)
            self.assertEqual((target/'app.py').read_text(),'old app.py')
            self.assertEqual((target/'static/app.js').read_text(),'old ui')

    def test_update_does_not_copy_compose_or_private_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root,source,target,originals=self.fixture(directory)
            originals['.env']="PIPER_VOICE='custom'\nSECRET='test-only'\n";(target/'.env').write_text(originals['.env'])
            with patch.object(deploy,'ROOT',source),patch.object(deploy,'preflight'),patch.object(deploy,'compose') as compose,patch.object(deploy,'wait_ready'):
                deploy.code_update(target,root/'no-phone',root/'no-monitor')
            for name,text in originals.items():self.assertEqual((target/name).read_text(),text)
            self.assertFalse(any('down' in call.args or '-v' in call.args for call in compose.call_args_list))

if __name__=='__main__':unittest.main()
