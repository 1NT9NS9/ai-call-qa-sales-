import importlib
import inspect
import json
import shutil
import unittest
import uuid
from pathlib import Path
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


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_API_ROOT = REPO_ROOT / "apps" / "app-api"
REQUIREMENTS_PATH = APP_API_ROOT / "requirements.txt"
APPROVED_TOOL_NAMES = ["retrieve_context", "get_call_metadata"]
ANALYSIS_METHOD_NAMES = (
    "analyze",
    "run_analysis",
    "invoke_analysis",
    "execute_analysis",
)
MODEL_PARAMETER_NAMES = (
    "llm",
    "chat_model",
    "model",
    "analysis_model",
    "llm_model",
)
FIXED_TRANSCRIPT_SEGMENTS = [
    {
        "speaker": "customer",
        "text": "The pricing feels expensive and our budget needs internal approval.",
        "start_ms": 0,
        "end_ms": 1000,
        "sequence_no": 1,
    },
    {
        "speaker": "agent",
        "text": "We should focus on value, approval steps, and the cost of inaction.",
        "start_ms": 1000,
        "end_ms": 2000,
        "sequence_no": 2,
    },
]
CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage4-t4",
    "source_type": "api",
    "metadata": {"campaign": "stage4", "channel": "sales"},
}
VALID_ANALYSIS_OUTPUT = {
    "summary": "Customer raised pricing and approval concerns.",
    "score": 7.5,
    "score_breakdown": [
        {
            "criterion": "Discovery",
            "score": 3.0,
            "max_score": 5.0,
            "reason": "Some context gathered.",
        }
    ],
    "objections": [
        {
            "text": "Pricing is expensive.",
            "handled": True,
            "evidence_segment_ids": [1],
        }
    ],
    "risks": [
        {
            "text": "Internal approval may stall.",
            "severity": "medium",
            "evidence_segment_ids": [1],
        }
    ],
    "next_best_action": "Send a mutual action plan.",
    "coach_feedback": "Tie value to approval process.",
    "used_knowledge": [
        {
            "document_id": 3,
            "chunk_id": 7,
            "reason": "Pricing objection guidance applied.",
        }
    ],
    "confidence": 0.82,
    "needs_review": False,
    "review_reasons": [],
}


class _FakeBoundLLM:
    def __init__(self, parent, tools):
        self._parent = parent
        self._tools = tools

    def invoke(self, payload):
        self._parent.invocations.append(payload)
        return {
            "content": json.dumps(VALID_ANALYSIS_OUTPUT),
            "tool_names": [_tool_name(tool) for tool in self._tools],
        }


class _FakeLangChainModel:
    def __init__(self) -> None:
        self.bound_tools = None
        self.invocations: list[object] = []

    def bind_tools(self, tools):
        self.bound_tools = list(tools)
        return _FakeBoundLLM(self, self.bound_tools)

    def invoke(self, payload):
        self.invocations.append(payload)
        return {"content": json.dumps(VALID_ANALYSIS_OUTPUT)}


class _FakeSessionContext:
    def __init__(self, call_session):
        self._call_session = call_session

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def scalars(self, *_args, **_kwargs):
        return []

    def get(self, *_args, **_kwargs):
        return self._call_session


class _FakeSessionFactory:
    def __init__(self, call_session):
        self._call_session = call_session

    def __call__(self):
        return _FakeSessionContext(self._call_session)


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

    if hasattr(tool, "definition"):
        definition = getattr(tool, "definition")
        value = getattr(definition, "name", None)
        if isinstance(value, str) and value:
            return value

    return None


def _analysis_service_module():
    module_name = "src.application.analysis_service"
    clear_src_modules()
    return importlib.import_module(module_name)


def _find_analysis_method(service: object):
    for method_name in ANALYSIS_METHOD_NAMES:
        method = getattr(service, method_name, None)
        if callable(method):
            return method_name, method

    raise AssertionError(
        "AnalysisService does not expose a Stage 4 analysis execution entry point. "
        f"Expected one of {list(ANALYSIS_METHOD_NAMES)}."
    )


