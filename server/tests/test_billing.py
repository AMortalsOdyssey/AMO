import hmac
import unittest
from hashlib import sha256

from app.services.billing import (
    build_mock_checkout_url,
    calculate_refunded_credits,
    extract_refund_lookup,
    verify_creem_signature,
)


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

    def test_extract_refund_lookup_reads_transaction_order(self):
        lookup = extract_refund_lookup(
            {
                "id": "evt_refund",
                "eventType": "refund.created",
                "object": {
                    "id": "ref_123",
                    "refund_amount": 100,
                    "transaction": {
                        "status": "refunded",
                        "amount": 100,
                        "order": "ord_123",
                    },
                },
            }
        )

        self.assertEqual(lookup["refund_id"], "ref_123")
        self.assertEqual(lookup["order_id"], "ord_123")
        self.assertEqual(lookup["refund_amount_cents"], 100)
        self.assertEqual(lookup["transaction_status"], "refunded")

    def test_calculate_refunded_credits_prorates_partial_refund(self):
        credits = calculate_refunded_credits(
            checkout_amount_cents=100,
            credits_to_grant=1000,
            refund_amount_cents=25,
            transaction_amount_cents=100,
            transaction_status="partially_refunded",
        )

        self.assertEqual(credits, 250)

    def test_calculate_refunded_credits_revokes_all_on_refunded_status(self):
        credits = calculate_refunded_credits(
            checkout_amount_cents=100,
            credits_to_grant=1000,
            refund_amount_cents=25,
            transaction_amount_cents=100,
            transaction_status="refunded",
        )

        self.assertEqual(credits, 1000)


if __name__ == "__main__":
    unittest.main()
