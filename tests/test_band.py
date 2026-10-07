import numpy as np

from canopy_news.band import _auc, balanced_centroid, stratum


def test_balanced_centroid_weighs_outlets_equally():
    v = np.array([[1, 0], [1, 0], [1, 0], [0, 1]], dtype=np.float32)   # outlet a: 3 candidates, b: 1
    outlets = np.array(["a", "a", "a", "b"])
    c = balanced_centroid(v, outlets, np.ones(4, dtype=bool))
    assert np.allclose(c, [2 ** -0.5, 2 ** -0.5])                       # not pulled towards a


def test_stratum_and_auc():
    cuts = {"band-top10": 0.8, "band-next20": 0.6}
    assert [stratum(x, cuts) for x in (0.9, 0.7, 0.1)] == ["band-top10", "band-next20", "rest"]
    assert _auc(np.array([3.0, 4.0]), np.array([1.0, 2.0])) == 1.0
    assert _auc(np.array([1.0]), np.array([2.0])) == 0.0
