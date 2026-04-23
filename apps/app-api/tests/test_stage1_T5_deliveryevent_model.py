import importlib
import sys
import unittest
from unittest.mock import patch

from conftest import APP_API_ROOT, MINIMAL_ENV_VALUES, SRC_ROOT
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.inspection import inspect as sqlalchemy_inspect


REQUIRED_DELIVERYEVENT_COLUMNS = {
    "call_id",
    "target_url",
    "delivery_status",
    "response_code",
    "attempt_no",
    "error_message",
}
def _candidate_module_names() -> list[str]:
    module_names: list[str] = []

    for path in sorted(SRC_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue

        module_text = path.read_text(encoding="utf-8")
        if "DeliveryEvent" not in module_text and "CallSession" not in module_text:
            continue

        module_name = ".".join(path.relative_to(APP_API_ROOT).with_suffix("").parts)
        module_names.append(module_name)

    return module_names


class Stage1DeliveryEventModelTests(unittest.TestCase):
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

    def test_deliveryevent_model_contains_required_stage1_columns(self) -> None:
        _, mapper = self._load_mapped_class("DeliveryEvent")

        column_names = {column.name for column in mapper.columns}

        self.assertTrue(
            REQUIRED_DELIVERYEVENT_COLUMNS.issubset(column_names),
            (
                "DeliveryEvent is missing one or more required persisted "
                f"fields: {sorted(REQUIRED_DELIVERYEVENT_COLUMNS - column_names)}"
            ),
        )

    def test_deliveryevent_call_id_links_to_callsession(self) -> None:
        call_session_model, _ = self._load_mapped_class("CallSession")
        delivery_event_model, mapper = self._load_mapped_class("DeliveryEvent")

        self.assertIn("call_id", mapper.columns)

        call_id_column = delivery_event_model.__table__.columns["call_id"]
        foreign_keys = list(call_id_column.foreign_keys)

        self.assertTrue(
            foreign_keys,
            "DeliveryEvent.call_id is expected to have a foreign key to CallSession.",
        )
        self.assertEqual(len(foreign_keys), 1)
        self.assertIs(
            next(iter(foreign_keys)).column.table,
            call_session_model.__table__,
        )
