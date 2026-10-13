#!/usr/bin/env python3
"""L2 meta-layer for the Adversarial Replication Flywheel prototype.

Port of the JS-ASIC / ARC-AGI-3 researcher layer, minimal. Python stdlib only.

Node model (researcher/rsi.json):
  INS  insight      {id, statement, falsifier, status ACTIVE|SUPERSEDED|KILLED}
                   falsifier is MANDATORY — an insight without one is refused.
  PC   policy_change {id, rules, derived_from: [INS-ids], status}
                   REFUSES: self-references, refs to non-existent INS,
                   refs to non-INS nodes (fixed JS-ASIC gap).
  EV   evaluation   {id, pc, criteria FROZEN at adoption, status PENDING|PASS|FAIL}

Rules:
  * ACTIVE cap 8: adding a 9th ACTIVE insight is refused until one is
    superseded or killed (catalog must shrink via supersession-by-enforcement).
  * rsi.py is the ONLY writer of generated views (INSIGHTS.md); render refuses
    if the file would stay stale; verify FAILS on missing or stale views.
  * No retroactive edits: nodes are append-only; status changes append a
    supersede/kill event with evidence.
  * PREDICTIONS.jsonl: one frozen row per campaign BEFORE it runs
    (point + band); scoring happens only after the campaign closes.

Commands:
  rsi.py verify                     # structure + refs + views + laws (boot gate)
  rsi.py render                     # regenerate INSIGHTS.md (single writer)
  rsi.py add-ins  --statement "..." --falsifier "..."
  rsi.py add-pc   --rules "..." --from INS-001,INS-002
  rsi.py add-ev   --pc PC-001 --criteria "<frozen criteria>"
  rsi.py ev       EV-001 PASS|FAIL --note "..."
  rsi.py kill     INS-001 --evidence "..."
  rsi.py predict  --campaign EXP-005 --metric val_ppl --point 0.12 --band 0.08,0.18
  rsi.py score    --campaign EXP-005 --actual 0.101
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RSI_DIR = ROOT / "researcher"
RSI_JSON = RSI_DIR / "rsi.json"
INSIGHTS_MD = RSI_DIR / "INSIGHTS.md"
PREDICTIONS = RSI_DIR / "PREDICTIONS.jsonl"
ACTIVE_CAP = 8


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load() -> dict:
    if not RSI_JSON.exists():
        raise SystemExit(f"FAIL: {RSI_JSON} missing")
    return json.loads(RSI_JSON.read_text())


def save(store: dict) -> None:
    tmp = RSI_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, indent=2) + "\n")
    tmp.replace(RSI_JSON)


def next_id(nodes: list[dict], prefix: str) -> str:
    nums = [int(n["id"].split("-")[1]) for n in nodes if n["id"].startswith(prefix + "-")]
    return f"{prefix}-{max(nums, default=0) + 1:03d}"


def render_insights(store: dict) -> str:
    lines = [
        "# INSIGHTS (generated view — single writer: tools/rsi.py)",
        "",
        f"_rendered {utcnow()} · ACTIVE cap {ACTIVE_CAP} · do not edit by hand_",
        "",
    ]
    active = [n for n in store["insights"] if n["status"] == "ACTIVE"]
    other = [n for n in store["insights"] if n["status"] != "ACTIVE"]
    lines.append(f"## ACTIVE ({len(active)}/{ACTIVE_CAP})")
    lines.append("")
    for n in active:
        lines.append(f"- **{n['id']}** — {n['statement']}")
        lines.append(f"  - falsifier: {n['falsifier']}")
        if n.get("derived_pcs"):
            lines.append(f"  - PCs: {', '.join(n['derived_pcs'])}")
    lines.append("")
    lines.append(f"## SUPERSEDED / KILLED ({len(other)})")
    lines.append("")
    for n in other:
        ev = f" — evidence: {n['kill_evidence']}" if n.get("kill_evidence") else ""
        sup = f" — superseded by {n['superseded_by']}" if n.get("superseded_by") else ""
        lines.append(f"- **{n['id']}** [{n['status']}]{ev}{sup}: {n['statement']}")
    lines += ["", "## POLICY CHANGES", ""]
    for pc in store["policy_changes"]:
        lines.append(
            f"- **{pc['id']}** (from {', '.join(pc['derived_from'])}): {pc['rules']}"
        )
    lines += ["", "## EVALUATIONS", ""]
    for ev in store["evaluations"]:
        lines.append(
            f"- **{ev['id']}** pc={ev['pc']} [{ev['status']}] criteria: {ev['criteria']}"
        )
    return "\n".join(lines) + "\n"


def check_structure(store: dict) -> list[str]:
    problems = []
    ins_ids = {n["id"] for n in store["insights"]}
    seen = set()
    for coll, kind in (("insights", "INS"), ("policy_changes", "PC"), ("evaluations", "EV")):
        for n in store.get(coll, []):
            if n["id"] in seen:
                problems.append(f"duplicate id {n['id']}")
            seen.add(n["id"])
            if not n["id"].startswith(kind + "-"):
                problems.append(f"{n['id']} in wrong collection {coll}")
    for n in store["insights"]:
        if not n.get("falsifier", "").strip():
            problems.append(f"{n['id']}: falsifier is mandatory")
    for pc in store["policy_changes"]:
        refs = pc.get("derived_from", [])
        if pc["id"] in refs:
            problems.append(f"{pc['id']}: PC self-reference refused")
        for r in refs:
            if r not in ins_ids:
                problems.append(f"{pc['id']}: derived_from {r} is not an existing INS")
    for ev in store["evaluations"]:
        if ev["pc"] not in {p["id"] for p in store["policy_changes"]}:
            problems.append(f"{ev['id']}: pc {ev['pc']} does not exist")
        if "criteria" not in ev or not str(ev["criteria"]).strip():
            problems.append(f"{ev['id']}: criteria must be frozen at adoption")
    active = [n for n in store["insights"] if n["status"] == "ACTIVE"]
    if len(active) > ACTIVE_CAP:
        problems.append(f"ACTIVE insights {len(active)} exceed cap {ACTIVE_CAP}")
    return problems


def cmd_verify(args) -> int:
    store = load()
    problems = check_structure(store)
    # generated-view freshness (fixed gap: missing views FAIL, not skip)
    if not INSIGHTS_MD.exists():
        problems.append(f"generated view missing: {INSIGHTS_MD.relative_to(ROOT)}")
    else:
        expected = render_insights(store)
        current = INSIGHTS_MD.read_text()
        # compare everything except the rendered timestamp line
        strip = lambda s: "\n".join(
            l for l in s.splitlines() if not l.startswith("_rendered"))
        if strip(expected) != strip(current):
            problems.append("INSIGHTS.md is stale (rerun `rsi.py render`)")
    if not PREDICTIONS.exists():
        problems.append("PREDICTIONS.jsonl missing")
    else:
        seen_campaigns = set()
        for line in PREDICTIONS.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("campaign") in seen_campaigns:
                problems.append(f"duplicate prediction row for {row.get('campaign')}")
            seen_campaigns.add(row.get("campaign"))
            if "point" not in row or "band" not in row or "frozen_at" not in row:
                problems.append(f"malformed prediction row: {row}")
    if problems:
        for p in problems:
            print(f"FAIL: {p}", file=sys.stderr)
        return 1
    print("OK rsi store verified (structure, refs, views, predictions)")
    return 0


def cmd_render(args) -> int:
    store = load()
    problems = check_structure(store)
    if problems:
        for p in problems:
            print(f"FAIL: {p}", file=sys.stderr)
        return 1
    INSIGHTS_MD.write_text(render_insights(store))
    print(f"OK rendered {INSIGHTS_MD.relative_to(ROOT)}")
    return 0


def cmd_add_ins(args) -> int:
    store = load()
    if not args.falsifier or not args.falsifier.strip():
        raise SystemExit("FAIL: --falsifier is mandatory for insights")
    active = [n for n in store["insights"] if n["status"] == "ACTIVE"]
    if len(active) >= ACTIVE_CAP:
        raise SystemExit(
            f"FAIL: ACTIVE cap {ACTIVE_CAP} reached — supersede or kill one first")
    node = {
        "id": next_id(store["insights"], "INS"),
        "statement": args.statement,
        "falsifier": args.falsifier,
        "status": "ACTIVE",
        "created": utcnow(),
        "derived_pcs": [],
        "events": [],
    }
    store["insights"].append(node)
    save(store)
    print(f"OK {node['id']} added (ACTIVE {len(active) + 1}/{ACTIVE_CAP})")
    return 0


def cmd_add_pc(args) -> int:
    store = load()
    refs = [r.strip() for r in args.src.split(",") if r.strip()]
    if not refs:
        raise SystemExit("FAIL: --from must list at least one INS id")
    ins_ids = {n["id"] for n in store["insights"]}
    for r in refs:
        if r not in ins_ids:
            raise SystemExit(f"FAIL: derived_from {r} is not an existing INS")
    node_id = next_id(store["policy_changes"], "PC")
    if node_id in refs:
        raise SystemExit("FAIL: PC self-reference refused")
    node = {
        "id": node_id,
        "rules": args.rules,
        "derived_from": refs,
        "status": "ADOPTED",
        "created": utcnow(),
    }
    store["policy_changes"].append(node)
    for n in store["insights"]:
        if n["id"] in refs:
            n["derived_pcs"].append(node_id)
    save(store)
    print(f"OK {node_id} adopted from {refs}")
    return 0


def cmd_add_ev(args) -> int:
    store = load()
    if args.pc not in {p["id"] for p in store["policy_changes"]}:
        raise SystemExit(f"FAIL: {args.pc} is not a PC id")
    node = {
        "id": next_id(store["evaluations"], "EV"),
        "pc": args.pc,
        "criteria": args.criteria,  # frozen at adoption
        "status": "PENDING",
        "created": utcnow(),
    }
    store["evaluations"].append(node)
    save(store)
    print(f"OK {node['id']} created (criteria frozen at adoption)")
    return 0


def cmd_ev(args) -> int:
    store = load()
    for ev in store["evaluations"]:
        if ev["id"] == args.ev_id:
            if ev["status"] != "PENDING":
                raise SystemExit(f"FAIL: {args.ev_id} already {ev['status']} (no retroactive edits)")
            if args.result not in ("PASS", "FAIL"):
                raise SystemExit("FAIL: result must be PASS|FAIL")
            ev["status"] = args.result
            ev["decided"] = utcnow()
            ev["note"] = args.note or ""
            save(store)
            print(f"OK {args.ev_id} -> {args.result}")
            return 0
    raise SystemExit(f"FAIL: {args.ev_id} not found")


def cmd_kill(args) -> int:
    store = load()
    for n in store["insights"]:
        if n["id"] == args.ins_id:
            n["status"] = "KILLED" if not args.superseded_by else "SUPERSEDED"
            if args.superseded_by:
                n["superseded_by"] = args.superseded_by
            n["kill_evidence"] = args.evidence
            n["events"].append({"event": n["status"], "at": utcnow(),
                                "evidence": args.evidence})
            save(store)
            print(f"OK {args.ins_id} -> {n['status']}")
            return 0
    raise SystemExit(f"FAIL: {args.ins_id} not found")


def cmd_predict(args) -> int:
    for line in PREDICTIONS.read_text().splitlines() if PREDICTIONS.exists() else []:
        if line.strip() and json.loads(line).get("campaign") == args.campaign:
            raise SystemExit(f"FAIL: campaign {args.campaign} already has a frozen row")
    lo, hi = (float(x) for x in args.band.split(","))
    point = float(args.point)
    row = {
        "campaign": args.campaign,
        "metric": args.metric,
        "point": point,
        "band": [lo, hi],
        "frozen_at": utcnow(),
        "actual": None,
        "scored": False,
    }
    if lo > point or point > hi:
        raise SystemExit("FAIL: point must lie inside the band")
    with PREDICTIONS.open("a") as f:
        f.write(json.dumps(row) + "\n")
    print(f"OK prediction frozen for {args.campaign}: point={point} band=[{lo},{hi}]")
    return 0


def cmd_score(args) -> int:
    rows = [json.loads(l) for l in PREDICTIONS.read_text().splitlines() if l.strip()]
    hit = None
    for r in rows:
        if r["campaign"] == args.campaign and not r["scored"]:
            hit = r
            break
    if hit is None:
        raise SystemExit(f"FAIL: no unscored prediction for {args.campaign}")
    hit["actual"] = float(args.actual)
    hit["scored"] = True
    hit["scored_at"] = utcnow()
    hit["in_band"] = hit["band"][0] <= hit["actual"] <= hit["band"][1]
    PREDICTIONS.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"OK scored {args.campaign}: actual={hit['actual']} in_band={hit['in_band']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify").set_defaults(fn=cmd_verify)
    sub.add_parser("render").set_defaults(fn=cmd_render)

    p = sub.add_parser("add-ins")
    p.add_argument("--statement", required=True)
    p.add_argument("--falsifier", required=True)
    p.set_defaults(fn=cmd_add_ins)

    p = sub.add_parser("add-pc")
    p.add_argument("--rules", required=True)
    p.add_argument("--from", dest="src", required=True)
    p.set_defaults(fn=cmd_add_pc)

    p = sub.add_parser("add-ev")
    p.add_argument("--pc", required=True)
    p.add_argument("--criteria", required=True)
    p.set_defaults(fn=cmd_add_ev)

    p = sub.add_parser("ev")
    p.add_argument("ev_id")
    p.add_argument("result")
    p.add_argument("--note")
    p.set_defaults(fn=cmd_ev)

    p = sub.add_parser("kill")
    p.add_argument("ins_id")
    p.add_argument("--evidence", required=True)
    p.add_argument("--superseded-by")
    p.set_defaults(fn=cmd_kill)

    p = sub.add_parser("predict")
    p.add_argument("--campaign", required=True)
    p.add_argument("--metric", required=True)
    p.add_argument("--point", required=True)
    p.add_argument("--band", required=True)
    p.set_defaults(fn=cmd_predict)

    p = sub.add_parser("score")
    p.add_argument("--campaign", required=True)
    p.add_argument("--actual", required=True)
    p.set_defaults(fn=cmd_score)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
