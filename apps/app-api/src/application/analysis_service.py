from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.application.analysis_tools import (
    AnalysisToolAPI,
    build_analysis_tool_api,
    build_langchain_tools,
)
from src.infrastructure.persistence.models import (
    CallAnalysis,
    CallProcessingStatus,
    CallSession,
    TranscriptSegment,
)
from src.observability import log_pipeline_event
from src.services.rag import RAGService


@dataclass(frozen=True)
class AnalysisAssets:
    prompt: str
    rubric: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class AnalysisSchemaContractSource:
    contract_path: Path
    fence_label: str


class AnalysisOutputValidationError(RuntimeError):
    pass


REVIEW_CONFIDENCE_THRESHOLD = 0.70
MIN_TRANSCRIPT_WORD_COUNT = 3
INVALID_OUTPUT_REVIEW_REASON = "analysis output remained invalid after retry"
LOW_CONFIDENCE_REVIEW_REASON = (
    f"confidence below {REVIEW_CONFIDENCE_THRESHOLD:.2f} threshold"
)
TRANSCRIPT_TOO_SHORT_ERROR = "Analysis transcript is empty or too short."


def _default_resources_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "resources" / "analysis"


def _load_schema_source(
    schema_manifest_path: Path,
) -> AnalysisSchemaContractSource:
    schema_manifest = json.loads(
        schema_manifest_path.read_text(encoding="utf-8")
    )
    source_config = schema_manifest["analysis_schema_contract_source"]
    return AnalysisSchemaContractSource(
        contract_path=(
            schema_manifest_path.parent / source_config["contract_path"]
        ).resolve(),
        fence_label=source_config["fence_label"],
    )


def load_analysis_schema_from_contracts(
    resources_dir: Path | None = None,
) -> dict[str, Any]:
    active_resources_dir = resources_dir or _default_resources_dir()
    schema_manifest_path = active_resources_dir / "analysis_schema.json"
    schema_source = _load_schema_source(schema_manifest_path)
    contract_text = schema_source.contract_path.read_text(encoding="utf-8")
    schema_match = re.search(
        rf"```{re.escape(schema_source.fence_label)}\r?\n(.*?)\r?\n```",
        contract_text,
        re.DOTALL,
    )
    if schema_match is None:
        raise RuntimeError(
            "Stage 4 analysis schema block was not found in docs/CONTRACTS.md."
        )

    return json.loads(schema_match.group(1))


