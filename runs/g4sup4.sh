#!/bin/bash
# g4sup4: relaunch after OS reboot killed g4sup3 mid r7-control (2026-10-06 20:59).
# r7 control is REGISTERED-unrecorded (EXP-006-R07, attempts=[]) -> legal re-run;
# run_batch ADOPTS the 10 earlier r7cval jobs by exact name (120-min window).
R=~/Desktop/bluequbit-grant-call/prototype
cd "$R" || exit 1
S="$R/runs/g4_supervisor.status"
L="$R/runs/g4_console.log"
run() {
  echo "[g4sup4] $1 $(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$S"
  "$R/.venv/bin/python" -u src/harness.py $2 >> "$L" 2>&1 \
    || { echo "[g4sup4] $1 FAILED $(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$S"; exit 1; }
}
run "round 7 control re-run (adopts r7cval)" "round --k 7 --control"
run "round 8 flywheel" "round --k 8"
run "round 8 control" "round --k 8 --control"
run "round 9 flywheel" "round --k 9"
run "round 9 control" "round --k 9 --control"
run "round 10 flywheel" "round --k 10"
run "round 10 control" "round --k 10 --control"
run "canary 10" "canary --k 10"
echo "[g4sup4] ALL ROUNDS COMPLETE $(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$S"
