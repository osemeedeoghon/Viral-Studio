"""Claude wrapper returning validated Pydantic objects via structured outputs."""
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from .config import settings

T = TypeVar("T", bound=BaseModel)
_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set — add it to .env and restart.")
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=600)
    return _client


def structured(system: str, content: str | list, schema: type[T], max_tokens: int = 16000) -> T:
    response = client().messages.parse(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_format=schema,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("The model declined this request. Try rewording the input.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise RuntimeError("The model response was cut off. Try a shorter input.")
    return response.parsed_output
