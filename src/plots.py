"""All plots for the prototype (matplotlib, src/ only)."""

from __future__ import annotations

import pathlib


def g1_plot(rows: list[dict], out: pathlib.Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sizes = sorted({r["n"] for r in rows})
    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=150)
    colors = {20: "#1b6ca8", 24: "#d1495b", 26: "#30638e"}
    for n in sizes:
        pts = sorted((r["depth"], r["cpu_xeb"], r["mps64_xeb"]) for r in rows if r["n"] == n)
        d = [p[0] for p in pts]
        ax.plot(d, [p[1] for p in pts], "o-", color=colors.get(n, "gray"),
                alpha=0.35, label=f"n={n} exact cpu sampler")
        ax.plot(d, [p[2] for p in pts], "s-", color=colors.get(n, "gray"),
                label=f"n={n} MPS chi=64 sampler")
    ax.set_xlabel("cycles (depth)")
    ax.set_ylabel("linear XEB fidelity vs exact ideal")
    ax.set_title("G1 — mini RCS XEB fidelity vs depth (BlueQubit cpu & mps.cpu samplers)")
    ax.axhline(0.0, color="k", lw=0.5, ls=":")
    ax.legend(fontsize=7, ncol=2)
    ax.set_ylim(-0.3, 1.15)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)


def staircase_plot(rounds: list[dict], control: list[dict] | None, out: pathlib.Path) -> None:
    """Cost-normalized score vs iteration with control overlay."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=150)
    xs = [r["round"] for r in rounds]
    ys = [r["val_score"] for r in rounds]
    ax.step(xs, ys, where="post", marker="o", color="#1b6ca8",
            label="flywheel (accepted = step up)")
    for r in rounds:
        if not r.get("accepted"):
            ax.plot(r["round"], r["val_score"], "x", color="#d1495b", ms=7)
    if control:
        cx = [c["round"] for c in control]
        cy = [c["val_score"] for c in control]
        ax.step(cx, cy, where="post", marker="s", color="#edae49", alpha=0.9,
                label="no-memory control (equal budget)")
    ax.set_xlabel("flywheel round")
    ax.set_ylabel("val score (suite metric)")
    ax.set_title("Closed-loop method refinement: val score by round")
    ax.legend(fontsize=8)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)


def pareto_plot(rounds: list[dict], out: pathlib.Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.4, 4.4), dpi=150)
    first = rounds[0]
    last = rounds[-1]
    for r in rounds:
        color = "#1b6ca8" if r.get("accepted") else "#bbbbbb"
        ax.scatter(r["cost_minutes"], r["val_score"], s=28, color=color, zorder=3)
    ax.scatter(first["cost_minutes"], first["val_score"], s=120, marker="*",
               color="#00798c", zorder=4, label="round 0 incumbent")
    ax.scatter(last["cost_minutes"], last["val_score"], s=120, marker="*",
               color="#d1495b", zorder=4, label="final round")
    ax.set_xlabel("cost: total queue+run minutes on val suite")
    ax.set_ylabel("val score")
    ax.set_title("Cost–fidelity Pareto, all rounds")
    ax.legend(fontsize=8)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
