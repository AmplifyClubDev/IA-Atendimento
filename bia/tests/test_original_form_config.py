"""A private form capability can only be handed to the approved original host."""
import unittest

from config import load_settings


class OriginalFormConfigTests(unittest.TestCase):
    def test_empty_setting_preserves_existing_private_form_host(self):
        settings = load_settings({})
        self.assertEqual(settings['form_public_url'], '')
        self.assertNotIn('form_public_url_invalid', settings['readiness_issues'])

    def test_only_approved_original_pilot_url_can_receive_form_capability(self):
        approved = 'https://amplify-cadastro.up.railway.app/cadastro/ensaio'
        settings = load_settings({'V5_FORM_PUBLIC_URL': approved})
        self.assertEqual(settings['form_public_url'], approved)
        self.assertNotIn('form_public_url_invalid', settings['readiness_issues'])
        for invalid in ('https://example.invalid/cadastro/ensaio', approved + '?next=other',
                        approved + '#s=other', approved.replace('https:', 'http:'),
                        approved.replace('.app/', '.app:444/'),
                        approved.replace('https://', 'https://user:pass@')):
            with self.subTest(url=invalid):
                settings = load_settings({'V5_FORM_PUBLIC_URL': invalid})
                self.assertIn('form_public_url_invalid', settings['readiness_issues'])
