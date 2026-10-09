import unittest
from setup import make_config,DIALPLAN
class Tests(unittest.TestCase):
 def test_tls_and_disabled_routing(self):
  s=make_config('123456_fwgai','ExampleSecret12345','192.168.50.10','8.8.8.8')
  self.assertIn('verify_server=yes',s);self.assertIn('protocol=tls',s)
  self.assertIn('context=fwg-provider-disabled',s);self.assertIn('media_encryption_optimistic=no',s)
  self.assertNotIn('Dial(',DIALPLAN);self.assertNotIn('AudioSocket(',DIALPLAN)
  self.assertIn('Hangup(21)',DIALPLAN)
 def test_config_injection_rejected(self):
  for password in ['abcdefgh;evil','abcdefgh\n[global]','"abcdefgh"']:
   with self.assertRaises(ValueError):make_config('123456_fwgai',password,'192.168.50.10','8.8.8.8')
 def test_subaccount_and_public_ip_required(self):
  with self.assertRaises(ValueError):make_config('123456','ExampleSecret12345','192.168.50.10','8.8.8.8')
  with self.assertRaises(ValueError):make_config('123456_fwgai','ExampleSecret12345','192.168.50.10','192.168.1.1')
if __name__=='__main__':unittest.main()
