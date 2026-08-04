"""Unified async client for calling OpenAI, Anthropic, and Google Gemini models.

Each provider's official SDK is wrapped behind a single `generate` method so
the rest of the app (evaluator, workers) never has to branch on provider.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from prompt_eval.config import Settings, get_settings
from prompt_eval.models import Provider


class LLMClientError(Exception):
    """Raised when a provider call fails or is misconfigured (e.g. missing API key)."""


@dataclass
class LLMResponse:
    """The normalized result of a single generation call."""

    text: str
    provider: Provider
    model_id: str
    latency_ms: float
    raw: dict[str, Any] = field(default_factory=dict)


class LLMClient:
    """Routes generation requests to the correct provider SDK.

    Provider SDK clients are constructed lazily and cached per-instance so
    that importing this module never requires API keys to be present.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._openai_client: Any = None
        self._anthropic_client: Any = None
        self._google_configured = False

    async def generate(
        self,
        provider: Provider,
        model_id: str,
        prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        extra_params: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Generate a completion for `prompt` using the given provider and model.

        Args:
            provider: Which LLM provider to call.
            model_id: Provider-native model identifier (e.g. "gpt-4o", "claude-sonnet-5").
            prompt: The fully-rendered prompt text to send.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            extra_params: Additional provider-specific keyword arguments.

        Returns:
            A normalized `LLMResponse`.

        Raises:
            LLMClientError: If the provider is unsupported, misconfigured, or the call fails.
        """
        extra_params = extra_params or {}
        start = time.perf_counter()

        if provider == Provider.OPENAI:
            text, raw = await self._call_openai(model_id, prompt, temperature, max_tokens, extra_params)
        elif provider == Provider.ANTHROPIC:
            text, raw = await self._call_anthropic(model_id, prompt, temperature, max_tokens, extra_params)
        elif provider == Provider.GOOGLE:
            text, raw = await self._call_google(model_id, prompt, temperature, max_tokens, extra_params)
        else:
            raise LLMClientError(f"Unsupported provider: {provider}")

        latency_ms = (time.perf_counter() - start) * 1000
        return LLMResponse(text=text, provider=provider, model_id=model_id, latency_ms=latency_ms, raw=raw)

    async def _call_openai(
        self, model_id: str, prompt: str, temperature: float, max_tokens: int, extra: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        if not self._settings.openai_api_key:
            raise LLMClientError("OPENAI_API_KEY is not configured.")
        if self._openai_client is None:
            from openai import AsyncOpenAI

            self._openai_client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        try:
            response = await self._openai_client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                **extra,
            )
        except Exception as exc:
            raise LLMClientError(f"OpenAI call failed: {exc}") from exc
        text = response.choices[0].message.content or ""
        return text, response.model_dump()

    async def _call_anthropic(
        self, model_id: str, prompt: str, temperature: float, max_tokens: int, extra: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        if not self._settings.anthropic_api_key:
            raise LLMClientError("ANTHROPIC_API_KEY is not configured.")
        if self._anthropic_client is None:
            from anthropic import AsyncAnthropic

            self._anthropic_client = AsyncAnthropic(api_key=self._settings.anthropic_api_key)
        try:
            response = await self._anthropic_client.messages.create(
                model=model_id,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                **extra,
            )
        except Exception as exc:
            raise LLMClientError(f"Anthropic call failed: {exc}") from exc
        text = "".join(block.text for block in response.content if block.type == "text")
        return text, response.model_dump()

    async def _call_google(
        self, model_id: str, prompt: str, temperature: float, max_tokens: int, extra: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        if not self._settings.google_api_key:
            raise LLMClientError("GOOGLE_API_KEY is not configured.")
        import google.generativeai as genai

        if not self._google_configured:
            genai.configure(api_key=self._settings.google_api_key)
            self._google_configured = True
        try:
            model = genai.GenerativeModel(model_id)
            response = await model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=temperature, max_output_tokens=max_tokens, **extra
                ),
            )
        except Exception as exc:
            raise LLMClientError(f"Google Gemini call failed: {exc}") from exc
        text = response.text or ""
        raw = {"candidates": [c.finish_reason for c in response.candidates]} if response.candidates else {}
        return text, raw
