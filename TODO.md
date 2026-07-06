# TODO — commoner-analyse

## Current

- [ ] Fix FDA: System Settings → Privacy & Security → Full Disk Access → add Claude Code binary
- [ ] Wait for partial-recall corpus filter fix before using `corpus="folder"` in MCP queries
- [ ] Import `notes/neva-bihar-citations.ris` into Zotero (File → Import)
- [ ] Verify Bihar first session date (22 July 1937) + Ram Dayalu Singh as Speaker — primary source before op-ed publication
- [ ] Search sansad.in written answers for NeVA year-wise expenditure by state

## Future

### NeVA / state assemblies
- [ ] Assam crawl — 14 sessions, only other state with question data
- [ ] Move recon script → `scripts/neva_probe.py` with persistent `state_registry.jsonl`
- [ ] Semantic/intelligence layer: OCR pipeline (two-path Shruti/Shree), translation, embeddings, answer extraction
- [ ] Test H1-H6 hypotheses against PDF answers (`notes/gujarat-assembly15-hypotheses.md`)
- [ ] Expand to UP (`upvs.neva.gov.in`) — largest state, highest volume
- [ ] Expand to Haryana (`hrla.neva.gov.in`)
- [ ] File RTI: MoPA — year-wise funds released per state under NeVA CSS 2019-26
- [ ] File RTI: Bihar Vidhan Sabha — status of pre-2022 paper records, digitization plan
- [ ] File RTI: NIC — status of vidhansabha.bih.nic.in data (migrating or abandoned?)
- [ ] Check Wayback Machine: vidhansabha.bih.nic.in snapshots 2010–2019
- [ ] Op-ed: finish verify checklist then share (notes/op-ed-draft-bihar-hollowtech.md)
- [ ] Publish `notes/neva-api-public-draft.md` once ≥10 states verified

### Central parliament (pre-existing)
- [ ] regex_v2 coverage audit (reference corpora, measure delta from ~28%)
- [ ] Entity resolver fix: Article 101 house+term disambiguation (`resolver.py`)
- [ ] CPR Accountability Initiative adapter (JS-rendered, RSS route preferred)
- [ ] TECHDEBT: duplicate HTTP layer (discourse.py + dossier.py → shared helper)
- [ ] TECHDEBT: topic_hash propagation into analysis_discourse.jsonl
- [ ] TECHDEBT: Channel enum

## Archive

- [x] Gujarat assembly 15 full crawl started (all 8 sessions, with PDFs) (2026-05-21)
- [x] Analytical hypotheses written + typeset as PDF (`notes/gujarat-assembly15-hypotheses.pdf`) (2026-05-21)
- [x] SESSION_LOG.md + WORKING.md maintained (2026-05-21)
- [x] Two mistakes logged to `_org/mistakes.md` (2026-05-21)
- [x] v1.1.0 released — changelog aligned, README updated (2026-05-20)
- [x] NeVA recon: reverse-engineered full Gujarat API surface (2026-05-20)
- [x] NeVA scraper written: neva.py + neva-crawl CLI command (2026-05-21)
- [x] Gujarat assembly 15 smoke test: 2,122 Q + 145 papers + 181 members (2026-05-21)
- [x] v1.0.0 released: ATR linkage, constitutional audit, mp/ministry dossier (2026-05-13)
- [x] CI workflow added (Python 3.10-3.13 matrix) (2026-05-13)
- [x] Security hardening PRs #19, #21 (2026-05-10)
- [x] mp-dossier + ministry-dossier feature v0.6.6 (2026-05-09)
- [ ] OCR pipeline for Session 8 answers (Tesseract 5.5.2 + guj)
- [ ] Analysis: Test H1-H7 against extracted Session 8 text
- [ ] Re-index partial-recall (awaiting corpus="folder" filter fix)
- [ ] Verify NeVA uniformity on Haryana (hrla.neva.gov.in)
- [ ] Verify NeVA uniformity on Tamil Nadu (tnla.neva.gov.in)
- [ ] Comparison: Map "Ghetto" ministries in TN vs GJ (Revenue vs Social Justice)
