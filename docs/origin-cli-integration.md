# Cursor Origin pull request verification

Empirical record for Cursor Origin support: registering an Origin pull request, watching it until it merges, merging it through `bin/fm-pr-merge.sh`, and proving the work landed at cleanup.
A project opts in with the `forge=origin` registry binding, which `bin/fm-project-mode.sh` owns; the watch, merge, and cleanup paths key off the pull request URL itself, and the binding decides only what a generated ship brief tells the worker (`bin/fm-dod-lib.sh`).
`bin/fm-pr-merge.sh`'s header owns the merge contract; this record holds the live CLI behavior it depends on.
All evidence below was collected on 2026-10-29 and 2026-10-30 against the live Origin service, reading `aaalexliu/genesis` and writing only to the throwaway repository `aaalexliu/fm-origin-sandbox`, which allows squash and merge commits and runs no checks.

## Versions

```
$ origin --version
2026.10.23-18-47-36-f52be1e

$ jq --version
jq-1.8.1

$ git --version
git version 2.33.1
```

The guarded-merge runs on 2026-10-30 pushed with `git version 2.56.0` and ran `GNU bash, version 5.3.9(1)-release`.

The clones used a per-clone credential helper rather than `origin auth setup-git`, which changes global Git configuration:

```
$ git -C <clone> config credential.https://origin.cursor.com.helper '!/Users/alexliu/.local/bin/origin credential-helper'
```

## URL shape

Origin serves a pull request page on `cursor.com`, not on its `origin.cursor.com` Git host:

```
$ origin pr create --head watch-e2e-1 --base main --title "Watch probe 1" --body "..."
Created pull request #1 in aaalexliu/fm-origin-sandbox.
  URL:         https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/1
  Status:      open
  Head ref:    watch-e2e-1
  Base ref:    main
  Version #1: a8eee929e6a05540df46a31d74be059b52e2db09 <- d5507415d4d1133e4466afdb117edcc5c14009c7

$ origin repo view aaalexliu/fm-origin-sandbox --json cloneUrl
{"cloneUrl":"https://origin.cursor.com/aaalexliu/fm-origin-sandbox.git"}
```

`fm_pr_url_parse` in `bin/fm-pr-lib.sh` therefore accepts exactly `https://cursor.com/codebase/<org>/<repo>/pull/<n>`, which the GitHub pattern cannot match because it allows only two path segments before `/pull/`.
`origin pr view` also takes that URL as its target.

## Reading one pull request

`origin pr view <n> -R <org>/<repo> --json <fields>` prints one compact JSON object holding exactly the requested fields; an unknown field exits 1 and lists the available ones.
`fm_pr_origin_read_record` reads `status,isDraft,headSha,headRef,baseRef,mergeCommitSha,mergedAt,url`, and the static poll in `bin/fm-pr-poll.sh` reads `status,url`.
The record reader requires only `status`, `isDraft`, `headSha`, and `url`; it exports `headRef`, `baseRef`, `mergeCommitSha`, and `mergedAt` as empty when Origin reports them null, empty, or malformed.
Origin spells the status `open`, `draft`, `merged`, or `closed`:

```
$ origin pr view 1 -R aaalexliu/genesis --json status,isDraft,headSha,headRef,baseRef,mergeCommitSha,mergedAt,url
{"status":"draft","isDraft":true,"headSha":"8ec318dfc4676680c937be57441e1a16a913e31f","headRef":"cursor/mac-transcript-5698","baseRef":"main","mergeCommitSha":null,"mergedAt":null,"url":"https://cursor.com/codebase/aaalexliu/genesis/pull/1"}

$ origin pr view 3 -R aaalexliu/fm-origin-sandbox --json status,isDraft,headSha,headRef,baseRef,mergeCommitSha,mergedAt,url,closedAt
{"status":"closed","isDraft":false,"headSha":"f3196efd215ae3015e06c8b71543e0370e0d0257","headRef":"watch-e2e-2","baseRef":"main","mergeCommitSha":null,"mergedAt":null,"url":"https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/3","closedAt":"2026-10-29T22:05:29Z"}

$ origin pr view 9 -R aaalexliu/fm-origin-sandbox --json status,headSha,mergeCommitSha,mergedAt,url
{"status":"merged","headSha":"09a8af05b3ae57ffc302bf9ce6bf7c45876b6faf","mergeCommitSha":"0360f8e3b79d528c13f07ddcc61024275ec22a44","mergedAt":"2026-10-29T22:33:41Z","url":"https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/9"}
```

