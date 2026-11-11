"""Preserve read API contracts while legacy write routes remain locked."""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import alpaca_trader as at
from mobile_api import app


class ApiContracts(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"MOBILE_API_KEY": "fixture-only"})
        self.environment.start()
        self.client = TestClient(app)
        self.auth = {"X-API-Key": "fixture-only"}

    def tearDown(self):
        self.client.close()
        self.environment.stop()

    def test_health_public_account_authenticated(self):
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertEqual(self.client.get('/positions').status_code, 401)
        with patch.dict(os.environ, {"MOBILE_API_KEY": ""}):
            self.assertEqual(self.client.get('/positions', headers=self.auth).status_code, 503)

    def test_empty_portfolio_and_failed_read_are_distinct(self):
        with patch.object(at, 'get_positions', return_value=[]):
            response = self.client.get('/positions', headers=self.auth)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), [])
        with patch.object(at, 'get_positions', side_effect=at.AlpacaReadError('HTTP 401', 401)):
            response = self.client.get('/positions', headers=self.auth)
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.json()['data_quality'], 'unavailable')

    def test_rest_order_and_cancel_never_reach_broker(self):
        with patch('requests.post', side_effect=AssertionError('unexpected write')), \
             patch('requests.delete', side_effect=AssertionError('unexpected write')):
            response = self.client.post('/orders', headers=self.auth,
                                        json={'symbol': 'SPY', 'qty': 1, 'side': 'buy'})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.client.delete('/orders/test', headers=self.auth).status_code, 400)


if __name__ == '__main__':
    unittest.main()
