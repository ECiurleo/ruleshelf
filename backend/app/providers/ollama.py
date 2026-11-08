"""Ollama native driver (chat + embeddings), no API key required."""

from __future__ import annotations

import json
from typing import Iterable, Iterator, Sequence

import httpx

from app.providers.base import ModelInfo, Provider, ProviderError

TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=30.0)


class OllamaProvider(Provider):
    kind = "ollama"
    supports_embeddings = True

    def _root(self) -> str:
        base = self._require_base_url()
        # Users often paste the OpenAI-compatible URL; both work here.
        return base[:-3] if base.endswith("/v1") else base

    def _url(self, path: str) -> str:
        return f"{self._root()}{path}"

    @staticmethod
    def _error(response: httpx.Response) -> ProviderError:
        try:
            detail = response.json().get("error") or response.text
        except Exception:  # noqa: BLE001
            detail = response.text
        return ProviderError(f"Ollama error ({response.status_code}): {str(detail)[:400]}")

    def list_models(self) -> list[ModelInfo]:
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.get(self._url("/api/tags"))
        except httpx.RequestError as exc:
            raise ProviderError(
                f"Could not reach Ollama at {self.config.base_url}. Is it running? ({exc})",
                502,
            ) from exc
        if resp.status_code >= 400:
            raise self._error(resp)
        out = []
        for item in resp.json().get("models", []):
            name = item.get("name") or item.get("model")
            if name:
                kind = "embedding" if "embed" in name.lower() or "bge" in name.lower() else "chat"
                out.append(ModelInfo(id=name, kind=kind))
        return sorted(out, key=lambda m: m.id)

    def chat(
        self,
        messages: Sequence[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        if not model:
            raise ProviderError("Choose a chat model for Ollama.", 400)
        payload = {
            "model": model,
            "messages": list(messages),
            "stream": True,
            # Ruleshelf sends several long excerpts; the Ollama default of 2048
            # tokens would silently truncate them. Keep the model warm too.
            "keep_alive": "30m",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": 8192,
            },
        }
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                with client.stream("POST", self._url("/api/chat"), json=payload) as resp:
                    if resp.status_code >= 400:
                        resp.read()
                        raise self._error(resp)
                    for line in resp.iter_lines():
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if event.get("error"):
                            raise ProviderError(f"Ollama: {event['error']}")
                        text = (event.get("message") or {}).get("content")
                        if text:
                            yield text
                        if event.get("done"):
                            break
        except httpx.RequestError as exc:
            raise ProviderError(
                f"Could not reach Ollama at {self.config.base_url}. Is it running? ({exc})",
                502,
            ) from exc

    def embed(self, texts: Iterable[str], model: str) -> list[list[float]]:
        items = list(texts)
        if not model:
            raise ProviderError("Choose an embedding model for Ollama (e.g. nomic-embed-text).", 400)
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.post(
                    self._url("/api/embed"), json={"model": model, "input": items}
                )
                if resp.status_code == 404:
                    # Older Ollama: one prompt per request.
                    vectors = []
                    for text in items:
                        single = client.post(
                            self._url("/api/embeddings"),
                            json={"model": model, "prompt": text},
                        )
                        if single.status_code >= 400:
                            raise self._error(single)
                        vectors.append(single.json()["embedding"])
                    return vectors
        except httpx.RequestError as exc:
            raise ProviderError(f"Could not reach Ollama: {exc}", 502) from exc
        if resp.status_code >= 400:
            raise self._error(resp)
        return resp.json().get("embeddings", [])


from app.providers import register_driver  # noqa: E402

register_driver(
    "ollama",
    "Ollama",
    "Local or remote Ollama: chat and embeddings without an API key.",
    cls=OllamaProvider,
    requires_api_key=False,
    default_base_url="http://localhost:11434",
)
