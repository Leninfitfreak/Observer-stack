from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def generate_reasoning(self, prompt: str, metadata: dict | None = None) -> str:
        raise NotImplementedError
