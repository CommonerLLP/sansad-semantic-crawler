from __future__ import annotations

import importlib
import json
import types
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode


def _load_commoner_probe_http() -> Any | None:
    try:
        return importlib.import_module("commoner_probe.http_client")
    except ModuleNotFoundError as exc:
        if exc.name not in {"commoner_probe", "commoner_probe.http_client"}:
            raise
        return None


_commoner_http = _load_commoner_probe_http()
USING_COMMONER_PROBE_HTTP = _commoner_http is not None
USER_AGENT = getattr(
    _commoner_http,
    "USER_AGENT",
    "commoner-analyse/2.2.0 (+https://github.com/CommonerLLP/commoner-analyse)",
)
DEFAULT_RATE_LIMIT_SEC = getattr(_commoner_http, "DEFAULT_RATE_LIMIT_SEC", 1.0)


if _commoner_http is not None:

    def make_session(rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC):
        return _commoner_http.make_session(rate_limit_sec=rate_limit_sec)

else:

    try:
        import requests  # type: ignore
    except ModuleNotFoundError:

        class StdlibResponse:
            def __init__(self, url: str, status_code: int, body: bytes):
                self.url = url
                self.status_code = status_code
                self._body = body
                self.text = body.decode("utf-8", errors="replace")

            def json(self) -> dict | list:
                return json.loads(self.text)

            def raise_for_status(self) -> None:
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code} for {self.url}")

            def iter_content(self, chunk_size: int = 16384):
                for i in range(0, len(self._body), chunk_size):
                    yield self._body[i : i + chunk_size]

        class StdlibSession:
            def __init__(self) -> None:
                self.headers: dict[str, str] = {"User-Agent": USER_AGENT}

            def get(self, url: str, **kwargs) -> StdlibResponse:
                params = kwargs.get("params")
                if params:
                    sep = "&" if "?" in url else "?"
                    url = url + sep + urlencode(params)
                headers = {**self.headers, **(kwargs.get("headers") or {})}
                timeout = kwargs.get("timeout") or 60
                req = urllib.request.Request(url, headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        return StdlibResponse(url, resp.status, resp.read())
                except urllib.error.HTTPError as exc:
                    return StdlibResponse(url, exc.code, exc.read())

        requests = types.SimpleNamespace(Session=StdlibSession)

    def make_session(rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC):
        return requests.Session()
