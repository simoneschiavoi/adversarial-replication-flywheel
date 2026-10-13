#!/bin/bash
# g4sup5: relaunch after SECOND OS reboot 2026-10-07 03:59 killed g4sup4 mid
# r10-control collect. r10 control REGISTERED-unrecorded -> legal re-run;
# run_batch adopts all earlier r10cval/r10ctrain jobs by exact name (120-min
# window) so the re-run collects instead of resubmitting. Then canary 10.
R=~/Desktop/bluequbit-grant-call/prototype
cd "$R" || exit 1
S="$R/runs/g4_supervisor.status"
L="$R/runs/g4_console.log"
run() {
  echo "[g4sup5] $1 $(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$S"
  "$R/.venv/bin/python" -u src/harness.py $2 >> "$L" 2>&1 \
    || { echo "[g4sup5] $1 FAILED $(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$S"; exit 1; }
}
run "round 10 control re-run (adopts r10c)" "round --k 10 --control"
run "canary 10" "canary --k 10"
echo "[g4sup5] ALL ROUNDS COMPLETE $(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$S"