def _build_service_with_fake_model(
    *,
    session_factory,
    rag_service,
    fake_model,
):
    analysis_service_module = _analysis_service_module()
    build_service = analysis_service_module.build_analysis_service
    signature = inspect.signature(build_service)

    kwargs = {}
    unsupported_required: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.name == "session_factory":
            kwargs["session_factory"] = session_factory
            continue
        if parameter.name == "rag_service":
            kwargs["rag_service"] = rag_service
            continue
        if parameter.name in MODEL_PARAMETER_NAMES:
            kwargs[parameter.name] = fake_model
            continue
        if parameter.default is inspect._empty:
            unsupported_required.append(parameter.name)

    if unsupported_required:
        raise AssertionError(
            "Could not build AnalysisService for T4 with bounded fakes; "
            f"unsupported required parameters: {unsupported_required}"
        )

    return build_service(**kwargs)


def _invoke_analysis(method, call_id: int):
    try:
        return method(call_id=call_id)
    except TypeError:
        return method(call_id)


class Stage4LangChainAnalysisServiceTests(unittest.TestCase):
    def test_stage4_requirements_include_langchain_dependency(self) -> None:
        requirements_text = REQUIREMENTS_PATH.read_text(encoding="utf-8").lower()
        self.assertIn(
            "langchain",
            requirements_text,
            "expected Stage 4 to declare a LangChain dependency in requirements.txt",
        )

    def test_stage4_analysis_service_exposes_analysis_execution_entry_point(self) -> None:
        analysis_service_module = _analysis_service_module()
        service = analysis_service_module.AnalysisService()

        method_name, _ = _find_analysis_method(service)

        self.assertIn(
            method_name,
            ANALYSIS_METHOD_NAMES,
            "expected AnalysisService to expose a Stage 4 analysis execution method",
        )

    def test_stage4_analysis_service_binds_only_approved_tools_for_langchain_invocation(
        self,
    ) -> None:
        from src.services.rag import RetrievedKnowledgeChunk

        fake_model = _FakeLangChainModel()
        rag_service = SimpleNamespace(
            search_for_call=lambda call_id, limit=5: [
                RetrievedKnowledgeChunk(
                    chunk_id=7,
                    document_id=3,
                    source_path="data/kb_seed/objection-handling-pricing.md",
                    chunk_text="Handle pricing objections by reframing value.",
                    chunk_index=0,
                    distance=0.12,
                )
            ][:limit]
        )
        session_factory = _FakeSessionFactory(
            SimpleNamespace(
                id=99,
                external_call_id="ext-99",
                processing_status=SimpleNamespace(value="transcribed"),
                audio_storage_key="call-99.wav",
                source_type="api",
                metadata_json={"campaign": "stage4", "channel": "sales"},
            )
        )

        service = _build_service_with_fake_model(
            session_factory=session_factory,
            rag_service=rag_service,
            fake_model=fake_model,
        )
        _, analyze_method = _find_analysis_method(service)
        _invoke_analysis(analyze_method, call_id=99)

        self.assertIsNotNone(
            fake_model.bound_tools,
            "expected Stage 4 analysis execution to bind tools through LangChain",
        )
        self.assertEqual(
            [_tool_name(tool) for tool in fake_model.bound_tools],
            APPROVED_TOOL_NAMES,
            "expected LangChain tool binding to expose only the approved Stage 4 tools",
        )
        self.assertEqual(
            len(fake_model.invocations),
            1,
            "expected the bound LangChain model to be invoked exactly once on the happy path",
        )

    def test_stage4_happy_path_analysis_invocation_completes_against_fixed_inputs(
        self,
    ) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage4-t4-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)

        try:
            with temporary_postgres_database("stage4_t4") as database_url:
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
                            session.commit()

                        fake_model = _FakeLangChainModel()
                        service = _build_service_with_fake_model(
                            session_factory=app.state.session_factory,
                            rag_service=app.state.rag_service,
                            fake_model=fake_model,
                        )
                        _, analyze_method = _find_analysis_method(service)
                        result = _invoke_analysis(analyze_method, call_id=call_id)

                        self.assertIsNotNone(
                            result,
                            "expected Stage 4 happy-path analysis invocation to return a result",
                        )
                        self.assertIsNotNone(
                            fake_model.bound_tools,
                            "expected Stage 4 happy-path analysis to bind tools through LangChain",
                        )
                        self.assertEqual(
                            [_tool_name(tool) for tool in fake_model.bound_tools],
                            APPROVED_TOOL_NAMES,
                            "expected only approved tools to be bound during happy-path analysis",
                        )
                        self.assertEqual(
                            len(fake_model.invocations),
                            1,
                            "expected exactly one LangChain invocation on the fixed happy path",
                        )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
