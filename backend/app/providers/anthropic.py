"""Anthropic Claude driver (Messages API, streaming)."""

from __future__ import annotations

import json
from typing import Iterator, Sequence

import httpx

from app.providers.base import ModelInfo, Provider, ProviderError

TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=30.0)
API_VERSION = "2023-06-01"


class AnthropicProvider(Provider):
    kind = "anthropic"

    def _headers(self) -> dict[str, str]:
        self._require_key()
        version = self.config.base_url.rstrip("/")
        return {
            "x-api-key": self.config.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
            "user-agent": f"ruleshelf/0.1 (+{version})",
        }

    def _url(self, path: str) -> str:
        base = self._require_base_url()
        if base.endswith("/v1"):
            return f"{base}{path}"
        return f"{base}/v1{path}"

    @staticmethod
    def _error(response: httpx.Response) -> ProviderError:
        detail = response.text
        try:
            payload = response.json()
            detail = payload.get("error", {}).get("message") or payload.get("error") or detail
        except Exception:  # noqa: BLE001
            pass
        return ProviderError(
            f"{response.status_code} from Anthropic: {str(detail)[:400]}",
            status_code=502 if response.status_code >= 500 else 400,
        )

    def list_models(self) -> list[ModelInfo]:
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.get(self._url("/models?limit=100"), headers=self._headers())
        except httpx.RequestError as exc:
            raise ProviderError(f"Could not reach {self.config.base_url}: {exc}", 502) from exc
        if resp.status_code >= 400:
            raise self._error(resp)
        return [
            ModelInfo(id=item["id"], kind="chat")
            for item in resp.json().get("data", [])
            if item.get("id")
        ]

    def chat(
        self,
        messages: Sequence[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        if not model:
            raise ProviderError("Choose a chat model for Claude.", 400)

        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        turns = [m for m in messages if m.get("role") != "system"]
        payload: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": turns,
            "stream": True,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                with client.stream(
                    "POST", self._url("/messages"), headers=self._headers(), json=payload
                ) as resp:
                    if resp.status_code >= 400:
                        resp.read()
                        raise self._error(resp)
                    for line in resp.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            event = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        if event.get("type") == "content_block_delta":
                            text = (event.get("delta") or {}).get("text")
                            if text:
                                yield text
                        elif event.get("type") == "error":
                            raise ProviderError(
                                (event.get("error") or {}).get("message", "Claude returned an error.")
                            )
        except httpx.RequestError as exc:
            raise ProviderError(f"Could not reach {self.config.base_url}: {exc}", 502) from exc


from app.providers import register_driver  # noqa: E402

register_driver(
    "anthropic",
    "Anthropic Messages API",
    "Claude models via the native Messages API.",
    cls=AnthropicProvider,
    supports_embeddings=False,
)
