# Branch owner live validation

## Execution boundary

Executed the installed Pi 1.4.0 SDK with the change's actual supervision extension and unmodified Firstmate shell scripts. Used a marked disposable FM_HOME inside the gate worktree, an isolated Pi agent directory, real SessionManager persistence, and a localhost OpenAI-compatible SSE emulator with synthetic tool-call responses. No provider credentials, operator data, default tmux server, or Herdr session were used. This proves local ownership and delivery behavior, not live-provider reasoning or authentication.

## Results

- Helper exclusion: real child SDK processes at PSTACK_SUBAGENT_DEPTH=1 and 2 loaded and disposed the extension under the parent's lock ancestry. Both exited zero without changing the primary owner bytes. Each subsequent wake reached the branch and persisted a routine report.
- Owner repair: deleting the owner or replacing its PID with a dead or foreign live PID, or replacing its generation, was repaired before the next branch request. Active task leases survived. A normal main prompt also repaired deletion without a reload. Row grants remained intact across the real report tool's ownership recheck.
- Lock boundary: absent and foreign session locks prevented owner recreation and wake acceptance. Restoring the primary lock restored owner registration through a normal main prompt and enabled the next durable branch report. Primary shutdown removed its owner record.

The live run finished with 8 persisted reports and 21 localhost requests. `owner-live-transcript.jsonl` contains owner/grant readbacks and the real report-tool results; `persisted-branch-outcomes.jsonl` is the product's resulting durable outcome store.

## Commands and reproducibility

Baseline targeted regression command (exit 0):

```sh
PSTACK_SUBAGENT_DEPTH=1 FM_PI_PACKAGE_DIR=/opt/homebrew/Cellar/pi-coding-agent/1.4.0/libexec/lib/node_modules/@earendil-works/pi-coding-agent bash bin/fm-test-run.sh tests/fm-pi-branch-extension.test.sh
```

Live driver preparation: mint `.owner-live-lab/home` using `bash bin/fm-lab-home.sh create`, copy the branch extension and its `lib` directory to `.owner-live-lab/repo/.pi/extensions`, and link that disposable repo's node_modules to the installed Pi package and its pi-ai, pi-tui, and typebox dependencies. Create `.owner-live-lab/agent`. Run from the gate worktree:

```sh
env -u FM_STATE_OVERRIDE -u FM_CONFIG_OVERRIDE -u FM_DATA_OVERRIDE -u FM_PROJECTS_OVERRIDE -u FM_GATE_REFUSE_BYPASS -u FM_TEST_SEAM \
  FM_HOME="$PWD/.owner-live-lab/home" FM_ROOT_OVERRIDE="$PWD" \
  PI_CODING_AGENT_DIR="$PWD/.owner-live-lab/agent" PSTACK_SUBAGENT_DEPTH=0 \
  PI_PACKAGE_DIR=/opt/homebrew/Cellar/pi-coding-agent/1.4.0/libexec/lib/node_modules/@earendil-works/pi-coding-agent \
  NODE_NO_WARNINGS=1 node ~/.no-mistakes/evidence/01M6RK0A3TJB5GFWZ09823QG6P/owner-live-driver.mjs
```

The first probe attempt lacked dispatch eligibility on a hand-built offer and declined before branch execution; switching to the product's exported offer constructor corrected that driver setup. The retained transcript is the complete successful rerun (exit 0).

The SDK sessions were disposed, both helper children were awaited, the HTTP server was closed, and the disposable worktree directory was removed. Final git status was clean. No source changes, broad suite, linters, formatters, publication, or CI were performed. No screenshot is applicable: the changed behavior is local persisted ownership and routing, not a rendered UI change.
