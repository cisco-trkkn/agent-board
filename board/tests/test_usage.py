import importlib, json, os, shutil, sqlite3, sys, tempfile, time, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FIX = HERE / "tests" / "fixtures" / "usage"
sys.path.insert(0, str(HERE))
import usage  # noqa: E402


class PricesTest(unittest.TestCase):
    """Fixtures are real transcripts captured with tools/usage-capture-fixture.py.

    Calibration sources (model -> fixture):
      claude-opus-5-5        opus-lead, opus-teammate, opus-haiku-mixed
      claude-opus-5-5[1m]    opus-1m
      claude-sonnet-5-5      sonnet-lead
      claude-haiku-5-5       haiku-with-subagent (+ its subagents/ file), opus-haiku-mixed
      claude-fable-5-1       fable-teammate
    A fixture with a subagents/ directory is summed with its subagent file before the comparison.
    """

    def test_prices_match_cost_state(self):
        prices = json.loads((HERE / "prices.json").read_text())["models"]
        checked = 0
        for fx in sorted(FIX.glob("*.jsonl")):
            calls, cost_state = {}, None
            files = [fx] + sorted((FIX / fx.stem / "subagents").glob("*.jsonl"))
            for f in files:
                for line in f.read_text().splitlines():
                    d = json.loads(line)
                    if d.get("type") == "cost-state":
                        cost_state = d
                    elif (d.get("message") or {}).get("usage"):
                        calls[d.get("requestId") or line] = d
            if not cost_state:
                continue
            for model, mu in cost_state["modelUsage"].items():
                got = sum(usage.call_cost(usage.row_from_line(d, False), {"models": prices})
                          for d in calls.values() if usage.norm_model(d["message"]["model"]) == usage.norm_model(model))
                self.assertAlmostEqual(got, mu["costUSD"], delta=max(mu["costUSD"] * 0.01, 1e-6), msg=f"{fx.name} {model}")
                checked += 1
        self.assertGreaterEqual(checked, 3, "need cost-state sessions for at least 3 models")


if __name__ == "__main__":
    unittest.main()
