# OCT-11 RUNBOOK — canonical campaign re-run on the PERSONAL account

The TEST-account campaign (this repo) is the dress rehearsal. On 2026-10-11
the SAME harness re-runs the canonical campaign on the personal account and
the results become the grant PDF's evidence appendix. Budget: **$8 personal
reserve** (TEST spend stays ≤ $2; it is at $0.00 — all cpu-class devices).

## 0. Non-negotiables (unchanged from the TEST run)

- Ledger first: every job runs under a REGISTERED experiment; PROMOTE only
  via `tools/ledger.py`. Never hand-edit metrics.json after `record`.
- Holdout evaluated exactly ONCE (src/holdout_eval.py writes the sentinel).
- Zero promotions is a valid outcome. Never fabricate; every number -> job ID.
- ≤ 2 concurrent jobs; mps.cpu+pauli-path ≤ 1K jobs/day; 15-min cap, design
  envelope ≤ 5 min/job.
- NO GPU/QPU devices unless a documented decision says otherwise (they burn
  the $25-class credits).

## 1. Environment

```bash
cd ~/Desktop/bluequbit-grant-call
# .env: BLUEQUBIT_API_KEY_ACCOUNT_TEST (default) and
#       BLUEQUBIT_API_KEY_ACCOUNT_PROD  (personal; legacy name
#       BLUEQUBIT_API_KEY_PERSONAL also accepted)
# src/bq.py selects by explicit switch and is FAIL-CLOSED: a missing
# selected key aborts the process (it never falls back to another key).
export BQ_ACCOUNT=personal
# NO-API-CALL key check (prints names/last-4 only, never values):
prototype/.venv/bin/python -c "import sys; sys.path.insert(0,'prototype/src'); import bq; print(bq.account_label())"
# expect: account=personal key=…REDACTED   — anything else = STOP
```

**Venv note (2026-10-07)**: `.venv` runs on **uv-managed CPython 3.12.12**
(`~/.local/share/uv/...`), NOT system python — an OS unattended-upgrade
deleted `/usr/bin/python3.12` mid-campaign (system is 3.14 now) and the uv
interpreter survived it. If `.venv/bin/python` ever exits 127:

```bash
uv venv --python 3.12 .venv-new    # downloads managed 3.12, immune to apt
uv pip install --python .venv-new/bin/python bluequbit==0.18.12b1 \
    matplotlib==3.11.2 numpy==2.5.3 qiskit==2.5.2 scipy==1.18.1 requests==2.34.2
mv .venv .venv-old && mv .venv-new .venv   # atomic swap; running jobs unaffected
```

## 2. Re-probe the three platform findings (cheap, ~15 min, all $0)

These were true on the TEST account on 2026-10-06; verify before designing:

1. **Peaked endpoint** — `GET /api/v1/peaked-circuits/file` returned 403 for
   every difficulty on TEST (EXP-002 parked, cause EXTERNAL_ENDPOINT_DENIED).
   Re-probe on personal: if it works, Lane P (36 sponsor peaked circuits,
   PPL scoring) becomes available again and the ORIGINAL EXP-003 design
   (36P+12R) can be restored — but only BEFORE freeze; never mid-campaign.
2. **mps.cpu count-key order** — keys are bit-REVERSED vs cpu/qiskit display
   order. `metrics.canonical_counts()` fixes it. Sanity-check once per
   account/SDK version: same job scored raw vs reversed must differ hugely
   (~0 vs ~1 for a near-exact sampler). Evidence job (TEST):
   see runs/20261006T025115Z_g1 amendments (rcs_n20_d4_s20263010:
   same-order -0.0329, reversed +1.0248).
3. **pauli-path on random RCS is degenerate** — ε ≤ 1e-5 rejected server-side
   ("truncation threshold too small / memory overflow"); ε ≥ 1e-4 RUNS but
   returns EV exactly 0.0 (empty retained path set) even at 20q weight-10
   with 280 s of real compute (TEST job tjiUQT7ynMGEAdix, exact = -0.001112).
   Do NOT spend personal budget re-litigating this; cite the TEST evidence.

