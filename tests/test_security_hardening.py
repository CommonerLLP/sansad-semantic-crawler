"""Regression tests for the v0.6.x security hardening pass.

Each test pins one finding from the security review against future
regressions. Findings reference: H1 (SSRF / endpoint scheme), H2 (redact
key list), H3 (env: api_key indirection), M1 (PDF dest path traversal),
M2 (LLM JSON fallback regex), M4 (exception text leakage).
"""

from __future__ import annotations

import json
import os
import re
import unittest
import unittest.mock as mock

from commoner_analyse.base import safe_filename_segment
from commoner_analyse.discourse import (
    CHANNEL_QA,
    DISCOURSE_LABEL_DESCRIPTIONS,
    LLM_CLASSIFIER_VERSION,
    _ALLOWED_LLM_SCHEMES,
    _parse_llm_json,
    _resolve_api_key,
    _validate_llm_endpoint,
    classify_response_llm,
)
from commoner_analyse.runlog import _is_secret_key, _redact


# --------------------------------------------------------------------------- #
# H1 — endpoint scheme/host validation (SSRF guard)                            #
# --------------------------------------------------------------------------- #


class EndpointValidationTests(unittest.TestCase):

    def test_http_endpoint_accepted(self):
        _validate_llm_endpoint("http://localhost:11434/v1")  # should not raise

    def test_https_endpoint_accepted(self):
        _validate_llm_endpoint("https://api.example.com/v1")

    def test_file_scheme_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _validate_llm_endpoint("file:///etc/passwd")
        self.assertIn("scheme", str(cm.exception).lower())

    def test_ftp_scheme_rejected(self):
        with self.assertRaises(ValueError):
            _validate_llm_endpoint("ftp://attacker.example/llm")

    def test_gopher_scheme_rejected(self):
        with self.assertRaises(ValueError):
            _validate_llm_endpoint("gopher://attacker.example/")

    def test_data_uri_rejected(self):
        with self.assertRaises(ValueError):
            _validate_llm_endpoint("data:text/plain;base64,SGk=")

    def test_javascript_uri_rejected(self):
        with self.assertRaises(ValueError):
            _validate_llm_endpoint("javascript:alert(1)")

    def test_localhost_blocked_when_allow_private_false(self):
        with self.assertRaises(ValueError):
            _validate_llm_endpoint(
                "http://localhost:11434/v1", allow_private=False
            )

    def test_loopback_ip_blocked_when_allow_private_false(self):
        with self.assertRaises(ValueError):
            _validate_llm_endpoint("http://127.0.0.1/", allow_private=False)

    def test_private_ip_blocked_when_allow_private_false(self):
        with self.assertRaises(ValueError):
            _validate_llm_endpoint("http://10.0.0.1/", allow_private=False)

    def test_link_local_blocked_when_allow_private_false(self):
        with self.assertRaises(ValueError):
            _validate_llm_endpoint(
                "http://169.254.169.254/latest/meta-data/", allow_private=False
            )

    def test_public_host_passes_when_allow_private_false(self):
        # If this raises, the hardened path can't reach any endpoint.
        fake_resolved = [(2, 1, 6, "", ("93.184.216.34", 0))]
        with mock.patch(
            "commoner_analyse.discourse.socket.getaddrinfo",
            return_value=fake_resolved,
        ):
            _validate_llm_endpoint(
                "https://api.openai.com/v1", allow_private=False
            )

    def test_allowed_schemes_constant_is_immutable(self):
        # Must be a frozenset so a runtime mutation cannot widen the policy.
        self.assertIsInstance(_ALLOWED_LLM_SCHEMES, frozenset)

    def test_hostname_resolving_to_private_ip_blocked(self):
        """Regression for the P1 finding from PR #19's chatgpt-codex review:
        a hostname (not an IP literal) was previously waved through, so a
        DNS name pointing at a private/internal IP would bypass
        --llm-block-private. Now we resolve and check every returned
        address."""
        # Mock getaddrinfo to return 10.0.0.5 for the hostname.
        fake_resolved = [(2, 1, 6, "", ("10.0.0.5", 0))]
        with mock.patch(
            "commoner_analyse.discourse.socket.getaddrinfo",
            return_value=fake_resolved,
        ):
            with self.assertRaises(ValueError) as cm:
                _validate_llm_endpoint(
                    "https://internal.corp.example/v1",
                    allow_private=False,
                )
            self.assertIn("private", str(cm.exception).lower())

    def test_hostname_resolving_to_link_local_ip_blocked(self):
        """169.254.169.254 (cloud metadata service) was the canonical SSRF
        target before this fix."""
        fake_resolved = [(2, 1, 6, "", ("169.254.169.254", 0))]
        with mock.patch(
            "commoner_analyse.discourse.socket.getaddrinfo",
            return_value=fake_resolved,
        ):
            with self.assertRaises(ValueError):
                _validate_llm_endpoint(
                    "http://metadata.attacker.example/",
                    allow_private=False,
                )

    def test_hostname_resolving_to_public_ip_passes(self):
        fake_resolved = [(2, 1, 6, "", ("8.8.8.8", 0))]
        with mock.patch(
            "commoner_analyse.discourse.socket.getaddrinfo",
            return_value=fake_resolved,
        ):
            _validate_llm_endpoint(
                "https://dns.google/v1", allow_private=False,
            )

    def test_hostname_with_mixed_resolution_blocked_when_any_private(self):
        """If a name resolves to BOTH public and private addresses, the
        validator must reject — otherwise an attacker can poison DNS
        with a public-prefixed first record and slip private ones in."""
        fake_resolved = [
            (2, 1, 6, "", ("8.8.8.8", 0)),
            (2, 1, 6, "", ("10.0.0.1", 0)),
        ]
        with mock.patch(
            "commoner_analyse.discourse.socket.getaddrinfo",
            return_value=fake_resolved,
        ):
            with self.assertRaises(ValueError):
                _validate_llm_endpoint(
                    "https://mixed.example/", allow_private=False,
                )

    def test_dns_failure_blocked_in_hardened_mode(self):
        """If we can't resolve the host at all, refuse rather than
        falling through and letting urllib do it (where it would
        bypass our policy check)."""
        with mock.patch(
            "commoner_analyse.discourse.socket.getaddrinfo",
            side_effect=OSError("nodename nor servname provided"),
        ):
            with self.assertRaises(ValueError) as cm:
                _validate_llm_endpoint(
                    "https://nonexistent.example/", allow_private=False,
                )
            self.assertIn("resolved", str(cm.exception).lower())

    def test_dns_resolution_skipped_when_allow_private_true(self):
        """The default zero-config local-Ollama path should not pay the
        DNS-resolution latency cost. The validator only resolves when
        allow_private=False."""
        called = []
        original = __import__(
            "commoner_analyse.discourse", fromlist=["socket"]
        ).socket.getaddrinfo

        def _track(*args, **kwargs):
            called.append(args)
            return original(*args, **kwargs)

        with mock.patch(
            "commoner_analyse.discourse.socket.getaddrinfo",
            side_effect=_track,
        ):
            _validate_llm_endpoint(
                "https://api.example.com/v1", allow_private=True,
            )
        self.assertEqual(
            called, [],
            "DNS resolution must not happen when allow_private=True",
        )


