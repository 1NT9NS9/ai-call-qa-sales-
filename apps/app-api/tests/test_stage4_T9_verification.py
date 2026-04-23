import importlib
import json
import shutil
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from conftest import (
    ALEMBIC_INI_PATH,
    TEST_TMP_ROOT,
    clear_src_modules,
    temporary_postgres_database,
)
from fastapi.testclient import TestClient
from sqlalchemy import insert


APPROVED_TOOL_NAMES = ["retrieve_context", "get_call_metadata"]
CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage4-t9",
    "source_type": "api",
    "metadata": {"campaign": "stage4", "channel": "sales"},
}
FIXED_TRANSCRIPT_SEGMENTS = [
    {
        "speaker": "customer",
        "text": "The pricing feels expensive and finance approval is moving slowly.",
        "start_ms": 0,
        "end_ms": 1200,
        "sequence_no": 1,
    },
    {
        "speaker": "agent",
        "text": "I can send ROI proof, approval guidance, and a mutual action plan.",
        "start_ms": 1200,
        "end_ms": 2600,
        "sequence_no": 2,
    },
]
VALID_ANALYSIS_RESULT = {
    "summary": "Customer raised pricing and approval concerns.",
    "score": 8.4,
    "score_breakdown": [
        {
            "criterion": "Discovery",
            "score": 4.0,
            "max_score": 5.0,
            "reason": "The rep identified the buyer's main blocker.",
        }
    ],
    "objections": [
        {
            "text": "Pricing feels expensive.",
            "handled": True,
            "evidence_segment_ids": [1],
        }
    ],
    "risks": [
        {
            "text": "Finance approval may delay the deal.",
            "severity": "medium",
            "evidence_segment_ids": [1],
        }
    ],
    "next_best_action": "Send ROI proof and a mutual action plan.",
    "coach_feedback": "Keep tying the proposal to approval urgency and value.",
    "used_knowledge": [
        {
            "document_id": 3,
            "chunk_id": 7,
            "reason": "Pricing objection guidance supported the recommendation.",
        }
    ],
    "confidence": 0.88,
    "needs_review": False,
    "review_reasons": [],
}


class _FakeBoundModel:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.invocations: list[object] = []

    def invoke(self, payload):
        self.invocations.append(payload)
        return SimpleNamespace(content=self._response_text)


class _FakeChatModel:
    def __init__(self, response_text: str) -> None:
        self.bound_tools = None
        self.bound_model = _FakeBoundModel(response_text)

    def bind_tools(self, tools):
        self.bound_tools = list(tools)
        return self.bound_model


def _tool_name(tool: object) -> str | None:
    if isinstance(tool, dict):
        if "name" in tool:
            return str(tool["name"])
        if "function" in tool and isinstance(tool["function"], dict):
            return str(tool["function"].get("name"))

    for attr_name in ("name", "tool_name", "__name__"):
        value = getattr(tool, attr_name, None)
        if isinstance(value, str) and value:
            return value

    if hasattr(tool, "func"):
        func = getattr(tool, "func")
        for attr_name in ("name", "tool_name", "__name__"):
            value = getattr(func, attr_name, None)
            if isinstance(value, str) and value:
                return value

    return None


class Stage4ApprovedToolBoundaryVerificationTests(unittest.TestCase):
    def test_stage4_bounded_analysis_run_uses_only_the_approved_tools(self) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage4-t9-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)

        try:
            with temporary_postgres_database("stage4_t9") as database_url:
                env_values = {
                    "APP_ENV": "test",
                    "APP_HOST": "127.0.0.1",
                    "APP_PORT": "8000",
                    "DATABASE_URL": database_url,
                    "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
                }

                with patch.dict("os.environ", env_values, clear=True):
                    alembic_config = Config(str(ALEMBIC_INI_PATH))
                    command.upgrade(alembic_config, "head")

                    clear_src_modules()
                    main_module = importlib.import_module("src.main")
                    analysis_service_module = importlib.import_module(
                        "src.application.analysis_service"
                    )
                    persistence_models = importlib.import_module(
                        "src.infrastructure.persistence.models"
                    )
                    app = main_module.create_app()

                    with TestClient(app) as client:
                        import_response = client.post("/knowledge/import")
                        embed_response = client.post("/knowledge/embed")
                        create_call_response = client.post(
                            "/calls",
                            json=CREATE_CALL_PAYLOAD,
                        )
                        self.assertEqual(import_response.status_code, 201)
                        self.assertEqual(embed_response.status_code, 200)
                        self.assertEqual(create_call_response.status_code, 201)

                        call_id = create_call_response.json()["id"]
                        with app.state.session_factory() as session:
                            session.execute(
                                insert(persistence_models.TranscriptSegment),
                                [
                                    {"call_id": call_id, **segment}
                                    for segment in FIXED_TRANSCRIPT_SEGMENTS
                                ],
                            )
                            call_session = session.get(
                                persistence_models.CallSession,
                                call_id,
                            )
                            call_session.processing_status = (
                                persistence_models.CallProcessingStatus.TRANSCRIBED
                            )
                            session.commit()

                        fake_chat_model = _FakeChatModel(
                            json.dumps(VALID_ANALYSIS_RESULT)
                        )
                        analysis_service = analysis_service_module.build_analysis_service(
                            session_factory=app.state.session_factory,
                            rag_service=app.state.rag_service,
                            chat_model=fake_chat_model,
                        )

                        self.assertEqual(
                            [definition["name"] for definition in analysis_service.tool_definitions()],
                            APPROVED_TOOL_NAMES,
                            "expected Stage 4 tool registration to expose only the approved tools before the analysis run",
                        )

                        invoked_tool_names: list[str] = []
                        original_invoke_tool = analysis_service.invoke_tool

                        def recording_invoke_tool(tool_name: str, **kwargs):
                            invoked_tool_names.append(tool_name)
                            return original_invoke_tool(tool_name, **kwargs)

                        analysis_service.invoke_tool = recording_invoke_tool
                        result_payload = analysis_service.analyze(call_id=call_id)

                self.assertIsInstance(
                    result_payload,
                    dict,
                    "expected the bounded Stage 4 analysis run to return a result payload",
                )
                self.assertEqual(
                    [_tool_name(tool) for tool in fake_chat_model.bound_tools],
                    APPROVED_TOOL_NAMES,
                    "expected LangChain tool binding during the Stage 4 analysis run to expose only the approved tools",
                )
                self.assertEqual(
                    sorted(set(invoked_tool_names)),
                    sorted(APPROVED_TOOL_NAMES),
                    "expected the bounded Stage 4 analysis run to invoke only retrieve_context and get_call_metadata while assembling analysis context",
                )
                self.assertEqual(
                    len(invoked_tool_names),
                    2,
                    "expected the bounded Stage 4 analysis run to invoke exactly the two approved tools once each",
                )
                self.assertEqual(
                    len(fake_chat_model.bound_model.invocations),
                    1,
                    "expected the bounded Stage 4 analysis run to invoke the model once on the happy path",
                )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
