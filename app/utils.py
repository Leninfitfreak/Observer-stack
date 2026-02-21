import json
import logging
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
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}
