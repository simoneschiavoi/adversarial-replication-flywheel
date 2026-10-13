"""Re-execute the evidence notebooks in place (outputs refreshed).

Usage (from the notebooks/ directory):
    python tools/run_all.py                 # all 0*.ipynb
    python tools/run_all.py 01_campaign_audit.ipynb
Fails loudly if any cell raises (every notebook asserts its own checks).
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(v, "2")

import nbformat
from nbclient import NotebookClient

NB_DIR = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    names = sys.argv[1:] or sorted(p.name for p in NB_DIR.glob("0*.ipynb"))
    for name in names:
        path = NB_DIR / name
        nb = nbformat.read(path, as_version=4)
        t0 = time.time()
        NotebookClient(nb, timeout=3600, kernel_name="python3",
                       resources={"metadata": {"path": str(NB_DIR)}}).execute()
        for c in nb.cells:
            c.metadata.pop("execution", None)
        nbformat.write(nb, path)
        print(f"{name}: executed in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
