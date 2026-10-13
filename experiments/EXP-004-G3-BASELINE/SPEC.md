# EXP-004 — G3 baseline incumbent

Incumbent (uniform-allocation config) on the frozen 48-circuit suite:
mps.cpu, chi=64 everywhere, 20k shots everywhere, identity site order.

Runs: val x2 (the second identical pass calibrates pure run-to-run noise),
train x1, plus a chi telemetry sweep on the val circuits at chi in
{32, 128, 256} (report evidence for the chi-vs-XEB gradient; chi=64 comes
from val run 1). NO acceptance decision here — this IS the incumbent.

min_delta formula (frozen): max(2.0 * sd(paired per-circuit XEB deltas between
the two identical val runs), 0.005).

Gates: caps only (jobs_max=90, usd_max=0.50; all cpu-class devices are $0).
