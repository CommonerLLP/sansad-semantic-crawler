"""Per-MP topic dossier.

For a single MP, produce a Markdown briefing of every question they have
asked in a corpus, grouped by topic, with the ministerial response label
distribution and excerpts of evasion text.

Topic clustering uses keyword overlap on the v0.6.5 ``question_subject``
field, normalised by stop-word removal + sorted-token-set keying. No
embeddings (those arrive in v0.7.0 only if keyword overlap is
demonstrably insufficient).

Records without a parsed ``question_subject`` fall into a single
``"Uncategorised"`` bucket rather than being silently dropped — coverage
is honest, not hidden.
"""

from __future__ import annotations

import hashlib
import calendar
import ipaddress
import json
import os
import re
import socket
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import request as _url_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

DOSSIER_VERSION = "mp_dossier_v1"
QUESTION_REFINE_VERSION = "question_refine_v1"

# Parliamentary boilerplate that should not contribute to topic identity.
# Keep this list narrow; we want the topic key to be the substantive
# nouns (LIBRARIES, VACANCIES, SHGS) not the framing verbs.
_TOPIC_STOPWORDS: frozenset[str] = frozenset({
    # Generic English stopwords — kept short, not exhaustive.
    "a", "an", "the", "of", "in", "on", "at", "by", "for", "to", "from",
    "and", "or", "but", "is", "are", "was", "were", "be", "been", "being",
    "with", "about", "into", "under", "over", "after", "before",
    "this", "that", "these", "those", "any", "all", "some", "no", "not",
    "as", "if", "then", "than", "so", "such",
    # Parliamentary boilerplate.
    "report", "details", "status", "scheme", "schemes", "programme",
    "programmes", "plan", "plans", "policy", "policies", "measure",
    "measures", "step", "steps", "action", "actions", "matter", "issue",
    "regard", "regarding", "thereto", "therein", "thereof", "thereof",
    "central", "centre", "centrally", "government", "ministry",
    "department", "country", "india", "national", "state", "states",
})

# Tokens contained on long ALL-CAPS subject lines that are noise rather
# than topic. e.g. some Lok Sabha PDFs prepend "URGENT" or "PRIORITY".
_TOPIC_NOISE_TOKENS: frozenset[str] = frozenset({
    "urgent", "priority", "starred", "unstarred", "supplementary",
})

_QUERY_HONORIFIC_RE = re.compile(
    r"\b(?:Shri|Smt|Dr|Prof|Mr|Mrs|Ms)\.?\s+",
    re.IGNORECASE,
)

_QUERY_GENERIC_WORDS: frozenset[str] = frozenset({
    "how", "many", "what", "which", "when", "where", "why", "who",
    "whom", "whose", "count", "counts", "number", "numbers", "posed",
    "asked", "answer", "answered", "answers", "offer", "offered",
    "questions", "question", "minister", "ministers", "ministry",
    "ministries", "house", "houses", "parliament", "floor", "since",
    "from", "after", "before", "between", "to", "in", "on", "of",
    "the", "and", "or", "both", "either",
})

_QUESTION_TYPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("unstarred", (
        r"\bunstarred\b",
        r"\bunstarred\s+questions?\b",
        r"\btype\s*:\s*unstarred\b",
        r"\bquestion\s*type\s*:\s*unstarred\b",
    )),
    ("starred", (
        r"\bstarred\b",
        r"\bstarred\s+questions?\b",
        r"\btype\s*:\s*starred\b",
        r"\bquestion\s*type\s*:\s*starred\b",
    )),
)

_RESPONDENT_ROLE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cabinet", (
        r"\bcabinet\s*(?:minister)?\b",
        r"\bunion\s+minister\b",
        r"\bhome\s+minister\b",
        r"\bminister\s+of\s+home\s+affairs\b",
        r"\bminister\s+of\s+cooperation\b",
        r"\bminister\s+of\s+state\s+for\s+home(?:\s+affairs)?\b",
        r"\bminister\s+of\s+state\s+for\s+cooperation\b",
        r"\bminister\s*:\s*cabinet\b",
        r"\bcabinet[-\s]*only\b",
    )),
    ("mos", (
        r"\bminister\s+of\s+state\b",
        r"\bmos\b",
        r"\bm\.o\.s\.\b",
        r"\bminister\s+of\s+state\s+for\s+home(?:\s+affairs)?\b",
        r"\bminister\s+of\s+state\s+for\s+cooperation\b",
        r"\bminister\s*:\s*mos\b",
        r"\bmos[-\s]*only\b",
    )),
)

_HOUSE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lok sabha", (
        r"\blok\s+sabha\b",
        r"\bls\b",
        r"\blower\s+house\b",
    )),
    ("rajya sabha", (
        r"\brajya\s+sabha\b",
        r"\brs\b",
        r"\bupper\s+house\b",
    )),
)

_MINISTRY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("HOME AFFAIRS", (
        r"\bministry\s+of\s+home\s+affairs\b",
        r"\bhome\s+affairs\b",
        r"\bhome\s+ministry\b",
        r"\bminister\s+of\s+state\s+for\s+home(?:\s+affairs)?\b",
        r"\bmos\s+home\b",
        r"\bmha\b",
    )),
    ("COOPERATION", (
        r"\bministry\s+of\s+cooperation\b",
        r"\bcooperation\b",
        r"\bminister\s+of\s+state\s+for\s+cooperation\b",
        r"\bmos\s+cooperation\b",
    )),
    ("SOCIAL JUSTICE AND EMPOWERMENT", (
        r"\bministry\s+of\s+social\s+justice\s+and\s+empowerment\b",
        r"\bsocial\s+justice\s+and\s+empowerment\b",
    )),
    ("TRIBAL AFFAIRS", (
        r"\bministry\s+of\s+tribal\s+affairs\b",
        r"\btribal\s+affairs\b",
    )),
    ("PERSONNEL, PUBLIC GRIEVANCES AND PENSIONS", (
        r"\bministry\s+of\s+personnel\b",
        r"\bpersonnel,\s*public\s+grievances\s+and\s+pensions\b",
        r"\bpersonnel\s+public\s+grievances\s+and\s+pensions\b",
        r"\bdopt\b",
    )),
    ("EDUCATION", (
        r"\bministry\s+of\s+education\b",
        r"\beducation\b",
        r"\bhigher\s+education\b",
    )),
    ("LABOUR AND EMPLOYMENT", (
        r"\bministry\s+of\s+labour\s+and\s+employment\b",
        r"\blabour\s+and\s+employment\b",
        r"\blabor\s+and\s+employment\b",
    )),
    ("MINORITY AFFAIRS", (
        r"\bministry\s+of\s+minority\s+affairs\b",
        r"\bminority\s+affairs\b",
    )),
    ("WOMEN AND CHILD DEVELOPMENT", (
        r"\bministry\s+of\s+women\s+and\s+child\s+development\b",
        r"\bwomen\s+and\s+child\s+development\b",
    )),
    ("FINANCE", (
        r"\bministry\s+of\s+finance\b",
        r"\bfinance\b",
    )),
    ("DEFENCE", (
        r"\bministry\s+of\s+defence\b",
        r"\bministry\s+of\s+defense\b",
        r"\bdefence\b",
        r"\bdefense\b",
    )),
    ("EXTERNAL AFFAIRS", (
        r"\bministry\s+of\s+external\s+affairs\b",
        r"\bexternal\s+affairs\b",
        r"\bmea\b",
    )),
    ("PORTS, SHIPPING AND WATERWAYS", (
        r"\bministry\s+of\s+ports[, ]\s*shipping\s+and\s+waterways\b",
        r"\bports[, ]\s*shipping\s+and\s+waterways\b",
    )),
)

_DATE_YEAR_RE = re.compile(r"\b(?P<year>(?:19|20)\d{2})\b")
_DATE_ISO_RE = re.compile(r"\b(?P<iso>(?:19|20)\d{2}-(?:0?[1-9]|1[0-2])(?:-(?:0?[1-9]|[12]\d|3[01]))?)\b")
_DATE_MONTH_NAME_RE = re.compile(
    r"\b(?P<month>(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|"
    r"may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|sept|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?))\s+(?P<year>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_DATE_RANGE_RE = re.compile(
    r"\b(?:between|from)\s+(?P<start>.+?)\s+(?:and|to)\s+(?P<end>.+?)(?=$|[,.;)])",
    re.IGNORECASE,
)
_DATE_SINCE_RE = re.compile(
    r"\b(?:since|after|from)\s+(?P<start>.+?)(?=$|[,.;)])",
    re.IGNORECASE,
)
_DATE_BEFORE_RE = re.compile(
    r"\b(?:before|until|to|upto|up\s+to)\s+(?P<end>.+?)(?=$|[,.;)])",
    re.IGNORECASE,
)