A missing pull request or repository exits 1 with an error on stderr and nothing on stdout:

```
$ origin pr view 999 -R aaalexliu/genesis --json status,url
Error: Origin pull request #999 not found in repo r_01m4p8n62ff94ss6jf8wqza1xn
(exit 1)

$ origin pr view 1 -R aaalexliu/nonexistent-repo-xyz --json status,url
Error: Repository aaalexliu/nonexistent-repo-xyz was not found on Origin.
(exit 1)
```

Both readers also require the record's own `url` to equal the watched URL, so a read that reached another pull request is treated as unreadable rather than as this one.

## Pushing, opening, and checks

A plain `git push` to the head branch of an open pull request records a new version with the new head, and `origin pr view <branch>` finds the open pull request for a branch:

```
$ git push -q origin watch-e2e-1
$ origin pr view watch-e2e-1 --json number,url,headSha
{"number":1,"url":"https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/1","headSha":"560b259ca5d94efdb4421a27f90211b9ca64ef46"}
```

`origin pr create --push` runs an ordinary push of an unpushed branch, which records the remote-tracking ref in the clone:

```
$ origin pr create --push --title "Watch probe 2" --body "..."
To https://origin.cursor.com/aaalexliu/fm-origin-sandbox.git
 * [new branch]      watch-e2e-2 -> watch-e2e-2
Branch 'watch-e2e-2' set up to track remote branch 'watch-e2e-2' from 'origin'.
Created pull request #3 in aaalexliu/fm-origin-sandbox.
```

`origin pr checks` exits 0 when every reported check passed and exits 1 when the pull request reports none.
With `--watch`, a pull request that reports no checks never returns; it was still waiting when stopped after 60 seconds:

```
$ origin pr checks 1 -R aaalexliu/genesis
Checks for 8ec318dfc467 (head 8ec318dfc467)
CI checks:
  - Vercel (Vercel)
    - Vercel – chinese-podcast-learner: completed (success) - https://vercel.com/...
    - Vercel Preview Comments: completed (success)
(exit 0)

$ origin pr checks 1 -R aaalexliu/fm-origin-sandbox
Checks for a8eee929e6a0 (head a8eee929e6a0)
No checks reported.
(exit 1)
```

## Refs Origin serves

Origin serves `refs/pull/<n>/merge` and `refs/changes/<n>/merge` for an open pull request, but no `refs/pull/<n>/head`, and the merge refs are gone once it merges:

```
$ git ls-remote origin
d5507415d4d1133e4466afdb117edcc5c14009c7	HEAD
0b5ce5802791b56a07dd2599a153dbf390edfef0	refs/changes/1/merge
d5507415d4d1133e4466afdb117edcc5c14009c7	refs/heads/main
a8eee929e6a05540df46a31d74be059b52e2db09	refs/heads/watch-e2e-1
0b5ce5802791b56a07dd2599a153dbf390edfef0	refs/pull/1/merge

$ git fetch --quiet origin refs/pull/1/head
fatal: couldn't find remote ref refs/pull/1/head
```

A fetch of a commit by its id succeeds, including the head of a branch deleted moments earlier:

```
$ git push -q origin --delete watch-e2e-2
$ git fetch --quiet origin f3196efd215ae3015e06c8b71543e0370e0d0257
(exit 0)
```

