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
- The LLM tier (`--llm-endpoint`) accepts arbitrary URLs — callers are responsible for pointing it at trusted endpoints only
- No authentication credentials are stored or transmitted beyond what the caller supplies
- `data/`, `notes/`, and `memory/` directories are gitignored and must never be committed
