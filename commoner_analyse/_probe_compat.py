"""Shared probe-delegation helpers for the SSC semantic wrappers.

Both ``sansad`` and ``committees`` wrap a commoner-probe probe and apply SSC's
semantic layer at append time. Two pieces of that layer are identical across the
two modules and live here so they have a single definition:

* ``with_crawled_at`` aliases the probe's ``probed_at`` to ``crawled_at``, for
  backward compatibility with consumers of the old local crawler's output.
* ``ClassifierRunLog`` wraps the probe's run log to inject SSC's
  ``classifier_mode`` (which the probe does not know about) and, when an
  ``appended_counter`` is supplied, correct the per-run ``added`` total to the
  number of records actually written after SSC's append-time semantic filter.
"""

from __future__ import annotations

from typing import Any, Callable


def with_crawled_at(record: dict) -> dict:
    out = dict(record)
    if "crawled_at" not in out and out.get("probed_at"):
        out["crawled_at"] = out["probed_at"]
    return out


class ClassifierRunLog:
    def __init__(
        self,
        runlog,
        *,
        classifier_mode: str,
        classifier_config: dict[str, Any],
        appended_counter: Callable[[], int] | None = None,
    ) -> None:
        self._runlog = runlog
        self._classifier_mode = classifier_mode
        self._classifier_config = classifier_config
        # Optional callable returning the running count of records actually
        # written to the manifest. Used to correct the per-run ``added`` total
        # when acquisition is delegated to commoner-probe: the probe counts at
        # acquisition time, before SSC's append-time semantic filter runs.
        self._appended_counter = appended_counter
        self._appended_at_start = 0

    def start(self, **kwargs):
        kwargs.setdefault("classifier_mode", self._classifier_mode)
        kwargs.setdefault("classifier_config", self._classifier_config)
        if self._appended_counter is not None:
            self._appended_at_start = self._appended_counter()
        return self._runlog.start(**kwargs)

    def finish(self, *, added: int) -> None:
        # When an appended_counter is supplied (the QA path), the probe's
        # ``added`` counts rows it acquired, but SSC's append-time filter may
        # drop non-matching rows. Report the count actually written so the run
        # total matches the local crawler's contract. Without a counter (the
        # committee path, which never drops) this just delegates unchanged.
        if self._appended_counter is not None:
            added = self._appended_counter() - self._appended_at_start
        return self._runlog.finish(added=added)

    def __getattr__(self, name: str):
        return getattr(self._runlog, name)