So `bin/fm-teardown.sh` and `bin/fm-review-diff.sh` fetch an Origin head by commit id when the copy lacks it.
Merging did not delete the head branch: `watch-e2e-1` stayed on the remote after pull request 1 merged until it was deleted by hand.

## End to end: register, watch, merge by hand, clean up

A scratch home held one ship record whose copy was a clone on branch `watch-e2e-4`, pushed and opened as pull request 9.
The worker-runtime tools that cleanup reaches (`treehouse`, `tmux`, `no-mistakes`, `gh`, `gh-axi`) were logging stubs on `PATH`, and `origin` was a shim logging each call before running the real CLI.

```
$ FM_HOME=<scratch> bin/fm-pr-check.sh watch-e2e-4 https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/9
armed: state/watch-e2e-4.check.sh

$ grep -E '^(pr|pr_head)=' <scratch>/state/watch-e2e-4.meta
pr=https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/9
pr_head=09a8af05b3ae57ffc302bf9ce6bf7c45876b6faf

$ cat <scratch>/state/watch-e2e-4.pr-poll
origin
https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/9
cursor.com
aaalexliu/fm-origin-sandbox
9

$ cat <origin shim log>
pr view 9 -R aaalexliu/fm-origin-sandbox --json status,isDraft,headSha,headRef,baseRef,mergeCommitSha,mergedAt,url

$ bash <scratch>/state/watch-e2e-4.check.sh
(nothing: the pull request is open)
```

A bounded `bin/fm-watch.sh` run read the pull request four times while it was open and raised no merge wake.
A person then merged it in Origin:

```
$ origin pr merge 9 -R aaalexliu/fm-origin-sandbox --squash --match-head-commit 09a8af05b3ae57ffc302bf9ce6bf7c45876b6faf
Merged pull request #9 in aaalexliu/fm-origin-sandbox.
  Merge commit: 0360f8e3b79d528c13f07ddcc61024275ec22a44

$ FM_HOME=<scratch> bin/fm-watch.sh
check: <scratch>/state/watch-e2e-4.check.sh: merged

$ tail -1 <scratch>/state/.wake-queue
1793313228	2	check	merged-watch-e2e-4-https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/9	check: merge landed: watch-e2e-4 https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/9 external
```

To make the merged record the only proof that the work landed, a second pull request (10) reworded the probe file on `main`, so a merge of the copy's head with `main` conflicts, and the head branch was deleted and pruned, so no remote-tracking ref holds the copy's head.
Cleanup then proved the work landed through the Origin record and finished:

```
$ FM_HOME=<scratch> bin/fm-teardown.sh watch-e2e-4
<project>: synced d550741..2399d1d
teardown watch-e2e-4 complete (window fm-e2e:fm-watch-e2e-4, worktree <copy>)
(exit 0)

$ cat <origin shim log>
pr view 9 -R aaalexliu/fm-origin-sandbox --json status,isDraft,headSha,headRef,baseRef,mergeCommitSha,mergedAt,url
```

`tests/fm-pr-check-security.test.sh`, `tests/fm-teardown.test.sh`, `tests/fm-crew-state.test.sh`, and `tests/fm-review-diff.test.sh` reproduce these paths hermetically with the `fm_fake_origin` stub from `tests/lib.sh`.

## Guarded merge

Each run below used a scratch Firstmate home whose task record named only the worker's copy, project, and mode.
`bin/fm-pr-check.sh` registered the pull request, as a ready report does, and then this repository's `bin/fm-pr-merge.sh` ran against it.
Lines from `bin/fm-guard.sh` about the scratch home's supervision are omitted.
`tests/fm-pr-merge.test.sh` pins every condition below with a stub `origin`, including the ones the sandbox cannot produce.

### CLI facts the merge path relies on

