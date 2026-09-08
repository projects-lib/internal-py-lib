import os
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class ConfigServerClient:
    def __init__(
        self,
        uri: Optional[str] = None,
        application: Optional[str] = None,
        profile: Optional[str] = None,
        label: Optional[str] = None,
        fail_fast: Optional[bool] = None,
        timeout: Optional[float] = None,
    ):
        self.uri = (uri or os.getenv("SPRING_CLOUD_CONFIG_URI", "http://localhost:8888")).rstrip("/")
        self.application = application or os.getenv("APPLICATION_NAME", "application")
        self.profile = profile or os.getenv("SPRING_CLOUD_CONFIG_PROFILE", "default")
        self.label = label or os.getenv("LABEL") or None
        self.fail_fast = (
            fail_fast
            if fail_fast is not None
            else _truthy(os.getenv("SPRING_CLOUD_CONFIG_FAIL_FAST", "true"))
        )
        self.timeout = (
            timeout
            if timeout is not None
            else float(os.getenv("SPRING_CLOUD_CONFIG_REQUEST_TIMEOUT", "10"))
        )

    def _build_url(self) -> str:
        parts = [self.uri, self.application, self.profile]
        if self.label:
            parts.append(self.label)
        return "/".join(parts)

    def fetch(self) -> Dict[str, Any]:
        url = self._build_url()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            msg = f"Failed to fetch configuration from Config Server ({url}): {exc}"
            if self.fail_fast:
                raise RuntimeError(msg) from exc
            logger.warning("%s. Continuing with defaults.", msg)
            return {}

        return self._merge_property_sources(payload)

    @staticmethod
    def _merge_property_sources(payload: Dict[str, Any]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        sources = payload.get("propertySources", []) or []
        for source in reversed(sources):
            src_map = source.get("source", {}) or {}
            merged.update(src_map)
        return merged