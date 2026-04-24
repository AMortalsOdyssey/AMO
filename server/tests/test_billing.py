import hmac
import unittest
from hashlib import sha256

from app.services.billing import build_mock_checkout_url, verify_creem_signature


class BillingServiceTests(unittest.TestCase):
    def test_verify_creem_signature_matches_sha256_hmac(self):
        payload = b'{"eventType":"checkout.completed","id":"evt_123"}'
        secret = "top-secret"
        signature = hmac.new(secret.encode("utf-8"), payload, sha256).hexdigest()

        self.assertTrue(verify_creem_signature(payload, signature, secret))
        self.assertFalse(verify_creem_signature(payload, "bad-signature", secret))

    def test_mock_checkout_url_targets_pricing_page(self):
        url = build_mock_checkout_url("amochk_demo")

        self.assertIn("/pricing", url)
        self.assertIn("mock_checkout_request_id=amochk_demo", url)


if __name__ == "__main__":
    unittest.main()
