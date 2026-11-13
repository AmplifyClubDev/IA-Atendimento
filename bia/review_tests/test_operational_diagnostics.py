"""Read-only operational projection: allowlist, redaction, no external calls."""
from copy import deepcopy
import json
import socket
import unittest
from unittest.mock import patch
from operational_diagnostics import operation_diagnostics

class OperationalDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        for guard in [patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')),
                      patch.object(socket,'create_connection',side_effect=AssertionError('network forbidden'))]:
            guard.start();self.addCleanup(guard.stop)
    def test_invalid_cycle_empty(self):
        for value in [None, [], 'raw', {}, {'real_operations':[]}, {'real_operations':None}]:
            with self.subTest(value=value):self.assertEqual(operation_diagnostics(value,{}),{})
    def test_fixed_allowlist_never_raw_or_unknown_operations(self):
        cycle={'real_operations':{'invite':{'status':'failed','reason':'invitation_rejected','confirmed':False,
               'creator':'@private','payload':{'password':'dont_dump'},'evidence':{'http_status':422,
               'post_attempted':True,'create_accepted':False,'raw':'dont_dump','body':{'secret':'dont_dump'}}},
               'private_operation':{'status':'dont_dump'}}}
        result=operation_diagnostics(cycle,{})
        self.assertEqual(set(result),{'invite'})
        self.assertEqual(result['invite'],{'status':'failed','reason':'invitation_rejected','confirmed':False,
                        'http_status':422,'post_attempted':True,'create_accepted':False,'provider_detail_available':False})
        self.assertNotIn('dont_dump',json.dumps(result));self.assertNotIn('@private',json.dumps(result))
    def test_no_details_does_not_invent_provider_reason(self):
        row=operation_diagnostics({'real_operations':{'invite':{'status':'failed','evidence':{'http_status':422}}}}, {})['invite']
        self.assertFalse(row['provider_detail_available']);self.assertNotIn('provider_message',row);self.assertNotIn('provider_code',row)
    def test_known_secrets_urls_emails_headers_redacted(self):
        secret='synthetic-secret-123'
        cycle={'real_operations':{'invite':{'status':'failed','evidence':{'upstream_code':secret,
               'upstream_message':'token=abc123 bearer XYZ123 https://test.invalid/secret user@example.invalid '+secret}}}}
        result=operation_diagnostics(cycle,{'api_key':secret});text=json.dumps(result)
        for forbidden in [secret,'abc123','XYZ123','https://test.invalid','user@example.invalid']:
            self.assertNotIn(forbidden,text)
        self.assertNotIn('provider_code',result['invite'])
    def test_malformed_values_excluded(self):
        row=operation_diagnostics({'real_operations':{'invite':{'status':{'raw':'x'},'reason':True,'confirmed':1,
             'evidence':{'http_status':True,'provider_http_status':700,'post_attempted':1,'create_accepted':'true',
                         'upstream_code':'invalid code','receipt':{'version':True,'method':'api'}}}}},{})['invite']
        self.assertEqual(row,{'provider_detail_available':False})
    def test_bounded_message_no_mutation(self):
        cycle={'real_operations':{'invite':{'evidence':{'upstream_message':'a '*10000}}}}
        before=deepcopy(cycle);settings={'api_key':'secret_123456'};original=deepcopy(settings)
        row=operation_diagnostics(cycle,settings)['invite']
        self.assertLessEqual(len(row['provider_message']),200);self.assertEqual(cycle,before);self.assertEqual(settings,original)
    def test_receipt_projection_fixed_fields(self):
        receipt={'version':1,'method':'api','status':'create_rejected','stage':'provider_response',
                 'provider_http_status':422,'provider_code':'BAD_REQUEST','provider_message':'Rejected',
                 'raw_headers':{'Authorization':'forbidden'},'raw_payload':'forbidden'}
        row=operation_diagnostics({'real_operations':{'invite':{'evidence':{'receipt':receipt}}}},{})['invite']
        self.assertTrue(row['provider_detail_available']);self.assertNotIn('forbidden',json.dumps(row))
        self.assertEqual(row['receipt']['status'],'create_rejected')
    def test_receipt_stage_cannot_leak_known_secret(self):
        secret='secret_stage_123456'
        result=operation_diagnostics({'real_operations':{'invite':{'evidence':{'receipt':{
              'version':1,'method':'api','stage':secret}}}}},{'api_key':secret})
        self.assertNotIn(secret,json.dumps(result))

if __name__=='__main__': unittest.main()