## 3. Canonical campaign (identical code, identical suite)

```bash
cd prototype
.venv/bin/python -u src/validate_core.py          # must print ALL PASS
.venv/bin/python -u src/freeze_suite.py           # G2: re-freeze (same seeds → same suite, §4)
.venv/bin/python -u src/freeze_suite.py --check   # sha + holdout lock
.venv/bin/python tools/ledger.py register EXP-003-G2-FREEZE experiments/EXP-003-G2-FREEZE/SPEC.md --gate jobs_max=1 --gate usd_max=0
.venv/bin/python tools/ledger.py record  EXP-003-G2-FREEZE runs/<stamp>_g2
.venv/bin/python -u src/harness.py baseline       # G3 (~84 mps jobs, $0)
.venv/bin/python -u src/harness.py round --k 1    # G4 flywheel r1..r10
.venv/bin/python -u src/harness.py canary --k 6   # and --k 10
.venv/bin/python -u src/harness.py round --k 1 --control   # control r1..r10
# repeat round --k 2..10 for each arm (or use runs/g4sup*.sh supervisor
# scripts); canaries AFTER rounds 6 and 10
.venv/bin/python - <<'EOF'
import json
s = json.load(open("runs/flywheel/state.json"))
fly = sum(1 for h in s.get("history", []) if h.get("arm") == "flywheel")
ctl = sum(1 for h in s.get("history", []) if h.get("arm") == "control")
ks = sorted(c.get("round_k") for c in s.get("canaries", []))
ok = fly >= 10 and ctl >= 10 and 6 in ks and 10 in ks
print(f"flywheel={fly} control={ctl} canaries={ks}")
print("INCOMPLETE — holdout locked" if not ok else "COMPLETE — holdout may run ONCE")
EOF
.venv/bin/python -u src/holdout_eval.py           # G6 ONCE (sentinel!)
.venv/bin/python -u src/report.py                 # G7 + claims.json
.venv/bin/python tools/rsi.py verify              # researcher-integrity store
```

Interleave the arms (fly r1, ctl r1, fly r2, …) or run blocks — the ledger
does not care; the control ladder index is independent of flywheel rounds.

**Run the long blocks detached, not in a foreground chat poll.** The TEST
machine rebooted twice mid-campaign (unattended-upgrades); anything tied to
a foreground process died with it. Pattern that survived both reboots
(templates: `runs/g4sup4.sh`, `runs/g4sup5.sh`):

```bash
nohup bash runs/g4sup5.sh >/dev/null 2>&1 & disown
tail -f runs/g4_supervisor.status   # one line per phase; FAILED = stop
```

Two properties make recovery near-free:
- **Job adoption**: before submitting a spec, the harness searches recent
  jobs by exact name and ADOPTS completed/running ones — a killed round
  re-runs in ~1 min at near-zero new-job cost.
- **Registered-but-unrecorded re-runs are legal** (L-004 only protects
  RECORDED rounds): a crash between register and record just re-runs.

## 4. Oct-11 run = REPLICATION mode (identical seeds)

Per the 2026-10-07 review: Oct 11 is NOT a fresh-seed run. The SAME seeds
regenerate the SAME suite, so any TEST→personal difference is platform
(account, pricing, queue), never design. Work this checklist top to bottom;
items 2–4 gate dispatch.

