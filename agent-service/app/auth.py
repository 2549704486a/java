from __future__ import annotations

import argparse
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from dotenv import load_dotenv

from app.config import Settings


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: int
    subject: str


class AuthenticationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class JwtAuthenticator:
    """验证访问令牌，并将不可篡改的 uid 声明转换为业务用户身份。"""

    def __init__(self, secret: str, issuer: str, audience: str) -> None:
        if len(secret) < 32:
            raise ValueError("AGENT_AUTH_SECRET 至少需要 32 个字符")
        self._secret = secret
        self._issuer = issuer
        self._audience = audience

    def authenticate(self, authorization: str | None) -> AuthenticatedUser:
        if not authorization:
            raise AuthenticationError("AUTH_REQUIRED", "请先提供访问令牌")

        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            raise AuthenticationError(
                "INVALID_AUTHORIZATION_HEADER",
                "Authorization 必须使用 Bearer 访问令牌",
            )

        try:
            claims = jwt.decode(
                token.strip(),
                self._secret,
                algorithms=["HS256"],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "uid"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("TOKEN_EXPIRED", "访问令牌已过期") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError("INVALID_TOKEN", "访问令牌无效") from exc

        user_id = claims.get("uid")
        subject = claims.get("sub")
        if (
            not isinstance(user_id, int)
            or isinstance(user_id, bool)
            or user_id <= 0
            or subject != f"user:{user_id}"
        ):
            raise AuthenticationError("INVALID_TOKEN_SUBJECT", "访问令牌身份无效")
        return AuthenticatedUser(user_id=user_id, subject=subject)

    def issue_token(self, user_id: int, ttl_seconds: int) -> str:
        if user_id <= 0:
            raise ValueError("user_id 必须是正整数")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds 必须大于 0")

        issued_at = datetime.now(UTC)
        claims = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": f"user:{user_id}",
            "uid": user_id,
            "iat": issued_at,
            "exp": issued_at + timedelta(seconds=ttl_seconds),
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(claims, self._secret, algorithm="HS256")


def authenticator_from_settings(settings: Settings) -> JwtAuthenticator:
    return JwtAuthenticator(
        settings.require_auth_secret(),
        settings.agent_auth_issuer,
        settings.agent_auth_audience,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="签发本地 Agent 演示访问令牌")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--ttl-seconds", type=int)
    args = parser.parse_args()

    load_dotenv()
    settings = Settings.from_env()
    authenticator = authenticator_from_settings(settings)
    ttl_seconds = args.ttl_seconds or settings.agent_access_token_ttl_seconds
    print(authenticator.issue_token(args.user_id, ttl_seconds))


if __name__ == "__main__":
    main()
