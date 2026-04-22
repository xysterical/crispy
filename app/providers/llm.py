from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LlmResponse:
    text: str
    model_used: str
    tokens_prompt: int = 0
    tokens_completion: int = 0
    estimated_cost: float = 0.0


class LlmProvider:
    """Interface for text generation providers."""

    def complete(self, prompt: str, *, model: str) -> LlmResponse:
        raise NotImplementedError


class KimiStubProvider(LlmProvider):
    """
    MVP-safe default provider.
    Replace with real Kimi API integration once credentials are available.
    """

    def complete(self, prompt: str, *, model: str) -> LlmResponse:
        snippet = prompt.strip().replace("\n", " ")[:280]
        text = f"[{model}] {snippet}"
        return LlmResponse(
            text=text,
            model_used=model,
            tokens_prompt=max(1, len(prompt) // 4),
            tokens_completion=max(1, len(text) // 4),
            estimated_cost=0.0,
        )


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, LlmProvider] = {"kimi": KimiStubProvider()}

    def get(self, name: str) -> LlmProvider:
        return self._providers.get(name, self._providers["kimi"])