_MINISTRY_QUERY_ALLOWED_SCHEMES = frozenset({"http", "https"})
_MINISTRY_QUERY_LLM_SYSTEM_PROMPT = (
    "You extract structured facets from a parliamentary query.\n"
    "Return JSON only with these keys:\n"
    "{"
    "\"question_types\": [\"starred\"|\"unstarred\"], "
    "\"respondent_roles\": [\"cabinet\"|\"mos\"], "
    "\"ministries\": [canonical ministry names], "
    "\"houses\": [\"lok sabha\"|\"rajya sabha\"], "
    "\"people\": [person names], "
    "\"date_from\": \"YYYY-MM-DD\" or null, "
    "\"date_to\": \"YYYY-MM-DD\" or null, "
    "\"notes\": [short strings]"
    "}\n"
    "Use empty arrays for facets not present. Do not invent facts. "
    "If a facet is unclear, leave it empty."
)
_MINISTRY_QUERY_LLM_TEXT_LIMIT = 1600

_ANSWER_ROLE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("mos", (
        r"\bminister\s+of\s+state\b",
        r"\bm\.o\.s\.\b",
        r"\bmos\b",
    )),
    ("cabinet", (
        r"\bcabinet\s+minister\b",
        r"\bunion\s+minister\b",
        r"\bminister\s+of\s+(?!state\b)[a-z][a-z\s,()-]{3,120}\b",
    )),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _slugify(value: str) -> str:
    """Filesystem-safe slug for output filenames."""
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    s = s.strip("_")
    return s or "unknown"


def _parse_date_fragment(fragment: str, *, start: bool) -> str | None:
    """Parse a date fragment into ISO date.

    Supports YYYY, YYYY-MM, YYYY-MM-DD, and month-year forms like
    "March 2024". For partial dates, choose the first or last plausible
    day depending on whether the fragment is a range start or end.
    """
    text = (fragment or "").strip().strip(".,;)")
    if not text:
        return None
    text = re.sub(r"\b(?:the\s+year\s+of\s+|year\s+of\s+)?", "", text, flags=re.IGNORECASE)
    text = text.strip()
    text = text.rstrip(".,;:!?")

    prefix_match = re.match(
        r"^(?P<date>(?:19|20)\d{2}(?:-\d{1,2}(?:-\d{1,2})?)?|"
        r"(?:\d{1,2}\s+[A-Za-z]+\s+(?:19|20)\d{2})|"
        r"(?:[A-Za-z]+\s+(?:19|20)\d{2}))\b",
        text,
    )
    if prefix_match:
        text = prefix_match.group("date")

    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt == "%Y":
                return f"{dt.year}-01-01" if start else f"{dt.year}-12-31"
            if fmt == "%Y-%m":
                if start:
                    return f"{dt.year}-{dt.month:02d}-01"
                last = calendar.monthrange(dt.year, dt.month)[1]
                return f"{dt.year}-{dt.month:02d}-{last:02d}"
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    for fmt in ("%d %B %Y", "%d %b %Y", "%B %Y", "%b %Y"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in ("%B %Y", "%b %Y"):
                if start:
                    return f"{dt.year}-{dt.month:02d}-01"
                last = calendar.monthrange(dt.year, dt.month)[1]
                return f"{dt.year}-{dt.month:02d}-{last:02d}"
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


def _strip_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    out: list[str] = []
    last = 0
    for start, end in sorted(spans):
        if start < last:
            continue
        out.append(text[last:start])
        last = end
    out.append(text[last:])
    return re.sub(r"\s{2,}", " ", "".join(out)).strip(" ,;:-")


def _validate_ministry_query_endpoint(endpoint: str, *, allow_private: bool = True) -> None:
    parts = urlsplit(endpoint)
    if parts.scheme not in _MINISTRY_QUERY_ALLOWED_SCHEMES:
        raise ValueError(
            f"LLM endpoint scheme must be one of {sorted(_MINISTRY_QUERY_ALLOWED_SCHEMES)}; "
            f"got {parts.scheme!r}"
        )
    if not parts.hostname:
        raise ValueError("LLM endpoint URL has no hostname")
    if allow_private:
        return
    host = parts.hostname
    try:
        ip_literal = ipaddress.ip_address(host)
    except ValueError:
        ip_literal = None
    if ip_literal is not None:
        if (
            ip_literal.is_private
            or ip_literal.is_loopback
            or ip_literal.is_link_local
            or ip_literal.is_multicast
            or ip_literal.is_reserved
            or ip_literal.is_unspecified
        ):
            raise ValueError(
                "LLM endpoint host is private/loopback; pass allow_private=True if intentional."
            )
        return
    if host in {"localhost", "ip6-localhost", "ip6-loopback"}:
        raise ValueError(
            "LLM endpoint host is loopback; pass allow_private=True if intentional."
        )
    try:
        resolved = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(
            f"LLM endpoint host could not be resolved: {type(exc).__name__}"
        ) from exc
    for _family, _kind, _proto, _name, sockaddr in resolved:
        addr_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError as exc:
            raise ValueError(
                "LLM endpoint host resolved to an unrecognised address; refusing to dispatch."
            ) from exc
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        ):
            raise ValueError(
                "LLM endpoint host is private/loopback; pass allow_private=True if intentional."
            )


def _resolve_ministry_query_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if api_key.startswith("env:"):
        return os.environ.get(api_key[4:])
    return api_key


def _ministry_query_http_post(
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout_s: float,
    api_key: str | None = None,
    allow_private: bool = True,
) -> str:
    _validate_ministry_query_endpoint(endpoint, allow_private=allow_private)
    base = endpoint.rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resolved_key = _resolve_ministry_query_api_key(api_key)
    if resolved_key:
        headers["Authorization"] = f"Bearer {resolved_key}"
    req = _url_request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with _url_request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"].get("content") or "{}"
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"LLM endpoint unreachable: {type(exc).__name__}") from exc


