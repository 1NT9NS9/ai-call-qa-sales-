import importlib
import json
import sys
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_API_ROOT = REPO_ROOT / "apps" / "app-api"
SRC_ROOT = APP_API_ROOT / "src"
DOCS_ROOT = REPO_ROOT / "docs"
CONTRACTS_PATH = DOCS_ROOT / "CONTRACTS.md"
TEXT_ASSET_SUFFIXES = {".json", ".md", ".txt", ".yaml", ".yml"}
ASSET_MARKERS = {
    "prompt": ("prompt",),
    "rubric": ("rubric",),
    "schema": ("schema",),
}
SCHEMA_GENERATOR_NAMES = (
    "generate_analysis_schema",
    "build_analysis_schema",
    "load_analysis_schema_from_contracts",
)


def _safe_lower_text(path: Path) -> str:
    if path.suffix.lower() not in TEXT_ASSET_SUFFIXES:
        return ""

    try:
        return path.read_text(encoding="utf-8").lower()
    except UnicodeDecodeError:
        return ""


def _contracts_text() -> str:
    return CONTRACTS_PATH.read_text(encoding="utf-8")


def _section_body(document_text: str, heading: str) -> str:
    section = document_text.split(heading, 1)[1]
    if "\n## " not in section:
        return section
    return section.split("\n## ", 1)[0]


def _analysis_contract_section() -> str:
    return _section_body(_contracts_text(), "## Analysis Result Contract")


def _approved_tool_section() -> str:
    return _section_body(_contracts_text(), "## Approved Tool API")


def _contract_analysis_fields() -> list[str]:
    fields: list[str] = []
    for line in _analysis_contract_section().splitlines():
        stripped = line.strip()
        if stripped == "Contract details:":
            break
        if stripped.startswith("- `") and stripped.endswith("`"):
            fields.append(stripped.removeprefix("- `").removesuffix("`"))
    return fields


def _contract_approved_tools() -> list[str]:
    return [
        line.strip().removeprefix("- `").removesuffix("`")
        for line in _approved_tool_section().splitlines()
        if line.strip().startswith("- `") and line.strip().endswith("`")
    ]


def _expected_schema_shape_from_contracts() -> dict[str, Any]:
    contract_fields = _contract_analysis_fields()
    return {
        "required": contract_fields,
        "properties": {
            "summary": {"type": "string"},
            "score": {"type": "number"},
            "score_breakdown": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["criterion", "score", "max_score", "reason"],
                    "properties": {
                        "criterion": {"type": "string"},
                        "score": {"type": "number"},
                        "max_score": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                },
            },
            "objections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["text", "handled", "evidence_segment_ids"],
                    "properties": {
                        "text": {"type": "string"},
                        "handled": {"type": "boolean"},
                        "evidence_segment_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                    },
                },
            },
            "risks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["text", "severity", "evidence_segment_ids"],
                    "properties": {
                        "text": {"type": "string"},
                        "severity": {"type": "string"},
                        "evidence_segment_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                    },
                },
            },
            "next_best_action": {"type": "string"},
            "coach_feedback": {"type": "string"},
            "used_knowledge": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["document_id", "chunk_id", "reason"],
                    "properties": {
                        "document_id": {"type": "integer"},
                        "chunk_id": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                },
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "needs_review": {"type": "boolean"},
            "review_reasons": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    }


def _find_external_analysis_assets() -> dict[str, list[Path]]:
    matches = {category: [] for category in ASSET_MARKERS}

    for path in APP_API_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".py", ".pyc"}:
            continue
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue

        relative_path = path.relative_to(APP_API_ROOT).as_posix().lower()
        if relative_path.startswith("src/services/"):
            continue

        search_text = f"{relative_path}\n{_safe_lower_text(path)}"
        if "analysis" not in search_text:
            continue

        for category, markers in ASSET_MARKERS.items():
            if any(marker in search_text for marker in markers):
                matches[category].append(path)

    return {category: sorted(paths) for category, paths in matches.items()}


