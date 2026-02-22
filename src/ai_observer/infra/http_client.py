from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class HttpClient:
    timeout_seconds: int = 30
    attempts: int = 3

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        timeout = kwargs.pop("timeout", self.timeout_seconds)
        attempts = max(1, kwargs.pop("attempts", self.attempts))

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = requests.request(method=method, url=url, timeout=timeout, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt == attempts:
                    break
        raise RuntimeError(f"request failed after {attempts} attempts: {last_error}") from last_error
