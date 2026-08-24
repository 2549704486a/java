from __future__ import annotations

import secrets
from dataclasses import dataclass

from app.auth import AuthenticationError
from app.config import Settings


@dataclass(frozen=True)
class AuthenticatedOperator:
    operator_id: str
    permissions: frozenset[str]


class OperatorPermissionError(Exception):
    pass


class OperatorAuthenticator:
    """运营入口使用独立不透明令牌，权限完全由服务端配置。"""

    def __init__(
        self,
        access_token: str | None,
        operator_id: str,
        permissions: frozenset[str],
    ) -> None:
        self._access_token = access_token
        self._operator_id = operator_id
        self._permissions = permissions

    def authenticate(self, authorization: str | None) -> AuthenticatedOperator:
        if not self._access_token:
            raise AuthenticationError(
                "OPERATOR_AUTH_NOT_CONFIGURED",
                "运营入口尚未配置访问令牌",
            )
        if not authorization:
            raise AuthenticationError("OPERATOR_AUTH_REQUIRED", "请提供运营访问令牌")
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            raise AuthenticationError(
                "INVALID_AUTHORIZATION_HEADER",
                "Authorization 必须使用 Bearer 访问令牌",
            )
        if not secrets.compare_digest(token.strip(), self._access_token):
            raise AuthenticationError("INVALID_OPERATOR_TOKEN", "运营访问令牌无效")
        return AuthenticatedOperator(self._operator_id, self._permissions)


def operator_authenticator_from_settings(settings: Settings) -> OperatorAuthenticator:
    return OperatorAuthenticator(
        settings.operator_access_token,
        settings.operator_id,
        settings.operator_permissions,
    )