def _analysis_source_files() -> list[Path]:
    source_files: list[Path] = []

    for path in sorted(SRC_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue

        text = path.read_text(encoding="utf-8").lower()
        relative_path = path.relative_to(APP_API_ROOT).as_posix().lower()
        if (
            "analysisservice" in text
            or "build_analysis_service" in text
            or "analysis_service" in relative_path
        ):
            source_files.append(path)

    return source_files


def _analysis_service_module():
    module_name = "src.application.analysis_service"
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def _schema_generator_callable():
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue

        module_text = path.read_text(encoding="utf-8")
        if "CONTRACTS.md" not in module_text:
            continue
        if "schema" not in module_text.lower():
            continue

        module_name = ".".join(path.relative_to(APP_API_ROOT).with_suffix("").parts)
        sys.modules.pop(module_name, None)
        module = importlib.import_module(module_name)
        for candidate_name in SCHEMA_GENERATOR_NAMES:
            candidate = getattr(module, candidate_name, None)
            if callable(candidate):
                return module_name, candidate_name, candidate

    return None


class Stage4ExternalAnalysisAssetsTests(unittest.TestCase):
    def test_contracts_document_defines_stage4_analysis_schema_and_tool_boundary(
        self,
    ) -> None:
        contracts_text = _contracts_text()

        self.assertIn("## Analysis Result Contract", contracts_text)
        self.assertIn("## Approved Tool API", contracts_text)

        self.assertEqual(
            _contract_analysis_fields(),
            [
                "summary",
                "score",
                "score_breakdown",
                "objections",
                "risks",
                "next_best_action",
                "coach_feedback",
                "used_knowledge",
                "confidence",
                "needs_review",
                "review_reasons",
            ],
        )
        self.assertEqual(
            _contract_approved_tools(),
            ["retrieve_context", "get_call_metadata"],
        )

    def test_stage4_prompt_rubric_and_schema_assets_exist_outside_service_code(
        self,
    ) -> None:
        assets = _find_external_analysis_assets()

        for category in ("prompt", "rubric", "schema"):
            self.assertTrue(
                assets[category],
                (
                    "expected Stage 4 to store the analysis "
                    f"{category} as an external artifact under apps/app-api; "
                    f"found none for {category}"
                ),
            )

        all_asset_paths = {
            path.relative_to(REPO_ROOT).as_posix()
            for paths in assets.values()
            for path in paths
        }
        self.assertTrue(
            all(
                not asset_path.startswith("apps/app-api/src/services/")
                for asset_path in all_asset_paths
            ),
            (
                "expected Stage 4 analysis assets to live outside service code; "
                f"found service-local asset paths: {sorted(all_asset_paths)}"
            ),
        )

    def test_stage4_analysis_layer_reads_external_assets_instead_of_embedding_them(
        self,
    ) -> None:
        source_files = _analysis_source_files()
        self.assertTrue(
            source_files,
            "expected a Stage 4 analysis layer source file under apps/app-api/src",
        )

        assets = _find_external_analysis_assets()
        asset_markers = {
            path.name.lower()
            for paths in assets.values()
            for path in paths
        }
        loader_markers = ("read_text(", ".open(", "importlib.resources", "files(")

        referencing_sources: list[str] = []
        for source_file in source_files:
            source_text = source_file.read_text(encoding="utf-8").lower()
            if not any(marker in source_text for marker in loader_markers):
                continue
            if any(asset_marker in source_text for asset_marker in asset_markers):
                referencing_sources.append(
                    source_file.relative_to(REPO_ROOT).as_posix()
                )

        self.assertTrue(
            referencing_sources,
            (
                "expected the Stage 4 analysis layer to read external prompt, "
                "rubric, and schema assets instead of embedding them inline"
            ),
        )

    def test_loaded_external_schema_matches_contracts_schema_contract(
        self,
    ) -> None:
        analysis_service_module = _analysis_service_module()
        service = analysis_service_module.build_analysis_service()
        loaded_schema = service.load_assets().schema
        expected_shape = _expected_schema_shape_from_contracts()

        self.assertEqual(loaded_schema.get("type"), "object")
        self.assertFalse(loaded_schema.get("additionalProperties", True))
        self.assertEqual(loaded_schema.get("required"), expected_shape["required"])
        self.assertEqual(
            set(loaded_schema.get("properties", {})),
            set(expected_shape["properties"]),
        )

        for field_name, field_shape in expected_shape["properties"].items():
            self.assertEqual(
                loaded_schema["properties"][field_name],
                field_shape,
                (
                    "expected the loaded external schema artifact to match "
                    f"the schema contract from docs/CONTRACTS.md for `{field_name}`"
                ),
            )

    def test_schema_artifact_is_generated_from_contracts_when_generator_exists(
        self,
    ) -> None:
        generator_details = _schema_generator_callable()
        if generator_details is None:
            self.skipTest("No Stage 4 schema generation callable from CONTRACTS.md found.")

        _, _, generator = generator_details
        generated_schema = generator()
        if isinstance(generated_schema, str):
            generated_schema = json.loads(generated_schema)

        analysis_service_module = _analysis_service_module()
        service = analysis_service_module.build_analysis_service()
        loaded_schema = service.load_assets().schema

        self.assertEqual(
            generated_schema,
            loaded_schema,
            (
                "expected the checked-in Stage 4 schema artifact to match the "
                "schema generated from docs/CONTRACTS.md"
            ),
        )

    def test_contracts_is_only_authoritative_source_for_approved_tool_boundary(
        self,
    ) -> None:
        approved_tools = _contract_approved_tools()
        self.assertEqual(approved_tools, ["retrieve_context", "get_call_metadata"])

        authoritative_duplicates: list[str] = []
        for path in sorted(DOCS_ROOT.rglob("*.md")):
            if path == CONTRACTS_PATH:
                continue

            text = path.read_text(encoding="utf-8")
            lower_text = text.lower()
            has_both_tools = all(tool in text for tool in approved_tools)
            if not has_both_tools:
                continue

            if "## approved tool api" in lower_text:
                authoritative_duplicates.append(path.relative_to(REPO_ROOT).as_posix())
                continue

            exact_bullets = sum(
                1 for tool in approved_tools if f"- `{tool}`" in text
            )
            if exact_bullets == len(approved_tools):
                authoritative_duplicates.append(path.relative_to(REPO_ROOT).as_posix())

        self.assertFalse(
            authoritative_duplicates,
            (
                "expected docs/CONTRACTS.md to remain the only authoritative "
                "document defining the approved Stage 4 tools; found duplicates in "
                f"{authoritative_duplicates}"
            ),
        )

        prompt_path = APP_API_ROOT / "src" / "resources" / "analysis" / "analysis_prompt.md"
        prompt_text = prompt_path.read_text(encoding="utf-8")
        self.assertNotIn("`retrieve_context`", prompt_text)
        self.assertNotIn("`get_call_metadata`", prompt_text)
