#!/usr/bin/env bash
# Drive the real fm-procevent.sh reconcile + fm-wake-drain.sh against a disposable lab home.
# usage: drive-procevent.sh <bin-dir> <label>
set -u
BIN=$1; LABEL=$2; WT=$(pwd)
LAB=$(mktemp -d "${TMPDIR:-/tmp}/fm-lab.XXXXXX")
"$WT/bin/fm-lab-home.sh" create "$LAB" >/dev/null
export FM_HOME="$LAB" FM_PROCEVENT_CLAIM_ROOT="$LAB/claims"
unset FM_ROOT_OVERRIDE FM_STATE_OVERRIDE FM_DATA_OVERRIDE FM_CONFIG_OVERRIDE FM_PROJECTS_OVERRIDE
Q="$LAB/state/.wake-queue"; M="$LAB/state/.watcher-down"
mkdir -p "$LAB/state/procevent-inbox"
printf 'daily review-pilot report\n' > "$LAB/state/procevent-inbox/review-pilot.1.result"
printf 'lavish\n' > "$LAB/state/procevent-inbox/review-pilot.1.adapter"
chmod 0600 "$LAB/state/procevent-inbox/"review-pilot.1.*
rows() { awk -F'\t' 'NF>=5' "$Q" 2>/dev/null | wc -l | tr -d ' '; }
echo "=== [$LABEL] S1: result captured; first watcher reconcile"
"$BIN/fm-procevent.sh" reconcile; echo "queue rows=$(rows)"; cut -f2- "$Q"
echo "=== [$LABEL] firstmate drains (begins handling, no ack yet)"
"$BIN/fm-wake-drain.sh" >/dev/null 2>&1; echo "drain exit=$?"
echo "recovery marker: $(cat "$M" 2>/dev/null)"
echo "=== [$LABEL] S2: watcher polls reconcile 5x while firstmate still handling"
for i in 1 2 3 4 5; do "$BIN/fm-procevent.sh" reconcile; echo "  poll $i: rows=$(rows) marker=$(cat "$M" 2>/dev/null)"; done
cut -f2- "$Q"
echo "=== [$LABEL] S3: firstmate acknowledges queued row (not yet handled); next reconcile"
seq=$(awk -F'\t' 'NF>=5{s=$2} END{print s}' "$Q"); gen=$(cat "$M" | awk -F: '{print $3}')
"$BIN/fm-wake-drain.sh" --ack-through "$seq" --recovery-generation "$gen" >/dev/null 2>&1; echo "ack exit=$? rows after ack=$(rows)"
"$BIN/fm-procevent.sh" reconcile; echo "rows after reconcile=$(rows)"; cut -f2- "$Q"
echo "=== [$LABEL] S4: a different unhandled result (seq 2) arrives while seq 1 row is queued"
printf 'second report\n' > "$LAB/state/procevent-inbox/review-pilot.2.result"
printf 'lavish\n' > "$LAB/state/procevent-inbox/review-pilot.2.adapter"
chmod 0600 "$LAB/state/procevent-inbox/"review-pilot.2.*
"$BIN/fm-procevent.sh" reconcile; "$BIN/fm-procevent.sh" reconcile; echo "rows=$(rows)"; cut -f2- "$Q"
echo "=== [$LABEL] S5: mark both handled, drain-ack, reconcile publishes nothing"
"$BIN/fm-procevent.sh" handled review-pilot 1; "$BIN/fm-procevent.sh" handled review-pilot 2
seq=$(awk -F'\t' 'NF>=5{s=$2} END{print s}' "$Q"); "$BIN/fm-wake-drain.sh" >/dev/null 2>&1; gen=$(cat "$M" | awk -F: '{print $3}')
"$BIN/fm-wake-drain.sh" --ack-through "$seq" --recovery-generation "$gen" >/dev/null 2>&1; echo "rows after ack=$(rows)"
"$BIN/fm-procevent.sh" reconcile; "$BIN/fm-procevent.sh" reconcile; echo "rows after 2 reconciles=$(rows)"
rm -rf "$LAB"