def _parse_llm_json(content: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        for start in range(len(content)):
            if content[start] != "{":
                continue
            try:
                obj, _end = decoder.raw_decode(content[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
        raise


def _canonicalize_ministry_name(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for canonical, patterns in _MINISTRY_PATTERNS:
        if _ministry_matches(text, canonical):
            return canonical
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return canonical
    return text.upper()


def _canonicalize_ministry_query_list(
    values: object,
    *,
    field: str,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        items = [values]
    elif isinstance(values, Iterable):
        items = [str(v) for v in values if str(v).strip()]
    else:
        items = [str(values)]
    out: list[str] = []
    for item in items:
        text = item.strip()
        if not text:
            continue
        if field == "question_types":
            lowered = text.lower()
            if "unstar" in lowered:
                canon = "unstarred"
            elif "star" in lowered:
                canon = "starred"
            else:
                canon = lowered
        elif field == "respondent_roles":
            lowered = text.lower()
            if "cabinet" in lowered or "union" in lowered:
                canon = "cabinet"
            elif "mos" in lowered or "minister of state" in lowered:
                canon = "mos"
            else:
                canon = lowered
        elif field == "houses":
            lowered = text.lower()
            if "rajya" in lowered or lowered == "rs":
                canon = "rajya sabha"
            elif "lok" in lowered or lowered == "ls":
                canon = "lok sabha"
            else:
                canon = lowered
        elif field == "ministries":
            canon = _canonicalize_ministry_name(text) or text.upper()
        else:
            canon = text
        if canon and canon not in out:
            out.append(canon)
    return tuple(out)


def _coerce_llm_ministry_query(raw_query: str, payload: dict[str, Any]) -> ParsedMinistryQuery:
    return ParsedMinistryQuery(
        raw=raw_query,
        question_types=_canonicalize_ministry_query_list(payload.get("question_types"), field="question_types")
        or ("starred", "unstarred"),
        respondent_roles=_canonicalize_ministry_query_list(payload.get("respondent_roles"), field="respondent_roles")
        or ("cabinet", "mos"),
        ministries=_canonicalize_ministry_query_list(payload.get("ministries"), field="ministries"),
        houses=_canonicalize_ministry_query_list(payload.get("houses"), field="houses")
        or ("lok sabha", "rajya sabha"),
        people=_canonicalize_ministry_query_list(payload.get("people"), field="people"),
        date_from=str(payload.get("date_from") or "").strip() or None,
        date_to=str(payload.get("date_to") or "").strip() or None,
        notes=tuple(str(n).strip() for n in (payload.get("notes") or []) if str(n).strip()),
    )


def _merge_ministry_query(regex: ParsedMinistryQuery, llm: ParsedMinistryQuery) -> ParsedMinistryQuery:
    def _merge(default_value: tuple[str, ...], override_value: tuple[str, ...], *, flag: str) -> tuple[str, ...]:
        if f"{flag} not specified" in regex.notes and override_value:
            return override_value
        return default_value

    date_from = regex.date_from
    date_to = regex.date_to
    if not date_from and llm.date_from:
        date_from = llm.date_from
    if not date_to and llm.date_to:
        date_to = llm.date_to

    notes = list(dict.fromkeys((*regex.notes, *llm.notes, "llm fallback used")))
    return ParsedMinistryQuery(
        raw=regex.raw,
        question_types=_merge(regex.question_types, llm.question_types, flag="question type"),
        respondent_roles=_merge(regex.respondent_roles, llm.respondent_roles, flag="respondent role"),
        ministries=_merge(regex.ministries, llm.ministries, flag="ministry"),
        houses=_merge(regex.houses, llm.houses, flag="house"),
        people=_merge(regex.people, llm.people, flag="person"),
        date_from=date_from,
        date_to=date_to,
        notes=tuple(notes),
    )


@dataclass(frozen=True)
class ParsedMinistryQuery:
    """Structured query facets for responder-side dossier requests."""

    raw: str
    question_types: tuple[str, ...]
    respondent_roles: tuple[str, ...]
    ministries: tuple[str, ...]
    houses: tuple[str, ...]
    people: tuple[str, ...]
    date_from: str | None = None
    date_to: str | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "raw": self.raw,
            "question_types": list(self.question_types),
            "respondent_roles": list(self.respondent_roles),
            "ministries": list(self.ministries),
            "houses": list(self.houses),
            "people": list(self.people),
            "date_from": self.date_from,
            "date_to": self.date_to,
            "notes": list(self.notes),
        }


def _normalize_topic_key(subject: str | None) -> str:
    """Tokenise a question subject, drop stopwords + boilerplate, sort,
    join. Two subjects that share their substantive nouns will produce
    the same key; ordering and stopword variations don't fragment topics.

    Examples:
      "ANNUAL INCOME OF SHGS"      → "ANNUAL INCOME SHGS"
      "SHG ANNUAL INCOME"          → "ANNUAL INCOME SHGS"
      "IMPACT ON LIBRARY FUNDING"  → "FUNDING IMPACT LIBRARY"
      "LIBRARY FUNDING IMPACT"     → "FUNDING IMPACT LIBRARY"

    Returns "" when the subject is empty or all-stopwords.
    """
    if not subject:
        return ""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]*", subject.upper())
    cleaned = [
        t for t in tokens
        if t.lower() not in _TOPIC_STOPWORDS
        and t.lower() not in _TOPIC_NOISE_TOKENS
        and len(t) > 1
    ]
    if not cleaned:
        return ""
    return " ".join(sorted(cleaned))


def parse_ministry_query(
    query: str,
    *,
    llm_tier: bool = False,
    endpoint: str = "http://localhost:11434/v1",
    model: str = "qwen2.5:7b",
    timeout_s: float = 30.0,
    api_key: str | None = None,
    allow_private: bool = True,
    _http_post: Callable[..., str] | None = None,
) -> ParsedMinistryQuery:
    """Parse a natural-language responder-side query into structured facets.

    This is regex-first and conservative:
    - explicit mentions of starred/unstarred drive ``question_types``;
    - explicit cabinet / MoS language drives ``respondent_roles``;
    - ministry aliases are matched from a small stable vocabulary;
    - date fragments are normalised to ISO dates;
    - remaining capitalised name-like spans become ``people``.

    Unspecified facets default to both question types, both respondent
    roles, and both houses so downstream code can filter only when the
    user actually constrained a facet.

    When ``llm_tier=True``, any facet the regex pass left unspecified is
    offered to an LLM second pass for normalization. Regex always wins on
    explicit matches; the LLM only fills gaps.
    """
    text = (query or "").strip()
    if not text:
        return ParsedMinistryQuery(
            raw="",
            question_types=("starred", "unstarred"),
            respondent_roles=("cabinet", "mos"),
            ministries=(),
            houses=("lok sabha", "rajya sabha"),
            people=(),
            notes=("empty query",),
        )

    working = text
    notes: list[str] = []
    spans_to_strip: list[tuple[int, int]] = []

    def _collect_patterns(patterns: tuple[str, ...], canonical: str, found: list[str]) -> None:
        nonlocal working
        for pattern in patterns:
            for m in re.finditer(pattern, working, flags=re.IGNORECASE):
                found.append(canonical)
                spans_to_strip.append((m.start(), m.end()))

    question_types_found: list[str] = []
    for canonical, patterns in _QUESTION_TYPE_PATTERNS:
        _collect_patterns(patterns, canonical, question_types_found)
    if not question_types_found:
        question_types = ("starred", "unstarred")
        notes.append("question type not specified")
    else:
        question_types = tuple(dict.fromkeys(question_types_found))

    roles_found: list[str] = []
    for canonical, patterns in _RESPONDENT_ROLE_PATTERNS:
        _collect_patterns(patterns, canonical, roles_found)
    if not roles_found:
        respondent_roles = ("cabinet", "mos")
        notes.append("respondent role not specified")
    else:
        respondent_roles = tuple(dict.fromkeys(roles_found))

    houses_found: list[str] = []
    for canonical, patterns in _HOUSE_PATTERNS:
        _collect_patterns(patterns, canonical, houses_found)
    if not houses_found:
        houses = ("lok sabha", "rajya sabha")
        notes.append("house not specified")
    else:
        houses = tuple(dict.fromkeys(houses_found))

    ministries_found: list[str] = []
    for canonical, patterns in _MINISTRY_PATTERNS:
        for pattern in patterns:
            for m in re.finditer(pattern, working, flags=re.IGNORECASE):
                ministries_found.append(canonical)
                spans_to_strip.append((m.start(), m.end()))
    ministries = tuple(dict.fromkeys(ministries_found))
    if not ministries:
        notes.append("ministry not specified")

    date_from: str | None = None
    date_to: str | None = None

    range_match = _DATE_RANGE_RE.search(working)
    if range_match:
        date_from = _parse_date_fragment(range_match.group("start"), start=True)
        date_to = _parse_date_fragment(range_match.group("end"), start=False)
        spans_to_strip.append((range_match.start(), range_match.end()))
    else:
        since_match = _DATE_SINCE_RE.search(working)
        if since_match:
            date_from = _parse_date_fragment(since_match.group("start"), start=True)
            spans_to_strip.append((since_match.start(), since_match.end()))
        before_match = _DATE_BEFORE_RE.search(working)
        if before_match:
            date_to = _parse_date_fragment(before_match.group("end"), start=False)
            spans_to_strip.append((before_match.start(), before_match.end()))

    if not date_from and not date_to:
        iso_matches = list(_DATE_ISO_RE.finditer(working))
        if len(iso_matches) == 1:
            date_from = _parse_date_fragment(iso_matches[0].group("iso"), start=True)
            date_to = date_from
            spans_to_strip.append((iso_matches[0].start(), iso_matches[0].end()))

    working = _strip_spans(working, spans_to_strip)
    working = _QUERY_HONORIFIC_RE.sub("", working)
    working = re.sub(r"\b(?:cabinet|mos|m\.o\.s\.|home minister|minister of state)\b", " ", working, flags=re.IGNORECASE)
    working = re.sub(r"\s+", " ", working).strip(" ,;:-")

    people: list[str] = []
    if working:
        for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b", working):
            candidate = m.group(1).strip()
            words = candidate.split()
            if not words:
                continue
            lowered_words = [w.lower() for w in words]
            if any(w in _QUERY_GENERIC_WORDS for w in lowered_words):
                continue
            if any(w.upper() in {"HOME", "AFFAIRS", "COOPERATION", "EDUCATION", "FINANCE", "DEFENCE", "DEFENSE", "TRIBAL", "PERSONNEL", "MINORITY", "WOMEN", "CHILD", "LABOUR", "EMPLOYMENT"} for w in words):
                continue
            people.append(candidate)
    people = list(dict.fromkeys(people))
    if not people:
        notes.append("person not specified")

    parsed = ParsedMinistryQuery(
        raw=text,
        question_types=question_types,
        respondent_roles=respondent_roles,
        ministries=ministries,
        houses=houses,
        people=tuple(people),
        date_from=date_from,
        date_to=date_to,
        notes=tuple(notes),
    )
    if not llm_tier or not parsed.notes:
        return parsed

    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _MINISTRY_QUERY_LLM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": text[:_MINISTRY_QUERY_LLM_TEXT_LIMIT],
                },
            ],
            "stream": False,
            "temperature": 0,
        }
        if _http_post is None:
            raw_content = _ministry_query_http_post(
                endpoint,
                payload,
                timeout_s=timeout_s,
                api_key=api_key,
                allow_private=allow_private,
            )
        else:
            raw_content = _http_post(
                endpoint=endpoint,
                payload=payload,
                timeout_s=timeout_s,
                api_key=api_key,
                allow_private=allow_private,
            )
        llm_payload = _parse_llm_json(raw_content)
        llm_parsed = _coerce_llm_ministry_query(text, llm_payload)
    except Exception:
        return parsed
    return _merge_ministry_query(parsed, llm_parsed)


