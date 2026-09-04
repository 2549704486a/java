from __future__ import annotations

import unittest
from pathlib import Path

from pydantic import ValidationError
from langchain_core.messages import ToolMessage

from app.research.agents import (
    ResearchExecutionTraceHandler,
    ResearchToolSession,
    SingleResearchRunner,
)
from app.research.models import (
    AssetType,
    CandidateAsset,
    EvidenceClaim,
    ResearchAgentOutput,
    SourceExcerptSelection,
    SupportStatus,
    load_research_brief,
)
from app.research.web import FetchedPage, SearchHit


BRIEFS_DIR = Path(__file__).resolve().parents[1] / "research-data" / "briefs"


class FakeWebClient:
    def __init__(self) -> None:
        self.search_calls: list[str] = []
        self.fetch_calls: list[str] = []

    def search(self, query: str, *, max_results: int):
        self.search_calls.append(query)
        return [
            SearchHit(
                title="Official band",
                url="https://example.com/band",
                snippet=f"discovery only, max={max_results}",
            )
        ]

    def fetch(self, url: str):
        self.fetch_calls.append(url)
        return FetchedPage(
            requested_url=url,
            final_url=url,
            title="Official band",
            publisher="example.com",
            text="The official page states 5ATM water resistance.",
            content_type="text/html",
            response_bytes=100,
            redirect_count=0,
        )


class FakeToolCallingAgent:
    def __init__(self, session: ResearchToolSession, output: ResearchAgentOutput) -> None:
        self._tools = {item.name: item for item in session.tools}
        self._output = output

    def invoke(self, inputs, config):
        del inputs, config
        search_result = self._tools["search_public_web"].invoke(
            {"query": "official smart band specifications"}
        )
        url = search_result["results"][0]["url"]
        self._tools["read_public_page"].invoke({"url": url})
        return {
            "messages": [],
            "structured_response": self._output,
        }


class FakeCollectionAgent:
    def __init__(self, session: ResearchToolSession) -> None:
        self._tools = {item.name: item for item in session.tools}

    def invoke(self, inputs, config):
        del inputs, config
        self._tools["read_public_page"].invoke({"url": "https://example.com/band"})
        return {"messages": []}


class CapturingFinalizer:
    def __init__(self, output: ResearchAgentOutput) -> None:
        self.output = output
        self.inputs = None

    def invoke(self, inputs, config):
        del config
        self.inputs = inputs
        return {"messages": [], "structured_response": self.output}


class ResearchSingleAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = load_research_brief(BRIEFS_DIR / "pilot-mixed-v1.json")

    def output(self) -> ResearchAgentOutput:
        candidate = CandidateAsset(
            candidate_id="award-smart-band-001",
            brief_id=self.brief.brief_id,
            brief_version=self.brief.version,
            asset_type=AssetType.AWARD_CANDIDATE,
            name="公开智能手环候选",
            summary="官方页面提供了可核验的公开防水规格。",
            project_fit="可作为数码类奖品候选，库存和兑换参数仍需内部确认。",
            claims=[
                EvidenceClaim(
                    text="官方页面列出 5ATM 防水规格。",
                    source_ids=["source-page-001"],
                    support_status=SupportStatus.SUPPORTED,
                    review_note="页面正文直接支持。",
                )
            ],
        )
        return ResearchAgentOutput(
            brief_id=self.brief.brief_id,
            brief_version=self.brief.version,
            source_selections=[
                SourceExcerptSelection(
                    source_id="source-page-001",
                    excerpt_id="source-page-001-excerpt-001",
                )
            ],
            candidates=[candidate],
        )

    def test_agent_calls_only_read_only_tools_and_materializes_real_source(self):
        web_client = FakeWebClient()
        session = ResearchToolSession(self.brief, web_client)  # type: ignore[arg-type]
        agent = FakeToolCallingAgent(session, self.output())

        run = SingleResearchRunner(agent, session).run(
            self.brief,
            experiment_id="experiment-pilot",
            run_id="project-single-run-001",
        )

        self.assertEqual(
            ["search_public_web", "read_public_page"],
            [item.name for item in session.tools],
        )
        self.assertEqual(
            ["official smart band specifications"],
            web_client.search_calls,
        )
        self.assertEqual(["https://example.com/band"], web_client.fetch_calls)
        self.assertEqual("source-page-001", run.bundle.sources[0].source_id)
        self.assertEqual(2, run.summary.stages[0].tool_call_count)
        self.assertIsNone(run.summary.stages[0].input_tokens)
        self.assertIsNone(run.summary.stages[0].output_tokens)

    def test_invalid_structured_output_fails_instead_of_regex_repair(self):
        web_client = FakeWebClient()
        session = ResearchToolSession(self.brief, web_client)  # type: ignore[arg-type]

        class InvalidAgent:
            def invoke(self, inputs, config):
                del inputs, config
                return {
                    "messages": [],
                    "structured_response": {
                        "brief_id": "pilot-mixed",
                        "brief_version": "v1",
                        "source_selections": [],
                        "candidates": [],
                        "unexpected": True,
                    },
                }

        with self.assertRaises(ValidationError):
            SingleResearchRunner(InvalidAgent(), session).run(
                self.brief,
                experiment_id="experiment-pilot",
                run_id="project-single-run-002",
            )

    def test_collection_and_finalization_have_separate_tool_boundaries(self):
        web_client = FakeWebClient()
        session = ResearchToolSession(self.brief, web_client)  # type: ignore[arg-type]
        finalizer = CapturingFinalizer(self.output())

        run = SingleResearchRunner(
            FakeCollectionAgent(session),
            session,
            finalizer=finalizer,
        ).run(
            self.brief,
            experiment_id="experiment-pilot",
            run_id="project-single-run-finalized-001",
        )

        finalization_prompt = finalizer.inputs["messages"][0]["content"]
        self.assertIn("source-page-001-excerpt-001", finalization_prompt)
        self.assertEqual(1, run.summary.stages[0].tool_call_count)

    def test_structured_output_requires_excerpt_for_every_referenced_source(self):
        payload = self.output().model_dump(mode="json")
        payload["source_selections"] = []

        with self.assertRaisesRegex(ValidationError, "缺少摘录"):
            ResearchAgentOutput.model_validate(payload)

    def test_structured_output_allows_distinct_excerpts_from_one_source(self):
        payload = self.output().model_dump(mode="json")
        payload["source_selections"].append(
            {
                "source_id": "source-page-001",
                "excerpt_id": "source-page-001-excerpt-002",
            }
        )

        parsed = ResearchAgentOutput.model_validate(payload)
        self.assertEqual(2, len(parsed.source_selections))

        payload["source_selections"].append(payload["source_selections"][0])
        with self.assertRaisesRegex(ValidationError, "只能选择一次"):
            ResearchAgentOutput.model_validate(payload)

    def test_excerpt_id_must_belong_to_selected_source(self):
        payload = self.output().model_dump(mode="json")
        payload["source_selections"][0]["excerpt_id"] = (
            "source-page-002-excerpt-001"
        )

        with self.assertRaisesRegex(ValidationError, "必须属于所选来源"):
            ResearchAgentOutput.model_validate(payload)

    def test_trace_extracts_status_without_storing_tool_body(self):
        handler = ResearchExecutionTraceHandler()
        handler.on_tool_end(
            ToolMessage(
                content=(
                    '{"ok":false,"code":"NETWORK_ERROR",'
                    '"source_id":"source-page-003",'
                    '"untrusted_material":"page body"}'
                ),
                tool_call_id="tool-call-001",
            )
        )

        self.assertEqual(False, handler.events[0]["ok"])
        self.assertEqual("NETWORK_ERROR", handler.events[0]["code"])
        self.assertNotIn("untrusted_material", handler.events[0])

    def test_materialization_rejects_unknown_excerpt_id(self):
        web_client = FakeWebClient()
        session = ResearchToolSession(self.brief, web_client)  # type: ignore[arg-type]
        output = self.output().model_copy(
            update={
                "source_selections": [
                    SourceExcerptSelection(
                        source_id="source-page-001",
                        excerpt_id="source-page-001-excerpt-999",
                    )
                ]
            }
        )
        agent = FakeToolCallingAgent(session, output)

        with self.assertRaisesRegex(ValueError, "不存在的证据片段"):
            SingleResearchRunner(agent, session).run(
                self.brief,
                experiment_id="experiment-pilot",
                run_id="project-single-run-003",
            )


if __name__ == "__main__":
    unittest.main()
