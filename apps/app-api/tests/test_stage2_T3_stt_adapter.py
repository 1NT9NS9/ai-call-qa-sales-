import ast
import importlib
import inspect
import sys
import unittest
from pathlib import Path


APP_API_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = APP_API_ROOT / "src"

if str(APP_API_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_API_ROOT))


def _clear_src_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)


def _iter_python_files() -> list[Path]:
    return [
        path
        for path in SRC_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _module_name_from_path(path: Path) -> str:
    return ".".join(path.relative_to(APP_API_ROOT).with_suffix("").parts)


class Stage2STTAdapterTests(unittest.TestCase):
    def _find_stt_adapter_modules(self) -> list[Path]:
        matches: list[Path] = []
        for path in _iter_python_files():
            module_text = path.read_text(encoding="utf-8")
            if "STTAdapter" in module_text:
                matches.append(path)
        return matches

    def test_stt_adapter_interface_exists_with_transcribe_method(self) -> None:
        adapter_modules = self._find_stt_adapter_modules()
        self.assertTrue(
            adapter_modules,
            "No STTAdapter definition was found under apps/app-api/src.",
        )

        try:
            for module_path in adapter_modules:
                module = importlib.import_module(_module_name_from_path(module_path))
                candidate = getattr(module, "STTAdapter", None)
                if candidate is None:
                    continue

                self.assertTrue(
                    inspect.isclass(candidate),
                    "STTAdapter exists but is not defined as a class.",
                )
                self.assertTrue(
                    hasattr(candidate, "transcribe"),
                    "STTAdapter is missing the required transcribe method.",
                )

                signature = inspect.signature(candidate.transcribe)
                self.assertIn("file_path", signature.parameters)
                return
        finally:
            _clear_src_modules()

        self.fail("No importable STTAdapter class was found under apps/app-api/src.")

    def test_exactly_one_concrete_stt_provider_is_defined(self) -> None:
        provider_classes: list[tuple[str, str]] = []

        for module_path in self._find_stt_adapter_modules():
            tree = ast.parse(module_path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                if node.name == "STTAdapter":
                    continue

                base_names = {
                    base.id
                    for base in node.bases
                    if isinstance(base, ast.Name)
                }
                base_names.update(
                    base.attr
                    for base in node.bases
                    if isinstance(base, ast.Attribute)
                )

                if "STTAdapter" in base_names:
                    provider_classes.append(
                        (module_path.as_posix(), node.name)
                    )

        self.assertEqual(
            len(provider_classes),
            1,
            "Expected exactly one concrete STT provider behind STTAdapter, "
            f"found {len(provider_classes)}: {provider_classes}",
        )