def _join_english(items: Iterable[str]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"


def _query_slug(query: str) -> str:
    base = _slugify(query)
    if len(base) > 48:
        base = base[:48].rstrip("_")
    digest = hashlib.sha1((query or "").encode("utf-8")).hexdigest()[:8]
    return f"{base}_{digest}" if base else digest


def _infer_answer_role(answer_text: str | None) -> str | None:
    text = (answer_text or "").strip()
    if not text:
        return None
    answer_section = text
    answer_marker = re.search(r"\bANSWER\b", text, re.IGNORECASE)
    if answer_marker:
        answer_section = text[answer_marker.end():]
    head = answer_section[:900]
    if re.search(r"\bminister\s+of\s+state\b|\bm\.o\.s\.\b|\bmos\b", head, re.IGNORECASE):
        return "mos"
    if re.search(r"\bcabinet\s+minister\b|\bunion\s+minister\b", head, re.IGNORECASE):
        return "cabinet"
    if re.search(
        r"\bminister\s+of\s+(?!state\b)(?:home\s+affairs|cooperation|finance|defence|defense|education|labour\s+and\s+employment|external\s+affairs|women\s+and\s+child\s+development|social\s+justice\s+and\s+empowerment|tribal\s+affairs|personnel(?:,\s*public\s+grievances\s+and\s+pensions)?)\b",
        head,
        re.IGNORECASE,
    ):
        return "cabinet"
    if re.search(r"\bminister\s+of\s+(?!state\b)", head, re.IGNORECASE):
        return "cabinet"
    return None


def _role_label(role: str | None) -> str:
    if not role:
        return "unknown"
    role = role.strip().lower()
    if role == "cabinet":
        return "Cabinet Minister"
    if role == "mos":
        return "Minister of State"
    return role


@dataclass(frozen=True)
class QuestionRefinementPrecedent:
    key: str
    date: str
    house: str
    ministry: str
    qtype: str
    title: str
    answer_minister_name: str
    respondent_role: str
    discourse_label: str
    score: float
    excerpt: str
    match_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "date": self.date,
            "house": self.house,
            "ministry": self.ministry,
            "qtype": self.qtype,
            "title": self.title,
            "answer_minister_name": self.answer_minister_name,
            "respondent_role": self.respondent_role,
            "discourse_label": self.discourse_label,
            "score": self.score,
            "excerpt": self.excerpt,
            "match_notes": list(self.match_notes),
        }


@dataclass(frozen=True)
class QuestionRefinement:
    raw_query: str
    parsed: ParsedMinistryQuery
    refined_summary: str
    refined_question: str
    risk_summary: str
    exact_match_count: int
    candidate_count: int
    precedents: tuple[QuestionRefinementPrecedent, ...]
    notes: tuple[str, ...] = ()
    version: str = QUESTION_REFINE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "parsed": self.parsed.to_dict(),
            "refined_summary": self.refined_summary,
            "refined_question": self.refined_question,
            "risk_summary": self.risk_summary,
            "exact_match_count": self.exact_match_count,
            "candidate_count": self.candidate_count,
            "precedents": [p.to_dict() for p in self.precedents],
            "notes": list(self.notes),
            "version": self.version,
        }


def _topic_display(key: str, sample_subjects: list[str]) -> str:
    """Pick a human-readable display label for a topic key.

    The key is a sorted-token form (e.g. "ANNUAL INCOME SHGS"); the
    display picks the most common original subject from the cluster
    so the briefing reads naturally, rather than showing the keyed form.
    """
    if not sample_subjects:
        return key.title() if key else "Uncategorised"
    most_common = Counter(s.strip().title() for s in sample_subjects).most_common(1)
    return most_common[0][0] if most_common else (key.title() if key else "Uncategorised")


# ---------------------------------------------------------------------------
# MP record selection
# ---------------------------------------------------------------------------


def _name_matches(query: str, name: str) -> bool:
    """Loose name match — last-name or substring, case-insensitive.

    The corpus has names with honorifics ("Shri", "Smt.", "Dr.") and
    sometimes initials. A loose substring match against the surname
    (last whitespace-separated token of the query) is the right
    behaviour for the analyst pasting a name in.
    """
    q = (query or "").strip().lower()
    n = (name or "").strip().lower()
    if not q or not n:
        return False
    if q in n:
        return True
    last = q.split()[-1] if q else ""
    return bool(last) and last in n


def _ministry_matches(query: str, ministry: str) -> bool:
    """Loose ministry match, case-insensitive and substring-aware.

    The crawler normalises ministry values inconsistently across houses and
    over time ("HOME AFFAIRS" vs "Ministry of Home Affairs"), so we accept
    either containment direction.
    """
    q = (query or "").strip().lower()
    m = (ministry or "").strip().lower()
    if not q or not m:
        return False
    return q in m or m in q


def find_mp_records(
    out_dir: Path,
    *,
    entity_id: str | None = None,
    name: str | None = None,
) -> list[tuple[dict, dict | None]]:
    """Return ``(manifest_record, discourse_record_or_None)`` tuples for
    every record where this MP is an asker. Discourse record is None
    when ``analyse-discourse`` hasn't been run for that key yet.

    Either ``entity_id`` or ``name`` must be provided. ``entity_id``
    is preferred (precise); ``name`` is loose-match fallback.
    """
    if not entity_id and not name:
        raise ValueError("either entity_id or name is required")
    manifest_rows = _read_jsonl(out_dir / "manifest.jsonl")
    discourse_rows = _read_jsonl(out_dir / "analysis_discourse.jsonl")
    discourse_by_key: dict[str, dict] = {}
    for r in discourse_rows:
        k = r.get("key")
        if k and k not in discourse_by_key:
            discourse_by_key[k] = r

    out: list[tuple[dict, dict | None]] = []
    for rec in manifest_rows:
        if rec.get("kind") != "qa":
            continue
        eids = rec.get("asker_entity_ids") or []
        details = rec.get("asker_details") or []
        plain_names = rec.get("askers") or []
        matched = False
        if entity_id:
            matched = entity_id in eids
        elif name:
            for d in details:
                n = d.get("name") if isinstance(d, dict) else None
                if n and _name_matches(name, n):
                    matched = True
                    break
            if not matched:
                for n in plain_names:
                    if _name_matches(name, str(n)):
                        matched = True
                        break
        if matched:
            out.append((rec, discourse_by_key.get(rec.get("key", ""))))
    return out


def find_ministry_records(
    out_dir: Path,
    *,
    ministry: str,
) -> list[tuple[dict, dict | None, dict | None]]:
    """Return ``(manifest_record, discourse_record_or_None, answer_record_or_None)``
    tuples for every QA record whose ministry matches ``ministry``.

    The ministry match is loose and case-insensitive. This lets callers use
    either shorthand ("Home Affairs") or the crawler's canonical uppercase
    form ("HOME AFFAIRS").
    """
    if not ministry:
        raise ValueError("ministry is required")
    manifest_rows = _read_jsonl(out_dir / "manifest.jsonl")
    discourse_rows = _read_jsonl(out_dir / "analysis_discourse.jsonl")
    answer_rows = _read_jsonl(out_dir / "answers.jsonl")
    discourse_by_key: dict[str, dict] = {}
    for r in discourse_rows:
        k = r.get("key")
        if k and k not in discourse_by_key:
            discourse_by_key[k] = r
    answers_by_key: dict[str, dict] = {}
    for r in answer_rows:
        k = r.get("key")
        if k and k not in answers_by_key:
            answers_by_key[k] = r

    out: list[tuple[dict, dict | None, dict | None]] = []
    for rec in manifest_rows:
        if rec.get("kind") != "qa":
            continue
        ministry_name = str(rec.get("ministry") or "")
        if not _ministry_matches(ministry, ministry_name):
            continue
        out.append((
            rec,
            discourse_by_key.get(rec.get("key", "")),
            answers_by_key.get(rec.get("key", "")),
        ))
    return out


