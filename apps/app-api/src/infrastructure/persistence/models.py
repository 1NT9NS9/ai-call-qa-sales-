from src.infrastructure.persistence.base import Base
from src.infrastructure.persistence.call_analysis import _AnalysisRecord
from src.infrastructure.persistence.call_session import (
    CallProcessingStatus,
    _SessionRecord,
)
from src.infrastructure.persistence.delivery_event import _DeliveryRecord
from src.infrastructure.persistence.knowledge_chunk import _ChunkRecord
from src.infrastructure.persistence.knowledge_document import _DocumentRecord
from src.infrastructure.persistence.transcript_segment import _SegmentRecord

CallSession = _SessionRecord
CallAnalysis = _AnalysisRecord
DeliveryEvent = _DeliveryRecord
TranscriptSegment = _SegmentRecord
KnowledgeDocument = _DocumentRecord
KnowledgeChunk = _ChunkRecord

__all__ = [
    "Base",
    "CallAnalysis",
    "CallProcessingStatus",
    "CallSession",
    "DeliveryEvent",
    "TranscriptSegment",
    "KnowledgeDocument",
    "KnowledgeChunk",
]
