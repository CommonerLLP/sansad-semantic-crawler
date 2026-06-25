"""MP roster + committee-member fetch — delegated to commoner-probe.

This module used to carry a byte-identical copy of the roster/lookup logic.
It now re-exports the implementation from ``commoner_probe.members`` so member
acquisition lives in exactly one place (the published ``commoner-probe``
package). The public surface is preserved so existing
``from sansad_semantic_crawler.members import ...`` callers keep working.
"""

from __future__ import annotations

from commoner_probe.members import (  # noqa: F401  (re-export)
    MPRoster,
    MemberInfo,
    fetch_committee_members,
)

__all__ = ["MPRoster", "MemberInfo", "fetch_committee_members"]
