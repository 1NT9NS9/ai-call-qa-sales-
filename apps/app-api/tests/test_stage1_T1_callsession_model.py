import importlib
import re
import sys
import unittest
from unittest.mock import patch

from conftest import APP_API_ROOT, MINIMAL_ENV_VALUES, SRC_ROOT
from sqlalchemy import CheckConstraint, Enum as SqlEnum
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.inspection import inspect as sqlalchemy_inspect


REQUIRED_CALLSESSION_COLUMNS = {
    "id",
    "external_call_id",
    "processing_status",
    "audio_storage_key",
    "source_type",
    "metadata",
    "created_at",
    "updated_at",
}
LIFECYCLE_STATUS_VALUES = (
    "created",
    "uploaded",
    "transcribed",
    "analyzed",
    "exported",
    "failed",
)
def _candidate_module_names() -> list[str]:
    module_names: list[str] = []

    for path in sorted(SRC_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue

        module_text = path.read_text(encoding="utf-8")
        if "CallSession" not in module_text:
            continue

        module_name = ".".join(path.relative_to(APP_API_ROOT).with_suffix("").parts)
        module_names.append(module_name)

    return module_names


class Stage1CallSessionModelTests(unittest.TestCase):
    def _load_callsession_mapper(self):
        candidate_class_found = False

        with patch.dict("os.environ", MINIMAL_ENV_VALUES, clear=True):
            for module_name in _candidate_module_names():
                sys.modules.pop(module_name, None)
                module = importlib.import_module(module_name)
                candidate = getattr(module, "CallSession", None)

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
                "Found a CallSession class, but it is not mapped as a "
                "SQLAlchemy persistence model."
            )

        self.fail(
            "No CallSession persistence model was found under apps/app-api/src."
        )

    def _extract_processing_status_values(self, call_session_model) -> tuple[str, ...]:
        processing_status_column = call_session_model.__table__.columns[
            "processing_status"
        ]

        if isinstance(processing_status_column.type, SqlEnum):
            enum_class = processing_status_column.type.enum_class
            if enum_class is not None:
                return tuple(member.value for member in enum_class)

            return tuple(processing_status_column.type.enums)

        for constraint in call_session_model.__table__.constraints:
            if not isinstance(constraint, CheckConstraint):
                continue

            constraint_text = str(constraint.sqltext)
            if "processing_status" not in constraint_text:
                continue

            values = tuple(re.findall(r"'([^']+)'", constraint_text))
            if values:
                return values

        self.fail(
            "CallSession.processing_status is database-backed, but no lifecycle "
            "value set was found on the mapped column or table constraints."
        )

    def test_callsession_model_contains_required_stage1_columns(self) -> None:
        _, mapper = self._load_callsession_mapper()

        column_names = {column.name for column in mapper.columns}

        self.assertTrue(
            REQUIRED_CALLSESSION_COLUMNS.issubset(column_names),
            (
                "CallSession is missing one or more required persisted fields: "
                f"{sorted(REQUIRED_CALLSESSION_COLUMNS - column_names)}"
            ),
        )

    def test_callsession_processing_status_uses_contract_lifecycle_values(
        self,
    ) -> None:
        call_session_model, mapper = self._load_callsession_mapper()

        self.assertIn("processing_status", mapper.columns)
        self.assertEqual(
            self._extract_processing_status_values(call_session_model),
            LIFECYCLE_STATUS_VALUES,
        )
