import importlib
import inspect
import sys
import types
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_API_ROOT = REPO_ROOT / "apps" / "app-api"
SRC_ROOT = APP_API_ROOT / "src"
CONTRACTS_PATH = REPO_ROOT / "docs" / "CONTRACTS.md"
APPROVED_TOOL_NAMES = ("retrieve_context", "get_call_metadata")
REGISTRY_ATTRIBUTE_NAMES = (
    "build_analysis_tool_registry",
    "build_analysis_tools",
    "build_tool_registry",
    "build_tool_api",
    "get_analysis_tool_registry",
    "get_analysis_tools",
    "ANALYSIS_TOOL_REGISTRY",
    "ANALYSIS_TOOLS",
    "analysis_tool_registry",
    "analysis_tools",
)


class _FakeRAGService:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def search_for_call(self, call_id: int, limit: int = 5) -> list[dict[str, Any]]:
        self.calls.append((call_id, limit))
        return [
            {
                "chunk_id": 11,
                "document_id": 7,
                "source_path": "data/kb_seed/pricing.md",
                "chunk_text": "Pricing approval guidance",
                "chunk_index": 0,
                "distance": 0.12,
            }
        ]


class _FakeCallSession:
    def __init__(self, call_id: int) -> None:
        self.id = call_id
        self.external_call_id = "ext-stage4-t2"
        self.processing_status = types.SimpleNamespace(value="transcribed")
        self.audio_storage_key = "call-123.wav"
        self.source_type = "api"
        self.metadata_json = {"campaign": "stage4", "channel": "sales"}


class _FakeSession:
    def __init__(self, call_id: int) -> None:
        self._call = _FakeCallSession(call_id)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, model: object, call_id: int):
        if call_id == self._call.id:
            return self._call
        return None

    def scalar(self, *args, **kwargs):
        return self._call


class _FakeSessionFactory:
    def __init__(self, call_id: int) -> None:
        self._call_id = call_id

    def __call__(self) -> _FakeSession:
        return _FakeSession(self._call_id)


class _FakeCallRepository:
    def __init__(self, call_id: int) -> None:
        self._call = _FakeCallSession(call_id)

    def get(self, call_id: int) -> _FakeCallSession | None:
        if call_id == self._call.id:
            return self._call
        return None

    def get_call_metadata(self, call_id: int) -> dict[str, Any]:
        if call_id != self._call.id:
            raise LookupError(call_id)
        return self._call.metadata_json


def _contracts_text() -> str:
    return CONTRACTS_PATH.read_text(encoding="utf-8")


def _section_body(document_text: str, heading: str) -> str:
    section = document_text.split(heading, 1)[1]
    if "\n## " not in section:
        return section
    return section.split("\n## ", 1)[0]


def _contract_approved_tools() -> list[str]:
    return [
        line.strip().removeprefix("- `").removesuffix("`")
        for line in _section_body(_contracts_text(), "## Approved Tool API").splitlines()
        if line.strip().startswith("- `") and line.strip().endswith("`")
    ]


