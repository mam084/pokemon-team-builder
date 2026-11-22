"""The teammate model's head start from the previous regulation (scripts/regulation_start_lab.py)."""

import time

import numpy as np

from scripts.train_teammates import head_start
from src.dex import load_dex
from src.synergy import HEAD_START_DAYS, TeammateModel, TeamRow, prior_matrix


def day(s: str) -> float:
    return time.mktime(time.strptime(s, "%Y-%m-%d"))


def test_only_in_the_first_days():
    dex = load_dex("regmc")
    vocab, prior = head_start("regmc", ["Incineroar"], dex, today=day("2026-09-12"))
    assert prior is not None and prior.shape == (len(vocab), len(vocab))
    assert "Incineroar" in vocab and len(vocab) > 100
    assert np.allclose(prior, prior.T) and not np.diag(prior).any()
    late = day("2026-09-09") + (HEAD_START_DAYS + 1) * 86400
    assert head_start("regmc", ["Incineroar"], dex, today=late) == (["Incineroar"], None)


def test_pulls_stay_near_the_prior_without_data():
    vocab = ["A", "B", "C", "D", "E", "F", "G"]
    prior = prior_matrix(vocab, {("A", "G"): 1.0, ("G", "A"): 1.0}, strength=0.5)
    rows = [TeamRow(roots=("A", "B", "C", "D", "E", "F"), weight=1.0, time=0.0, source="test")] * 3
    with_prior = TeammateModel(vocab).fit(rows, epochs=5, prior=prior)
    without = TeammateModel(vocab).fit(rows, epochs=5)
    a, g = vocab.index("A"), vocab.index("G")
    assert with_prior.W[a, g] > without.W[a, g] + 0.2
