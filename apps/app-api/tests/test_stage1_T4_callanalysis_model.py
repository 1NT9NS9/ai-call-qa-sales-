import importlib
import sys
import unittest
from unittest.mock import patch

from conftest import APP_API_ROOT, MINIMAL_ENV_VALUES, SRC_ROOT
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.inspection import inspect as sqlalchemy_inspect


REQUIRED_CALLANALYSIS_COLUMNS = {
    "call_id",
    "result_json",
    "confidence",
    "review_required",
    "review_reasons",
    "model_name",
    "prompt_version",
    "created_at",
    "updated_at",
}
def _candidate_module_names() -> list[str]:
    module_names: list[str] = []

    for path in sorted(SRC_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue

        module_text = path.read_text(encoding="utf-8")
        if "CallAnalysis" not in module_text and "CallSession" not in module_text:
            continue

        module_name = ".".join(path.relative_to(APP_API_ROOT).with_suffix("").parts)
        module_names.append(module_name)

    return module_names


class Stage1CallAnalysisModelTests(unittest.TestCase):
    def _load_mapped_class(self, class_name: str):
        candidate_class_found = False

        with patch.dict("os.environ", MINIMAL_ENV_VALUES, clear=True):
            for module_name in _candidate_module_names():
                sys.modules.pop(module_name, None)
                module = importlib.import_module(module_name)
                candidate = getattr(module, class_name, None)

                if candidate is None:
                    continue

                candidate_class_found = True

                try:
                    mapper = sqlalchemy_inspect(candidate)
                except NoInspectionAvailable:
                    continue

                return candidate, mapper

        if candidate_class_found:
            self.fail(
                f"Found a {class_name} class, but it is not mapped as a "
                "SQLAlchemy persistence model."
            )

        self.fail(
            f"No {class_name} persistence model was found under apps/app-api/src."
        )

    def test_callanalysis_model_contains_required_stage1_columns(self) -> None:
        _, mapper = self._load_mapped_class("CallAnalysis")

        column_names = {column.name for column in mapper.columns}

        self.assertTrue(
            REQUIRED_CALLANALYSIS_COLUMNS.issubset(column_names),
            (
                "CallAnalysis is missing one or more required persisted "
                f"fields: {sorted(REQUIRED_CALLANALYSIS_COLUMNS - column_names)}"
            ),
        )

    def test_callanalysis_call_id_links_to_callsession(self) -> None:
        call_session_model, _ = self._load_mapped_class("CallSession")
        call_analysis_model, mapper = self._load_mapped_class("CallAnalysis")

        self.assertIn("call_id", mapper.columns)

        call_id_column = call_analysis_model.__table__.columns["call_id"]
        foreign_keys = list(call_id_column.foreign_keys)

        self.assertTrue(
            foreign_keys,
            "CallAnalysis.call_id is expected to have a foreign key to CallSession.",
        )
        self.assertEqual(len(foreign_keys), 1)
        self.assertIs(
            next(iter(foreign_keys)).column.table,
            call_session_model.__table__,
        )

    def test_review_fields_live_on_callanalysis_not_callsession(self) -> None:
        call_session_model, call_session_mapper = self._load_mapped_class(
            "CallSession"
        )
        _, call_analysis_mapper = self._load_mapped_class("CallAnalysis")

        call_session_columns = {column.name for column in call_session_mapper.columns}
        call_analysis_columns = {
            column.name for column in call_analysis_mapper.columns
        }

        self.assertIn("processing_status", call_session_columns)
        self.assertIn("review_required", call_analysis_columns)
        self.assertIn("review_reasons", call_analysis_columns)
        self.assertNotIn("review_required", call_session_columns)
        self.assertNotIn("review_reasons", call_session_columns)
        self.assertIn("processing_status", call_session_model.__table__.columns)
