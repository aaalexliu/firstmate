#!/usr/bin/env bash
set -eu
unset FM_ROOT_OVERRIDE FM_STATE_OVERRIDE FM_DATA_OVERRIDE FM_CONFIG_OVERRIDE FM_PROJECTS_OVERRIDE FM_SUPERVISION_ACTOR
export FM_HOME="$PWD/.live-validation/return-home"
bin/fm-lab-home.sh create "$FM_HOME"
touch "$FM_HOME/config/supervision-host-off"
printf '[backends.tasks-toml]\nfile = "%s/tasks.toml"\n' "$FM_HOME" > "$FM_HOME/.tasks.toml"
# Real tasks-axi configuration uses its supported simple format, copied from the tracked default.
cp .tasks.toml "$FM_HOME/.tasks.toml"
bin/fm-branch-outcome.sh append --task previous --verdict routine --summary 'per your standing authority: PREVIOUS_WINDOW'
sleep 2
bin/fm-afk-contract.sh enter
entered=$(bin/fm-afk-contract.sh field entered_epoch)
printf '%s\n' "$entered" > "$FM_HOME/state/.afk"
bin/fm-branch-outcome.sh append --task review --verdict routine --summary 'per your standing authority: ask-user-authority permits restoring accepted CSV export; authorized the in-scope correction.'
bin/fm-branch-outcome.sh append --task mixed --verdict routine --summary 'per your standing authority: task yolo=on permits landing; per your away instructions: keep the schema unchanged; approved local export fix only.'
bin/fm-branch-outcome.sh append --task money --verdict captain --summary 'per your standing authority: financial acceptance needs the captain; declined purchase and held for return.'
bin/fm-branch-outcome.sh append --task silent --verdict routine --silent true --summary 'per your standing authority: SILENT_NO_CHANGE'
bin/fm-branch-outcome.sh append --task near --verdict routine --summary 'per your standing authority without a colon is not the decision marker.'
touch "$FM_HOME/state/.last-watcher-beat"
bin/fm-afk-return.sh begin