class SsrfThroughClassifyResponseLlmTests(unittest.TestCase):
    """The classifier must catch the ValueError and return UNCLASSIFIED
    with a categorical reason — not propagate the exception, not leak
    the bad URL into the corpus."""

    def test_file_scheme_returns_unclassified_categorical(self):
        c = classify_response_llm(
            "any text",
            CHANNEL_QA,
            endpoint="file:///etc/passwd",
        )
        self.assertEqual(c.label, "UNCLASSIFIED")
        self.assertIn("safety policy", c.audit_description)
        # The file:// path itself must not appear in the public output.
        self.assertNotIn("/etc/passwd", c.audit_description)
        self.assertNotIn("file://", c.audit_description)


# --------------------------------------------------------------------------- #
# H2 — redact key list (substring-based)                                       #
# --------------------------------------------------------------------------- #


class RedactKeyTests(unittest.TestCase):

    def test_api_key_redacted(self):
        self.assertTrue(_is_secret_key("api_key"))

    def test_apikey_camel_redacted(self):
        self.assertTrue(_is_secret_key("apiKey"))

    def test_apikey_lowercase_redacted(self):
        self.assertTrue(_is_secret_key("apikey"))

    def test_OPENAI_API_KEY_redacted(self):
        self.assertTrue(_is_secret_key("OPENAI_API_KEY"))

    def test_secret_redacted(self):
        self.assertTrue(_is_secret_key("secret"))

    def test_client_secret_redacted(self):
        self.assertTrue(_is_secret_key("client_secret"))

    def test_access_token_redacted(self):
        self.assertTrue(_is_secret_key("access_token"))

    def test_bearer_token_redacted(self):
        self.assertTrue(_is_secret_key("bearer_token"))

    def test_password_redacted(self):
        self.assertTrue(_is_secret_key("password"))

    def test_authorization_redacted(self):
        self.assertTrue(_is_secret_key("authorization"))

    def test_credential_redacted(self):
        self.assertTrue(_is_secret_key("credential"))

    def test_innocent_keys_not_redacted(self):
        for k in ("model", "endpoint", "temperature", "channel", "topic"):
            self.assertFalse(
                _is_secret_key(k),
                f"{k!r} should not be flagged as a credential key",
            )

    def test_redact_walks_nested_dicts(self):
        obj = {
            "model": "qwen2.5",
            "config": {
                "api_key": "sk-real-secret",
                "client_secret": "shh",
                "endpoint": "http://localhost:11434/v1",
            },
        }
        out = _redact(obj)
        self.assertEqual(out["model"], "qwen2.5")
        self.assertEqual(out["config"]["api_key"], "<redacted>")
        self.assertEqual(out["config"]["client_secret"], "<redacted>")
        self.assertEqual(out["config"]["endpoint"], "http://localhost:11434/v1")

    def test_redact_walks_lists_of_dicts(self):
        obj = {"members": [{"api_key": "x"}, {"name": "y"}]}
        out = _redact(obj)
        self.assertEqual(out["members"][0]["api_key"], "<redacted>")
        self.assertEqual(out["members"][1]["name"], "y")


