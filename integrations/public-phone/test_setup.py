import unittest
from setup import number, dialplan, patch_section, section

class Tests(unittest.TestCase):
    def test_number_normalization_and_injection_rejection(self):
        self.assertEqual(number('+1 (248) 555-0123'),'12485550123')
        self.assertEqual(number('2485550123'),'12485550123')
        for value in ['911','011442071234567','2485550123\nHangup()','2485550123;Dial(SIP/x)','1234567890','+124855501230']:
            with self.assertRaises(ValueError):number(value)

    def test_patch_preserves_credentials_and_other_endpoints(self):
        original='[1001]\ntype=endpoint\ncontext=fwg-internal\n\n[fwg-provider-auth]\nusername=test\npassword=fake-test-only\n\n[fwg-provider-disabled]\ntype=endpoint\ncontext=fwg-provider-disabled\nmedia_encryption=sdes\n'
        changed=patch_section(original,'fwg-provider-disabled',{'context':'fwg-public','aors':'fwg-provider-aor'})
        self.assertEqual(section(changed,'1001'),section(original,'1001'))
        self.assertEqual(section(changed,'fwg-provider-auth'),section(original,'fwg-provider-auth'))
        self.assertEqual(changed.count('context=fwg-public'),1)
        self.assertIn('media_encryption=sdes',changed)

    def test_public_routing_is_bounded_and_fixed_destination(self):
        text=dialplan('19475550123','12485550123',['12485550123','14165550123'],['12125550123'])
        self.assertLess(text.index('="12125550123"'),text.index('Read(FWG_SCREEN'))
        self.assertLess(text.index('="12485550123"'),text.index('Read(FWG_SCREEN'))
        self.assertIn('"${FWG_SCREEN}"="5"',text)
        self.assertIn('GROUP_COUNT(incoming@fwg-public)}>1',text)
        self.assertIn('TIMEOUT(absolute)=600',text)
        self.assertIn('Dial(PJSIP/12485550123@fwg-provider-disabled,30,iL(600000))',text)
        self.assertEqual(text.count('Dial('),1)
        self.assertNotIn('include =>',text)
        self.assertNotIn('Dial(PJSIP/${EXTEN}',text)
        self.assertIn('Goto(fwg-internal,700,1)',text)

if __name__=='__main__':unittest.main()
