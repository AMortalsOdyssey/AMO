import unittest
from unittest.mock import patch

from app.core.config import settings
from app.services import auth as auth_service


class AuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.original_require_verified = settings.auth_require_verified_email
        settings.auth_require_verified_email = True

    def tearDown(self):
        settings.auth_require_verified_email = self.original_require_verified

    def test_normalize_email_strips_and_lowercases(self):
        self.assertEqual(
            auth_service.normalize_email("  USER@Example.COM "),
            "user@example.com",
        )

    @patch("app.services.auth.get_firebase_app", return_value=object())
    @patch("app.services.auth.firebase_auth.verify_id_token")
    def test_verify_identity_token_accepts_google_identity(self, verify_id_token_mock, _firebase_app_mock):
        verify_id_token_mock.return_value = {
            "uid": "firebase-user-1",
            "sub": "firebase-user-1",
            "email": "hanli@example.com",
            "email_verified": True,
            "name": "韩立",
            "picture": "https://example.com/avatar.png",
            "firebase": {
                "sign_in_provider": "google.com",
                "identities": {
                    "google.com": ["google-sub-123"],
                    "email": ["hanli@example.com"],
                },
            },
        }

        identity = auth_service.verify_identity_token("sample-token")

        self.assertEqual(identity.provider, "google.com")
        self.assertEqual(identity.provider_user_id, "google-sub-123")
        self.assertEqual(identity.email, "hanli@example.com")
        self.assertTrue(identity.email_verified)
        self.assertEqual(identity.display_name, "韩立")

    @patch("app.services.auth.get_firebase_app", return_value=object())
    @patch("app.services.auth.firebase_auth.verify_id_token")
    def test_verify_identity_token_rejects_unverified_email(self, verify_id_token_mock, _firebase_app_mock):
        verify_id_token_mock.return_value = {
            "uid": "firebase-user-2",
            "sub": "firebase-user-2",
            "email": "ziyan@example.com",
            "email_verified": False,
            "firebase": {
                "sign_in_provider": "password",
                "identities": {
                    "email": ["ziyan@example.com"],
                },
            },
        }

        with self.assertRaises(auth_service.AuthError) as ctx:
            auth_service.verify_identity_token("sample-token")

        self.assertEqual(ctx.exception.code, "email_not_verified")


if __name__ == "__main__":
    unittest.main()
