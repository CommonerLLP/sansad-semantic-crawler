from __future__ import annotations

import importlib
import sys
import types
import unittest
import unittest.mock as mock
from collections.abc import Callable
from contextlib import contextmanager
from types import ModuleType
from typing import Iterator


REAL_IMPORT_MODULE = importlib.import_module
TARGET_MODULE = "sansad_semantic_crawler.http_client"


@contextmanager
def reloaded_http_client(
    import_module: Callable[[str], ModuleType],
) -> Iterator[ModuleType]:
    original = sys.modules.pop(TARGET_MODULE, None)
    package = sys.modules.get("sansad_semantic_crawler")
    old_attr = getattr(package, "http_client", None) if package is not None else None
    if package is not None and hasattr(package, "http_client"):
        delattr(package, "http_client")
    try:
        with mock.patch("importlib.import_module", side_effect=import_module):
            yield REAL_IMPORT_MODULE(TARGET_MODULE)
    finally:
        sys.modules.pop(TARGET_MODULE, None)
        if original is not None:
            sys.modules[TARGET_MODULE] = original
        if package is not None and old_attr is not None:
            setattr(package, "http_client", old_attr)


class HttpClientCompatTests(unittest.TestCase):
    def test_make_session_delegates_to_commoner_probe_when_available(self):
        calls: list[float] = []

        fake_commoner_http = types.ModuleType("commoner_probe.http_client")
        fake_commoner_http.USER_AGENT = "commoner-probe/test"
        fake_commoner_http.DEFAULT_RATE_LIMIT_SEC = 2.5

        def fake_make_session(rate_limit_sec: float = 2.5):
            calls.append(rate_limit_sec)
            return {"rate_limit_sec": rate_limit_sec}

        fake_commoner_http.make_session = fake_make_session

        def fake_import_module(name: str) -> ModuleType:
            if name == "commoner_probe.http_client":
                return fake_commoner_http
            return REAL_IMPORT_MODULE(name)

        with reloaded_http_client(fake_import_module) as http_client:
            self.assertTrue(http_client.USING_COMMONER_PROBE_HTTP)
            self.assertEqual(http_client.USER_AGENT, "commoner-probe/test")

            session = http_client.make_session(rate_limit_sec=0.25)

        self.assertEqual(session, {"rate_limit_sec": 0.25})
        self.assertEqual(calls, [0.25])

    def test_make_session_falls_back_when_commoner_probe_is_unavailable(self):
        def fake_import_module(name: str) -> ModuleType:
            if name == "commoner_probe.http_client":
                raise ModuleNotFoundError(name, name="commoner_probe")
            return REAL_IMPORT_MODULE(name)

        with reloaded_http_client(fake_import_module) as http_client:
            self.assertFalse(http_client.USING_COMMONER_PROBE_HTTP)
            session = http_client.make_session()

        self.assertTrue(hasattr(session, "get"))
        self.assertTrue(hasattr(session, "headers"))

    def test_commoner_probe_internal_import_errors_are_not_silently_hidden(self):
        def fake_import_module(name: str) -> ModuleType:
            if name == "commoner_probe.http_client":
                raise ModuleNotFoundError(
                    "No module named 'missing_dependency'",
                    name="missing_dependency",
                )
            return REAL_IMPORT_MODULE(name)

        with self.assertRaises(ModuleNotFoundError):
            with reloaded_http_client(fake_import_module):
                pass


if __name__ == "__main__":
    unittest.main()
