"""Bills / legislation crawler — acquisition delegated to commoner-probe.

sansad.in bill acquisition lives in the published ``commoner-probe`` package (the single source
of truth). SSC has no bill-specific semantic layer yet — discourse analysis covers Q/A and
committee responses only (see ``weighting.py``) — so this module is a thin re-export of the
probe's ``BillsProbe`` and its key helper, mirroring ``members.py``. A semantic wrapper
(``BillsCrawler(BillsProbe)`` overriding ``append``) belongs here only once bill-level analysis
exists; until then there is nothing to wrap, and an empty wrapper would just be dead code.

Note: ``commoner_probe.bills`` ships in the probe's new-data-sources release; it is newer than
the committee/Q-A delegation surface. ``cli.py`` imports this module lazily (inside
``crawl_bills_cmd``) so the rest of the CLI keeps working against an older probe, exactly as it
does for ``members``.
"""

from __future__ import annotations

from commoner_probe.bills import (  # noqa: F401  (re-export)
    BILLS_API,
    BillsProbe,
    bill_key,
)