- [ ] **1. Tree prep — fresh copy, sealed original.** Copy the prototype
  tree into a NEW location, EXCLUDING `suite/`, `runs/`,
  `ledger/jobs.sqlite`, `ledger/experiments.json`,
  `researcher/PREDICTIONS.jsonl`, `researcher/rsi.json` and
  `researcher/INSIGHTS.md` — everything in them regenerates:
  ```bash
  rsync -a --exclude suite/ --exclude runs/ \
        --exclude ledger/jobs.sqlite --exclude ledger/experiments.json \
        --exclude researcher/PREDICTIONS.jsonl \
        --exclude researcher/rsi.json --exclude researcher/INSIGHTS.md \
        --exclude experiments/EXP-008-GATE-CALIBRATION/data/ \
        ~/Desktop/bluequbit-grant-call/prototype/ \
        ~/Desktop/bluequbit-grant-call/prototype-oct11/
  # EXP-008's 4.2 GB of raw payloads are sealed TEST artifacts and stay in
  # the ORIGINAL tree; the fresh appendix needs ONLY its analysis JSON,
  # copied back in (dry-run-verified 2026-10-09: 16,626 files / ~675 MB copy):
  mkdir -p ~/Desktop/bluequbit-grant-call/prototype-oct11/experiments/EXP-008-GATE-CALIBRATION/data
  cp ~/Desktop/bluequbit-grant-call/prototype/experiments/EXP-008-GATE-CALIBRATION/data/analysis.json \
     ~/Desktop/bluequbit-grant-call/prototype-oct11/experiments/EXP-008-GATE-CALIBRATION/data/
  ```
  The exclusions are load-bearing: freeze_suite REFUSES to run if
  `suite/MANIFEST.json` exists (src/freeze_suite.py:70-73); the G3 baseline
  refuses if `runs/flywheel/state.json` carries an incumbent (L-004);
  rsi.py predict refuses a duplicate campaign row (tools/rsi.py:290-292);
  the virgin ledger re-registers EXP-003/004/… from scratch. The
  destination is a SIBLING of `prototype/` (src/bq.py resolves
  `ROOT.parent/.env` = the project `.env`; a copy under `~` would break
  that), and `researcher/rsi.json`/`INSIGHTS.md` are generated views with
  TEST-run memory — excluded so they REGENERATE in the fresh tree instead
  of leaking learned history into the replication. The ORIGINAL
  tree stays byte-untouched: it is the sealed TEST record (suite sha
  `bee1e97245f2cabf…`, $0.00, 905 jobs) and the fallback appendix (item 8).
- [ ] **2. Identical suite, verified — ABORT on any mismatch.** Seeds are
  hardcoded constants, not flags: `R_BASE_SEED = 20261100`
  (src/freeze_suite.py:47), per-circuit seed `R_BASE_SEED + n*100 + d*10 + s`
  (line 86), 24/12/12 split via `SPLIT_SEED = 20261107` numpy default_rng
  permutation (lines 46, 107-112). Running the SAME freeze_suite.py in the
  fresh tree (same .venv → deterministic .qpy + truth bytes) must reproduce
  the TEST suite exactly. Where the sha comes from:
  `body["suite_sha256"] = canonical_sha(body)` (src/freeze_suite.py:162);
  canonical_sha (lines 58-63) hashes EVERY manifest field except
  `suite_sha256` — INCLUDING `frozen_at` (line 142, wall-clock at freeze).
  Therefore:
  - The fresh manifest's own `suite_sha256` will NOT print
    `bee1e97245f2cabfe34d3dab5c9aa19e64135db8d30a2ff3d4c7c03ef1fb36f7` —
    that value embeds the TEST freeze timestamp and can never recur; it
    stays the sealed TEST record. A different `suite_sha256` alone is NOT
    a failure.
  - The replication gate is the seed-dependent content: strip `frozen_at`
    and `suite_sha256` from BOTH manifests — they MUST be equal (content
    sha `c2856e7374a1a0e9cd12a3683b524ebac0b563bd62b7b40082cf14780062422b`
    on both sides; equivalently the 48-entry `circuits[]` — id, seed, qpy
    sha256, truth_sha256, split — plus `counts` byte-identical). Run from
    the FRESH tree:
    ```bash
    .venv/bin/python - <<'EOF'
    import json, hashlib, os, sys
    strip = lambda p: {k: v for k, v in json.loads(
        open(os.path.expanduser(p)).read()).items()
        if k not in ("suite_sha256", "frozen_at")}
    blob = lambda d: hashlib.sha256(json.dumps(
        d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    fresh  = strip("suite/MANIFEST.json")   # cwd = fresh prototype copy
    sealed = strip("~/Desktop/bluequbit-grant-call/prototype/suite/MANIFEST.json")
    print("fresh  sha:", blob(fresh))
    print("sealed sha:", blob(sealed))
    print("REPLICATION OK" if fresh == sealed else "FAIL: suites differ")
    sys.exit(0 if fresh == sealed else 1)
    EOF
    ```
  - ABORT if it differs (nondeterministic generation — e.g. library drift
    changing qpy/truth bytes — or an edited freeze_suite.py): investigate
    BEFORE spending a cent. Record the fresh `suite_sha256`: the appendix
    FACTS block (§5) must cite it for the personal run.