class AnalysisService:
    def __init__(
        self,
        resources_dir: Path | None = None,
        tool_api: AnalysisToolAPI | None = None,
        session_factory: sessionmaker[Session] | None = None,
        chat_model: Any | None = None,
        langchain_tools: list[Any] | None = None,
    ) -> None:
        self._resources_dir = resources_dir or _default_resources_dir()
        self._tool_api = tool_api
        self._session_factory = session_factory
        self._chat_model = chat_model
        self._langchain_tools = langchain_tools or []

    def load_assets(self) -> AnalysisAssets:
        prompt_path = self._resources_dir / "analysis_prompt.md"
        rubric_path = self._resources_dir / "analysis_rubric.md"
        return AnalysisAssets(
            prompt=prompt_path.read_text(encoding="utf-8"),
            rubric=rubric_path.read_text(encoding="utf-8"),
            schema=load_analysis_schema_from_contracts(self._resources_dir),
        )

    def tool_definitions(self) -> list[dict[str, Any]]:
        if self._tool_api is None:
            return []

        return [
            {
                "name": definition.name,
                "description": definition.description,
                "parameters": definition.parameters,
            }
            for definition in self._tool_api.definitions()
        ]

    def invoke_tool(self, tool_name: str, **kwargs: Any) -> Any:
        if self._tool_api is None:
            raise RuntimeError("Analysis tool API is not configured.")

        return self._tool_api.invoke(tool_name, **kwargs)

    def analyze(self, call_id: int) -> Any:
        if self._chat_model is None:
            raise RuntimeError("Analysis chat model is not configured.")

        analysis_started_at = perf_counter()
        payload = self._build_analysis_payload(call_id=call_id)
        log_pipeline_event(
            event="analysis.started",
            call_id=call_id,
            stage="analysis",
            status="started",
            transcript_segment_count=len(payload["context"]["transcript"]),
        )
        if self._supports_persistence() and self._transcript_is_empty_or_too_short(
            payload["context"]["transcript"]
        ):
            self._fail_call_for_short_transcript(call_id=call_id)
            log_pipeline_event(
                event="analysis.failed",
                call_id=call_id,
                stage="analysis",
                status="failed",
                reason="transcript_too_short",
                duration_ms=round((perf_counter() - analysis_started_at) * 1000, 2),
            )
            raise RuntimeError(TRANSCRIPT_TOO_SHORT_ERROR)
        bound_model = self._bind_langchain_tools(self._chat_model)
        last_error: AnalysisOutputValidationError | None = None

        for _attempt in range(2):
            response = bound_model.invoke(payload)
            try:
                validated_output = self._parse_and_validate_analysis_output(
                    response=response,
                    schema=payload["schema"],
                )
                finalized_result = self._finalize_valid_analysis(
                    call_id=call_id,
                    validated_output=validated_output,
                    schema=payload["schema"],
                )
                log_pipeline_event(
                    event="analysis.completed",
                    call_id=call_id,
                    stage="analysis",
                    status="success",
                    processing_status=CallProcessingStatus.ANALYZED.value,
                    confidence=finalized_result.get("confidence"),
                    needs_review=bool(finalized_result.get("needs_review", False)),
                    duration_ms=round((perf_counter() - analysis_started_at) * 1000, 2),
                )
                return finalized_result
            except AnalysisOutputValidationError as exc:
                last_error = exc

        if self._supports_persistence():
            review_payload = self._persist_review_required_invalid_output(
                call_id=call_id,
                review_reasons=self._invalid_output_review_reasons(last_error),
            )
            log_pipeline_event(
                event="analysis.completed",
                call_id=call_id,
                stage="analysis",
                status="review_required",
                processing_status=CallProcessingStatus.ANALYZED.value,
                confidence=None,
                needs_review=True,
                duration_ms=round((perf_counter() - analysis_started_at) * 1000, 2),
            )
            return review_payload

        raise AnalysisOutputValidationError(
            "Analysis output remained invalid after one retry."
        ) from last_error

    def build_prompt_context(
        self,
        call_id: int,
        context_limit: int = 5,
    ) -> dict[str, Any]:
        if self._tool_api is None or self._session_factory is None:
            raise RuntimeError(
                "Analysis prompt-context assembly requires tool_api and session_factory."
            )

        transcript = self._load_transcript(call_id=call_id)
        return {
            "call_id": call_id,
            "transcript": transcript,
            "retrieved_context": self.invoke_tool(
                "retrieve_context",
                call_id=call_id,
                limit=context_limit,
            ),
            "call_metadata": self.invoke_tool(
                "get_call_metadata",
                call_id=call_id,
            ),
        }

    def _load_transcript(self, call_id: int) -> list[dict[str, Any]]:
        if self._session_factory is None:
            raise RuntimeError(
                "Analysis transcript loading requires session_factory."
            )

        with self._session_factory() as session:
            segments = list(
                session.scalars(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.call_id == call_id)
                    .order_by(TranscriptSegment.sequence_no, TranscriptSegment.id)
                )
            )

        return [
            {
                "segment_id": segment.id,
                "speaker": segment.speaker,
                "text": segment.text,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "sequence_no": segment.sequence_no,
            }
            for segment in segments
        ]

    def _build_analysis_payload(self, call_id: int) -> dict[str, Any]:
        assets = self.load_assets()
        return {
            "prompt": assets.prompt,
            "rubric": assets.rubric,
            "schema": assets.schema,
            "context": self.build_prompt_context(call_id=call_id),
        }

    def _bind_langchain_tools(self, chat_model: Any) -> Any:
        if not self._langchain_tools:
            raise RuntimeError("LangChain tools are not configured.")
        if not hasattr(chat_model, "bind_tools"):
            raise RuntimeError("Configured analysis chat model does not support bind_tools.")

        bind_tools = getattr(chat_model, "bind_tools", None)
        if bind_tools is None:
            raise RuntimeError("Configured analysis chat model does not support bind_tools.")

        return bind_tools(self._langchain_tools)

    def _finalize_valid_analysis(
        self,
        *,
        call_id: int,
        validated_output: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._supports_persistence():
            return validated_output

        finalized_output = dict(validated_output)
        computed_confidence = self._compute_confidence(
            result_payload=finalized_output,
            schema=schema,
        )
        finalized_output["confidence"] = computed_confidence
        finalized_output = self._apply_review_rules(
            result_payload=finalized_output,
            confidence=computed_confidence,
        )
        self._persist_valid_analysis(
            call_id=call_id,
            result_payload=finalized_output,
            confidence=computed_confidence,
        )
        return finalized_output

    def _supports_persistence(self) -> bool:
        if self._session_factory is None:
            return False

        with self._session_factory() as session:
            return all(
                hasattr(session, method_name)
                for method_name in ("add", "commit", "get")
            )

    def _parse_and_validate_analysis_output(
        self,
        *,
        response: Any,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        content = self._extract_response_content(response)
        try:
            parsed_output = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AnalysisOutputValidationError("Analysis output is invalid JSON.") from exc

        validation_errors = self._validate_schema_instance(
            instance=parsed_output,
            schema=schema,
        )
        if validation_errors:
            raise AnalysisOutputValidationError(
                "Analysis output failed schema validation: "
                + "; ".join(validation_errors)
            )

        return parsed_output

    @staticmethod
    def _extract_response_content(response: Any) -> str:
        if isinstance(response, str):
            return response
        if isinstance(response, dict) and "content" in response:
            content = response["content"]
            if isinstance(content, str):
                return content
        content = getattr(response, "content", None)
        if isinstance(content, str):
            return content

        raise AnalysisOutputValidationError(
            "Analysis response did not provide string content."
        )

    def _compute_confidence(
        self,
        *,
        result_payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> float:
        required_fields = schema.get("required", [])
        populated_required_fields = sum(
            1
            for field_name in required_fields
            if field_name in result_payload and result_payload[field_name] is not None
        )
        completeness = (
            populated_required_fields / len(required_fields)
            if required_fields
            else 0.0
        )

        evidence_items = [
            *result_payload.get("objections", []),
            *result_payload.get("risks", []),
        ]
        evidence_bearing_total = len(evidence_items)
        evidence_with_segments = sum(
            1
            for item in evidence_items
            if item.get("evidence_segment_ids")
        )
        evidence_coverage = (
            evidence_with_segments / evidence_bearing_total
            if evidence_bearing_total
            else 0.0
        )

        knowledge_usage = 1.0 if result_payload.get("used_knowledge") else 0.0
        confidence = (
            0.50 * completeness
            + 0.30 * evidence_coverage
            + 0.20 * knowledge_usage
        )
        return round(confidence, 2)

    def _apply_review_rules(
        self,
        *,
        result_payload: dict[str, Any],
        confidence: float,
    ) -> dict[str, Any]:
        finalized_payload = dict(result_payload)
        review_reasons = list(finalized_payload.get("review_reasons") or [])
        needs_review = bool(finalized_payload.get("needs_review", False))

        if confidence < REVIEW_CONFIDENCE_THRESHOLD:
            needs_review = True
            if LOW_CONFIDENCE_REVIEW_REASON not in review_reasons:
                review_reasons.append(LOW_CONFIDENCE_REVIEW_REASON)

        finalized_payload["needs_review"] = needs_review
        finalized_payload["review_reasons"] = review_reasons
        return finalized_payload

    def _persist_valid_analysis(
        self,
        *,
        call_id: int,
        result_payload: dict[str, Any],
        confidence: float,
    ) -> None:
        if self._session_factory is None:
            raise RuntimeError("Analysis persistence requires session_factory.")

        with self._session_factory() as session:
            persisted_analysis = session.get(CallAnalysis, call_id)
            if persisted_analysis is None:
                persisted_analysis = CallAnalysis(call_id=call_id)
                session.add(persisted_analysis)

            persisted_analysis.result_json = result_payload
            persisted_analysis.confidence = confidence
            persisted_analysis.review_required = bool(result_payload.get("needs_review", False))
            persisted_analysis.review_reasons = result_payload.get("review_reasons")

            persisted_call = session.get(CallSession, call_id)
            if persisted_call is None:
                raise RuntimeError(f"CallSession not found for call_id={call_id}.")
            persisted_call.processing_status = CallProcessingStatus.ANALYZED

            session.commit()

    def _persist_review_required_invalid_output(
        self,
        *,
        call_id: int,
        review_reasons: list[str],
    ) -> dict[str, Any]:
        if self._session_factory is None:
            raise RuntimeError("Analysis persistence requires session_factory.")

        review_payload = {
            "needs_review": True,
            "review_reasons": review_reasons,
        }
        with self._session_factory() as session:
            persisted_analysis = session.get(CallAnalysis, call_id)
            if persisted_analysis is None:
                persisted_analysis = CallAnalysis(call_id=call_id)
                session.add(persisted_analysis)

            persisted_analysis.result_json = None
            persisted_analysis.confidence = None
            persisted_analysis.review_required = True
            persisted_analysis.review_reasons = review_reasons

            persisted_call = session.get(CallSession, call_id)
            if persisted_call is None:
                raise RuntimeError(f"CallSession not found for call_id={call_id}.")
            persisted_call.processing_status = CallProcessingStatus.ANALYZED

            session.commit()

        return review_payload

    def _fail_call_for_short_transcript(self, *, call_id: int) -> None:
        if not self._supports_persistence():
            return

        session_factory = self._session_factory
        if session_factory is None:
            return

        with session_factory() as session:
            persisted_call = session.get(CallSession, call_id)
            if persisted_call is None:
                raise RuntimeError(f"CallSession not found for call_id={call_id}.")
            persisted_call.processing_status = CallProcessingStatus.FAILED
            session.commit()

    @staticmethod
    def _invalid_output_review_reasons(
        error: AnalysisOutputValidationError | None,
    ) -> list[str]:
        if error is None:
            return [INVALID_OUTPUT_REVIEW_REASON]
        return [INVALID_OUTPUT_REVIEW_REASON, str(error)]

    @staticmethod
    def _transcript_is_empty_or_too_short(
        transcript: list[dict[str, Any]],
    ) -> bool:
        transcript_words = sum(
            len(str(segment.get("text", "")).split())
            for segment in transcript
        )
        return transcript_words < MIN_TRANSCRIPT_WORD_COUNT

    def _validate_schema_instance(
        self,
        *,
        instance: Any,
        schema: dict[str, Any],
        path: str = "$",
    ) -> list[str]:
        errors: list[str] = []
        schema_type = schema.get("type")

        if schema_type == "object":
            if not isinstance(instance, dict):
                return [f"{path} must be an object"]

            required_fields = schema.get("required", [])
            for field_name in required_fields:
                if field_name not in instance:
                    errors.append(f"{path}.{field_name} is required")

            properties = schema.get("properties", {})
            if schema.get("additionalProperties") is False:
                unexpected_fields = sorted(
                    field_name
                    for field_name in instance
                    if field_name not in properties
                )
                for field_name in unexpected_fields:
                    errors.append(f"{path}.{field_name} is not allowed")

            for field_name, field_schema in properties.items():
                if field_name not in instance:
                    continue
                errors.extend(
                    self._validate_schema_instance(
                        instance=instance[field_name],
                        schema=field_schema,
                        path=f"{path}.{field_name}",
                    )
                )
            return errors

        if schema_type == "array":
            if not isinstance(instance, list):
                return [f"{path} must be an array"]

            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(instance):
                    errors.extend(
                        self._validate_schema_instance(
                            instance=item,
                            schema=item_schema,
                            path=f"{path}[{index}]",
                        )
                    )
            return errors

        if schema_type == "string":
            if not isinstance(instance, str):
                return [f"{path} must be a string"]
            return errors

        if schema_type == "boolean":
            if not isinstance(instance, bool):
                return [f"{path} must be a boolean"]
            return errors

        if schema_type == "integer":
            if isinstance(instance, bool) or not isinstance(instance, int):
                return [f"{path} must be an integer"]
            return errors

        if schema_type == "number":
            if isinstance(instance, bool) or not isinstance(instance, (int, float)):
                return [f"{path} must be a number"]
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            numeric_instance = float(instance)
            if minimum is not None and numeric_instance < float(minimum):
                errors.append(f"{path} must be >= {minimum}")
            if maximum is not None and numeric_instance > float(maximum):
                errors.append(f"{path} must be <= {maximum}")
            return errors

        return errors


def build_analysis_service(
    resources_dir: Path | None = None,
    session_factory: sessionmaker[Session] | None = None,
    rag_service: RAGService | None = None,
    chat_model: Any | None = None,
    llm: Any | None = None,
    model: Any | None = None,
    analysis_model: Any | None = None,
) -> AnalysisService:
    tool_api = None
    langchain_tools = None
    if session_factory is not None or rag_service is not None:
        if session_factory is None or rag_service is None:
            raise ValueError(
                "session_factory and rag_service must be provided together."
            )
        tool_api = build_analysis_tool_api(
            session_factory=session_factory,
            rag_service=rag_service,
        )
        langchain_tools = build_langchain_tools(
            session_factory=session_factory,
            rag_service=rag_service,
        )

    resolved_chat_model = chat_model
    for candidate in (llm, model, analysis_model):
        if candidate is not None:
            resolved_chat_model = candidate
            break

    return AnalysisService(
        resources_dir=resources_dir,
        tool_api=tool_api,
        session_factory=session_factory,
        chat_model=resolved_chat_model,
        langchain_tools=langchain_tools,
    )
