import importlib
import shutil
import unittest
import uuid
from unittest.mock import Mock, patch

from alembic import command
from alembic.config import Config
from conftest import ALEMBIC_INI_PATH, TEST_TMP_ROOT, clear_src_modules
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage2-t5",
    "source_type": "api",
    "metadata": {"campaign": "stage2", "channel": "sales"},
}
AUDIO_UPLOAD = {
    "file": (
        "call.wav",
        b"RIFF$\x00\x00\x00WAVEfmt ",
        "audio/wav",
    )
}
class Stage2SplitTranscriptSegmentsTests(unittest.TestCase):
    def test_post_call_audio_converts_transcript_output_into_ordered_transcriptsegment_records(
        self,
    ) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage2-t5-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)
        engine = None

        env_values = {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8000",
            "DATABASE_URL": f"sqlite:///{(temp_root / 'stage2.db').as_posix()}",
            "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
        }

        try:
            with patch.dict("os.environ", env_values, clear=True):
                alembic_config = Config(str(ALEMBIC_INI_PATH))
                command.upgrade(alembic_config, "head")

                clear_src_modules()
                main_module = importlib.import_module("src.main")
                stt_module = importlib.import_module("src.adapters.stt")
                persistence_models = importlib.import_module(
                    "src.infrastructure.persistence.models"
                )

                try:
                    app = main_module.create_app()
                    app.state.stt_adapter = Mock(
                        transcribe=Mock(
                            return_value=[
                                stt_module.TranscribedSegment(
                                    speaker="agent",
                                    text="second",
                                    start_ms=200,
                                    end_ms=300,
                                    sequence_no=2,
                                ),
                                stt_module.TranscribedSegment(
                                    speaker="customer",
                                    text="first",
                                    start_ms=0,
                                    end_ms=100,
                                    sequence_no=1,
                                ),
                            ]
                        )
                    )

                    with TestClient(app) as client:
                        create_response = client.post("/calls", json=CREATE_CALL_PAYLOAD)
                        self.assertEqual(create_response.status_code, 201)

                        call_id = create_response.json()["id"]
                        upload_response = client.post(
                            f"/calls/{call_id}/audio",
                            files=AUDIO_UPLOAD,
                        )
                        self.assertGreaterEqual(upload_response.status_code, 200)
                        self.assertLess(upload_response.status_code, 300)
                finally:
                    clear_src_modules()

            engine = create_engine(env_values["DATABASE_URL"])
            session_factory = sessionmaker(bind=engine)
            with session_factory() as session:
                transcript_segments = session.scalars(
                    select(persistence_models.TranscriptSegment)
                    .where(persistence_models.TranscriptSegment.call_id == call_id)
                    .order_by(persistence_models.TranscriptSegment.sequence_no)
                ).all()

            self.assertEqual(len(transcript_segments), 2)
            self.assertTrue(
                all(
                    isinstance(segment, persistence_models.TranscriptSegment)
                    for segment in transcript_segments
                ),
                "Expected transcription output to be converted into TranscriptSegment records.",
            )
            self.assertEqual(
                [segment.sequence_no for segment in transcript_segments],
                [1, 2],
            )
            self.assertEqual(
                [segment.text for segment in transcript_segments],
                ["first", "second"],
            )
            self.assertEqual(
                [segment.speaker for segment in transcript_segments],
                ["customer", "agent"],
            )
        finally:
            clear_src_modules()
            if engine is not None:
                engine.dispose()
            shutil.rmtree(temp_root, ignore_errors=True)
