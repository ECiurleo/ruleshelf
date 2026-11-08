"""OpenAI-compatible driver.

Covers OpenAI, DeepSeek, Qwen/DashScope, OpenRouter, LM Studio, vLLM, LiteLLM
gateways, Azure OpenAI-compatible proxies and anything else implementing
``POST {base_url}/chat/completions`` and ``POST {base_url}/embeddings``.
"""

from __future__ import annotations

import json
from typing import Iterable, Iterator, Sequence

import httpx

from app.providers.base import ModelInfo, Provider, ProviderError

TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=30.0)


class OpenAICompatProvider(Provider):
    kind = "openai_compat"
    supports_embeddings = True

    def _headers(self) -> dict[str, str]:
        self._require_key()
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self._require_base_url()}{path}"

    @staticmethod
    def _error(response: httpx.Response) -> ProviderError:
        detail = response.text.strip()
        try:
            payload = response.json()
            detail = (
                payload.get("error", {}).get("message")
                if isinstance(payload.get("error"), dict)
                else payload.get("error") or payload.get("detail") or detail
            )
        except Exception:  # noqa: BLE001 - body may not be JSON
            pass
        return ProviderError(
            f"{response.status_code} from provider: {str(detail)[:400]}",
            status_code=502 if response.status_code >= 500 else 400,
        )

    def list_models(self) -> list[ModelInfo]:
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.get(self._url("/models"), headers=self._headers())
        except httpx.RequestError as exc:
            raise ProviderError(f"Could not reach {self.config.base_url}: {exc}", 502) from exc
        if resp.status_code >= 400:
            raise self._error(resp)
        data = resp.json().get("data", [])
        out: list[ModelInfo] = []
        for item in data:
            model_id = item.get("id") if isinstance(item, dict) else str(item)
            if not model_id:
                continue
            lowered = model_id.lower()
            kind = "embedding" if "embed" in lowered else "chat"
            out.append(ModelInfo(id=model_id, kind=kind))
        return sorted(out, key=lambda m: m.id)

    def chat(
        self,
        messages: Sequence[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        if not model:
            raise ProviderError(f"Choose a chat model for {self.config.name}.", 400)
        payload = {
            "model": model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                with client.stream(
                    "POST", self._url("/chat/completions"), headers=self._headers(), json=payload
                ) as resp:
                    if resp.status_code >= 400:
                        resp.read()
                        raise self._error(resp)
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data in ("", "[DONE]"):
                            continue
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        for choice in chunk.get("choices", []):
                            delta = choice.get("delta") or {}
                            text = delta.get("content")
                            if text:
                                yield text
        except httpx.RequestError as exc:
            raise ProviderError(f"Could not reach {self.config.base_url}: {exc}", 502) from exc

    def embed(self, texts: Iterable[str], model: str) -> list[list[float]]:
        items = list(texts)
        if not model:
            raise ProviderError(f"Choose an embedding model for {self.config.name}.", 400)
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.post(
                    self._url("/embeddings"),
                    headers=self._headers(),
                    json={"model": model, "input": items},
                )
        except httpx.RequestError as exc:
            raise ProviderError(f"Could not reach {self.config.base_url}: {exc}", 502) from exc
        if resp.status_code >= 400:
            raise self._error(resp)
        data = resp.json().get("data", [])
        data = sorted(data, key=lambda d: d.get("index", 0))
        return [row["embedding"] for row in data]


from app.providers import register_driver  # noqa: E402  (registry is initialised first)

register_driver(
    "openai_compat",
    "OpenAI-compatible",
    "Any endpoint implementing /chat/completions and /embeddings.",
    cls=OpenAICompatProvider,
)
