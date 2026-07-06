"""Floor-debate crawler — acquisition delegated to commoner-probe.

Lok Sabha per-sitting-day debate-transcript acquisition lives in the published
``commoner-probe`` package. Debates are document-level PDFs (one transcript per sitting day)
with no SSC semantic layer yet — the analysed corpus is Q/A + committee reports only (see
``weighting.py``) — so this is a thin re-export of the probe's ``DebateProbe`` and its date
helpers, mirroring ``members.py``.

Note: ``commoner_probe.debates`` ships in the probe's new-data-sources release. ``cli.py``
imports this module lazily (inside ``crawl_debates_cmd``) so the rest of the CLI keeps working
against an older probe.
"""

from __future__ import annotations

from commoner_probe.debates import (  # noqa: F401  (re-export)
    LS_DEBATE_API,
    DebateProbe,
    date_to_iso,
    date_to_mdy,
)
