from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


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
    def transcribe(self, file_path: str | Path) -> list[TranscribedSegment]:
        resolved_path = Path(file_path)
        audio_bytes = resolved_path.read_bytes()
        if not audio_bytes:
            return []

        return [
            TranscribedSegment(
                speaker="unknown",
                text=f"Transcript for {resolved_path.stem}",
                start_ms=0,
                end_ms=len(audio_bytes),
                sequence_no=0,
            )
        ]


def build_stt_adapter() -> STTAdapter:
    return SimpleFileSTTProvider()
