#!/usr/bin/env bash
set -eu
ROOT=$PWD
E=~/.no-mistakes/evidence/01M6T2JMPDD9H6PNZATQV84A36
unset FM_ROOT_OVERRIDE FM_STATE_OVERRIDE FM_DATA_OVERRIDE FM_CONFIG_OVERRIDE FM_PROJECTS_OVERRIDE FM_SUPERVISION_ACTOR
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
HOME_LAB="$ROOT/.live-validation/home"
export FM_HOME="$HOME_LAB"
P="$ROOT/.live-validation/project"
W="$ROOT/.live-validation/worker"
git init -q -b main "$P"
git -C "$P" config user.name 'Lab'
git -C "$P" config user.email 'lab@example.invalid'
git -C "$P" commit -q --allow-empty -m base
BASE=$(git -C "$P" rev-parse HEAD)
git -C "$P" worktree add -q -b fm/lab "$W"
printf 'approved change\n' > "$W/change.txt"
git -C "$W" add change.txt
git -C "$W" commit -q -m approved
X=$(git -C "$W" rev-parse HEAD)
printf 'kind=ship\nmode=local-only\nbranch=fm/lab\nproject=%s\nworktree=%s\nspawn_gen=lab-1\nyolo=on\n' "$P" "$W" > "$FM_HOME/state/task.meta"
. "$ROOT/bin/fm-dod-lib.sh"
fm_dod_accept_ship_done ship local-only "$W" "$P" 'done: approved' "$FM_HOME/state" task "$FM_HOME/state/task.meta"
refuse() {
  local rc=0
  echo "--- $1: branch requests local landing"
  FM_SUPERVISION_ACTOR=branch "$ROOT/bin/fm-merge-local.sh" task || rc=$?
  echo "exit=$rc default_head=$(git -C "$P" rev-parse HEAD)"
  test "$rc" -ne 0
  test "$(git -C "$P" rev-parse HEAD)" = "$BASE"
  test ! -e "$P/change.txt"
}
refuse attended
"$ROOT/bin/fm-afk-contract.sh" enter
"$ROOT/bin/fm-afk-contract.sh" readback
# A later unapproved commit must not inherit approval.
git -C "$W" commit -q --allow-empty -m unapproved
refuse away-unapproved-head
git -C "$W" reset -q --hard "$X"
echo '--- away: land the approved local head'
FM_SUPERVISION_ACTOR=branch "$ROOT/bin/fm-merge-local.sh" task
echo "approved_head=$X default_head=$(git -C "$P" rev-parse HEAD) file=$(<"$P/change.txt")"
test "$(git -C "$P" rev-parse HEAD)" = "$X"
test -z "$(git -C "$P" status --porcelain)"
# Reset disposable project only to make subsequent refusal observable.
git -C "$P" reset -q --hard "$BASE"
"$ROOT/bin/fm-afk-contract.sh" archive
refuse archived
printf 'version: 99\n' > "$FM_HOME/state/.afk-contract"
refuse invalid-record
echo '--- attended MAIN: invalid away record must not remove existing landing authority'
FM_SUPERVISION_ACTOR=main "$ROOT/bin/fm-merge-local.sh" task
test "$(git -C "$P" rev-parse HEAD)" = "$X"
echo "main_head=$(git -C "$P" rev-parse HEAD)"
