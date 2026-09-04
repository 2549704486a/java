from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.research.artifacts import ResearchRunStore
from app.research.gates import evaluate_candidate_bundle
from app.research.models import (
    AssetType,
    CandidateAsset,
    CandidateBundle,
    EvidenceClaim,
    SourceDiscoveryMethod,
    SourceEvidence,
    SourceReadStatus,
    SupportStatus,
    load_research_brief,
)


BRIEFS_DIR = Path(__file__).resolve().parents[1] / "research-data" / "briefs"


class ResearchGatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = load_research_brief(BRIEFS_DIR / "official-awards-v1.json")
        self.source = SourceEvidence(
            source_id="source-product-001",
            url="https://example.com/product",
            title="Official product",
            publisher="example.com",
            retrieved_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
            discovered_by=SourceDiscoveryMethod.AGENT_SEARCH,
            excerpt="The product has a 1.6 inch display.",
            read_status=SourceReadStatus.READABLE,
        )

    def candidate(
        self,
        candidate_id: str,
        *,
        name: str = "公开智能手环",
        status: SupportStatus = SupportStatus.SUPPORTED,
        source_ids: list[str] | None = None,
        project_fit: str = "适合作为数码类候选，库存与兑换参数仍需内部确认。",
    ) -> CandidateAsset:
        return CandidateAsset(
            candidate_id=candidate_id,
            brief_id=self.brief.brief_id,
            brief_version=self.brief.version,
            asset_type=AssetType.AWARD_CANDIDATE,
            name=name,
            summary="公开页面可以证实该商品的显示屏规格。",
            project_fit=project_fit,
            claims=[
                EvidenceClaim(
                    text="该商品公开页面列出了显示屏规格。",
                    source_ids=source_ids or [self.source.source_id],
                    support_status=status,
                    review_note="正文直接支持该结论。",
                )
            ],
        )

    def test_reports_partial_failure_without_discarding_valid_candidate(self):
        good = self.candidate("award-band-001")
        unsupported = self.candidate(
            "award-band-002",
            name="另一款公开手环",
            status=SupportStatus.UNSUPPORTED,
        )
        bundle = CandidateBundle(
            brief_id=self.brief.brief_id,
            brief_version=self.brief.version,
            sources=[self.source],
            candidates=[good, unsupported],
        )

        report = evaluate_candidate_bundle(self.brief, bundle)

        self.assertEqual([good.candidate_id], report.approvable_candidate_ids)
        self.assertEqual([unsupported.candidate_id], report.rejected_candidate_ids)
        self.assertEqual(
            "CLAIM_NOT_FULLY_SUPPORTED",
            report.decisions[1].issues[0].code,
        )

    def test_rejects_unknown_source_duplicate_and_forbidden_project_fact(self):
        duplicate = self.candidate("award-band-002")
        unknown_source = self.candidate(
            "award-watch-003",
            name="公开智能手表",
            source_ids=["source-missing-999"],
        )
        forbidden_fact = self.candidate(
            "award-speaker-004",
            name="公开智能音箱",
            project_fit="适合作为数码奖品，当前项目库存为 100 件。",
        )
        bundle = CandidateBundle(
            brief_id=self.brief.brief_id,
            brief_version=self.brief.version,
            sources=[self.source],
            candidates=[
                self.candidate("award-band-001"),
                duplicate,
                unknown_source,
                forbidden_fact,
            ],
        )

        report = evaluate_candidate_bundle(self.brief, bundle)
        issue_codes = {
            issue.code for decision in report.decisions for issue in decision.issues
        }

        self.assertIn("DUPLICATE_CANDIDATE", issue_codes)
        self.assertIn("UNKNOWN_SOURCE_REFERENCE", issue_codes)
        self.assertIn("FORBIDDEN_PROJECT_FACT", issue_codes)

    def test_run_store_is_isolated_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "knowledge-manifest.json"
            activity_state = root / "activity-state.json"
            manifest.write_text('{"version":"unchanged"}', encoding="utf-8")
            activity_state.write_text('{"status":"RUNNING"}', encoding="utf-8")
            store = ResearchRunStore(root / "runs")

            with patch("pymysql.connect") as mysql_connect:
                run_dir = store.create_run_directory(
                    experiment_id="experiment-v1",
                    arm="PROJECT_SINGLE",
                    run_id="run-001",
                )
                output = store.write_json_once(run_dir, "bundle.json", {"ok": True})
                with self.assertRaises(FileExistsError):
                    store.write_json_once(run_dir, "bundle.json", {"ok": False})
                with self.assertRaises(FileExistsError):
                    store.create_run_directory(
                        experiment_id="experiment-v1",
                        arm="PROJECT_SINGLE",
                        run_id="run-001",
                    )

            mysql_connect.assert_not_called()
            self.assertEqual({"ok": True}, json.loads(output.read_text(encoding="utf-8")))
            self.assertEqual(
                '{"version":"unchanged"}',
                manifest.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                '{"status":"RUNNING"}',
                activity_state.read_text(encoding="utf-8"),
            )

    def test_run_store_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResearchRunStore(Path(temp_dir) / "runs")

            with self.assertRaisesRegex(ValueError, "安全的运行目录名"):
                store.create_run_directory(
                    experiment_id="../outside",
                    arm="PROJECT_SINGLE",
                    run_id="run-001",
                )


if __name__ == "__main__":
    unittest.main()
