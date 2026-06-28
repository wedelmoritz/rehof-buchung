"""Reine Tests für das Commit-Reveal des Los-Seeds (ADR 0062), ohne Django."""
from booking import lottery as L


def test_seed_commitment_deterministisch():
    # Gleicher Seed → gleiche Prüfsumme; SHA-256 = 64 Hex-Zeichen.
    c = L.seed_commitment(123456789)
    assert c == L.seed_commitment(123456789)
    assert len(c) == 64 and all(ch in "0123456789abcdef" for ch in c)
    # Anderer Seed → andere Prüfsumme.
    assert L.seed_commitment(123456789) != L.seed_commitment(987654321)


def test_verify_commitment():
    seed = 42
    commit = L.seed_commitment(seed)
    assert L.verify_commitment(seed, commit) is True
    assert L.verify_commitment(seed, commit.upper()) is True   # Groß/klein egal
    assert L.verify_commitment(seed + 1, commit) is False
    assert L.verify_commitment(seed, "") is False
