"""Circuit generation and transforms (qiskit).

- RCS brickwork: per cycle, a layer of random 1q gates then a brick layer of
  random SU(4) 2q gates, alternating even/odd pairs. Seeded, reproducible.
- Peaked circuits fetched from the sponsor's API (get_peaked_circuit).
- qubit->site permutation: relabel qubits (MPS site order) — a mutation knob.

Frozen circuits are stored as QPY (the same encoding the BlueQubit SDK uses
for transport); arbitrary SU(4) UnitaryGates survive exactly.
"""

from __future__ import annotations

import hashlib
import io

from qiskit import QuantumCircuit, qpy
from qiskit.circuit.library import UnitaryGate
from qiskit.quantum_info import random_unitary


def rcs_circuit(n_qubits: int, depth: int, seed: int) -> QuantumCircuit:
    """1D-brickwork RCS circuit with random SU(4) layers (Sycamore-style scaled down).

    Deterministic given (n_qubits, depth, seed): the circuit carries an explicit
    name so the QPY serialization is byte-stable.
    """
    qc = QuantumCircuit(n_qubits, name=f"rcs_n{n_qubits}_d{depth}_s{seed}")
    for d in range(depth):
        # random 1q layer (three rotations per qubit, PRDG-style)
        for q in range(n_qubits):
            h = int(hashlib.sha256(f"{seed}:{d}:{q}:h".encode()).hexdigest(), 16)
            qc.u((h % 628) / 100.0, ((h >> 10) % 628) / 100.0, ((h >> 20) % 628) / 100.0, q)
        # brick layer of random SU(4)
        even = d % 2 == 0
        pairs = (
            [(q, q + 1) for q in range(0, n_qubits - 1, 2)]
            if even
            else [(q, q + 1) for q in range(1, n_qubits - 1, 2)]
        )
        for a, b in pairs:
            u = random_unitary(4, seed=(seed * 1_000_003 + d * 1_009 + a * 7 + 1) % (2**31))
            qc.append(UnitaryGate(u.data), [a, b])
    return qc


def measure_all(qc: QuantumCircuit) -> QuantumCircuit:
    out = qc.copy()
    out.measure_all()
    return out


def permuted(qc: QuantumCircuit, permutation: list[int]) -> QuantumCircuit:
    """Relabel logical qubit i -> physical site permutation[i].

    Implemented by composing with the routing permutation on instructions,
    keeping a pure qubit-permutation semantics (no synthesis noise).
    """
    n = qc.num_qubits
    assert sorted(permutation) == list(range(n)), "permutation must be a bijection"
    out = QuantumCircuit(n, name=f"{qc.name}_perm")
    # logical qubit L lives at site permutation[L]
    site_of_logical = dict(enumerate(permutation))
    for inst in qc.data:
        qargs = [site_of_logical[qc.find_bit(b).index] for b in inst.qubits]
        out.append(inst.operation, qargs, [])
    return out


def circuit_sha256(qc: QuantumCircuit) -> str:
    import hashlib

    buf = io.BytesIO()
    qpy.dump(qc, buf, version=13)
    return hashlib.sha256(buf.getvalue()).hexdigest()


def save_circuit(qc: QuantumCircuit, path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        qpy.dump(qc, f, version=13)
    return circuit_sha256(qc)


def load_circuit(path) -> QuantumCircuit:
    with open(path, "rb") as f:
        return qpy.load(f)[0]


def permute_pauli_label(label: str, permutation: list[int]) -> str:
    """Transform a Pauli-string observable under the same site permutation
    applied to the circuit by permuted(), so the target EV is invariant.

    Qiskit label convention: label[i] acts on qubit (n-1-i). permutation maps
    logical qubit L -> site permutation[L], so the transformed observable acts
    on qubit permutation[L] exactly where the original acted on L.
    """
    n = len(label)
    assert sorted(permutation) == list(range(n)), "permutation must be a bijection"
    char_of_qubit = {q: label[n - 1 - q] for q in range(n)}
    out = [""] * n
    for logical, site in enumerate(permutation):
        out[n - 1 - site] = char_of_qubit[logical]
    return "".join(out)


def fetch_peaked(client, difficulty: int, circuit_id: int | None = None):
    """Fetch a sponsor peaked circuit; returns (qiskit circuit without measurement
    semantics as given, peak key string, metadata)."""
    pc = client.get_peaked_circuit(difficulty, circuit_id)
    return pc.circuit, pc.key, pc.metadata
