from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


APP_API_DIR = Path(__file__).resolve().parents[1]
if str(APP_API_DIR) not in sys.path:
    sys.path.insert(0, str(APP_API_DIR))


@tool
def ping() -> str:
    """Return a static ping response."""
    return "pong"


def _extract_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
                continue
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
        return "".join(text_parts).strip()
    return str(content)


def main() -> None:
    from src.config.settings import load_settings
    from src.main import _build_analysis_chat_model

    settings = load_settings()
    model = _build_analysis_chat_model(settings)
    bound_model = model.bind_tools([ping])
    response = bound_model.invoke(
        "Reply with exactly this JSON and do not call any tool: "
        '{"ok": true, "provider": "langchain-openai"}'
    )
    text = _extract_text(response)
    parsed = json.loads(text)

    assert parsed["ok"] is True
    assert parsed["provider"] == "langchain-openai"

    print("LangChain OpenAI smoke test passed.")
    print(f"model={settings.model}")
    print(f"openai_base_url={settings.openai_base_url or 'https://api.openai.com/v1'}")
    print(text)


if __name__ == "__main__":
    main()
