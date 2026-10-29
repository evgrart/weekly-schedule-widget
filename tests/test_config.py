from tests import support
import json
from pathlib import Path
import unittest

import app_paths
import config_store


class ConfigurationTests(unittest.TestCase):
    def tearDown(self):
        config_store.CONFIG.unlink(missing_ok=True)

    def test_data_is_outside_checkout_and_defaults_have_no_account(self):
        self.assertFalse(app_paths.DATA_ROOT.is_relative_to(app_paths.CODE_ROOT))
        self.assertEqual(config_store.load_config()['feed_url'],'')

    def test_atomic_round_trip_and_invalid_refresh_fallback(self):
        config_store.save_config({'feed_url':'','refresh_seconds':1})
        self.assertEqual(config_store.load_config()['refresh_seconds'],60)
        config_store.CONFIG.write_text(json.dumps({'refresh_seconds':'invalid'}),encoding='utf-8')
        self.assertEqual(config_store.load_config()['refresh_seconds'],120)
        self.assertFalse(config_store.CONFIG.with_suffix('.tmp').exists())

    def test_rejects_non_google_and_embedded_credentials(self):
        self.assertFalse(config_store.valid_feed('https://example.com/calendar.ics'))
        self.assertFalse(config_store.valid_feed('https://user:pass@calendar.google.com/demo.ics'))
        self.assertFalse(config_store.valid_feed('javascript:alert(1)'))


if __name__=='__main__':
    unittest.main()
