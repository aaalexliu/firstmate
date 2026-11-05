# Local usage report: live validation

The real `bin/fm-usage-report.sh` and its generated offline HTML were executed in this run using disposable synthetic JSONL transcripts, a synthetic no-mistakes SQLite ledger, synthetic task records, and an external-boundary `quota-axi` fixture. No operator accounting data, provider credentials, live quota service, default fleet session, or real launchd agent was used.

## Executed scenarios

- Import/replay: the focused public CLI suite exercised Pi/Claude/Codex normalization, cumulative counters, fragments, compaction, file rotation and partial lines, and no-mistakes overlap ownership. The additional CLI drive retained actual product records; reimport left facts unchanged and the review ledger owned its overlapping native session.
- Attribution: native home sessions, the distinct supervision store, task-bound workers, and review invocations retained their proven roles; an unproven session remained unassigned. Focused public CLI cases also exercised response-ID overlap in both orders and binding retention through cleanup/pool reuse.
- Quota: synthetic 30% account readings allocated exactly 30% across each provider's priced current-window usage; Claude displayed its published seed. Hourly readings with reset jitter trained four usable pairs and left seeded mode. True resets, stale/multiple lanes, and unavailable readings did not train. The delayed-refresh and explicit-clock cases passed in the targeted suite. Actual retained stores are in `edge-accounting-observed.json`.
- Privacy/fallback: unsupported prices stayed unknown; missing Grok quota displayed token shares, not quota. Prompt/account fixture secrets did not enter persisted accounting/report output. A script-breakout session ID stayed literal in the running browser without setting `window.INJECTED`.
- Navigation/detail: Chrome opened the real generated file, followed role and all-session controls, checked nine current-window sessions (excluding a larger old session), verified descending default tokens from the overview header, toggled tokens and quota both directions, opened rows and keyboard selections, and displayed token splits, role evidence, confidence and provider windows. Source-log, task-record and review-run links were followed to actual synthetic files before cleanup. Desktop and 390px emulated viewport screenshots were retained; console was empty.
- Scheduling: install wrote a home-specific plist with StartInterval=3600 and isolated refresh arguments; uninstall removed it. These commands only emitted load/unload instructions; no launchctl action was run.

## Commands and artifacts

`TMPDIR="$PWD/.test-usage/tmp" PYTHONDONTWRITEBYTECODE=1 bash bin/fm-test-run.sh tests/fm-usage-report.test.sh` passed all 26 focused public CLI cases without a gate skip. This was not the repository-wide suite. No lint, static analysis, documentation pipeline, push, PR, or CI phase was run.

Scratch drivers `drive_cli.py`, `drive_browser.py`, and `retain_edge_evidence.py` are retained alongside the evidence. Their executed copies lived under `.test-usage/`. `cli-transcript.txt` and `browser-transcript.txt` show actual commands and product output. `accounting-observed.json` and `edge-accounting-observed.json` retain actual product state. `synthetic-report.html` is fresh generated product output, not the author's earlier screenshots.

The named Chrome bridge was stopped, all temporary fixtures and browser profile files were removed, and the worktree was clean at completion. Local source links in the retained HTML point to those now-removed fixtures; successful link opens are recorded in the browser transcript. No product or permanent test source changed.

The private design file `data/usage-dashboard-design/report.md` was absent from the supplied worktree. Validation used the explicit intent, recorded decisions, tracked configuration contract and executable public interfaces instead. There were no unresolved product failures.