def _candidate_tool_modules() -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []

    for base_dir in (SRC_ROOT / "application", SRC_ROOT):
        for path in sorted(base_dir.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue

            module_text = path.read_text(encoding="utf-8").lower()
            if not all(tool_name in module_text for tool_name in APPROVED_TOOL_NAMES):
                continue
            if "tool" not in module_text:
                continue

            module_name = ".".join(path.relative_to(APP_API_ROOT).with_suffix("").parts)
            if (module_name, path) not in candidates:
                candidates.append((module_name, path))

    return candidates


def _normalize_tool_name(tool: object) -> str | None:
    if isinstance(tool, str):
        return tool
    if isinstance(tool, dict) and "name" in tool:
        return str(tool["name"])

    for attr_name in ("name", "tool_name", "__name__"):
        value = getattr(tool, attr_name, None)
        if isinstance(value, str) and value:
            return value

    if hasattr(tool, "func"):
        return _normalize_tool_name(getattr(tool, "func"))

    return None


def _normalize_registry(registry: object) -> dict[str, object]:
    if isinstance(registry, dict):
        return dict(registry)

    if isinstance(registry, (list, tuple, set)):
        normalized: dict[str, object] = {}
        for tool in registry:
            tool_name = _normalize_tool_name(tool)
            if tool_name is not None:
                normalized[tool_name] = tool
        return normalized

    return {}


def _factory_kwargs(signature: inspect.Signature) -> dict[str, object]:
    fake_rag_service = _FakeRAGService()
    fake_session_factory = _FakeSessionFactory(call_id=123)
    fake_repository = _FakeCallRepository(call_id=123)

    def retrieve_context(call_id: int, limit: int = 5):
        return fake_rag_service.search_for_call(call_id=call_id, limit=limit)

    def get_call_metadata(call_id: int):
        return fake_repository.get_call_metadata(call_id)

    available_dependencies: dict[str, object] = {
        "rag_service": fake_rag_service,
        "session_factory": fake_session_factory,
        "call_repository": fake_repository,
        "call_session_repository": fake_repository,
        "retrieve_context": retrieve_context,
        "retrieve_context_fn": retrieve_context,
        "retrieve_context_impl": retrieve_context,
        "context_retriever": retrieve_context,
        "get_call_metadata": get_call_metadata,
        "get_call_metadata_fn": get_call_metadata,
        "get_call_metadata_impl": get_call_metadata,
        "metadata_loader": get_call_metadata,
        "call_metadata_loader": get_call_metadata,
    }

    kwargs: dict[str, object] = {}
    unsupported_required: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue

        if parameter.name in available_dependencies:
            kwargs[parameter.name] = available_dependencies[parameter.name]
            continue

        if parameter.default is inspect._empty:
            unsupported_required.append(parameter.name)

    if unsupported_required:
        raise AssertionError(
            "Could not build the analysis tool registry with bounded fakes; "
            f"unsupported required parameters: {unsupported_required}"
        )

    return kwargs


def _discover_tool_registry() -> tuple[str, Path, str, dict[str, object]]:
    for module_name, module_path in _candidate_tool_modules():
        sys.modules.pop(module_name, None)
        module = importlib.import_module(module_name)

        for attribute_name in REGISTRY_ATTRIBUTE_NAMES:
            attribute = getattr(module, attribute_name, None)
            if attribute is None:
                continue

            if callable(attribute):
                registry = attribute(**_factory_kwargs(inspect.signature(attribute)))
            else:
                registry = attribute

            normalized_registry = _normalize_registry(registry)
            if normalized_registry:
                return module_name, module_path, attribute_name, normalized_registry

        implicit_registry = {
            tool_name: getattr(module, tool_name)
            for tool_name in APPROVED_TOOL_NAMES
            if callable(getattr(module, tool_name, None))
        }
        if implicit_registry:
            return module_name, module_path, "<implicit>", implicit_registry

    raise AssertionError(
        "No Stage 4 analysis tool registry or callable tool module was found under "
        "apps/app-api/src/application."
    )


def _invoke_tool(tool: object, call_id: int) -> object:
    invocation_payload = {"call_id": call_id, "limit": 2}

    if hasattr(tool, "invoke") and callable(getattr(tool, "invoke")):
        return tool.invoke(invocation_payload)

    if hasattr(tool, "func") and callable(getattr(tool, "func")):
        tool = getattr(tool, "func")

    if not callable(tool):
        raise AssertionError(f"Registered tool is not callable: {tool!r}")

    signature = inspect.signature(tool)
    kwargs: dict[str, object] = {}
    unsupported_required: list[str] = []

    for parameter in signature.parameters.values():
        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue

        if parameter.name in invocation_payload:
            kwargs[parameter.name] = invocation_payload[parameter.name]
            continue

        if parameter.default is inspect._empty:
            unsupported_required.append(parameter.name)

    if unsupported_required:
        raise AssertionError(
            "Could not invoke registered analysis tool with bounded inputs; "
            f"unsupported required parameters: {unsupported_required}"
        )

    return tool(**kwargs)


class Stage4ApprovedToolAPITests(unittest.TestCase):
    def test_contracts_document_limits_stage4_tool_api_to_two_approved_tools(
        self,
    ) -> None:
        self.assertEqual(
            _contract_approved_tools(),
            list(APPROVED_TOOL_NAMES),
            "expected docs/CONTRACTS.md to define only the approved Stage 4 tools",
        )

    def test_stage4_analysis_tool_registration_exposes_only_the_approved_tools(
        self,
    ) -> None:
        _, module_path, registry_attribute, registry = _discover_tool_registry()

        self.assertEqual(
            sorted(registry),
            sorted(APPROVED_TOOL_NAMES),
            (
                "expected the Stage 4 analysis tool registry to expose only "
                f"{list(APPROVED_TOOL_NAMES)}; found {sorted(registry)} in "
                f"{module_path.relative_to(REPO_ROOT).as_posix()} via {registry_attribute}"
            ),
        )

    def test_stage4_approved_tools_support_bounded_invocation_and_no_extra_tool(
        self,
    ) -> None:
        _, module_path, registry_attribute, registry = _discover_tool_registry()

        invocation_results: dict[str, object] = {}
        for tool_name in APPROVED_TOOL_NAMES:
            invocation_results[tool_name] = _invoke_tool(registry[tool_name], call_id=123)

        self.assertEqual(
            sorted(registry),
            sorted(APPROVED_TOOL_NAMES),
            (
                "expected the bounded invocation check to run against a registry "
                f"with no extra tools; found {sorted(registry)} in "
                f"{module_path.relative_to(REPO_ROOT).as_posix()} via {registry_attribute}"
            ),
        )
        self.assertIsNotNone(
            invocation_results["retrieve_context"],
            "expected retrieve_context to return a bounded result",
        )
        self.assertIsNotNone(
            invocation_results["get_call_metadata"],
            "expected get_call_metadata to return a bounded result",
        )
