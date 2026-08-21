from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import ValidationError

from app.api_client import BusinessApiClient, BusinessApiError
from app.confirmation_store import ConfirmationStatus, ConfirmationStore
from app.models import (
    AwardData,
    EligibilityData,
    ExchangePreparationData,
    ToolEnvelope,
)


logger = logging.getLogger(__name__)

ExchangeAction = Literal["CONFIRM", "CANCEL"]
_CONFIRM_PHRASES = {
    "确认",
    "确认兑换",
    "确定兑换",
    "我确认",
    "我确认兑换",
    "确认兑换该奖品",
    "就换这个",
    "就兑换这个",
}
_CANCEL_PHRASES = {
    "取消",
    "取消兑换",
    "不换了",
    "先不换了",
    "暂不兑换",
}


def explicit_exchange_action(message: str) -> ExchangeAction | None:
    """只识别保守白名单，避免把含糊的自然语言推断成高风险写授权。"""
    normalized = re.sub(r"[\s，。！？!?、]+", "", message).casefold()
    if normalized in _CONFIRM_PHRASES:
        return "CONFIRM"
    if normalized in _CANCEL_PHRASES:
        return "CANCEL"
    return None


class ControlledExchangeSkill:
    """将资格查询、一次性授权和旧链路写调用编排为受控状态机。"""

    def __init__(
        self,
        client: BusinessApiClient,
        confirmation_store: ConfirmationStore,
    ) -> None:
        self.client = client
        self.confirmation_store = confirmation_store

    def prepare(
        self,
        *,
        user_id: int,
        session_id: str,
        request_id: str,
        award_id: int,
    ) -> ToolEnvelope:
        try:
            eligibility_envelope = self.client.check_exchange_eligibility(
                user_id, award_id
            )
            if not eligibility_envelope.success:
                return eligibility_envelope
            eligibility = EligibilityData.model_validate(eligibility_envelope.data)
            if not eligibility.eligible:
                return ToolEnvelope(
                    success=False,
                    code=eligibility.reason_code,
                    data=eligibility.model_dump(mode="json", by_alias=True),
                    message=eligibility.reason,
                    retryable=False,
                )

            award_envelope = self.client.get_award_detail(award_id)
            if not award_envelope.success:
                return award_envelope
            award = AwardData.model_validate(award_envelope.data)
        except BusinessApiError as exc:
            return exc.as_envelope()
        except (TypeError, ValidationError, ValueError):
            return ToolEnvelope(
                success=False,
                code="INVALID_BUSINESS_RESPONSE",
                data=None,
                message="业务数据格式异常，当前无法发起兑换确认",
                retryable=False,
            )

        record = self.confirmation_store.create(
            user_id=user_id,
            session_id=session_id,
            award_id=award_id,
            award_name=award.name,
            current_points=eligibility.current_points,
            required_points=eligibility.required_points,
            request_id=request_id,
        )
        data = ExchangePreparationData(
            confirmationId=record.confirmation_id,
            status="AWAITING_CONFIRMATION",
            awardId=award_id,
            awardName=award.name,
            currentPoints=eligibility.current_points,
            requiredPoints=eligibility.required_points,
            remainingPoints=eligibility.current_points - eligibility.required_points,
            expiresAt=record.expires_at,
        )
        logger.info(
            "exchange_prepared request_id=%s user_id=%s session_id=%s award_id=%s",
            request_id,
            user_id,
            session_id,
            award_id,
        )
        return ToolEnvelope(
            success=True,
            code="EXCHANGE_CONFIRMATION_REQUIRED",
            data=data.model_dump(mode="json", by_alias=True),
            message="请核对奖品和积分消耗，并明确确认是否兑换",
            retryable=False,
        )

    def confirm(
        self,
        *,
        user_id: int,
        session_id: str,
        request_id: str,
        confirmation_id: str,
    ) -> ToolEnvelope:
        claim = self.confirmation_store.claim(
            confirmation_id,
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
        )
        if not claim.claimed:
            return ToolEnvelope(
                success=False,
                code=claim.code,
                data=None,
                message=self._confirmation_error_message(claim.code),
                retryable=False,
            )

        record = claim.record
        assert record is not None
        try:
            result = self.client.submit_exchange(
                user_id=user_id,
                award_id=record.award_id,
                request_id=request_id,
                idempotency_key=record.confirmation_id,
            )
        except BusinessApiError:
            self.confirmation_store.finish(
                confirmation_id,
                ConfirmationStatus.UNKNOWN,
                "SUBMISSION_UNKNOWN",
            )
            return self._submission_unknown()

        if result.code == "EXCHANGE_PROCESSING" and result.success:
            status = ConfirmationStatus.PROCESSING
        elif result.code in {"EXCHANGE_REJECTED", "ALREADY_REDEEMED"}:
            status = ConfirmationStatus.REJECTED
        else:
            self.confirmation_store.finish(
                confirmation_id,
                ConfirmationStatus.UNKNOWN,
                "SUBMISSION_UNKNOWN",
            )
            return self._submission_unknown()

        self.confirmation_store.finish(confirmation_id, status, result.code)
        logger.info(
            "exchange_confirmed request_id=%s user_id=%s session_id=%s award_id=%s result=%s",
            request_id,
            user_id,
            session_id,
            record.award_id,
            result.code,
        )
        return result

    def cancel(self, *, user_id: int, session_id: str) -> ToolEnvelope:
        cancelled = self.confirmation_store.cancel_pending(
            user_id=user_id,
            session_id=session_id,
        )
        return ToolEnvelope(
            success=True,
            code="EXCHANGE_CANCELLED" if cancelled else "NO_PENDING_CONFIRMATION",
            data={"cancelledCount": cancelled},
            message="已取消待确认兑换" if cancelled else "当前没有待确认兑换",
            retryable=False,
        )

    @staticmethod
    def _submission_unknown() -> ToolEnvelope:
        return ToolEnvelope(
            success=False,
            code="SUBMISSION_UNKNOWN",
            data=None,
            message="当前无法判断兑换请求是否已受理，请先到订单页面核对，不要立即重复兑换",
            retryable=False,
        )

    @staticmethod
    def _confirmation_error_message(code: str) -> str:
        if code == "CONFIRMATION_EXPIRED":
            return "兑换确认已过期，请重新发起兑换并核对最新条件"
        if code == "CONFIRMATION_ALREADY_USED":
            return "该兑换确认已使用或已取消，不会重复提交"
        if code == "CONFIRMATION_REQUIRES_NEW_TURN":
            return "请先核对本轮展示的兑换摘要，再通过下一条消息明确确认"
        return "当前会话没有可用的兑换确认，请重新发起兑换"
