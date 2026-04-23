import importlib
import inspect
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from alembic import command
from alembic.config import Config
from conftest import ALEMBIC_INI_PATH, TEST_TMP_ROOT, clear_src_modules
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select


CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage2-t8",
    "source_type": "api",
    "metadata": {"campaign": "stage2", "channel": "sales"},
}
AUDIO_BYTES = b"RIFF$\x00\x00\x00WAVEfmt "
AUDIO_UPLOAD = {
    "file": (
        "call.wav",
        AUDIO_BYTES,
        "audio/wav",
    )
}
class Stage2BoundedVerificationTests(unittest.TestCase):
    def _create_clean_database_context(self) -> tuple[Path, str]:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage2-t8-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{(temp_root / 'stage2.db').as_posix()}"
        return temp_root, database_url

    def test_audio_upload_to_transcribed_flow_is_stable_for_happy_path(self) -> None:
        temp_root, database_url = self._create_clean_database_context()
        storage_root = temp_root / "audio"
        engine = None

        env_values = {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8000",
            "DATABASE_URL": database_url,
            "STORAGE_AUDIO_DIR": str(storage_root),
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

                provider_classes = [
                    cls
                    for _, cls in inspect.getmembers(stt_module, inspect.isclass)
                    if issubclass(cls, stt_module.STTAdapter)
                    and cls is not stt_module.STTAdapter
                ]
                self.assertEqual(provider_classes, [stt_module.SimpleFileSTTProvider])

                try:
                    app = main_module.create_app()
                    self.assertIsInstance(
                        app.state.stt_adapter,
                        stt_module.SimpleFileSTTProvider,
                    )
                    transcribe_mock = Mock(
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
                    app.state.stt_adapter = Mock(transcribe=transcribe_mock)

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

            engine = create_engine(database_url)
            with engine.connect() as connection:
                call_row = connection.execute(
                    select(persistence_models.CallSession.__table__).where(
                        persistence_models.CallSession.id == call_id
                    )
                ).mappings().one()
                transcript_rows = connection.execute(
                    select(persistence_models.TranscriptSegment.__table__)
                    .where(persistence_models.TranscriptSegment.call_id == call_id)
                    .order_by(persistence_models.TranscriptSegment.sequence_no)
                ).mappings().all()

            audio_storage_key = call_row["audio_storage_key"]
            self.assertIsNotNone(audio_storage_key)
            stored_audio_path = storage_root / audio_storage_key
            self.assertTrue(stored_audio_path.is_file())
            self.assertEqual(stored_audio_path.read_bytes(), AUDIO_BYTES)
            transcribe_mock.assert_called_once_with(stored_audio_path)

            self.assertEqual(
                getattr(call_row["processing_status"], "value", call_row["processing_status"]),
                "transcribed",
            )
            self.assertEqual(len(transcript_rows), 2)
            self.assertEqual([row["sequence_no"] for row in transcript_rows], [1, 2])
            self.assertEqual([row["text"] for row in transcript_rows], ["first", "second"])
            self.assertEqual(
                [row["speaker"] for row in transcript_rows],
                ["customer", "agent"],
            )

            with patch.dict("os.environ", env_values, clear=True):
                clear_src_modules()
                reloaded_main_module = importlib.import_module("src.main")

                try:
                    with TestClient(reloaded_main_module.create_app()) as client:
                        get_response = client.get(f"/calls/{call_id}")
                finally:
                    clear_src_modules()

            self.assertEqual(get_response.status_code, 200)
            payload = get_response.json()
            self.assertEqual(payload["processing_status"], "transcribed")
            self.assertEqual(payload["audio_storage_key"], audio_storage_key)
            self.assertEqual(
                [segment["sequence_no"] for segment in payload["transcript_segments"]],
                [1, 2],
            )
            self.assertEqual(
                [segment["text"] for segment in payload["transcript_segments"]],
                ["first", "second"],
            )
            self.assertEqual(
                [segment["speaker"] for segment in payload["transcript_segments"]],
                ["customer", "agent"],
            )
        finally:
            clear_src_modules()
            if engine is not None:
                engine.dispose()
            shutil.rmtree(temp_root, ignore_errors=True)
