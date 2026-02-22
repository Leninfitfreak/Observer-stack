import json
import logging
import math
import re
import time
from typing import Any

import requests

LOGGER = logging.getLogger("ai-observer")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def request_with_retry(
    method: str,
    url: str,
    *,
    attempts: int = 3,
    timeout: int = 10,
    **kwargs: Any,
) -> requests.Response:
    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as err:
            last_err = err
            LOGGER.warning(
                "request failed method=%s url=%s attempt=%d/%d error=%s",
                method,
                url,
                attempt,
                attempts,
                err,
            )
            if attempt < attempts:
                time.sleep(0.5 * attempt)

    raise RuntimeError(f"request failed after {attempts} attempts: {last_err}") from last_err


def parse_json_safe(value: str) -> dict[str, Any]:
    if not value:
        return {}

    def _try_parse(raw: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    parsed = _try_parse(value)
    if parsed:
        return parsed

    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
        parsed = _try_parse(cleaned)
        if parsed:
            return parsed

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        candidate = cleaned[start : end + 1]
        parsed = _try_parse(candidate)
        if parsed:
            return parsed

        repaired = candidate
        repaired = repaired.replace("“", '"').replace("”", '"').replace("’", "'")
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
        repaired = re.sub(r"\n\s*\n", "\n", repaired)
        parsed = _try_parse(repaired)
        if parsed:
            return parsed

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def clean_float(value: Any) -> float | None:
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except Exception:
        return None
