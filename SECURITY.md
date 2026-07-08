# Security Policy

## Supported Versions

Only the latest release on `main` receives security fixes.

| Version | Supported |
|---------|-----------|
| 0.x (latest, `commoner-analyse`) | ✅ |
| any `sansad-semantic-crawler` release | ❌ |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report privately via GitHub's [Security Advisories](https://github.com/CommonerLLP/commoner-analyse/security/advisories/new) feature.

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix if known

You will receive a response within 7 days. If the vulnerability is confirmed, a patch will be released as soon as possible with a coordinated disclosure.

## Scope

This package is a read-only analysis library over records acquired by `commoner-probe`. It optionally makes outbound HTTP requests to a local Ollama endpoint for the LLM discourse tier. It writes JSONL and SQLite files locally.

Known constraints:
- The discourse-tier LLM classifier (`analyse-discourse --llm-tier`) and the
  ministry-query refinement path validate the endpoint scheme (HTTP/HTTPS
  only) via `llm_client.py`, and can optionally reject loopback/private/
  link-local hosts (`allow_private=False`) to defeat SSRF against internal
  services.
- **Known gap:** the topic classifier's `llm` mode
  (`commoner_analyse/classifiers/llm.py`) does *not* go through
  `llm_client.py` and has no equivalent scheme or private-host validation —
  its `--classifier llm --endpoint <url>` accepts any URL unchecked. Treat
  this mode's endpoint the same as any other untrusted-input surface until
  it is consolidated onto the shared guard.
- No authentication credentials are stored or transmitted beyond what the caller supplies
- `data/`, `notes/`, and `memory/` directories are gitignored and must never be committed
