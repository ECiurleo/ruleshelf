"""Provider contract.

To support a new API dialect:

1. Create ``app/providers/mydriver.py``.
2. Subclass :class:`Provider`, set ``kind`` and call :func:`register_driver`.
3. Restart. The driver appears in the "Add provider" dialog automatically.

Providers that speak the OpenAI REST shape need no new file: add a custom
provider in the UI and pick the ``openai_compat`` driver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence


class ProviderError(Exception):
    """Raised for any upstream/configuration problem. Message is user-facing."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class ProviderConfig:
    id: str
    name: str
    kind: str
    base_url: str
    api_key: str = ""
    chat_model: str = ""
    embed_model: str = ""

    @classmethod
    def from_row(cls, row) -> "ProviderConfig":
        return cls(
            id=row["id"],
            name=row["name"],
            kind=row["kind"],
            base_url=(row["base_url"] or "").rstrip("/"),
            api_key=row["api_key"] or "",
            chat_model=row["chat_model"] or "",
            embed_model=row["embed_model"] or "",
        )


@dataclass(slots=True)
class ModelInfo:
    id: str
    kind: str = "chat"  # chat | embedding | unknown


class Provider:
    kind = "base"
    supports_embeddings = False

    def __init__(self, config: ProviderConfig):
        self.config = config

    # -- helpers ---------------------------------------------------------
    def _require_key(self) -> None:
        if not self.config.api_key:
            raise ProviderError(
                f"{self.config.name} has no API key. Add one in Settings → AI providers.",
                status_code=400,
            )

    def _require_base_url(self) -> str:
        if not self.config.base_url:
            raise ProviderError(f"{self.config.name} has no base URL configured.", 400)
        return self.config.base_url

    # -- capability API --------------------------------------------------
    def list_models(self) -> list[ModelInfo]:
        raise NotImplementedError

    def chat(
        self,
        messages: Sequence[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        """Yield response text deltas."""
        raise NotImplementedError

    def embed(self, texts: Iterable[str], model: str) -> list[list[float]]:
        raise ProviderError(f"{self.config.name} does not support embeddings.", 400)

    def test(self) -> str:
        models = self.list_models()
        return f"Connected — {len(models)} model(s) available."