- [ ] **3. Prediction freeze BEFORE round-1 dispatch.** Same procedure as
  TEST, now stricter: the row lands in `researcher/PREDICTIONS.jsonl`
  BEFORE round 1 of EITHER arm is dispatched. The exact call is emitted by
  cmd_baseline at src/harness.py:447-454:
  ```bash
  .venv/bin/python tools/rsi.py predict \
    --campaign flywheel-test \
    --metric final_incumbent_holdout_mean_xeb \
    --point <point:.6f> --band <base:.6f>,<max(point,0.999):.6f>
  # from the NEW G3: base = mean val XEB of baseline run 1;
  #                  point = base + 0.5*(1 - base)
  # TEST reference: base 0.953184 -> point 0.976592, band [0.953184, 0.999]
  ```
  On TEST this call crashed inside cmd_baseline (rsi.py str-vs-float, fixed
  2026-10-06: cmd_predict now parses --point to float, tools/rsi.py:294)
  and the row was frozen manually at 07:01:55Z — 3.5 min after flywheel
  round-1 dispatch BEGAN (06:58:32Z; two r1 results had already been
  collected at 07:00:17Z), before the control's round-1 dispatch
  (07:53:21Z) and before any round-level gate decision (first PROMOTE
  08:52:13Z). With the fix, cmd_baseline freezes it
  automatically at G3 close; VERIFY the row exists (campaign flywheel-test,
  actual null) before dispatching any round; if the auto-freeze failed, run
  the command above manually. Expected mid-flow: `tools/rsi.py verify`
  FAILS with "PREDICTIONS.jsonl missing" until this row lands.
- [ ] **4. Account/key + credits.** Personal account created 2026-10-07;
  its key lives in `../.env` as `BLUEQUBIT_API_KEY_ACCOUNT_PROD` (verified
  .env names: only *_ACCOUNT_TEST and *_ACCOUNT_PROD are present). Run with
  `export BQ_ACCOUNT=personal`: src/bq.py load_env() resolves personal to
  `BLUEQUBIT_API_KEY_PERSONAL` (legacy) OR `BLUEQUBIT_API_KEY_ACCOUNT_PROD`,
  TEST to `BLUEQUBIT_API_KEY_ACCOUNT_TEST`; a missing selected key aborts
  (fail-closed), and an in-process BQ_ACCOUNT switch re-resolves.
  End-to-end already smoke-tested = EXP-009 (experiments/EXP-009-PROD-KEY-SMOKE,
  runs/20261007T103821Z_g9prod, 2026-10-07): 4q GHZ on cpu, job
  YW9stZy29kWIPOaW COMPLETED, $0.00, announce `account=personal key=…REDACTED`.
  Fresh-tree smoke (virgin ledger there): register then run —
  `.venv/bin/python tools/ledger.py register EXP-009-PROD-KEY-SMOKE experiments/EXP-009-PROD-KEY-SMOKE/SPEC.md --gate jobs_max=5 --gate usd_max=0`
  then `BQ_ACCOUNT=personal .venv/bin/python -u src/g9_prod_smoke.py`
  (4q GHZ on cpu, billed $0.00; prints the [bq] announce — verify
  account=personal).
  Promo code WKWOSNLDVC: the user MUST confirm the credits are VISIBLE in
  the personal dashboard BEFORE dispatch — no visible credits, no run.
