from __future__ import annotations

from abc import ABC, abstractmethod
import base64
from dataclasses import dataclass
import mimetypes
from pathlib import Path

import httpx
from openai import OpenAI

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


@dataclass(frozen=True)
class TranscribedSegment:
    speaker: str
    text: str
    start_ms: int
    end_ms: int
    sequence_no: int


class STTAdapter(ABC):
    @abstractmethod
    def transcribe(self, file_path: str | Path) -> list[TranscribedSegment]:
        raise NotImplementedError


class SimpleFileSTTProvider(STTAdapter):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-4o-mini-transcribe",
        gemini_api_key: str | None = None,
        gemini_model: str = "gemini-2.5-flash",
        base_url: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._gemini_api_key = gemini_api_key
        self._gemini_model = gemini_model
        self._base_url = base_url or DEFAULT_OPENAI_BASE_URL
        self._gemini_base_url = DEFAULT_GEMINI_BASE_URL
        self._timeout_seconds = timeout_seconds

    def transcribe(self, file_path: str | Path) -> list[TranscribedSegment]:
        resolved_path = Path(file_path)
        audio_bytes = resolved_path.read_bytes()
        if not audio_bytes:
            return []

        if self._gemini_api_key:
            transcript_text = self._transcribe_with_gemini(
                resolved_path=resolved_path,
                audio_bytes=audio_bytes,
            )
        elif self._api_key:
            transcript_text = self._transcribe_with_openai(
                resolved_path=resolved_path,
            )
        else:
            transcript_text = f"Transcript for {resolved_path.stem}"

        if not transcript_text:
            return []

        end_ms = 0 if (self._gemini_api_key or self._api_key) else len(audio_bytes)
        return [
            TranscribedSegment(
                speaker="unknown",
                text=transcript_text,
                start_ms=0,
                end_ms=end_ms,
                sequence_no=0,
            )
        ]

    def _transcribe_with_gemini(
        self,
        *,
        resolved_path: Path,
        audio_bytes: bytes,
    ) -> str:
        mime_type, _ = mimetypes.guess_type(resolved_path.name)
        encoded_audio = base64.b64encode(audio_bytes).decode("ascii")
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "Generate a verbatim transcript of the speech in this "
                                "audio. Return only the transcript text."
                            )
                        },
                        {
                            "inline_data": {
                                "mime_type": mime_type or "audio/mpeg",
                                "data": encoded_audio,
                            }
                        },
                    ]
                }
            ]
        }
        response = httpx.post(
            f"{self._gemini_base_url}/models/{self._gemini_model}:generateContent",
            headers={
                "x-goog-api-key": str(self._gemini_api_key),
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        response_data = response.json()
        return self._extract_text(response_data).strip()

    @staticmethod
    def _extract_text(response_data: dict) -> str:
        candidates = response_data.get("candidates", [])
        for candidate in candidates:
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return text
        return ""

    def _transcribe_with_openai(
        self,
        *,
        resolved_path: Path,
    ) -> str:
        client = OpenAI(
            api_key=str(self._api_key),
            base_url=self._base_url or DEFAULT_OPENAI_BASE_URL,
        )
        with resolved_path.open("rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                file=audio_file,
                model=self._model,
            )

        return str(getattr(transcription, "text", "")).strip()


def build_stt_adapter(
    *,
    api_key: str | None,
    model: str,
    gemini_api_key: str | None = None,
    gemini_model: str = "gemini-2.5-flash",
    base_url: str | None = None,
) -> STTAdapter:
    return SimpleFileSTTProvider(
        api_key=api_key,
        model=model,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        base_url=base_url,
    )