def _load_qa_records(out_dir: Path) -> list[tuple[dict, dict | None, dict | None]]:
    manifest_rows = _read_jsonl(out_dir / "manifest.jsonl")
    discourse_rows = _read_jsonl(out_dir / "analysis_discourse.jsonl")
    answer_rows = _read_jsonl(out_dir / "answers.jsonl")
    discourse_by_key: dict[str, dict] = {}
    for r in discourse_rows:
        k = r.get("key")
        if k and k not in discourse_by_key:
            discourse_by_key[k] = r
    answers_by_key: dict[str, dict] = {}
    for r in answer_rows:
        k = r.get("key")
        if k and k not in answers_by_key:
            answers_by_key[k] = r
    out: list[tuple[dict, dict | None, dict | None]] = []
    for rec in manifest_rows:
        if rec.get("kind") != "qa":
            continue
        out.append((
            rec,
            discourse_by_key.get(rec.get("key", "")),
            answers_by_key.get(rec.get("key", "")),
        ))
    return out


def _tokenise_query(text: str) -> set[str]:
    tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]*", text or "")
    }
    return {
        token for token in tokens
        if token not in _QUERY_GENERIC_WORDS
        and token not in _TOPIC_STOPWORDS
        and token not in _TOPIC_NOISE_TOKENS
        and len(token) > 1
    }


def _build_refined_question_text(
    raw_query: str,
    parsed: ParsedMinistryQuery,
    *,
    exact_match_count: int,
    nearest_titles: list[str],
) -> tuple[str, str]:
    ministries = _join_english(parsed.ministries) or "the relevant ministry"
    question_types = _join_english(parsed.question_types) or "parliamentary"
    roles = _join_english(_role_label(role) for role in parsed.respondent_roles)
    people = _join_english(parsed.people)
    house = _join_english(parsed.houses)
    if parsed.date_from and parsed.date_to:
        date_clause = f"between {parsed.date_from} and {parsed.date_to}"
    elif parsed.date_from:
        date_clause = f"since {parsed.date_from}"
    elif parsed.date_to:
        date_clause = f"before {parsed.date_to}"
    else:
        date_clause = ""

    intro_target = ministries
    if parsed.people and parsed.ministries:
        intro_target = f"{people} and the {ministries}"
    elif parsed.people and not parsed.ministries:
        intro_target = people

    parts: list[str] = []
    if parsed.people:
        parts.append(
            f"How many {question_types} questions addressed to {intro_target}"
            + (f" {date_clause}" if date_clause else "")
            + (
                f" were answered by {roles}"
                if roles
                else " were answered"
            )
            + (
                f" in {house}"
                if house and parsed.houses != ("lok sabha", "rajya sabha")
                else ""
            )
            + ";"
        )
        parts.append("on which dates were those replies furnished;")
        parts.append(
            "and what broad form did the replies take"
            ", including direct factual disclosure, statement laid on the Table, data withholding, or substitution?"
        )
    else:
        parts.append(
            f"Will the Minister of {ministries} be pleased to state:"
        )
        parts.append(
            f"(a) how many {question_types} questions were addressed to {ministries}"
            + (f" {date_clause}" if date_clause else "")
            + (" in " + house if house and parsed.houses != ("lok sabha", "rajya sabha") else "")
            + ";"
        )
        parts.append(
            f"(b) whether the replies were given by {roles if roles else 'the Cabinet Minister and Ministers of State'};"
        )
        parts.append(
            "(c) the dates on which such replies were furnished; and"
        )
        parts.append(
            "(d) the broad form each reply took, including direct factual disclosure, statement laid on the Table, data withholding, or substitution?"
        )

    refined_question = " ".join(parts).replace("  ", " ").strip()
    if exact_match_count == 0 and nearest_titles:
        summary = (
            f"No exact corpus match for the full facet set; nearest precedents are "
            f"topical matches such as {nearest_titles[0]}."
        )
    elif exact_match_count == 0:
        summary = "No exact corpus match for the full facet set."
    else:
        summary = (
            f"Found {exact_match_count} exact corpus match{'es' if exact_match_count != 1 else ''}; "
            f"the draft is tightened around those precedents."
        )
    if exact_match_count == 0 and raw_query:
        refined_question = (
            f"{refined_question} The source corpus did not surface an exact full-facet precedent, so keep the ask narrow and explicit."
        )
    return summary, refined_question


def _build_risk_summary(label_counts: Counter, exact_match_count: int) -> str:
    if not label_counts:
        return "No matched precedents were available to estimate answer style."
    total = sum(label_counts.values()) or 1
    parts = []
    for label, count in label_counts.most_common():
        pct = round((count / total) * 100)
        parts.append(f"{label} {pct}%")
    prefix = "Exact matches show" if exact_match_count else "Nearest precedents show"
    return f"{prefix} answer-style mix: " + ", ".join(parts) + "."


def _select_question_refinement_precedents(
    out_dir: Path,
    parsed: ParsedMinistryQuery,
    *,
    limit: int = 5,
) -> tuple[list[QuestionRefinementPrecedent], int, int, Counter]:
    records = _load_qa_records(out_dir)
    query_tokens = _tokenise_query(parsed.raw)
    exact: list[tuple[float, QuestionRefinementPrecedent]] = []
    near: list[tuple[float, QuestionRefinementPrecedent]] = []
    exact_match_count = 0
    label_counts: Counter = Counter()

    for manifest, discourse, answer in records:
        qtype = str(manifest.get("qtype") or "").strip().lower()
        house = str(manifest.get("house") or "").strip().lower()
        ministry = str(manifest.get("ministry") or "").strip()
        date = str(manifest.get("date") or "").strip()
        title = (
            (answer or {}).get("question_subject")
            or manifest.get("title")
            or ""
        ).strip()
        answer_text = (answer or {}).get("answer_text") or ""
        answer_minister_name = str((answer or {}).get("answer_minister_name") or "").strip()
        respondent_role = _infer_answer_role(answer_text) or "unknown"
        label = str((discourse or {}).get("label") or "UNCLASSIFIED").strip() or "UNCLASSIFIED"
        excerpt = (
            (answer or {}).get("answer_body")
            or (discourse or {}).get("text_excerpt")
            or answer_text
            or ""
        )
        match_notes: list[str] = []
        score = 0.0

        if parsed.question_types and qtype in parsed.question_types:
            score += 2.0
        elif parsed.question_types != ("starred", "unstarred"):
            match_notes.append("question type mismatch")

        if parsed.houses and house in parsed.houses:
            score += 1.0
        elif parsed.houses != ("lok sabha", "rajya sabha"):
            match_notes.append("house mismatch")

        if parsed.ministries and any(_ministry_matches(m, ministry) for m in parsed.ministries):
            score += 2.5
        elif parsed.ministries:
            match_notes.append("ministry mismatch")

        if parsed.date_from and date and date >= parsed.date_from:
            score += 0.75
        elif parsed.date_from:
            match_notes.append("before start date")
        if parsed.date_to and date and date <= parsed.date_to:
            score += 0.75
        elif parsed.date_to:
            match_notes.append("after end date")

        if parsed.respondent_roles:
            if respondent_role in parsed.respondent_roles:
                score += 2.5
            elif respondent_role == "unknown":
                match_notes.append("respondent role unresolved")
            else:
                match_notes.append("respondent role mismatch")

        if parsed.people:
            if any(_name_matches(person, answer_minister_name) for person in parsed.people if answer_minister_name):
                score += 2.0
            elif answer_minister_name:
                match_notes.append("answering minister mismatch")
            else:
                match_notes.append("answering minister missing")

        title_tokens = _tokenise_query(title)
        if query_tokens and title_tokens:
            overlap = len(query_tokens & title_tokens)
            if overlap:
                score += min(2.0, overlap / max(len(query_tokens), len(title_tokens)) * 4.0)

        if not match_notes:
            exact_match_count += 1

        label_counts[label] += 1
        prec = QuestionRefinementPrecedent(
            key=str(manifest.get("key") or ""),
            date=date,
            house=str(manifest.get("house") or ""),
            ministry=ministry,
            qtype=str(manifest.get("qtype") or ""),
            title=title,
            answer_minister_name=answer_minister_name,
            respondent_role=respondent_role,
            discourse_label=label,
            score=round(score, 3),
            excerpt=str(excerpt).replace("\n", " ").strip()[:260],
            match_notes=tuple(match_notes),
        )
        if not match_notes:
            exact.append((score, prec))
        else:
            near.append((score, prec))

    exact.sort(key=lambda item: (-item[0], item[1].date, item[1].key))
    near.sort(key=lambda item: (-item[0], item[1].date, item[1].key))
    selected: list[QuestionRefinementPrecedent] = [prec for _score, prec in exact[:limit]]
    if len(selected) < limit:
        for _score, prec in near:
            if len(selected) >= limit:
                break
            selected.append(prec)
    candidate_count = len(exact) + len(near)
    return selected, exact_match_count, candidate_count, label_counts


