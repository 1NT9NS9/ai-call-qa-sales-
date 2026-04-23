import importlib
import shutil
import unittest
import uuid
from dataclasses import asdict
from pathlib import Path
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
    "external_call_id": "ext-call-stage4-t3",
    "source_type": "api",
    "metadata": {"campaign": "stage4", "channel": "sales"},
}
CONTEXT_BUILDER_NAMES = (
    "assemble_prompt_context",
    "build_prompt_context",
    "assemble_analysis_context",
    "build_analysis_context",
    "assemble_context",
    "build_context",
)


def _find_context_builder(service: object):
    for method_name in CONTEXT_BUILDER_NAMES:
        method = getattr(service, method_name, None)
        if callable(method):
            return method_name, method

    raise AssertionError(
        "AnalysisService does not expose a Stage 4 context assembly entry point. "
        f"Expected one of {list(CONTEXT_BUILDER_NAMES)}."
    )


def _invoke_context_builder(method, call_id: int):
    try:
        return method(call_id=call_id)
    except TypeError:
        return method(call_id)


def _transcript_text(context: dict[str, object]) -> str:
    transcript = context["transcript"]
    if isinstance(transcript, str):
        return transcript

    if isinstance(transcript, list):
        collected_lines: list[str] = []
        for item in transcript:
            if isinstance(item, dict):
                collected_lines.append(str(item["text"]))
                continue

            text = getattr(item, "text", None)
            if text is not None:
                collected_lines.append(str(text))
                continue

            raise AssertionError(
                "Stage 4 transcript context entries must expose `text`."
            )

        return "\n".join(collected_lines)

    raise AssertionError(
        "Stage 4 transcript context must be a string or a list of transcript entries."
    )


class Stage4ContextAssemblyTests(unittest.TestCase):
    def test_stage4_context_assembly_happy_path_includes_transcript_retrieved_context_and_call_metadata(
        self,
    ) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage4-t3-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)

        try:
            with temporary_postgres_database("stage4_t3") as database_url:
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
                            session.commit()

                        service = analysis_service_module.build_analysis_service(
                            session_factory=app.state.session_factory,
                            rag_service=app.state.rag_service,
                        )
                        builder_name, context_builder = _find_context_builder(service)
                        context = _invoke_context_builder(context_builder, call_id=call_id)

                        self.assertIsInstance(
                            context,
                            dict,
                            (
                                "expected Stage 4 context assembly to return a mapping "
                                f"from {builder_name}"
                            ),
                        )
                        self.assertIn("transcript", context)
                        self.assertIn("retrieved_context", context)
                        self.assertIn("call_metadata", context)

                        transcript_text = _transcript_text(context)
                        expected_transcript_text = " ".join(
                            segment["text"] for segment in FIXED_TRANSCRIPT_SEGMENTS
                        )
                        self.assertIn(
                            expected_transcript_text,
                            transcript_text.replace("\n", " "),
                            "expected assembled context to include the fixed persisted transcript fixture",
                        )

                        retrieved_context = context["retrieved_context"]
                        self.assertIsInstance(
                            retrieved_context,
                            list,
                            "expected retrieved_context to be a list of retrieved KB matches",
                        )
                        self.assertTrue(
                            retrieved_context,
                            "expected Stage 4 context assembly to include retrieved KB context",
                        )
                        expected_matches = [
                            asdict(match)
                            for match in app.state.rag_service.search_for_call(
                                call_id=call_id,
                                limit=5,
                            )
                        ]
                        self.assertEqual(
                            retrieved_context,
                            expected_matches,
                            (
                                "expected assembled retrieved_context to come from the real "
                                "Stage 3 retrieval path for the same call"
                            ),
                        )

                        self.assertEqual(
                            context["call_metadata"],
                            service.invoke_tool("get_call_metadata", call_id=call_id),
                            "expected assembled call_metadata to match the stored call metadata",
                        )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
