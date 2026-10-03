import unittest

import numpy as np
import pandas as pd

from invest_site import signals as sg
from invest_site.main import build_indicators, sample_getter


def daily(values):
    idx = pd.date_range(end="2026-10-02", periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype="float64")


class Rules(unittest.TestCase):
    def test_vix_peak_passed(self):
        s = daily([15] * 300 + [35, 32, 28, 25])
        self.assertEqual(sg.vix(s).status, "signal")

    def test_vix_panic(self):
        self.assertEqual(sg.vix(daily([15] * 300 + [36])).status, "watch")

    def test_hy_spread_spike_then_narrowing(self):
        s = daily([3.0] * 300 + list(np.linspace(3.0, 5.0, 20)) + [4.8, 4.5, 4.4])
        self.assertEqual(sg.hy_spread(s).status, "signal")

    def test_trend_cross_above_200d(self):
        s = daily(list(np.linspace(100, 80, 260)) + list(np.linspace(80, 100, 15)))
        self.assertEqual(sg.trend_200d("x", "us", "x", "", s).status, "signal")

    def test_fear_greed_recovery(self):
        self.assertEqual(sg.fear_greed(daily([50] * 300 + [15] * 10 + [35])).status, "signal")

    def test_sample_run_has_no_errors(self):
        inds = build_indicators(sample_getter())
        self.assertEqual([i.id for i in inds if i.error], [])


if __name__ == "__main__":
    unittest.main()