def build_question_refinement(
    out_dir: Path,
    *,
    query: str,
    llm_tier: bool = False,
    endpoint: str = "http://localhost:11434/v1",
    model: str = "qwen2.5:7b",
    timeout_s: float = 30.0,
    api_key: str | None = None,
    allow_private: bool = True,
    max_precedents: int = 5,
    log_fn: Callable[..., None] = print,
) -> Path | None:
    parsed = parse_ministry_query(
        query,
        llm_tier=llm_tier,
        endpoint=endpoint,
        model=model,
        timeout_s=timeout_s,
        api_key=api_key,
        allow_private=allow_private,
    )
    precedents, exact_match_count, candidate_count, label_counts = _select_question_refinement_precedents(
        out_dir,
        parsed,
        limit=max_precedents,
    )
    nearest_titles = [p.title for p in precedents[:3] if p.title]
    refined_summary, refined_question = _build_refined_question_text(
        query,
        parsed,
        exact_match_count=exact_match_count,
        nearest_titles=nearest_titles,
    )
    risk_summary = _build_risk_summary(label_counts, exact_match_count)
    notes = list(parsed.notes)
    if exact_match_count == 0:
        notes.append("no exact corpus match for the full facet set")
    if llm_tier:
        notes.append("llm fallback enabled for query parsing")
    result = QuestionRefinement(
        raw_query=query,
        parsed=parsed,
        refined_summary=refined_summary,
        refined_question=refined_question,
        risk_summary=risk_summary,
        exact_match_count=exact_match_count,
        candidate_count=candidate_count,
        precedents=tuple(precedents),
        notes=tuple(dict.fromkeys(notes)),
    )
    slug = _query_slug(query)
    ref_dir = out_dir / "question_refinements"
    ref_dir.mkdir(parents=True, exist_ok=True)
    md_path = ref_dir / f"{slug}.md"
    json_path = ref_dir / f"{slug}.json"

    md_lines: list[str] = []
    md_lines.append("# Question Refinement")
    md_lines.append("")
    md_lines.append(f"*Generated:* {_now()}")
    md_lines.append(f"*Corpus:* `{out_dir}`")
    md_lines.append(f"*Query:* `{query}`")
    md_lines.append("")
    md_lines.append("## Parsed Facets")
    md_lines.append("")
    md_lines.append(f"- **Question types:** {_join_english(parsed.question_types) or '—'}")
    md_lines.append(f"- **Respondent roles:** {_join_english(parsed.respondent_roles) or '—'}")
    md_lines.append(f"- **Ministries:** {_join_english(parsed.ministries) or '—'}")
    md_lines.append(f"- **Houses:** {_join_english(parsed.houses) or '—'}")
    md_lines.append(f"- **People:** {_join_english(parsed.people) or '—'}")
    if parsed.date_from or parsed.date_to:
        md_lines.append(
            f"- **Date range:** {parsed.date_from or '—'} – {parsed.date_to or '—'}"
        )
    if parsed.notes:
        md_lines.append(f"- **Parse notes:** {', '.join(parsed.notes)}")
    md_lines.append("")
    md_lines.append("## Refined Draft")
    md_lines.append("")
    md_lines.append(refined_question)
    md_lines.append("")
    md_lines.append("## Why This Is Sharper")
    md_lines.append("")
    md_lines.append(refined_summary)
    md_lines.append("")
    md_lines.append("## Answer-Style Risk")
    md_lines.append("")
    md_lines.append(risk_summary)
    md_lines.append("")
    md_lines.append("## Precedents")
    md_lines.append("")
    if precedents:
        for prec in precedents:
            md_lines.append(
                f"- `{prec.key}` — {prec.date or '?'}; {prec.title or '(untitled)'}; "
                f"{prec.discourse_label}; {prec.answer_minister_name or prec.respondent_role or '?'}"
            )
            if prec.excerpt:
                md_lines.append(f"  > {prec.excerpt}")
            if prec.match_notes:
                md_lines.append(f"  - Notes: {', '.join(prec.match_notes)}")
    else:
        md_lines.append("- No corpus precedents found.")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    md_lines.append(f"*Generated by `{QUESTION_REFINE_VERSION}`.*")
    md_lines.append("")

    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    json_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log_fn(
        f"question-refine: wrote {md_path} and {json_path} "
        f"({candidate_count} candidates; exact={exact_match_count}; precedents={len(precedents)})"
    )
    return md_path


def _resolve_display_identity(
    pairs: list[tuple[dict, dict | None]],
) -> tuple[str, str | None]:
    """Pick a canonical display name + entity_id from the matched records.

    Different records may carry different forms of the name ("Shri X",
    "Smt. X", bare "X"). Pick the most common form. Returns
    (display_name, entity_id_or_None).
    """
    name_counter: Counter = Counter()
    eid_counter: Counter = Counter()
    for manifest, _ in pairs:
        for d in manifest.get("asker_details") or []:
            if isinstance(d, dict) and d.get("name"):
                name_counter[d["name"]] += 1
        for eid in manifest.get("asker_entity_ids") or []:
            if eid:
                eid_counter[eid] += 1
    name = name_counter.most_common(1)[0][0] if name_counter else "(unknown)"
    eid = eid_counter.most_common(1)[0][0] if eid_counter else None
    return name, eid


def _resolve_ministry_identity(
    triples: list[tuple[dict, dict | None, dict | None]],
    *,
    fallback: str,
) -> str:
    """Pick a canonical ministry label from the matched records."""
    counter: Counter = Counter()
    for manifest, _discourse, _answer in triples:
        ministry = str(manifest.get("ministry") or "").strip()
        if ministry:
            counter[ministry] += 1
    return counter.most_common(1)[0][0] if counter else fallback.strip() or "Unknown"


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


@dataclass
class _TopicGroup:
    questions: int = 0
    ministries: Counter = field(default_factory=Counter)
    label_counts: Counter = field(default_factory=Counter)
    dates: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    samples_evasive: list[dict] = field(default_factory=list)
    samples_substantive: list[dict] = field(default_factory=list)


_SUBSTANTIVE = frozenset({"ACCEPTED", "REJECTED", "FACTUAL_DISCLOSURE"})
_EVASIVE = frozenset({
    "DEFLECTED", "ABSORBED", "SUBSTITUTED",
    "DATA_WITHHELD", "SCOPE_NARROWED", "CIRCULAR_REFERENCE",
    "CONSTITUTIONAL_DEFAULT",
})


def _classify_label(label: str | None) -> str:
    if not label or label == "UNCLASSIFIED":
        return "unclassified"
    if label in _SUBSTANTIVE:
        return "substantive"
    if label in _EVASIVE:
        return "evasive"
    return "unclassified"