- `origin pr view <n> -R <org>/<repo> --json <fields>` also serves `parentChangeId`, `mergeability`, and `ciState`.
- `ciState.checkRunGroups[].checkRuns[]` carries `name`, `status`, `conclusion`, and `headSha`; a repository with no checks reports `"checkRunGroups":[]`.
- A check run's `status` is one of `queued`, `in_progress`, `completed`, `rerequested`, or `failing`, and its `conclusion` is one of `success`, `failure`, `neutral`, `cancelled`, `skipped`, `timed_out`, `action_required`, or `stale` (the CLI's own enums).
- The CLI passes `success`, `neutral`, and `skipped`; `origin agent prompt` says `origin pr checks` "exits 0 when every check passed, 1 when a check failed or there are no checks, and 8 while checks are pending".
- `mergeability.mergeConflictState` is `MERGE_CONFLICT_STATE_CLEAN` only for a clean answer; the CLI's own guide says `MERGE_CONFLICT_STATE_PENDING` "means Origin is still checking, so `hasMergeConflicts: false` beside it is not clean".
- `mergeability.evaluatedHeadSha` names the head the verdict was computed at.
- `parentChangeId` is set on a stacked pull request and stays set after its parent merges.
- `origin pr merge` offers only `--merge` and `--squash`, with no rebase merge; the merge passes `--squash` unless the caller names `--merge`, and leaves a method the repository disallows for `origin pr merge` to refuse.
- `origin pr merge <n> --match-head-commit <sha>` refuses when the head moved, and without `--auto` it merges now.
- A user principal cannot post check runs: `POST /repos/{owner}/{repo}/check-runs` through `origin api` answers `HTTP 403` with `"This Origin endpoint does not support user principals"`.

An open pull request with no checks, abridged to the fields the merge reads:

```
$ origin pr view 2 -R aaalexliu/fm-origin-sandbox --json number,url,status,isDraft,headSha,parentChangeId,stackId,mergeability,ciState,mergeCommitSha,mergedAt,mergeWhenReady
"url": "https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/2",
"status": "open",
"isDraft": false,
"headSha": "0712eee9d915f713bdce99451a27e9716df0eec1",
"parentChangeId": null,
"mergeability": {
  "mergeable": true,
  "hasMergeConflicts": false,
  "mergeability": { "verdict": "mergeable", "evaluations": [], "blockers": [], "configurationDiagnostics": [] },
  "evaluatedHeadSha": "0712eee9d915f713bdce99451a27e9716df0eec1",
  "mergeConflictState": "MERGE_CONFLICT_STATE_CLEAN",
  ...
},
"ciState": { "checkRunGroups": [] },
"mergeCommitSha": null,
"mergedAt": null
```

### Register, then merge

Registration records the head Origin reports, and the merge refuses a pull request with no check unless the attended waiver for that one condition is named:

```
$ fm-pr-check.sh task-live https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/12
armed: state/task-live.check.sh

$ grep -E '^(pr|pr_head)=' state/task-live.meta
pr=https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/12
pr_head=e9f09e13c8bcdf28a7b4ff9c40f9494e00bd1829

$ fm-pr-merge.sh task-live https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/12
armed: state/task-live.check.sh
error: refusing to merge https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/12
  - no check has reported at head e9f09e13c8bcdf28a7b4ff9c40f9494e00bd1829
exit=1

$ fm-pr-merge.sh task-live https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/12 --allow-no-pipeline
armed: state/task-live.check.sh
verified: https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/12 is open and mergeable at the recorded head e9f09e13c8bcdf28a7b4ff9c40f9494e00bd1829, with no checks, waived by --allow-no-pipeline
verified: https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/12 is merged as commit ba1a256c2c60b3f2f68cd146b117614bc2cdddd5 at 2026-10-30T02:41:33Z
exit=0
```

The task's durable outcome and persisted merge authority:

```
$ cat state/.wake-queue
1793328093	1	check	merged-task-live-https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/12	check: merge landed: task-live https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/12

$ cat state/task-live.merge-authority
fm-merge-authority-v1
origin
cursor.com
aaalexliu/fm-origin-sandbox
12
attended
```