- [ ] **5. Budget — three layers.** (a) $8 hard ceiling TOTAL (human rule);
  (b) the ledger's own `usd_budget_total = 2.0` (enforced per UTC day —
  budget_epoch rows — NOT cumulative across days; the human $8 ceiling
  spans the whole run and is checked by eye against the dashboard)
  (tools/bq_jobs.py:39, enforced at every reserve, :147-149) — binds FIRST
  if mps.cpu prices above $0; (c) per-experiment gates `usd_max=0.50` (e.g.
  EXP-004, src/harness.py:382). Gates binding early on the personal account is the
  budget working as designed, not a failure. Live usage:
  `sqlite3 ledger/jobs.sqlite "SELECT day, mps_jobs_used, cpu_jobs_used, round(usd_used+usd_reserved,2) FROM budget_epoch ORDER BY day;"`
- [ ] **6. Daily caps.** ≤ 900 mps+pauli-path jobs/day — hardcoded in the
  reservation path (tools/bq_jobs.py:37, enforced :135-141: a batch that
  would cross it FAILs BEFORE dispatch). Full replication ≈ 850-905 jobs
  (TEST total: 905 over two days) → run the sqlite line in item 5 before
  each phase; spilling into the next UTC day is fine (TEST did).
- [ ] **7. Wall time.** 26-49 s/job seen on TEST mps.cpu; the 5-min design
  envelope keeps ~3x headroom. If the MEDIAN val job exceeds 5 min, or ANY
  job exceeds 10 min (⅔ of the hard 15-min cap): STOP and re-check device
  caps (a personal-account limit change is the likely cause) before
  dispatching more. (TEST saw occasional 5.5–5.6 min singles in r8 —
  within cap, not a stop condition.)
- [ ] **8. ABORT RULE — the deadline wins.** If the campaign is not FULLY
  closed by **Oct 12 18:00 local time**, OR spend exceeds $8 → STOP and
  ship the already-gated TEST-account appendix
  (grant/evidence-appendix.pdf, visual-judge 4/4 PASS) with a one-line
  note in the form answers. Replication must never jeopardize the Oct-14
  submission.

Carried over from the TEST plan (still true): the tombstone chmod fix in
`src/holdout_eval.py` (the .EVALUATED sentinel needs a dir write bit) and
all report.py plot fixes already travel in src/ — no manual steps on
Oct 11. Expected result shape, replication reading: a faithful rerun
should land near the TEST shape (~1 control promotion via the χ split,
flywheel plateau near baseline); the interesting readings are (a) whether
the χ-dependent permutation damage replicates, (b) whether memory (χ
allocation) pays off where it didn't on TEST, (c) the prediction-band
verdict (TEST: MISS via a ~0.026 val→holdout gap). Divergence from TEST is
itself a finding — do not tune toward any outcome; report what happens.

## 5. Deliverable

`src/report.py` output (runs/report/) + claims.json + jobs export → the
4-page PDF evidence appendix: **`grant/make_appendix.py` is data-driven**
— it renders every numeric surface from `runs/report/rounds.json` and
`runs/report/summary.json` (both emitted by report.py; no number is
transcribed by hand). After the fresh run: adapt the blocks marked
`# PROSE` (outcome interpretation) and `# FACTS TO ADAPT ON A FRESH RUN`
(account name, campaign-close date, "$0.00" — verify on the billing
dashboard), then rebuild with the linuxbrew interpreter — reportlab/pypdf/PIL
are NOT in .venv: `cd prototype-oct11 && /home/linuxbrew/.linuxbrew/bin/python3 grant/make_appendix.py`.
Post-build pipeline: re-apply Producer metadata
'http://z.ai' (pypdf, see end of make_appendix.py), run pdf_qa.py,
render pages (pdftoppm -r 150), and pass the **documents:visual-judge
gate** (one verdict per page; fix + re-render on any fail). Grant form
answers live in the parent folder's grant notes (already drafted);
submit NOTHING automatically — the user submits by hand before 2026-10-14.