def _render_dossier(
    display_name: str,
    entity_id: str | None,
    pairs: list[tuple[dict, dict | None]],
    *,
    topic_path: Path | None = None,
    corpus_dir: Path | None = None,
) -> str:
    """Render the Markdown dossier from matched record pairs."""
    if not pairs:
        return (
            f"# MP Dossier — {display_name}\n\n"
            f"*Corpus:* {corpus_dir or '(unspecified)'}\n"
            f"*Generated:* {_now()}\n\n"
            f"No questions found. Run `crawl` against a topic profile this "
            f"MP has actually engaged with — the dossier is corpus-scoped "
            f"and will only show records present in `manifest.jsonl`.\n"
        )

    # Group by normalised topic key.
    groups: dict[str, _TopicGroup] = {}
    party_counter: Counter = Counter()
    house_counter: Counter = Counter()
    state_counter: Counter = Counter()
    answer_records = _read_jsonl((corpus_dir or Path("."))/"answers.jsonl") if corpus_dir else []
    answers_by_key: dict[str, dict] = {}
    for r in answer_records:
        k = r.get("key")
        if k and k not in answers_by_key:
            answers_by_key[k] = r

    for manifest, discourse in pairs:
        # Stash demographic info for the header.
        for d in manifest.get("asker_details") or []:
            if isinstance(d, dict):
                if d.get("party"):
                    party_counter[d["party"]] += 1
                if d.get("state"):
                    state_counter[d["state"]] += 1
        if manifest.get("house"):
            house_counter[manifest["house"]] += 1

        ans = answers_by_key.get(manifest.get("key", ""), {})
        subject = ans.get("question_subject") or manifest.get("title") or ""
        topic_key = _normalize_topic_key(subject)
        bucket_key = topic_key or "_uncategorised"
        grp = groups.setdefault(bucket_key, _TopicGroup())
        if subject:
            grp.subjects.append(subject)
        grp.questions += 1
        if manifest.get("ministry"):
            grp.ministries[manifest["ministry"]] += 1
        if manifest.get("date"):
            grp.dates.append(manifest["date"])

        label = (discourse or {}).get("label") or "UNCLASSIFIED"
        grp.label_counts[label] += 1

        # Capture a short excerpt of the response for sample pools.
        # Prefer the v0.6.5 ``answer_body`` (minister preamble stripped) over
        # the regex-tier ``text_excerpt`` because the cleaner text reads
        # better in the briefing. Fall back to text_excerpt for records
        # extracted before v0.6.5.
        excerpt = ans.get("answer_body") or (discourse or {}).get("text_excerpt") or ""
        sample = {
            "key": manifest.get("key"),
            "date": manifest.get("date"),
            "ministry": manifest.get("ministry"),
            "label": label,
            "excerpt": excerpt[:240].replace("\n", " ").strip(),
        }
        cls = _classify_label(label)
        if cls == "evasive" and len(grp.samples_evasive) < 3:
            grp.samples_evasive.append(sample)
        elif cls == "substantive" and len(grp.samples_substantive) < 2:
            grp.samples_substantive.append(sample)

    # Sort topics: most-asked first; uncategorised always last.
    sortable = [(k, g) for k, g in groups.items() if k != "_uncategorised"]
    sortable.sort(key=lambda kv: (-kv[1].questions, kv[0]))
    if "_uncategorised" in groups:
        sortable.append(("_uncategorised", groups["_uncategorised"]))

    # Compute summary stats.
    total_q = sum(g.questions for _, g in sortable)
    all_dates = [d for _, g in sortable for d in g.dates if d]
    date_range = (
        f"{min(all_dates)} – {max(all_dates)}" if all_dates else "(no dates)"
    )
    most_ministry = Counter()
    label_total: Counter = Counter()
    for _, g in sortable:
        most_ministry.update(g.ministries)
        label_total.update(g.label_counts)

    # Identifying Systemic Gaps: Representation Data Omission
    constitutional_defaults = label_total.get("CONSTITUTIONAL_DEFAULT", 0)
    is_institutional_default = constitutional_defaults > 0

    top_ministry = most_ministry.most_common(1)[0] if most_ministry else (None, 0)
    party = party_counter.most_common(1)[0][0] if party_counter else "—"
    state = state_counter.most_common(1)[0][0] if state_counter else "—"
    house = house_counter.most_common(1)[0][0] if house_counter else "—"

    lines: list[str] = []
    lines.append(f"# MP Dossier — {display_name}")
    if is_institutional_default:
        lines.append(f"### ⚠️ SYSTEMIC GAP: Representation Data Omitted")
    lines.append("")
    lines.append(f"*Generated:* {_now()}")
    if corpus_dir:
        lines.append(f"*Corpus:* `{corpus_dir}`")
    if topic_path:
        lines.append(f"*Topic profile:* `{topic_path}`")
    if entity_id:
        lines.append(f"*Entity ID:* `{entity_id}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total questions:** {total_q}")
    lines.append(f"- **Date range:** {date_range}")
    if is_institutional_default:
        lines.append(f"- **Analytical Debt:** This MP's record includes {constitutional_defaults} instances of missing categorical data.")
    lines.append(f"- **Party (most observed):** {party}")
    lines.append(f"- **State / constituency:** {state}")
    lines.append(f"- **House:** {house}")
    if top_ministry[0]:
        lines.append(f"- **Most-asked ministry:** {top_ministry[0]} ({top_ministry[1]})")
    lines.append(f"- **Topics surfaced:** {len(sortable)}")
    if label_total:
        lines.append("- **Response-label totals:**")
        for lab, n in label_total.most_common():
            lines.append(f"  - {lab}: {n}")
    lines.append("")

    lines.append("## Topics")
    lines.append("")
    for k, g in sortable:
        display = (
            "Uncategorised" if k == "_uncategorised"
            else _topic_display(k, g.subjects)
        )
        lines.append(f"### {display} ({g.questions} questions)")
        lines.append("")
        if g.ministries:
            mins = ", ".join(f"{m} ({n})" for m, n in g.ministries.most_common())
            lines.append(f"**Ministries asked:** {mins}")
        if g.dates:
            lines.append(f"**Dates:** {min(g.dates)} – {max(g.dates)}")
        if g.label_counts:
            lc = ", ".join(f"{lab} ({n})" for lab, n in g.label_counts.most_common())
            lines.append(f"**Responses:** {lc}")
        lines.append("")
        if g.samples_evasive:
            lines.append("**Sample evasive responses:**")
            for s in g.samples_evasive:
                lines.append(
                    f"- *{s['label']}* — {s.get('ministry') or '?'}, "
                    f"{s.get('date') or '?'} (`{s.get('key')}`)"
                )
                if s.get("excerpt"):
                    lines.append(f"  > {s['excerpt']}")
            lines.append("")
        if g.samples_substantive:
            lines.append("**Sample substantive responses:**")
            for s in g.samples_substantive:
                lines.append(
                    f"- *{s['label']}* — {s.get('ministry') or '?'}, "
                    f"{s.get('date') or '?'} (`{s.get('key')}`)"
                )
            lines.append("")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"*Generated by `{DOSSIER_VERSION}`.*")
    lines.append("")
    return "\n".join(lines)


