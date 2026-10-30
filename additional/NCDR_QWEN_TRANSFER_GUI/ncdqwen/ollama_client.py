"""Small JSON-only client for the local Ollama service."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE_URL = "http://localhost:11434"


class OllamaError(RuntimeError):
    """Ollama is unavailable or returned an unusable response."""


class OllamaClient:
    def __init__(self, model: str, base_url: str = BASE_URL, timeout: int = 180):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, endpoint: str, payload: dict | None = None) -> dict:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{endpoint}",
            data=body,
            headers={"Content-Type": "application/json"} if body is not None else {},
            method="POST" if body is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OllamaError(f"Local Ollama request failed: {exc}") from exc
        if not isinstance(result, dict):
            raise OllamaError("Ollama returned a non-object response")
        if result.get("error"):
            raise OllamaError(str(result["error"]))
        return result

    def model_available(self) -> bool:
        try:
            result = self._request("/api/tags")
        except OllamaError:
            return False
        names = {
            str(item.get("name") or item.get("model"))
            for item in result.get("models", [])
            if isinstance(item, dict) and (item.get("name") or item.get("model"))
        }
        normalized = {name.removesuffix(":latest") for name in names}
        wanted = self.model.removesuffix(":latest")
        return self.model in names or wanted in normalized

    def chat_json(self, system_prompt: str, user_prompt: str) -> tuple[str, dict]:
        result = self._request("/api/chat", {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0.1, "num_ctx": 8192, "num_predict": 512},
        })
        message = result.get("message")
        raw = message.get("content", "") if isinstance(message, dict) else ""
        if not isinstance(raw, str) or not raw.strip():
            raise OllamaError("Ollama returned an empty message")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Qwen response was not valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("Qwen response must be a JSON object")
        return raw, value
