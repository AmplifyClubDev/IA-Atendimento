"""The form-only relationship path is opt-in and restricted to the real pilot."""
import unittest

from config import load_settings


class FormRelationshipConfiguration30Tests(unittest.TestCase):
    def test_default_keeps_existing_flow(self):
        self.assertFalse(load_settings({})['relationship_check_in_form'])

    def test_new_mode_requires_real_pilot_and_original_form_namespace(self):
        values = {'V5_RELATIONSHIP_CHECK_IN_FORM': 'true', 'V5_TIKTOK_MODE': 'real',
                  'V5_TEST_PHONE': '+5547991154859', 'CHATWOOT_ACCOUNT_ID': '1',
                  'CHATWOOT_INBOX_ID': '3',
                  'V5_FORM_PUBLIC_URL': 'https://amplify-cadastro.up.railway.app/cadastro/ensaio'}
        self.assertNotIn('form_relationship_configuration_invalid', load_settings(values)['readiness_issues'])
        for key, value in [('V5_TIKTOK_MODE', 'simulated'), ('CHATWOOT_INBOX_ID', '4'),
                           ('V5_TEST_PHONE', '+5511999999999'), ('V5_FORM_PUBLIC_URL', '')]:
            with self.subTest(key=key):
                self.assertIn('form_relationship_configuration_invalid',
                              load_settings({**values, key: value})['readiness_issues'])


if __name__ == '__main__':
    unittest.main()
