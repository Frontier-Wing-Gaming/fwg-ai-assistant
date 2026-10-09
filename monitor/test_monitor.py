import datetime as dt
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import monitor

class MonitorTests(unittest.TestCase):
    def test_failure_recovery_debounce(self):
        state = {}
        for _ in range(2): self.assertEqual(monitor.update(state, {'x': (False, 'down')}), [])
        self.assertEqual(monitor.update(state, {'x': (False, 'down')})[0][1], True)
        state['checks']['x']['alerted'] = True
        self.assertEqual(monitor.update(state, {'x': (True, 'up')}), [])
        self.assertEqual(monitor.update(state, {'x': (True, 'up')})[0][1], False)

    def test_unsent_alert_retries_and_summary_once(self):
        config = {'webhook': 'not-a-real-webhook', 'timezone': 'America/New_York', 'summary_hour': 9}
        state = {}
        now = dt.datetime(2026, 10, 8, 10)
        with patch.object(monitor, 'checks', return_value={'x': (False, 'down')}):
            for _ in range(3): monitor.run(config, state, lambda *args: False, now)
            self.assertFalse(state['checks']['x']['alerted'])
            self.assertNotIn('last_summary', state)
            sent = []
            def notify(url, message): sent.append(message); return True
            monitor.run(config, state, notify, now)
            self.assertTrue(state['checks']['x']['alerted'])
            self.assertEqual(len(sent), 2)
            monitor.run(config, state, notify, now)
            self.assertEqual(len(sent), 2)

    def test_private_atomic_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'config.json'
            monitor.save(path, {'test': True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

if __name__ == '__main__': unittest.main()
