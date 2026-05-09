"""Per-MP topic dossier — the v0.6.6 deliverable.

For a single MP, produce a Markdown briefing of every question they have
asked in a corpus, grouped by topic, with the ministerial response label
distribution and excerpts of evasion text.

This is the artefact the analyst reads to make the bridging-knowledge
call (per ``notes/PRODUCT_DESIGN.md §IV.5`` and ``notes/ROADMAP.md``).
The crawler does *not* suggest reframings; it makes the gap visible —
"on libraries, this MP got SCOPE_NARROWED 3 times" — so the analyst
applies their domain knowledge to suggest a better framing (e.g. "ask
about RRRLF instead").

Topic clustering uses keyword overlap on the v0.6.5 ``question_subject``
field, normalised by stop-word removal + sorted-token-set keying. No
embeddings (those arrive in v0.7.0 only if v0.6.6 keyword overlap is
demonstrably insufficient).

Records without a parsed ``question_subject`` (about 67% of the ADP
corpus today) fall into a single ``"Uncategorised"`` bucket rather
than being silently dropped — coverage is honest, not hidden.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

DOSSIER_VERSION = "mp_dossier_v1"

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


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
    top_ministry = most_ministry.most_common(1)[0] if most_ministry else (None, 0)
    party = party_counter.most_common(1)[0][0] if party_counter else "—"
    state = state_counter.most_common(1)[0][0] if state_counter else "—"
    house = house_counter.most_common(1)[0][0] if house_counter else "—"

    lines: list[str] = []
    lines.append(f"# MP Dossier — {display_name}")
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
    lines.append(
        "*This dossier surfaces patterns; it does not suggest reframings. "
        "Use it as the artefact for the bridging-knowledge call (per "
        "`notes/PRODUCT_DESIGN.md §IV` and `notes/ROADMAP.md §I`).*"
    )
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
