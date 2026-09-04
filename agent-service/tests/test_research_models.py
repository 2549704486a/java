from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.research.models import (
    AssetType,
    EvidenceClaim,
    ResearchBrief,
    ResearchPlan,
    SourceDiscoveryMethod,
    SourceEvidence,
    SourceReadStatus,
    SupportStatus,
    load_experiment_policy,
    load_research_brief,
)


BRIEFS_DIR = Path(__file__).resolve().parents[1] / "research-data" / "briefs"


class ResearchModelsTest(unittest.TestCase):
    def test_loads_pilot_and_three_official_briefs(self):
        paths = sorted(BRIEFS_DIR.glob("*.json"))

        briefs = [load_research_brief(path) for path in paths]

        self.assertEqual(4, len(briefs))
        self.assertEqual(3, sum(brief.run_kind.value == "OFFICIAL" for brief in briefs))
        self.assertEqual(1, sum(brief.run_kind.value == "PILOT" for brief in briefs))
        self.assertEqual(
            {
                AssetType.AWARD_CANDIDATE,
                AssetType.CAMPAIGN_PATTERN,
                AssetType.SEGMENT_RULE_TEMPLATE,
            },
            {target.asset_type for brief in briefs for target in brief.targets},
        )

    def test_brief_rejects_missing_required_field_invalid_enum_and_extra_field(self):
        valid = load_research_brief(BRIEFS_DIR / "official-awards-v1.json")
        payload = valid.model_dump(mode="json")

        missing = dict(payload)
        missing.pop("source_requirements")
        with self.assertRaises(ValidationError):
            ResearchBrief.model_validate(missing)

        invalid_enum = dict(payload)
        invalid_enum["run_kind"] = "PRODUCTION"
        with self.assertRaises(ValidationError):
            ResearchBrief.model_validate(invalid_enum)

        extra = dict(payload)
        extra["database_table"] = "award"
        with self.assertRaisesRegex(ValidationError, "Extra inputs are not permitted"):
            ResearchBrief.model_validate(extra)

    def test_brief_and_plan_enforce_quantity_boundaries(self):
        brief = load_research_brief(BRIEFS_DIR / "pilot-mixed-v1.json")
        payload = brief.model_dump(mode="json")
        payload["targets"][0]["target_count"] = 11
        with self.assertRaises(ValidationError):
            ResearchBrief.model_validate(payload)

        with self.assertRaises(ValidationError):
            ResearchPlan.model_validate(
                {
                    "brief_id": "pilot-mixed",
                    "brief_version": "v1",
                    "tasks": [
                        {
                            "task_id": f"task-{index}",
                            "focus_key": f"focus-{index}",
                            "objective": "研究一个相互独立的公开资料方向",
                            "asset_types": ["AWARD_CANDIDATE"],
                            "search_queries": ["official product"],
                            "max_pages": 1,
                        }
                        for index in range(4)
                    ],
                }
            )

    def test_readable_source_requires_actual_page_metadata_and_excerpt(self):
        with self.assertRaisesRegex(ValidationError, "可读来源必须包含"):
            SourceEvidence(
                source_id="source-demo-001",
                url="https://example.com/product",
                retrieved_at=datetime.now(timezone.utc),
                discovered_by=SourceDiscoveryMethod.AGENT_SEARCH,
                read_status=SourceReadStatus.READABLE,
            )

    def test_failed_source_cannot_carry_excerpt_ids(self):
        with self.assertRaisesRegex(ValidationError, "片段 ID"):
            SourceEvidence(
                source_id="source-demo-001",
                url="https://example.com/product",
                retrieved_at=datetime.now(timezone.utc),
                discovered_by=SourceDiscoveryMethod.AGENT_SEARCH,
                excerpt_ids=["source-demo-001-excerpt-001"],
                read_status=SourceReadStatus.NETWORK_ERROR,
            )

    def test_supported_and_conflicting_claims_require_sources(self):
        with self.assertRaisesRegex(ValidationError, "必须引用来源"):
            EvidenceClaim(
                text="公开页面给出了商品规格",
                support_status=SupportStatus.SUPPORTED,
                review_note="缺少引用",
            )
        with self.assertRaisesRegex(ValidationError, "至少两个来源"):
            EvidenceClaim(
                text="两个页面给出的价格口径存在冲突",
                source_ids=["source-demo-001"],
                support_status=SupportStatus.CONFLICTING,
                review_note="需要保留冲突",
            )

    def test_official_briefs_share_frozen_budget_and_policy_is_complete(self):
        policy = load_experiment_policy(
            BRIEFS_DIR.parent / "experiment-policy-v1.json"
        )
        briefs = [
            load_research_brief(BRIEFS_DIR / filename)
            for filename in policy.official_brief_files
        ]

        self.assertTrue(all(brief.run_kind.value == "OFFICIAL" for brief in briefs))
        self.assertTrue(all(brief.budget == policy.source_budget for brief in briefs))
        self.assertEqual(4, len(policy.arms))
        self.assertEqual(2, policy.retention_rule.required_brief_wins)
        self.assertEqual(
            2,
            policy.retention_rule.required_extra_approvable_candidates,
        )


if __name__ == "__main__":
    unittest.main()
