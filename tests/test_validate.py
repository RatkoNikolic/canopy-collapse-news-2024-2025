import pytest

from canopy_news.validate import alpha_nominal, evaluate, gold_labels, wilson


def test_alpha_nominal():
    assert alpha_nominal([["a", "a"], ["b", "b"], ["a", "a"]]) == 1.0
    # by hand: coincidences aa 2, bb 2, ab 1, ba 1; n_a = n_b = 3; D_o = 2, D_e = 18/5
    assert alpha_nominal([["a", "a"], ["b", "b"], ["a", "b"]]) == pytest.approx(1 - 2 / 3.6)
    assert alpha_nominal([["a"]]) is None                              # single values do not count


def test_gold_majority_on_shared():
    sample = [{"event_id": "s"}, {"event_id": "o"}]
    assignment = [{"event_id": "s", "shared": True}, {"event_id": "o", "shared": False}]
    def lab(e, c, ins, cl):
        return {"event_id": e, "coder": c, "in_scope": ins, "clauses": cl}

    labels = [lab("s", "R1", True, [2, 3]), lab("s", "R2", True, [2]), lab("s", "R3", False, []),
              lab("o", "R2", False, [])]
    g = gold_labels(sample, labels, assignment)
    assert g["s"] == {"in_scope": True, "clauses": [2]} and g["o"]["in_scope"] is False
    assert "s" not in gold_labels(sample, labels[:2], assignment)      # shared needs all three


def test_weighted_precision_recall_and_extension_rule():
    # candidates (weight 10): 4 gold-in, classifier says in for 3 of them and for 1 gold-out;
    # rest (weight 100, never classified): 1 gold-in of 2 -> recall = 30 / (40 + 100)
    def s(e, st, w):
        return {"event_id": e, "stratum": f"{st}:a", "weight": w}

    sample = [s(f"c{k}", "candidate", 10) for k in range(5)] + [s("r0", "rest", 100),
                                                               s("r1", "rest", 100)]
    gold = {f"c{k}": {"in_scope": k < 4} for k in range(5)} | {"r0": {"in_scope": True},
                                                              "r1": {"in_scope": False}}
    main = {"c0": True, "c1": True, "c2": True, "c3": False, "c4": True}
    out = evaluate(sample, gold, main, repeat={"c0": True, "c1": False})
    assert out["overall"]["precision"] == pytest.approx(30 / 40)
    assert out["overall"]["recall"] == pytest.approx(30 / 140)
    assert out["extension_rule"]["rest"]["extend"] is True
    assert out["stability"]["n"] == 2 and out["stability"]["agree"] == 1


def test_wilson():
    lo, hi = wilson(50, 100)
    assert lo == pytest.approx(0.404, abs=1e-3) and hi == pytest.approx(0.596, abs=1e-3)
