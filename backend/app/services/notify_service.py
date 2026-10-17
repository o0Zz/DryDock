from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 10.0


def send(webhook_url: str, event: str, payload: dict[str, Any]) -> bool:
    """POST a JSON notification to the configured webhook.

    Never raises: a broken webhook must not fail the scan that triggered it.
    Returns True when the endpoint accepted the delivery.
    """
    url = (webhook_url or "").strip()
    if not url:
        return False

    body = {"source": "drydock", "event": event, **payload}
    try:
        response = httpx.post(url, json=body, timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Webhook delivery for %s failed: %s", event, exc)
        return False
    logger.info("Webhook delivered for %s", event)
    return True
