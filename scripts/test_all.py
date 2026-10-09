#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
for folder,module in [('.', 'test_deploy'),('assistant','test_security'),('monitor','test_monitor'),
                      ('integrations/callshield','test_callshield'),('integrations/voipms','test_config'),
                      ('integrations/public-phone','test_setup')]:
    subprocess.run([sys.executable,'-m','unittest','-v',module],cwd=ROOT/folder,check=True)
print('All automated configuration/security tests passed; Docker/telephone acceptance tests are separate.')