def _render_ministry_dossier(
    display_name: str,
    ministry_query: str,
    triples: list[tuple[dict, dict | None, dict | None]],
    *,
    topic_path: Path | None = None,
    corpus_dir: Path | None = None,
) -> str:
    """Render a responder-side briefing for all QA records at one ministry."""
    if not triples:
        return (
            f"# Ministry Dossier — {display_name}\n\n"
            f"*Corpus:* {corpus_dir or '(unspecified)'}\n"
            f"*Generated:* {_now()}\n\n"
            f"No questions found. Run `crawl` against a corpus that includes "
            f"`{ministry_query}`.\n"
        )

    groups: dict[str, _TopicGroup] = {}
    house_counter: Counter = Counter()
    ministry_counter: Counter = Counter()
    qtype_counter: Counter = Counter()
    answer_minister_counter: Counter = Counter()
    answer_records = _read_jsonl((corpus_dir or Path(".")) / "answers.jsonl") if corpus_dir else []
    answers_by_key: dict[str, dict] = {}
    for r in answer_records:
        k = r.get("key")
        if k and k not in answers_by_key:
            answers_by_key[k] = r

    for manifest, discourse, answer in triples:
        if manifest.get("house"):
            house_counter[manifest["house"]] += 1
        if manifest.get("ministry"):
            ministry_counter[manifest["ministry"]] += 1
        if manifest.get("qtype"):
            qtype_counter[str(manifest["qtype"]).strip().title() or "Unknown"] += 1

        ans = answer or answers_by_key.get(manifest.get("key", ""), {})
        answer_minister = (ans or {}).get("answer_minister_name")
        if answer_minister:
            answer_minister_counter[str(answer_minister).strip()] += 1

        subject = (ans or {}).get("question_subject") or manifest.get("title") or ""
        topic_key = _normalize_topic_key(subject)
        bucket_key = topic_key or "_uncategorised"
        grp = groups.setdefault(bucket_key, _TopicGroup())
        if subject:
            grp.subjects.append(subject)
        grp.questions += 1
        if manifest.get("ministry"):
            grp.ministries[manifest["ministry"]] += 1
        if manifest.get("date"):
            grp.dates.append(manifest["date"])
        if manifest.get("qtype"):
            grp.label_counts[f"QTYPE:{str(manifest['qtype']).strip().title()}"] += 1

        label = (discourse or {}).get("label") or "UNCLASSIFIED"
        grp.label_counts[label] += 1

        excerpt = (ans or {}).get("answer_body") or (discourse or {}).get("text_excerpt") or ""
        sample = {
            "key": manifest.get("key"),
            "date": manifest.get("date"),
            "ministry": manifest.get("ministry"),
            "label": label,
            "qtype": manifest.get("qtype"),
            "answer_minister_name": answer_minister,
            "excerpt": excerpt[:240].replace("\n", " ").strip(),
        }
        cls = _classify_label(label)
        if cls == "evasive" and len(grp.samples_evasive) < 3:
            grp.samples_evasive.append(sample)
        elif cls == "substantive" and len(grp.samples_substantive) < 2:
            grp.samples_substantive.append(sample)

    sortable = [(k, g) for k, g in groups.items() if k != "_uncategorised"]
    sortable.sort(key=lambda kv: (-kv[1].questions, kv[0]))
    if "_uncategorised" in groups:
        sortable.append(("_uncategorised", groups["_uncategorised"]))

    total_q = sum(g.questions for _, g in sortable)
    all_dates = [d for _, g in sortable for d in g.dates if d]
    date_range = (
        f"{min(all_dates)} – {max(all_dates)}" if all_dates else "(no dates)"
    )
    top_ministry = ministry_counter.most_common(1)[0] if ministry_counter else (display_name, total_q)
    house = house_counter.most_common(1)[0][0] if house_counter else "—"
    qtype_line = ", ".join(f"{lab} ({n})" for lab, n in qtype_counter.most_common()) or "—"

    label_total: Counter = Counter()
    for _, g in sortable:
        label_total.update(g.label_counts)

    # Identifying Systemic Gaps: Representation Data Omission
    constitutional_defaults = label_total.get("CONSTITUTIONAL_DEFAULT", 0)
    is_institutional_default = constitutional_defaults > 0

    lines: list[str] = []
    lines.append(f"# Ministry Dossier — {display_name}")
    if is_institutional_default:
        lines.append(f"## 🛑 STATUS: SYSTEMIC DATA OMISSION (Article 16 Compliance)")
    lines.append("")
    lines.append(f"*Generated:* {_now()}")
    if corpus_dir:
        lines.append(f"*Corpus:* `{corpus_dir}`")
    if topic_path:
        lines.append(f"*Topic profile:* `{topic_path}`")
    lines.append(f"*Ministry query:* `{ministry_query}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total questions:** {total_q}")
    if is_institutional_default:
        lines.append(f"- **Audit Status:** **CRITICAL**. Detected {constitutional_defaults} instances of missing categorical data.")
    lines.append(f"- **Date range:** {date_range}")
    lines.append(f"- **House:** {house}")
    if top_ministry[0]:
        lines.append(f"- **Ministry (most observed):** {top_ministry[0]} ({top_ministry[1]})")
    lines.append(f"- **Question types:** {qtype_line}")
    if answer_minister_counter:
        mins = ", ".join(f"{m} ({n})" for m, n in answer_minister_counter.most_common())
        lines.append(f"- **Answering ministers:** {mins}")
    lines.append(f"- **Topics surfaced:** {len(sortable)}")
    if label_total:
        lines.append("- **Response-label totals:**")
        for lab, n in label_total.most_common():
            if lab.startswith("QTYPE:"):
                continue
            lines.append(f"  - {lab}: {n}")
    lines.append("")

    lines.append("## Topics")
    lines.append("")
    for k, g in sortable:
        display = (
            "Uncategorised" if k == "_uncategorised"
            else _topic_display(k, g.subjects)
        )
        lines.append(f"### {display} ({g.questions} questions)")
        lines.append("")
        if g.ministries:
            mins = ", ".join(f"{m} ({n})" for m, n in g.ministries.most_common())
            lines.append(f"**Ministries:** {mins}")
        if g.dates:
            lines.append(f"**Dates:** {min(g.dates)} – {max(g.dates)}")
        qtypes = Counter()
        for lab, n in g.label_counts.items():
            if lab.startswith("QTYPE:"):
                qtypes[lab.removeprefix("QTYPE:")] += n
        if qtypes:
            qline = ", ".join(f"{lab} ({n})" for lab, n in qtypes.most_common())
            lines.append(f"**Question types:** {qline}")
        response_labels = Counter({k: v for k, v in g.label_counts.items() if not k.startswith("QTYPE:")})
        if response_labels:
            lc = ", ".join(f"{lab} ({n})" for lab, n in response_labels.most_common())
            lines.append(f"**Responses:** {lc}")
        lines.append("")
        if g.samples_evasive:
            lines.append("**Sample evasive responses:**")
            for s in g.samples_evasive:
                lines.append(
                    f"- *{s['label']}* — {s.get('qtype') or '?'}; "
                    f"{s.get('ministry') or '?'}, {s.get('date') or '?'} "
                    f"(`{s.get('key')}`)"
                )
                if s.get("answer_minister_name"):
                    lines.append(f"  - Answering minister: {s['answer_minister_name']}")
                if s.get("excerpt"):
                    lines.append(f"  > {s['excerpt']}")
            lines.append("")
        if g.samples_substantive:
            lines.append("**Sample substantive responses:**")
            for s in g.samples_substantive:
                lines.append(
                    f"- *{s['label']}* — {s.get('qtype') or '?'}; "
                    f"{s.get('ministry') or '?'}, {s.get('date') or '?'} "
                    f"(`{s.get('key')}`)"
                )
                if s.get("answer_minister_name"):
                    lines.append(f"  - Answering minister: {s['answer_minister_name']}")
            lines.append("")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"*Generated by `{DOSSIER_VERSION}`.*")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_mp_dossier(
    out_dir: Path,
    *,
    entity_id: str | None = None,
    name: str | None = None,
    topic_profile_path: Path | None = None,
    log_fn: Callable[..., None] = print,
) -> Path | None:
    """Build a single MP's dossier; return the output Path, or None if
    no records matched.

    Output is written to ``<out_dir>/mp_dossiers/<slug>.md``. The slug is
    derived from the entity_id when present, otherwise from the matched
    name. The dossier is overwritten on each run; provenance is via
    ``Generated`` timestamp + version constant.
    """
    pairs = find_mp_records(out_dir, entity_id=entity_id, name=name)
    if not pairs:
        log_fn(f"mp-dossier: no records found for entity_id={entity_id!r} name={name!r}")
        return None
    display_name, found_eid = _resolve_display_identity(pairs)
    md = _render_dossier(
        display_name,
        found_eid or entity_id,
        pairs,
        topic_path=topic_profile_path,
        corpus_dir=out_dir,
    )
    slug = _slugify(found_eid or entity_id or display_name)
    dossier_dir = out_dir / "mp_dossiers"
    dossier_dir.mkdir(parents=True, exist_ok=True)
    out_path = dossier_dir / f"{slug}.md"
    tmp = out_path.with_name(out_path.name + ".tmp")
    tmp.write_text(md, encoding="utf-8")
    tmp.replace(out_path)
    log_fn(
        f"mp-dossier: {display_name} → {out_path} "
        f"({len(pairs)} questions; {len(md.splitlines())} lines)"
    )
    return out_path


def build_ministry_dossier(
    out_dir: Path,
    *,
    ministry: str,
    topic_profile_path: Path | None = None,
    log_fn: Callable[..., None] = print,
) -> Path | None:
    """Build a single ministry's dossier; return the output Path, or None
    if no records matched."""
    triples = find_ministry_records(out_dir, ministry=ministry)
    if not triples:
        log_fn(f"ministry-dossier: no records found for ministry={ministry!r}")
        return None
    display_name = _resolve_ministry_identity(triples, fallback=ministry)
    md = _render_ministry_dossier(
        display_name,
        ministry,
        triples,
        topic_path=topic_profile_path,
        corpus_dir=out_dir,
    )
    slug = _slugify(display_name)
    dossier_dir = out_dir / "ministry_dossiers"
    dossier_dir.mkdir(parents=True, exist_ok=True)
    out_path = dossier_dir / f"{slug}.md"
    tmp = out_path.with_name(out_path.name + ".tmp")
    tmp.write_text(md, encoding="utf-8")
    tmp.replace(out_path)
    qtypes = Counter()
    for manifest, _discourse, _answer in triples:
        qtype = str(manifest.get("qtype") or "").strip().title() or "Unknown"
        qtypes[qtype] += 1
    log_fn(
        f"ministry-dossier: {display_name} → {out_path} "
        f"({len(triples)} questions; qtypes={dict(qtypes)}; "
        f"{len(md.splitlines())} lines)"
    )
    return out_path
