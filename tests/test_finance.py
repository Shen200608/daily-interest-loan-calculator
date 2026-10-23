#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面版（desktop/app.py）公式验收测试。

运行:
    python tests/test_finance.py
或:
    python -m unittest discover -s tests -p "test_*.py"

本文件是 SPEC 第 7 节验收标准的可执行版本。
如果测试失败，请修改 desktop/app.py 使其符合 SPEC 第 3.7 节，不要改测试。
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import unittest

# Windows 控制台默认可能是 cp1252/cp936，强制 UTF-8 输出，避免打印中文时 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PATH = os.path.join(ROOT, "desktop", "app.py")
JS_PATH = os.path.join(ROOT, "js", "finance.js")
RATES_PATH = os.path.join(ROOT, "data", "rates.json")
NODE = os.environ.get("LIXI_NODE", "node")


def load_app_module():
    """从文件路径加载 desktop/app.py（不依赖包结构、不启动 GUI）。"""
    if not os.path.exists(APP_PATH):
        raise unittest.SkipTest(f"desktop/app.py 不存在: {APP_PATH}")
    spec = importlib.util.spec_from_file_location("lixi_desktop_app", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["lixi_desktop_app"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


APP = None
IMPORT_ERROR = None
try:
    APP = load_app_module()
except unittest.SkipTest as exc:  # pragma: no cover
    IMPORT_ERROR = str(exc)
except Exception as exc:  # pragma: no cover
    IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


def need(name: str):
    if APP is None:
        raise unittest.SkipTest(f"desktop/app.py 无法导入: {IMPORT_ERROR}")
    fn = getattr(APP, name, None)
    if fn is None:
        raise AssertionError(f"desktop/app.py 缺少函数 {name}（见 SPEC 3.7）")
    return fn


class TestBasics(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(need("DAY_BASIS")(), 365) if callable(getattr(APP, "DAY_BASIS", None)) else None
        self.assertEqual(getattr(APP, "DAY_BASIS"), 365)

    def test_normalize_to_annual(self):
        f = need("normalize_to_annual")
        cases = [
            ((3.65, "annual_pct"), 3.65),
            ((1.0, "monthly_pct"), 12.0),
            ((0.05, "daily_pct"), 18.25),
            ((1.0, "monthly_fen"), 12.0),
            ((1.0, "annual_fen"), 10.0),
            ((5.0, "monthly_li"), 6.0),
            ((5.0, "annual_li"), 5.0),
            ((5.0, "monthly_hao"), 0.6),
            ((5.0, "daily_wan"), 18.25),
            ((0.5, "per10k_yuan"), 1.825),
            ((60.0, "lpr_plus_bp"), 3.6),
            ((4.0, "lpr_multiple"), 12.0),
        ]
        for args, expected in cases:
            with self.subTest(kind=args[1]):
                got = f(args[0], args[1])
                self.assertAlmostEqual(float(got), expected, places=6)

    def test_normalize_range_kinds(self):
        f = need("normalize_to_annual")
        # 区间类：value 为 None，用 min/max 取中值
        got = f(None, "range_annual_pct", min=7.2, max=24.0)
        self.assertAlmostEqual(float(got), 15.6, places=6)
        # 日息万2~万6，中值万4 → 年化 4*365/100 = 14.6%
        got = f(None, "range_daily_wan", min=2.0, max=6.0)
        self.assertAlmostEqual(float(got), 14.6, places=6)

    def test_breakdown(self):
        f = need("breakdown")
        r = f(3.65)
        self.assertAlmostEqual(r["annualPct"], 3.65, places=6)
        self.assertAlmostEqual(r["monthlyPct"], 3.65 / 12, places=6)
        self.assertAlmostEqual(r["dailyPct"], 3.65 / 365, places=6)


class TestDailyInterest(unittest.TestCase):
    """验收标准 2：本金 10000、3.65% → 1.00/天；7.3% → 2.00/天。"""

    def test_compound_uses_daily_period(self):
        """复利必须以「日」为计息周期。

        回归测试：旧实现写成 ``(1+年化)^(d/365)``（把「年」当周期），
        导致复利反而小于单利，且 365 天时复利退化成单利。
        """
        f = need("daily_interest")
        for rate, days in [(1.5, 30), (3.65, 30), (12, 30), (24, 30), (3.65, 365), (12, 90)]:
            with self.subTest(rate=rate, days=days):
                simple = f(10000, rate, days, compound=False)["periodInterest"]
                comp = f(10000, rate, days, compound=True)["periodInterest"]
                self.assertGreaterEqual(comp, simple, f"复利({comp})应 >= 单利({simple})")
                expected = 10000 * ((1 + rate / 100 / 365) ** days - 1)
                self.assertAlmostEqual(comp, round(expected, 2), delta=0.01)
        # 365 天复利必须严格大于单利（旧 bug 下两者相等）
        year = f(10000, 3.65, 365, compound=True)["periodInterest"]
        self.assertAlmostEqual(year, 371.72, delta=0.02)
        self.assertGreater(year, f(10000, 3.65, 365, compound=False)["periodInterest"] + 6)

    def test_cent_per_day(self):
        f = need("daily_interest")
        r = f(10000, 3.65)
        self.assertAlmostEqual(r["daily"], 1.00, places=2)
        r = f(10000, 7.3)
        self.assertAlmostEqual(r["daily"], 2.00, places=2)

    def test_monthly_and_annual(self):
        f = need("daily_interest")
        r = f(10000, 3.65)
        self.assertAlmostEqual(r["monthly"], 30.42, places=2)
        self.assertAlmostEqual(r["annual"], 365.00, places=2)

    def test_period(self):
        f = need("daily_interest")
        r = f(10000, 3.65, 30)
        self.assertAlmostEqual(r["periodInterest"], round(365.0 * 30 / 365, 2), places=2)

    def test_invalid_input_raises(self):
        f = need("daily_interest")
        for bad in ((0, 3.65), (-1, 3.65), (10000, -1)):
            with self.subTest(bad=bad):
                with self.assertRaises((ValueError, ZeroDivisionError)):
                    f(*bad)


class TestCompare(unittest.TestCase):
    def test_compare_b_better(self):
        f = need("compare_rates")
        r = f(10000, 3.65, 7.3)
        self.assertEqual(r["better"], "b")
        self.assertAlmostEqual(r["diffDaily"], 1.00, places=2)
        self.assertAlmostEqual(r["diffAnnual"], 365.00, places=2)

    def test_compare_a_better(self):
        f = need("compare_rates")
        r = f(10000, 12.0, 3.65)
        self.assertEqual(r["better"], "a")
        self.assertLess(r["diffDaily"], 0)

    def test_compare_equal(self):
        f = need("compare_rates")
        r = f(10000, 5.0, 5.0)
        self.assertEqual(r["better"], "equal")


class TestLoans(unittest.TestCase):
    """验收标准 3、4。"""

    def check_invariants(self, result, principal):
        sched = result["schedule"]
        self.assertIsInstance(sched, list)
        self.assertGreater(len(sched), 0)
        sum_principal = sum(row["principal"] for row in sched)
        sum_interest = sum(row["interest"] for row in sched)
        self.assertAlmostEqual(sum_principal, principal, places=2)
        self.assertAlmostEqual(sum_interest, result["totalInterest"], places=2)
        self.assertAlmostEqual(
            sum(row["payment"] for row in sched), result["totalPayment"], places=2
        )
        self.assertAlmostEqual(sched[-1]["remaining"], 0.0, places=2)
        for row in sched:
            self.assertAlmostEqual(row["payment"], row["principal"] + row["interest"], places=2)

    def test_equal_installment_1m_30y(self):
        f = need("equal_installment")
        r = f(1000000, 4.9, 360)
        # 标准结果 ≈ 5307.27
        self.assertAlmostEqual(r["payment"], 5307.27, delta=5307.27 * 0.005)
        self.assertAlmostEqual(r["totalPayment"], r["payment"] * 360, delta=1.0)
        self.assertAlmostEqual(
            r["totalInterest"], r["totalPayment"] - 1000000, delta=1.0
        )
        self.assertAlmostEqual(r["totalInterest"], 910600, delta=910600 * 0.02)
        self.check_invariants(r, 1000000)

    def test_equal_installment_12m(self):
        f = need("equal_installment")
        r = f(12000, 12, 12)
        self.assertAlmostEqual(r["payment"], 1066.19, delta=1.0)
        self.check_invariants(r, 12000)

    def test_equal_installment_zero_rate(self):
        f = need("equal_installment")
        r = f(12000, 0, 12)
        self.assertAlmostEqual(r["payment"], 1000.0, places=2)
        self.assertAlmostEqual(r["totalInterest"], 0.0, places=2)
        self.check_invariants(r, 12000)

    def test_zero_rate_no_phantom_interest(self):
        """零利率免息分期不得出现「幻影利息」。

        本金不能被期数整除到「分」时，旧实现会把取整残差当成利息，
        出现「免息却要付利息」甚至「总还款 < 本金」（负利息）。
        """
        f = need("equal_installment")
        for principal, months in [
            (100, 7),
            (1000, 365),
            (5000, 24),
            (999.99, 7),
            (12000, 12),
            (0.01, 3),
        ]:
            with self.subTest(principal=principal, months=months):
                r = f(principal, 0, months)
                self.assertAlmostEqual(r["totalInterest"], 0.0, places=2)
                self.assertAlmostEqual(r["totalPayment"], principal, places=2)
                self.assertAlmostEqual(
                    sum(x["principal"] for x in r["schedule"]), principal, places=2
                )
                self.assertAlmostEqual(r["schedule"][-1]["remaining"], 0.0, places=2)
                for row in r["schedule"]:
                    self.assertAlmostEqual(row["interest"], 0.0, places=2)

    def test_equal_principal(self):
        f = need("equal_principal")
        r = f(12000, 12, 12)
        self.assertAlmostEqual(r["schedule"][0]["principal"], 1000.0, places=2)
        self.assertAlmostEqual(r["schedule"][0]["interest"], 120.0, places=2)
        self.assertAlmostEqual(r["schedule"][0]["payment"], 1120.0, places=2)
        self.assertAlmostEqual(r["schedule"][-1]["payment"], 1010.0, places=2)
        # 等额本金总利息 = P*i*(n+1)/2 = 12000*0.01*13/2 = 780
        self.assertAlmostEqual(r["totalInterest"], 780.0, places=2)
        self.check_invariants(r, 12000)

    def test_interest_first(self):
        f = need("interest_first")
        r = f(10000, 12, 12)
        self.assertAlmostEqual(r["totalInterest"], 1200.0, places=2)
        self.assertAlmostEqual(r["schedule"][0]["payment"], 100.0, places=2)
        self.assertAlmostEqual(r["schedule"][-1]["payment"], 10100.0, places=2)
        self.check_invariants(r, 10000)

    def test_bullet(self):
        f = need("bullet")
        r = f(10000, 12, 12)
        self.assertAlmostEqual(r["totalInterest"], 1200.0, places=2)
        self.assertAlmostEqual(r["schedule"][-1]["payment"], 11200.0, places=2)
        self.check_invariants(r, 10000)

    def test_loan_schedule_dispatch(self):
        f = need("loan_schedule")
        for method in ("equal_installment", "equal_principal", "interest_first", "bullet"):
            with self.subTest(method=method):
                r = f(50000, 8, 24, method)
                self.assertEqual(r["method"], method)
                self.check_invariants(r, 50000)

    def test_schedule_summary(self):
        li = need("loan_schedule")
        sm = need("schedule_summary")
        r = li(50000, 8, 24, "equal_installment")
        s = sm(r["schedule"])
        self.assertAlmostEqual(s["totalInterest"], r["totalInterest"], places=2)
        self.assertAlmostEqual(s["totalPayment"], r["totalPayment"], places=2)
        self.assertEqual(s["months"], 24)


class TestOnlineLoan(unittest.TestCase):
    """验收标准 6：日息万5、10000 元 → 每日 5 元，30 天 150 元。"""

    def test_daily_payment(self):
        f = need("daily_payment")
        r = f(10000, 18.25, 30)
        self.assertAlmostEqual(r["dailyInterest"], 5.00, places=2)
        self.assertAlmostEqual(r["totalInterest"], 150.00, places=2)

    def test_daily_payment_interest_first(self):
        f = need("online_loan")
        r = f(10000, 18.25, 30, "interest_first")
        self.assertAlmostEqual(r["dailyInterest"], 5.00, places=2)
        self.assertAlmostEqual(r["totalInterest"], 150.00, places=2)
        self.assertAlmostEqual(r["totalPayment"], 10150.00, places=2)

    def test_daily_payment_installment(self):
        f = need("online_loan")
        r = f(10000, 18.25, 30, "equal_installment_daily")
        sched = r["schedule"]
        self.assertAlmostEqual(sum(x["principal"] for x in sched), 10000.00, places=2)
        self.assertAlmostEqual(sched[-1]["remaining"], 0.0, places=2)
        self.assertGreater(r["totalInterest"], 0)


class TestConversionTools(unittest.TestCase):
    """验收标准 5：月费率 0.6%、12 期 → 真实年化约 13%。"""

    def test_apr_from_fee(self):
        f = need("apr_from_fee")
        r = f(10000, 0.6, 12)
        self.assertGreater(r["aprAnnual"], 12.0)
        self.assertLess(r["aprAnnual"], 15.0)
        self.assertAlmostEqual(r["aprSimple"], 7.2, places=6)
        self.assertAlmostEqual(r["totalFee"], 720.0, places=2)
        self.assertAlmostEqual(r["totalPayment"], 10720.0, places=2)

    def test_apr_from_fee_zero_fee(self):
        f = need("apr_from_fee")
        r = f(10000, 0.0, 12)
        self.assertAlmostEqual(r["aprAnnual"], 0.0, places=2)

    def test_irr(self):
        f = need("irr")
        # -1000 然后 5 期 250：等额年金因子 4，irr ≈ 7.93%/期
        v = f([-1000, 250, 250, 250, 250, 250])
        self.assertAlmostEqual(v, 0.0793, delta=0.002)

    def test_effective_annual(self):
        f = need("effective_annual")
        self.assertAlmostEqual(f(12, 12), 12.6825, places=2)
        self.assertAlmostEqual(f(12, 1), 12.0, places=6)

    def test_convert(self):
        f = need("convert")
        r = f(3.65, "annual_pct")
        self.assertAlmostEqual(r["annualPct"], 3.65, places=6)
        self.assertAlmostEqual(r["dailyWan"], 1.0, places=6)
        self.assertAlmostEqual(r["basisPoints"], 365.0, places=4)
        self.assertAlmostEqual(r["monthlyFen"], 3.65 / 12, places=6)
        self.assertAlmostEqual(r["annualFen"], 0.365, places=6)
        self.assertAlmostEqual(r["monthlyLi"], 3.65 / 12 / 0.1, places=6)


class TestRatesData(unittest.TestCase):
    def test_rates_json_loads_and_is_rich(self):
        self.assertTrue(os.path.exists(RATES_PATH), "data/rates.json 不存在")
        with open(RATES_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("meta", data)
        self.assertIn("groups", data)
        self.assertIn("rates", data)
        self.assertGreaterEqual(len(data["rates"]), 45, "利率条目应 ≥ 45 条")
        group_ids = {g["id"] for g in data["groups"]}
        for need_group in ("official", "customary", "deposit", "loan", "online_loan"):
            self.assertIn(need_group, group_ids)
        ids = [r["id"] for r in data["rates"]]
        self.assertEqual(len(ids), len(set(ids)), "rates.id 必须唯一")
        for r in data["rates"]:
            self.assertIn(r["group"], group_ids, f"{r['id']} 的 group 非法")
            self.assertTrue(r.get("name"), f"{r['id']} 缺少 name")
            self.assertTrue(r.get("aliases"), f"{r['id']} 缺少 aliases")

    def test_validate_rates_tool_passes(self):
        tool = os.path.join(ROOT, "tools", "validate_rates.py")
        if not os.path.exists(tool):
            self.skipTest("tools/validate_rates.py 不存在")
        proc = subprocess.run(
            [sys.executable, tool, RATES_PATH],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(proc.returncode, 0, f"校验失败:\n{proc.stdout}\n{proc.stderr}")


class TestCrossLanguageConsistency(unittest.TestCase):
    """双端一致性：同一组用例，Python 与 Node 结果必须一致（差异 < 0.01）。"""

    CASES = [
        ("daily_interest", [10000, 3.65]),
        ("daily_interest", [123456.78, 7.3]),
        ("daily_interest", [888888.88, 4.35, 90]),
        ("equal_installment", [1000000, 4.9, 360]),
        ("equal_installment", [50000, 8.4, 24]),
        ("equal_principal", [120000, 5.6, 36]),
        ("interest_first", [30000, 12, 12]),
        ("bullet", [20000, 6, 6]),
        ("daily_payment", [10000, 18.25, 30]),
        ("apr_from_fee", [10000, 0.6, 12]),
        ("normalize_to_annual", [5, "daily_wan"]),
        ("normalize_to_annual", [1, "monthly_fen"]),
    ]

    @classmethod
    def setUpClass(cls):
        if APP is None:
            raise unittest.SkipTest(f"desktop/app.py 无法导入: {IMPORT_ERROR}")
        if not os.path.exists(JS_PATH):
            raise unittest.SkipTest("js/finance.js 不存在")
        try:
            subprocess.run(
                [NODE, "--version"], capture_output=True, check=True, timeout=20
            )
        except Exception as exc:  # pragma: no cover
            raise unittest.SkipTest(f"node 不可用: {exc}")

    def _py_call(self, name, args):
        py_name = {
            "daily_interest": "daily_interest",
            "daily_payment": "daily_payment",
            "equal_installment": "equal_installment",
            "equal_principal": "equal_principal",
            "interest_first": "interest_first",
            "bullet": "bullet",
            "apr_from_fee": "apr_from_fee",
            "normalize_to_annual": "normalize_to_annual",
        }[name]
        fn = getattr(APP, py_name)
        return fn(*args)

    def test_python_matches_node(self):
        script = r"""
const F = require(process.argv[1]);
const cases = JSON.parse(process.argv[2]);
const map = {
  daily_interest: 'dailyInterest',
  daily_payment: 'dailyPayment',
  equal_installment: 'equalInstallment',
  equal_principal: 'equalPrincipal',
  interest_first: 'interestFirst',
  bullet: 'bullet',
  apr_from_fee: 'aprFromFee',
  normalize_to_annual: 'normalizeToAnnual',
};
const out = [];
for (const c of cases) {
  const fn = F[map[c.name]];
  if (typeof fn !== 'function') { out.push({ error: 'missing:' + map[c.name] }); continue; }
  const r = fn.apply(null, c.args);
  const pick = (o, keys) => { const r2 = {}; for (const k of keys) if (k in o) r2[k] = o[k]; return r2; };
  if (r && typeof r === 'object') {
    const res = pick(r, ['daily','monthly','annual','periodInterest','payment','totalPayment',
      'totalInterest','dailyInterest','aprAnnual','monthlyIrr']);
    if (Array.isArray(r.schedule)) {
      res.schedule_len = r.schedule.length;
      res.schedule_last = r.schedule[r.schedule.length - 1];
    }
    out.push(res);
  } else {
    out.push({ value: r });
  }
}
console.log(JSON.stringify(out));
"""
        payload = [{"name": n, "args": a} for n, a in self.CASES]
        proc = subprocess.run(
            [NODE, "-e", script, JS_PATH, json.dumps(payload)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, f"node 执行失败:\n{proc.stdout}\n{proc.stderr}")
        js_results = json.loads(proc.stdout.strip().splitlines()[-1])

        for (name, args), js in zip(self.CASES, js_results):
            with self.subTest(case=name, args=args):
                self.assertNotIn("error", js, f"JS 缺少函数: {js}")
                py = self._py_call(name, args)
                if not isinstance(py, dict):
                    self.assertAlmostEqual(float(py), float(js["value"]), places=6)
                    continue
                for key, js_val in js.items():
                    if key in ("schedule_len", "schedule_last"):
                        continue
                    if key not in py:
                        continue
                    # 字段名映射：JS daily -> Py daily
                    self.assertAlmostEqual(
                        float(py[key]), float(js_val), delta=0.01, msg=f"{name}.{key} 两端不一致"
                    )
                if "schedule_len" in js:
                    self.assertEqual(len(py["schedule"]), js["schedule_len"], f"{name} 期数不一致")
                    last = js["schedule_last"]
                    self.assertAlmostEqual(
                        float(py["schedule"][-1]["payment"]), float(last["payment"]), delta=0.01
                    )


def main() -> int:
    if APP is None:
        print(f"[警告] desktop/app.py 尚不可用：{IMPORT_ERROR}", file=sys.stderr)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