The read-back and the base branch agree on the merge commit, a single-parent squash:

```
$ origin pr view 12 -R aaalexliu/fm-origin-sandbox --json status,mergeCommitSha,mergedAt,headSha
{"status":"merged","mergeCommitSha":"ba1a256c2c60b3f2f68cd146b117614bc2cdddd5","mergedAt":"2026-10-30T02:41:33Z","headSha":"e9f09e13c8bcdf28a7b4ff9c40f9494e00bd1829"}

$ git log --format="%H %P %s" -2 origin/main
ba1a256c2c60b3f2f68cd146b117614bc2cdddd5 6d085c48a9bc0f4a0293bee7dbc5e0b60d7f7ef5 merge: guarded merge probe 2 (#12)
6d085c48a9bc0f4a0293bee7dbc5e0b60d7f7ef5 2399d1db3a667f5dd77fefd3c46e13efbba41b5b Watch probe 6 (#11)
```

### A push after registration refuses

A second commit pushed after registration moves the live head away from the recorded one, so the merge refuses.
This run predates the merge keeping the recorded head: its last line shows the head it re-recorded, where the merge now leaves `713882b7175272aa8a22b34ca993cf8279750a61`, so a retry still refuses until the moved head is reviewed and a fresh `fm-pr-check.sh` registration from a done report records it:

```
$ fm-pr-check.sh task-live https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/13
armed: state/task-live.check.sh
pr_head=713882b7175272aa8a22b34ca993cf8279750a61

$ git push origin merge-guarded-3
$ origin pr view 13 -R aaalexliu/fm-origin-sandbox --json headSha
{"headSha":"0013b4e4348e7330e0da53df333c6b53d19efada"}

$ fm-pr-merge.sh task-live https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/13 --allow-no-pipeline
armed: state/task-live.check.sh
error: refusing to merge https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/13
  - the live head 0013b4e4348e7330e0da53df333c6b53d19efada is not the recorded head 713882b7175272aa8a22b34ca993cf8279750a61
exit=1
pr_head=0013b4e4348e7330e0da53df333c6b53d19efada
```

Origin enforces the same pin on its own when a head moves between the read and the merge:

```
$ origin pr merge 2 -R aaalexliu/fm-origin-sandbox --squash --match-head-commit d5507415d4d1133e4466afdb117edcc5c14009c7
Error: head of pull request #2 does not match the expected SHA: expected d5507415d4d1133e4466afdb117edcc5c14009c7, found 0712eee9d915f713bdce99451a27e9716df0eec1
exit=1
```

### A stacked pull request

Pull request 7 was opened with `origin pr create --stack-on 4`.
Origin itself reported it mergeable, so `origin pr merge 7` would have landed 4 and 7 together:

```
{"number":7,"status":"open","isDraft":false,"headSha":"f837910b566808196d962dfd7629ec931972d22b","parentChangeId":"pr_01m64vnh42ecbvqrxpvhxg14hy","stackId":"stk_01m64vnr49fx8tka7g34hq4p7a","mergeable":true,"hasMergeConflicts":false,"mergeConflictState":"MERGE_CONFLICT_STATE_CLEAN","evaluatedHeadSha":"f837910b566808196d962dfd7629ec931972d22b","blockers":[],"ci":{"checkRunGroups":[]}}
```

```
$ fm-pr-merge.sh task-live https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/7 --allow-no-pipeline
armed: state/task-live.check.sh
error: refusing to merge https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/7
  - the pull request is stacked on parent change pr_01m64vnh42ecbvqrxpvhxg14hy; merging it would land every open pull request from the stack root through it in one commit
exit=1
```

The stack root, pull request 4, has no parent, so it merges alone; this run also names the merge-commit method:

```
$ fm-pr-merge.sh task-live https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/4 --allow-no-pipeline -- --merge
armed: state/task-live.check.sh
verified: https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/4 is open and mergeable at the recorded head 27c0784ba6224d59594809e422b68c8c322cf8ef, with no checks, waived by --allow-no-pipeline
verified: https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/4 is merged as commit 1bc536c7af3227eec76f386384e12cf15d77b0c6 at 2026-10-29T22:15:32Z
exit=0

$ git log --format="%H %P %s" -2 origin/main
1bc536c7af3227eec76f386384e12cf15d77b0c6 ab7fe1f8dbbb1c7d983feb1a1d258e5fd07d3606 27c0784ba6224d59594809e422b68c8c322cf8ef merge: stack base (#4)
27c0784ba6224d59594809e422b68c8c322cf8ef ab7fe1f8dbbb1c7d983feb1a1d258e5fd07d3606 Add a stack base file
```

After its parent merged, pull request 7 keeps `parentChangeId`, and Origin blocks it on its own:

```
{"number":7,"status":"open","parentChangeId":"pr_01m64vnh42ecbvqrxpvhxg14hy","stackId":"stk_01m64vnr49fx8tka7g34hq4p7a","headSha":"f837910b566808196d962dfd7629ec931972d22b","baseRef":"merge-stack-base","mergeable":false,"conflict":"MERGE_CONFLICT_STATE_CLEAN","blockers":["base-branch-merged"],"prefix":["4","7"]}
```

### A draft and a conflicting pull request

A draft reports its conflict check as pending, which is not a clean answer:

```
$ fm-pr-merge.sh task-live https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/5 --allow-no-pipeline
armed: state/task-live.check.sh
error: refusing to merge https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/5
  - status is "draft", not open
  - the pull request is a draft
  - mergeable is "false", not true (blockers: change-is-draft)
  - mergeConflictState is MERGE_CONFLICT_STATE_PENDING: Origin is still checking for conflicts, which is not a clean answer
exit=1

$ fm-pr-merge.sh task-live https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/6 --allow-no-pipeline
armed: state/task-live.check.sh
error: refusing to merge https://cursor.com/codebase/aaalexliu/fm-origin-sandbox/pull/6
  - mergeable is "false", not true (blockers: stack-conflicts-with-root-base)
  - hasMergeConflicts is "true", not false
  - mergeConflictState is "MERGE_CONFLICT_STATE_CONFLICTS", not MERGE_CONFLICT_STATE_CLEAN
exit=1
```

### Real checks, read only

The draft pull request in `aaalexliu/genesis` has two completed Vercel check runs, each `"status":"completed","conclusion":"success"` with `headSha` equal to the pull request head, and they passed the check reading; only its draft state and pending conflict check refused.
`origin` was wrapped so that only `pr view`, `pr checks`, `pr list`, and `repo view` could reach it:

```
$ fm-pr-merge.sh task-live https://cursor.com/codebase/aaalexliu/genesis/pull/1
armed: state/task-live.check.sh
error: refusing to merge https://cursor.com/codebase/aaalexliu/genesis/pull/1
  - status is "draft", not open
  - the pull request is a draft
  - mergeable is "false", not true (blockers: change-is-draft)
  - mergeConflictState is MERGE_CONFLICT_STATE_PENDING: Origin is still checking for conflicts, which is not a clean answer
exit=1
```

## Not verified here

- A no-mistakes run pushing to an `origin.cursor.com` remote with `--skip pr,ci`; the generated brief relies on the pipeline's push step reaching Origin like any Git remote.
- A pending or failing check: a user principal cannot post one (the 403 above), and `origin pr gate` "is not enabled for your account yet", so the merge path's refusal of queued, running, and failing check runs and the `--allow-red` waiver rest on the CLI's own enums and passing set quoted above.
- A merge command that succeeds without a provable landing, and `origin pr merge` refusing a method the repository disallows.
- On the verification machine, Apple Git 2.54 (`/usr/bin/git`) hung on every fetch from `origin.cursor.com` with the per-clone helper set, while Homebrew Git 2.33 fetched normally; the watch end-to-end run used Homebrew Git.
