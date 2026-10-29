# Cursor Origin pull request watch verification

Empirical record for the watch-only Cursor Origin support: registering an Origin pull request, watching it until a person merges it in Origin, and proving the work landed at cleanup.
Firstmate does not merge an Origin pull request yet; `bin/fm-pr-merge.sh` refuses one.
A project opts in with the `forge=origin` registry binding, which `bin/fm-project-mode.sh` owns; the watch and cleanup paths key off the pull request URL itself, and the binding decides only what a generated ship brief tells the worker (`bin/fm-dod-lib.sh`).
All evidence below was collected on 2026-10-29 against the live Origin service, reading `aaalexliu/genesis` and writing only to the throwaway repository `aaalexliu/fm-origin-sandbox`.

## Versions

```
$ origin --version
2026.10.23-18-47-36-f52be1e

$ jq --version
jq-1.8.1

$ git --version
git version 2.33.1
```

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

## Not verified here

- A no-mistakes run pushing to an `origin.cursor.com` remote with `--skip pr,ci`; the generated brief relies on the pipeline's push step reaching Origin like any Git remote.
- `origin pr checks` while a check is still running; the feature request (kunchenguid/firstmate#7971) reports exit 8, which no brief or script depends on.
- On the verification machine, Apple Git 2.54 (`/usr/bin/git`) hung on every fetch from `origin.cursor.com` with the per-clone helper set, while Homebrew Git 2.33 fetched normally; the end-to-end run above used Homebrew Git.