# --------------------------------------------------------------------------- #
# H3 — env: indirection for api_key                                            #
# --------------------------------------------------------------------------- #


class ApiKeyResolutionTests(unittest.TestCase):

    def test_none_returns_none(self):
        self.assertIsNone(_resolve_api_key(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_resolve_api_key(""))

    def test_literal_key_passes_through(self):
        self.assertEqual(_resolve_api_key("sk-abc"), "sk-abc")

    def test_env_indirection_resolved(self):
        with mock.patch.dict(os.environ, {"MY_LLM_KEY": "sk-fromenv"}):
            self.assertEqual(_resolve_api_key("env:MY_LLM_KEY"), "sk-fromenv")

    def test_env_indirection_missing_var_returns_none(self):
        # If the env var doesn't exist, return None — caller should
        # treat as "no auth header sent" rather than literal "env:VAR".
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEFINITELY_NOT_SET", None)
            self.assertIsNone(_resolve_api_key("env:DEFINITELY_NOT_SET"))


class ApiKeyEndToEndTests(unittest.TestCase):
    """The api_key parameter must reach _discourse_http_post via
    classify_response_llm, and env: indirection must be resolved."""

    def test_api_key_reaches_http_post(self):
        captured = {}

        def _capture(endpoint, payload, *, timeout_s, api_key=None, allow_private=True):
            captured["api_key"] = api_key
            return json.dumps({"label": "DEFLECTED", "confidence": 0.8})

        classify_response_llm(
            "text",
            CHANNEL_QA,
            api_key="sk-explicit",
            _http_post=_capture,
        )
        self.assertEqual(captured["api_key"], "sk-explicit")


# --------------------------------------------------------------------------- #
# M1 — safe filename segment                                                   #
# --------------------------------------------------------------------------- #


class SafeFilenameSegmentTests(unittest.TestCase):
    """The contract is *safety* (the result cannot escape its parent
    directory or carry shell metacharacters), not *prettiness*. Tests
    assert properties — never an equality match — so the sanitization
    rule can evolve without churning the test suite."""

    SAFE_RE = re.compile(r"^[A-Za-z0-9._-]+$")

    def test_simple_alphanumeric_passes_through(self):
        self.assertEqual(safe_filename_segment("finance_18_42"), "finance_18_42")

    def test_result_is_always_in_safe_charset(self):
        for inp in (
            "../../etc/passwd",
            "/etc/shadow",
            "..\\..\\windows\\system32",
            "name with spaces",
            "स्थायी_समिति",
            "name|`rm -rf /`",
            "name;injection&attack",
            "name<script>",
            "C:\\Users\\admin",
        ):
            seg = safe_filename_segment(inp)
            self.assertRegex(
                seg, self.SAFE_RE,
                f"sanitized output {seg!r} contains unsafe chars (input {inp!r})",
            )

    def test_path_separators_neutralized(self):
        for inp in ("../../etc/passwd", "/etc/shadow", "a/b/c", "a\\b\\c"):
            seg = safe_filename_segment(inp)
            self.assertNotIn("/", seg)
            self.assertNotIn("\\", seg)

    def test_no_parent_directory_traversal(self):
        # Even after sanitization, the result must not be ``..`` or ``.``.
        for inp in ("..", ".", "...", "../..", "./.."):
            seg = safe_filename_segment(inp)
            self.assertNotIn(seg, {".", ".."})

    def test_none_returns_unknown(self):
        self.assertEqual(safe_filename_segment(None), "unknown")

    def test_empty_string_returns_unknown(self):
        self.assertEqual(safe_filename_segment(""), "unknown")
        self.assertEqual(safe_filename_segment("   "), "unknown")

    def test_int_input_stringified(self):
        self.assertEqual(safe_filename_segment(42), "42")

    def test_shell_metacharacters_neutralized(self):
        for c in ("&", ";", "|", "`", "$", ">", "<", "*", "?", "(", ")"):
            seg = safe_filename_segment(f"name{c}injection")
            self.assertNotIn(c, seg, f"{c!r} survived sanitization in {seg!r}")


# --------------------------------------------------------------------------- #
# M2 — LLM JSON parse fallback handles nested objects                          #
# --------------------------------------------------------------------------- #


class ParseLlmJsonTests(unittest.TestCase):

    def test_pure_json_parses(self):
        out = _parse_llm_json('{"label": "DEFLECTED", "confidence": 0.8}')
        self.assertEqual(out["label"], "DEFLECTED")

    def test_json_in_markdown_fence_recovered(self):
        wrapped = '```json\n{"label": "DEFLECTED", "confidence": 0.8}\n```'
        out = _parse_llm_json(wrapped)
        self.assertEqual(out["label"], "DEFLECTED")

    def test_nested_objects_recovered(self):
        prefix = "Here is the result:\n"
        wrapped = prefix + '{"label": "ACCEPTED", "metadata": {"k": "v"}}'
        out = _parse_llm_json(wrapped)
        self.assertEqual(out["label"], "ACCEPTED")
        self.assertEqual(out["metadata"]["k"], "v")

    def test_first_object_returned_when_trailing_object_present(self):
        """Regression for the P2 finding from PR #19's chatgpt-codex
        review: a greedy ``\\{.*\\}`` pattern would span from the first
        ``{`` to the LAST ``}`` and json.loads would fail on the
        concatenated content. Now we use raw_decode which returns the
        first valid JSON value and ignores trailing content."""
        content = (
            '{"label": "DEFLECTED", "confidence": 0.8}\n\n'
            'Here is an example: {"label": "EXAMPLE", "confidence": 1.0}'
        )
        out = _parse_llm_json(content)
        self.assertEqual(out["label"], "DEFLECTED")
        self.assertAlmostEqual(out["confidence"], 0.8)

    def test_object_after_markdown_fence_with_trailing_prose(self):
        content = (
            '```json\n{"label": "ACCEPTED", "confidence": 0.9}\n```\n\n'
            'Note: this is an example response.'
        )
        out = _parse_llm_json(content)
        self.assertEqual(out["label"], "ACCEPTED")

    def test_object_with_nested_array_of_objects(self):
        content = (
            'The result is: '
            '{"label": "DEFLECTED", "evidence": [{"phrase": "in due course"}, '
            '{"phrase": "under consideration"}]}'
        )
        out = _parse_llm_json(content)
        self.assertEqual(out["label"], "DEFLECTED")
        self.assertEqual(len(out["evidence"]), 2)

    def test_garbage_prefix_skipped_to_first_valid_object(self):
        content = '{ this is not valid json }\nbut later: {"label": "ABSORBED"}'
        out = _parse_llm_json(content)
        self.assertEqual(out["label"], "ABSORBED")

    def test_no_json_at_all_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            _parse_llm_json("totally non-json prose with no braces at all")


# --------------------------------------------------------------------------- #
# M4 — exception text never leaks into audit_description                      #
# --------------------------------------------------------------------------- #


class ExceptionTextDoesNotLeakTests(unittest.TestCase):

    def test_network_error_returns_categorical_message(self):
        def _exploding(endpoint, payload, *, timeout_s, api_key=None, allow_private=True):
            # An exception with potentially-sensitive content.
            raise RuntimeError(
                "GET https://internal.corp/secrets/deploy-key HTTP/1.1 401"
            )

        c = classify_response_llm("text", CHANNEL_QA, _http_post=_exploding)
        self.assertEqual(c.label, "UNCLASSIFIED")
        # The URL/secret/error must NOT leak.
        self.assertNotIn("internal.corp", c.audit_description)
        self.assertNotIn("deploy-key", c.audit_description)
        self.assertNotIn("https://", c.audit_description)
        # Categorical message is fine.
        self.assertIn("LLM tier", c.audit_description)

    def test_unrecognised_label_does_not_leak_label_text(self):
        def _bad_label(endpoint, payload, *, timeout_s, api_key=None, allow_private=True):
            return json.dumps({
                "label": "<script>alert('xss-from-llm')</script>",
                "confidence": 0.9,
            })

        c = classify_response_llm("text", CHANNEL_QA, _http_post=_bad_label)
        self.assertEqual(c.label, "UNCLASSIFIED")
        # The attacker-controllable label string must not be reflected.
        self.assertNotIn("<script>", c.audit_description)
        self.assertNotIn("xss", c.audit_description.lower())


# --------------------------------------------------------------------------- #
# Sanity: documented label set is exactly 9                                    #
# --------------------------------------------------------------------------- #


class DiscourseLabelTaxonomySanityTests(unittest.TestCase):

    def test_classifier_version_pinned(self):
        self.assertEqual(LLM_CLASSIFIER_VERSION, "llm_discourse_v2")

    def test_nine_labels_in_taxonomy(self):
        self.assertEqual(len(DISCOURSE_LABEL_DESCRIPTIONS), 13)


if __name__ == "__main__":
    unittest.main()
