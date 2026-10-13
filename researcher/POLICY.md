# POLICY.md — R-rules for the prototype loop

Ratified at boot (2026-10-06). Changes require a dated judgment record in
`DIRECTION.md` and a PC node in `rsi.json` derived from at least one INS.

- **R-01** One mutation per flywheel round. The round's SPEC declares the
  mutation and its numeric gate before dispatch.
- **R-02** Acceptance = paired val improvement with 95% CI excluding zero
  beyond the preregistered min-Δ, AND cost noninferior within 2% (law L-005
  defines cost).
- **R-03** No LLM-judged scores. Every metric is computed from job outputs by
  deterministic code, and every number traces to a job ID.
- **R-04** No retroactive edits to specs, preregistrations, runs, or laws.
  Supersession is append-only with evidence.
- **R-05** The improver sees train/val only. Any process that touches
  `suite/holdout/` before campaign close voids the campaign (law L-003).
- **R-06** Equal-budget controls: the no-memory arm gets the same job and shot
  budget as the flywheel arm. Comparisons are descriptive in the prototype.
- **R-07** Infra failures get one reconciliation attempt via job search, then a
  cause-classed re-reservation. Healthy reruns are refused (law L-004).
- **R-08** Daily mps+pps job budget 900 (account 1000); ≤2 concurrent; spend
  cap $2 test / $8 personal; GPU/QPU never on the test account.
- **R-09** Honest plateau: if zero promotions occur, the report ships the
  plateau with the fixed-budget Pareto frontier — that is a designed outcome.
