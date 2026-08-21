from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

import jwt

from app.auth import AuthenticationError, JwtAuthenticator


TEST_SECRET = "unit-test-auth-secret-that-is-longer-than-32-characters"
TEST_ISSUER = "test-incentive-agent"
TEST_AUDIENCE = "test-incentive-web"


class JwtAuthenticatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.authenticator = JwtAuthenticator(
            TEST_SECRET,
            TEST_ISSUER,
            TEST_AUDIENCE,
        )

    def test_issued_token_restores_trusted_user_identity(self):
        token = self.authenticator.issue_token(10, 60)

        identity = self.authenticator.authenticate(f"Bearer {token}")

        self.assertEqual(10, identity.user_id)
        self.assertEqual("user:10", identity.subject)

    def test_rejects_missing_or_malformed_authorization_header(self):
        with self.assertRaises(AuthenticationError) as missing:
            self.authenticator.authenticate(None)
        with self.assertRaises(AuthenticationError) as malformed:
            self.authenticator.authenticate("Basic abc")

        self.assertEqual("AUTH_REQUIRED", missing.exception.code)
        self.assertEqual("INVALID_AUTHORIZATION_HEADER", malformed.exception.code)

    def test_rejects_expired_and_wrongly_signed_tokens(self):
        now = datetime.now(UTC)
        expired = jwt.encode(
            {
                "iss": TEST_ISSUER,
                "aud": TEST_AUDIENCE,
                "sub": "user:10",
                "uid": 10,
                "iat": now - timedelta(minutes=2),
                "exp": now - timedelta(minutes=1),
            },
            TEST_SECRET,
            algorithm="HS256",
        )
        wrong_signature = JwtAuthenticator(
            "another-test-secret-that-is-longer-than-32-characters",
            TEST_ISSUER,
            TEST_AUDIENCE,
        ).issue_token(10, 60)

        with self.assertRaises(AuthenticationError) as expired_error:
            self.authenticator.authenticate(f"Bearer {expired}")
        with self.assertRaises(AuthenticationError) as signature_error:
            self.authenticator.authenticate(f"Bearer {wrong_signature}")

        self.assertEqual("TOKEN_EXPIRED", expired_error.exception.code)
        self.assertEqual("INVALID_TOKEN", signature_error.exception.code)

    def test_rejects_inconsistent_subject_and_user_id(self):
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "iss": TEST_ISSUER,
                "aud": TEST_AUDIENCE,
                "sub": "user:11",
                "uid": 10,
                "iat": now,
                "exp": now + timedelta(minutes=1),
            },
            TEST_SECRET,
            algorithm="HS256",
        )

        with self.assertRaises(AuthenticationError) as error:
            self.authenticator.authenticate(f"Bearer {token}")

        self.assertEqual("INVALID_TOKEN_SUBJECT", error.exception.code)


if __name__ == "__main__":
    unittest.main()
