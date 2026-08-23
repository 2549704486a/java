from __future__ import annotations

import unittest

from app.models import ToolEnvelope
from app.tools import build_tools


class ExchangeRecordClient:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int | None]] = []

    def list_exchange_records(self, user_id: int, award_id: int | None = None):
        self.calls.append((user_id, award_id))
        return ToolEnvelope(
            success=True,
            code="EXCHANGE_RECORDS_FOUND",
            data=[
                {
                    "orderId": 101,
                    "awardId": award_id or 6,
                    "awardName": "智能手表",
                    "status": "SUCCESS",
                    "statusMessage": "兑换成功",
                    "createTime": "2026-08-24T10:00:00",
                    "updateTime": "2026-08-24T10:00:01",
                }
            ],
            message="兑换记录查询成功",
        )


class ExchangeRecordsToolTest(unittest.TestCase):
    def test_queries_current_users_persisted_exchange_result(self):
        client = ExchangeRecordClient()
        tools = build_tools(client, 10)
        query = next(tool for tool in tools if tool.name == "list_my_exchange_records")

        result = query.invoke({"award_id": 6})

        self.assertEqual("EXCHANGE_RECORDS_FOUND", result["code"])
        self.assertEqual("SUCCESS", result["data"][0]["status"])
        self.assertEqual([(10, 6)], client.calls)


if __name__ == "__main__":
    unittest.main()
