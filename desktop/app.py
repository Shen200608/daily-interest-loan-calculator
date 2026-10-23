#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""利息计算器 · 桌面版（Windows / macOS / Linux 通用）

纯标准库实现：tkinter + ttk + json + csv + datetime + math + argparse，零第三方依赖。
公式与 js/finance.js 完全一致（SPEC 第 3.7 节 API 契约、365 天基准、金额四舍五入到分、
最后一期强制结平），函数名用 Python 风格、一一对应，返回字段名保持 JS 的驼峰写法。

用法：
    python app.py                # 启动图形界面
    python app.py --selftest     # 无头自检：跑完所有公式验收用例，输出 JSON 后退出
    python app.py --selftest -o report.json

退出码：0 = 成功；1 = 自检失败或运行环境不可用。
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import math
import os
import sys

# --------------------------------------------------------------------------------------
# Windows 控制台默认可能是 cp1252/cp936，直接 print 中文会 UnicodeEncodeError。
# 必须在任何输出之前把 stdout/stderr 切到 UTF-8。
#
# 另外：PyInstaller 的 --windowed 模式下 sys.stdout / sys.stderr 是 None
# （没有控制台），此时任何 print 都会抛 AttributeError/OSError。这里统一兜底到
# devnull，保证 --selftest 在打包后的 exe 里也能正常跑完并返回正确的退出码。
# --------------------------------------------------------------------------------------
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")

for _stream in (sys.stdout, sys.stderr):
    try:  # pragma: no cover - 取决于运行环境
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # pragma: no cover
        pass

# tkinter 可能因环境缺失（极简发行版/无 Tk 的 Python），导入失败不应影响公式模块被 import。
try:  # pragma: no cover - 取决于运行环境
    import tkinter as tk
    from tkinter import filedialog, font as tkfont, messagebox, ttk

    TK_AVAILABLE = True
except Exception:  # pragma: no cover
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    tkfont = None  # type: ignore[assignment]
    filedialog = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    TK_AVAILABLE = False

__version__ = "1.0.0"
__all__ = [
    "DAY_BASIS",
    "ROUND",
    "normalize_to_annual",
    "breakdown",
    "daily_interest",
    "compare_rates",
    "equal_installment",
    "equal_principal",
    "interest_first",
    "bullet",
    "loan_schedule",
    "schedule_summary",
    "daily_payment",
    "online_loan",
    "irr",
    "apr_from_fee",
    "effective_annual",
    "convert",
    "platform_to_annual",
    "load_rates",
    "get_rate_dataset",
    "build_rate_options",
    "run_selftest",
    "App",
]

DAY_BASIS = 365
DEFAULT_LPR_1Y = 3.0
DEFAULT_JUDICIAL_MULTIPLE = 4
RATE_PRECISION = 6          # 比率保留 6 位小数
MONEY_PRECISION = 2         # 金额保留 2 位（分）

#: 复利口径下界（避免 (1+r)^n 溢出）
_COMPOUND_MAX_YEARS = 500.0


# ======================================================================================
# 一、基础工具
# ======================================================================================
def ROUND(x) -> float:
    """四舍五入到分（2 位），语义同 JS 的 ``Math.round(x*100)/100``。

    ``Math.round`` 对 .5 一律向 +∞ 取整，这里用 floor(x*100+0.5) 精确复刻，
    保证 Python 与 JS 两端对同一输入的舍入结果完全一致。
    """
    v = float(x)
    if not math.isfinite(v):
        raise ValueError("数值不能是 NaN 或无穷大")
    if v == 0.0:
        return 0.0
    return math.floor(v * 100 + 0.5) / 100


def _r6(x) -> float:
    """比率四舍五入到 6 位小数。"""
    v = float(x)
    if not math.isfinite(v):
        raise ValueError("数值不能是 NaN 或无穷大")
    return round(v, RATE_PRECISION) + 0.0


def _finite(x, name: str = "数值") -> float:
    """把任意输入转成有限浮点数，NaN/Infinity/非数字一律抛 ValueError。"""
    if isinstance(x, bool):
        raise ValueError(f"{name}必须是数字")
    if x is None:
        raise ValueError(f"{name}不能为空")
    try:
        v = float(x)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}必须是数字") from exc
    if math.isnan(v) or math.isinf(v):
        raise ValueError(f"{name}不能是 NaN 或无穷大")
    return v


def _positive(x, name: str = "数值") -> float:
    v = _finite(x, name)
    if v <= 0:
        raise ValueError(f"{name}必须大于 0")
    return v


def _non_negative(x, name: str = "数值") -> float:
    v = _finite(x, name)
    if v < 0:
        raise ValueError(f"{name}不能为负数")
    return v


def _months(x) -> int:
    """月数归一化：1 ~ 1200 的整数。"""
    v = _finite(x, "期数")
    n = int(round(v))
    if n < 1:
        raise ValueError("期数必须大于等于 1")
    if n > 1200:
        raise ValueError("期数不能超过 1200")
    return n


def _days(x) -> int:
    """天数归一化：1 ~ 36500 的整数。"""
    v = _finite(x, "天数")
    n = int(round(v))
    if n < 1:
        raise ValueError("天数必须大于等于 1")
    if n > 36500:
        raise ValueError("天数不能超过 36500")
    return n


def _annual_pct(x, name: str = "年化利率") -> float:
    v = _non_negative(x, name)
    if v > 1000:
        raise ValueError(f"{name}不能超过 1000%")
    return v


# ======================================================================================
# 二、利率归一化（SPEC 3.1 / 3.7-1 / 第 6 节换算表）
# ======================================================================================
KIND_LABELS = {
    "annual_pct": "年化利率（%）",
    "monthly_pct": "月利率（%）",
    "daily_pct": "日利率（%）",
    "monthly_fen": "月息（分）",
    "annual_fen": "年息（分）",
    "monthly_li": "月息（厘）",
    "annual_li": "年息（厘）",
    "monthly_hao": "月息（毫）",
    "daily_wan": "日息（万几）",
    "per10k_yuan": "万份收益（元/万份/天）",
    "lpr_plus_bp": "LPR + 基点（BP）",
    "lpr_multiple": "LPR 倍数",
    "range_annual_pct": "年化区间（取中值，%）",
    "range_daily_wan": "日息万几区间（取中值）",
}

RANGE_KINDS = ("range_annual_pct", "range_daily_wan")

GROUP_SHORT = {
    "official": "官方",
    "customary": "民间",
    "deposit": "存款",
    "loan": "贷款",
    "online_loan": "网贷",
}


def normalize_to_annual(value, kind: str, min=None, max=None, lpr1y: float = DEFAULT_LPR_1Y) -> float:
    """把任意口径换算成年化利率（百分数，如 3.65 表示 3.65%）。

    ``min`` / ``max`` 与内置同名函数冲突，故在函数体内改用别名 ``lo`` / ``hi``。
    """
    lo, hi = min, max
    base = _finite(lpr1y, "LPR（1年期）")
    if kind in RANGE_KINDS:
        if lo is None or hi is None:
            raise ValueError(f"区间口径 {kind} 必须提供 min 和 max")
        lo_f, hi_f = _finite(lo, "区间下限"), _finite(hi, "区间上限")
        if lo_f > hi_f:
            raise ValueError("区间下限不能大于上限")
        mid = (lo_f + hi_f) / 2
        if kind == "range_annual_pct":
            return mid
        # range_daily_wan：万几 → 百分比，年化 = 万几 * 365 / 100
        return mid * DAY_BASIS / 100

    if value is None:
        raise ValueError(f"口径 {kind} 需要提供数值")

    v = _finite(value, "利率数值")
    if kind == "annual_pct":
        return v
    if kind == "monthly_pct":
        return v * 12
    if kind == "daily_pct":
        return v * DAY_BASIS
    if kind == "monthly_fen":
        return v * 12                      # 1 分 = 1%/月
    if kind == "annual_fen":
        return v * 10                      # 1 分 = 10%/年
    if kind == "monthly_li":
        return v * 0.1 * 12                # 1 厘 = 0.1%/月
    if kind == "annual_li":
        return v * 1                       # 1 厘 = 1%/年
    if kind == "monthly_hao":
        return v * 0.01 * 12               # 1 毫 = 0.01%/月
    if kind == "daily_wan":
        return v * DAY_BASIS / 100         # 万5 = 0.05%/日 → 18.25%/年
    if kind == "per10k_yuan":
        # 万份收益 v 元/万份/天：日利率 = v/10000，年化百分数 = v*365/100
        # 与 js/finance.js 完全一致（0.5 元 → 1.825% 年化）
        return v * DAY_BASIS / 100
    if kind == "lpr_plus_bp":
        return base + v / 100
    if kind == "lpr_multiple":
        return base * v
    raise ValueError(f"未知的利率口径: {kind}")


def platform_to_annual(rate, kind: str, lpr1y: float = DEFAULT_LPR_1Y) -> float:
    """网贷平台利率口径换算，复用 :func:`normalize_to_annual`。"""
    return normalize_to_annual(rate, kind, lpr1y=lpr1y)


def breakdown(annual_pct) -> dict:
    """年化 → 年/月/日三个口径（SPEC 3.7-2）。"""
    a = _finite(annual_pct, "年化利率")
    return {
        "annualPct": _r6(a),
        "monthlyPct": _r6(a / 12),
        "dailyPct": _r6(a / DAY_BASIS),
    }


# ======================================================================================
# 三、每日利息与收益率对比（SPEC 3.2 / 3.7-3,4）
# ======================================================================================
def daily_interest(principal, annual_pct, days=365, compound: bool = False) -> dict:
    """每日/每月/每年/期间利息（单利；``compound=True`` 时期间利息走复利）。"""
    p = _positive(principal, "本金")
    a = _annual_pct(annual_pct)
    d = _days(days)
    per_day = p * a / 100 / DAY_BASIS
    if compound:
        # 复利必须以「日」为计息周期：日利率 = 年化 / 365，终值 = P*(1+i)^d。
        # 旧实现误把「年」当周期写成 (1+年化)^(d/365)，导致复利反而小于单利。
        if d / DAY_BASIS > _COMPOUND_MAX_YEARS:
            raise ValueError("复利计算的天数过大")
        period = p * ((1 + a / 100 / DAY_BASIS) ** d - 1)
    else:
        period = per_day * d
    return {
        "principal": p,
        "annualPct": _r6(a),
        "days": d,
        "daily": ROUND(per_day),
        "monthly": ROUND(p * a / 100 / 12),
        "annual": ROUND(p * a / 100),
        "periodInterest": ROUND(period),
        "compound": bool(compound),
    }


def compare_rates(principal, annual_pct_a, annual_pct_b, days=365, compound: bool = False) -> dict:
    """两个收益率并排对比（SPEC 3.7-4）。"""
    a_pct = _annual_pct(annual_pct_a, "A 的年化利率")
    b_pct = _annual_pct(annual_pct_b, "B 的年化利率")
    res_a = daily_interest(principal, a_pct, days, compound=compound)
    res_b = daily_interest(principal, b_pct, days, compound=compound)

    if abs(a_pct - b_pct) < 1e-12:
        better = "equal"
    elif b_pct > a_pct:
        better = "b"
    else:
        better = "a"

    ratio = None if res_a["daily"] == 0 else _r6(res_b["daily"] / res_a["daily"])
    return {
        "a": res_a,
        "b": res_b,
        "principal": res_a["principal"],
        "days": res_a["days"],
        "diffDaily": ROUND(res_b["daily"] - res_a["daily"]),
        "diffMonthly": ROUND(res_b["monthly"] - res_a["monthly"]),
        "diffAnnual": ROUND(res_b["annual"] - res_a["annual"]),
        "diffPeriod": ROUND(res_b["periodInterest"] - res_a["periodInterest"]),
        "better": better,
        "higherAnnualPct": _r6(max(a_pct, b_pct)),
        "lowerAnnualPct": _r6(min(a_pct, b_pct)),
        "ratio": ratio,
    }


# ======================================================================================
# 四、贷款分期（SPEC 3.3 / 3.7-5..10）
#
# 舍入口径（两端必须一致，且同时满足 SPEC 3.7 的闭合约束）：
#   * 每期「月供」= ROUND(理论月供)，全程固定；
#   * 每期「利息」= ROUND(上期剩余本金 × 月利率)；
#   * 每期「本金」= ROUND(月供 − 利息)；
#   * 最后一期「本金」= 当期剩余本金（强制结平，消除浮点误差），
#     并且保持月供不变，差额吸收进最后一期利息（= 月供 − 本金）。
#   由此三个等式同时成立，且逐行满足 payment == principal + interest：
#     Σ每期本金 == principal
#     Σ每期利息 == totalInterest
#     Σ每期还款额 == totalPayment == payment × months
# ======================================================================================
def _loan_envelope(method: str, principal: float, annual_pct: float, months: int) -> dict:
    monthly_rate = annual_pct / 100 / 12
    return {
        "method": method,
        "principal": ROUND(principal),
        "annualPct": _r6(annual_pct),
        "months": months,
        "monthlyRate": _r6(monthly_rate),
        "payment": 0.0,
        "totalPayment": 0.0,
        "totalInterest": 0.0,
        "schedule": [],
    }


def _finalize(result: dict) -> dict:
    """按 schedule 回算汇总字段，保证与逐期明细逐分一致。

    ``totalPayment`` = Σ每期还款额，满足 §3.7 的 ``Σpayment == totalPayment``；
    ``totalInterest`` = Σ每期利息；
    ``totalPrincipal`` = Σ每期本金，恒等于本金（最后一期结平）；
    ``totalRepayment`` = totalPayment（还款总额，已含本金），供界面展示。
    """
    schedule = result["schedule"]
    total_payment = sum(row["payment"] for row in schedule)
    total_principal = sum(row["principal"] for row in schedule)
    result["totalPayment"] = ROUND(total_payment)
    result["totalInterest"] = ROUND(sum(row["interest"] for row in schedule))
    result["totalPrincipal"] = ROUND(total_principal)
    result["totalRepayment"] = ROUND(total_payment)
    return result


def equal_installment(principal, annual_pct, months) -> dict:
    """等额本息（SPEC 3.7-5）。"""
    p = _positive(principal, "本金")
    a = _annual_pct(annual_pct)
    n = _months(months)
    i = a / 100 / 12

    if i == 0:
        payment = ROUND(p / n)
    else:
        growth = (1 + i) ** n
        payment = ROUND(p * i * growth / (growth - 1))

    result = _loan_envelope("equal_installment", p, a, n)
    result["payment"] = payment

    if i == 0:
        # 零利率（免息分期）：不允许产生任何利息。
        # 本金不能被期数整除到「分」时，无法同时做到「月供恒定」与「逐分结清」，
        # 这里按银行真实账单的做法：前 n-1 期等额，最后一期用差额调整（仍是本金，不装成利息）。
        total_cents = int(round(ROUND(p) * 100))
        base_cents = total_cents // n
        tail_cents = total_cents - base_cents * (n - 1)
        schedule = []
        remaining_cents = total_cents
        for period in range(1, n + 1):
            cents = base_cents if period < n else tail_cents
            remaining_cents -= cents
            schedule.append(
                {
                    "period": period,
                    "payment": cents / 100,
                    "principal": cents / 100,
                    "interest": 0.0,
                    "remaining": 0.0 if period == n else max(remaining_cents, 0) / 100,
                }
            )
        result["schedule"] = schedule
        return _finalize(result)

    remaining = ROUND(p)
    schedule = []
    for period in range(1, n + 1):
        if period == n:
            # 最后一期：本金结平（= 剩余本金），还款额保持固定，差额吸收进末期利息。
            # 这样 Σ每期还款额 == 月供 × 期数，且 Σ每期本金 == 本金、Σ每期利息 == 总利息。
            row_principal = remaining
            row_payment = payment
            row_interest = ROUND(row_payment - row_principal)
            if row_interest < 0:  # pragma: no cover - 极小本金/极高利率的退化保护
                row_payment = ROUND(row_principal + max(row_interest, 0.0))
                row_interest = max(row_interest, 0.0)
        else:
            row_interest = ROUND(remaining * i)
            row_principal = ROUND(payment - row_interest)
            # 极小本金/极小月供时，四舍五入可能算出负本金 → 夹紧，保证单调还本
            if row_principal < 0:
                row_principal = 0.0
            if row_principal > remaining:
                row_principal = remaining
            row_payment = ROUND(row_principal + row_interest)
        remaining = ROUND(remaining - row_principal)
        schedule.append(
            {
                "period": period,
                "payment": row_payment,
                "principal": row_principal,
                "interest": row_interest,
                "remaining": 0.0 if period == n else remaining,
            }
        )
    result["schedule"] = schedule
    return _finalize(result)


def equal_principal(principal, annual_pct, months) -> dict:
    """等额本金（SPEC 3.7-6）。"""
    p = _positive(principal, "本金")
    a = _annual_pct(annual_pct)
    n = _months(months)
    i = a / 100 / 12
    per_principal = ROUND(p / n)

    result = _loan_envelope("equal_principal", p, a, n)
    remaining = ROUND(p)
    schedule = []
    for period in range(1, n + 1):
        interest = ROUND(remaining * i)
        row_principal = remaining if period == n else per_principal
        if period == n and row_principal > remaining:  # pragma: no cover - 防御
            row_principal = remaining
        remaining = ROUND(remaining - row_principal)
        schedule.append(
            {
                "period": period,
                "payment": ROUND(row_principal + interest),
                "principal": row_principal,
                "interest": interest,
                "remaining": 0.0 if period == n else remaining,
            }
        )
    result["payment"] = schedule[0]["payment"]
    result["schedule"] = schedule
    return _finalize(result)


def interest_first(principal, annual_pct, months) -> dict:
    """先息后本（SPEC 3.7-7）。"""
    p = _positive(principal, "本金")
    a = _annual_pct(annual_pct)
    n = _months(months)
    per_interest = ROUND(p * a / 100 / 12)

    result = _loan_envelope("interest_first", p, a, n)
    result["payment"] = per_interest
    schedule = []
    for period in range(1, n + 1):
        is_last = period == n
        row_principal = ROUND(p) if is_last else 0.0
        schedule.append(
            {
                "period": period,
                "payment": ROUND(row_principal + per_interest),
                "principal": row_principal,
                "interest": per_interest,
                "remaining": 0.0 if is_last else ROUND(p),
            }
        )
    result["schedule"] = schedule
    return _finalize(result)


def bullet(principal, annual_pct, months) -> dict:
    """到期一次还本付息（单利、按月计息，SPEC 3.7-8）。"""
    p = ROUND(_positive(principal, "本金"))
    a = _annual_pct(annual_pct)
    n = _months(months)
    total_interest = ROUND(p * a / 100 / 12 * n)

    result = _loan_envelope("bullet", p, a, n)
    schedule = []
    for period in range(1, n + 1):
        is_last = period == n
        schedule.append(
            {
                "period": period,
                "payment": ROUND(p + total_interest) if is_last else 0.0,
                "principal": p if is_last else 0.0,
                "interest": total_interest if is_last else 0.0,
                "remaining": 0.0 if is_last else p,
            }
        )
    result["schedule"] = schedule
    _finalize(result)
    result["payment"] = result["schedule"][-1]["payment"]  # 到期应还总额（含本金）
    return result


LOAN_METHODS = {
    "equal_installment": equal_installment,
    "equal_principal": equal_principal,
    "interest_first": interest_first,
    "bullet": bullet,
}

LOAN_METHOD_LABELS = {
    "equal_installment": "等额本息",
    "equal_principal": "等额本金",
    "interest_first": "先息后本",
    "bullet": "到期一次还本付息",
}


def loan_schedule(principal, annual_pct, months, method: str = "equal_installment") -> dict:
    """贷款分期统一入口（SPEC 3.7-9）。"""
    if method not in LOAN_METHODS:
        raise ValueError(f"未知的还款方式: {method}")
    return LOAN_METHODS[method](principal, annual_pct, months)


def schedule_summary(schedule) -> dict:
    """逐期明细汇总（SPEC 3.7-10）。"""
    if not isinstance(schedule, (list, tuple)) or not schedule:
        raise ValueError("还款计划不能为空")
    payments = [_finite(row["payment"], "月供") for row in schedule]
    interests = [_finite(row["interest"], "利息") for row in schedule]
    total_payment = ROUND(sum(payments))
    total_interest = ROUND(sum(interests))
    return {
        "months": len(schedule),
        "totalPayment": total_payment,
        "totalInterest": total_interest,
        "firstPayment": ROUND(payments[0]),
        "lastPayment": ROUND(payments[-1]),
        "avgPayment": ROUND(total_payment / len(schedule)),
        "principalPart": ROUND(total_payment - total_interest),
    }


# ======================================================================================
# 五、网贷 / 日还款（SPEC 3.4 / 3.7-11,12）
# ======================================================================================
def daily_payment(principal, annual_pct, days) -> dict:
    """按天计息、按天还本（SPEC 3.7-11）。"""
    p = _positive(principal, "本金")
    a = _annual_pct(annual_pct)
    d = _days(days)
    daily_interest = ROUND(p * a / 100 / DAY_BASIS)
    daily_principal = ROUND(p / d)
    return {
        "principal": ROUND(p),
        "annualPct": _r6(a),
        "days": d,
        "dailyInterest": daily_interest,
        "dailyPrincipal": daily_principal,
        "dailyPayment": ROUND(daily_interest + daily_principal),
        "totalDays": d,
        "totalInterest": ROUND(daily_interest * d),
        "totalPayment": ROUND(ROUND(p) + daily_interest * d),
    }


ONLINE_LOAN_METHODS = ("interest_first", "equal_installment_daily")

ONLINE_LOAN_METHOD_LABELS = {
    "interest_first": "每日还息、到期还本",
    "equal_installment_daily": "每日等额本息",
}


def online_loan(principal, annual_pct, days, method: str = "interest_first") -> dict:
    """网贷：每日还息到期还本 / 每日等额本息（SPEC 3.7-12）。"""
    if method not in ONLINE_LOAN_METHODS:
        raise ValueError(f"未知的网贷还款方式: {method}")

    p = _positive(principal, "本金")
    a = _annual_pct(annual_pct)
    d = _days(days)
    i = a / 100 / DAY_BASIS
    daily_interest = ROUND(p * i)

    if method == "interest_first":
        schedule = []
        for day in range(1, d + 1):
            is_last = day == d
            row_principal = ROUND(p) if is_last else 0.0
            row_payment = ROUND(row_principal + daily_interest)
            schedule.append(
                {
                    "day": day,
                    "payment": row_payment,
                    "principal": row_principal,
                    "interest": daily_interest,
                    "remaining": 0.0 if is_last else ROUND(p),
                }
            )
        total_interest = ROUND(daily_interest * d)
        return {
            "method": method,
            "principal": ROUND(p),
            "annualPct": _r6(a),
            "days": d,
            "dailyInterest": daily_interest,
            "dailyPayment": ROUND(ROUND(p) + total_interest) if d == 1 else daily_interest,
            "totalInterest": total_interest,
            "totalPayment": ROUND(ROUND(p) + total_interest),
            "schedule": schedule,
        }

    # 每日等额本息：i = 年化/100/365，最后一期结平
    if i == 0:
        payment = ROUND(p / d)
    else:
        growth = (1 + i) ** d
        payment = ROUND(p * i * growth / (growth - 1))

    schedule = []
    remaining = ROUND(p)
    for day in range(1, d + 1):
        interest = ROUND(remaining * i)
        if day == d:
            row_principal = remaining
            row_interest = ROUND(payment - row_principal)
        else:
            row_principal = ROUND(payment - interest)
            row_interest = interest
        remaining = ROUND(remaining - row_principal)
        schedule.append(
            {
                "day": day,
                "payment": payment,
                "principal": row_principal,
                "interest": row_interest,
                "remaining": 0.0 if day == d else remaining,
            }
        )

    total_payment = ROUND(sum(row["payment"] for row in schedule))
    total_interest = ROUND(sum(row["interest"] for row in schedule))
    return {
        "method": method,
        "principal": ROUND(p),
        "annualPct": _r6(a),
        "days": d,
        "dailyInterest": daily_interest,
        "dailyPayment": payment,
        "totalInterest": total_interest,
        "totalPayment": total_payment,
        "schedule": schedule,
    }


# ======================================================================================
# 六、折算工具（SPEC 3.5 / 3.7-13..16）
# ======================================================================================
def _npv(rate: float, cashflows) -> float:
    """净现值 NPV(rate) = Σ cf_i / (1+rate)^i。

    使用 Horner 形式求值，避免直接计算 ``(1+rate)**i``：
    期数很大（如网贷 365 天）且 rate 接近 -1 时，``(1+rate)**i`` 会下溢到 0 并触发除零。
    Horner 只用除法，极端情况下得到 ±inf 而不是抛异常，二分法依然能靠符号收敛。
    """
    n = len(cashflows)
    if n == 1:
        return float(cashflows[0])
    q = 1.0 + rate
    if q <= 0.0:  # 二分区间下界为 -0.999999，理论上不会落到这里
        q = 1e-12
    acc = float(cashflows[-1])
    for amount in reversed(cashflows[1:-1]):
        acc = amount + acc / q
    try:
        return float(cashflows[0]) + acc / q
    except (OverflowError, ZeroDivisionError):  # pragma: no cover - 防御
        return math.copysign(float("inf"), cashflows[-1])


def irr(cashflows) -> float:
    """通用 IRR（二分法，区间 [-0.999999, 10]，200 次迭代，精度 1e-12）。"""
    if not isinstance(cashflows, (list, tuple)) or len(cashflows) < 2:
        raise ValueError("现金流至少需要 2 个")
    flows = [_finite(x, "现金流") for x in cashflows]
    if all(x >= 0 for x in flows) or all(x <= 0 for x in flows):
        raise ValueError("现金流必须同时包含正负值")

    low, high = -0.999999, 10.0
    f_low, f_high = _npv(low, flows), _npv(high, flows)
    # 端点可能是 ±inf（期数极大时的溢出），NaN 视为无解
    if math.isnan(f_low) or math.isnan(f_high):
        raise ValueError("该现金流没有可求的内部收益率")
    if f_low * f_high > 0:
        raise ValueError("该现金流没有可求的内部收益率")

    midpoint = (low + high) / 2
    for _ in range(200):
        midpoint = (low + high) / 2
        f_mid = _npv(midpoint, flows)
        if abs(f_mid) < 1e-12:
            return midpoint
        if f_low * f_mid <= 0:
            high, f_high = midpoint, f_mid
        else:
            low, f_low = midpoint, f_mid
        if abs(high - low) < 1e-12:
            break
    return midpoint


def apr_from_fee(principal, monthly_fee_pct, months) -> dict:
    """分期手续费口径 → 真实年化（IRR，SPEC 3.7-14）。"""
    p = _positive(principal, "本金")
    fee = _non_negative(monthly_fee_pct, "月费率")
    n = _months(months)

    monthly_fee = p * fee / 100
    installment = p / n + monthly_fee
    flows = [p] + [-installment] * n
    monthly_irr = irr(flows)
    apr_annual = ((1 + monthly_irr) ** 12 - 1) * 100
    total_fee = ROUND(monthly_fee * n)

    return {
        "principal": ROUND(p),
        "monthlyFeePct": _r6(fee),
        "months": n,
        "monthlyIrr": _r6(monthly_irr),
        "aprAnnual": _r6(apr_annual),
        "aprSimple": _r6(fee * 12),
        "totalFee": total_fee,
        "totalPayment": ROUND(ROUND(p) + total_fee),
        "monthlyPayment": ROUND(installment),
    }


def effective_annual(annual_pct, compounds_per_year) -> float:
    """有效年利率（SPEC 3.7-15）。"""
    a = _finite(annual_pct, "年化利率")
    n_raw = _finite(compounds_per_year, "复利次数")
    n = int(round(n_raw))
    if n < 1:
        raise ValueError("每年复利次数必须大于等于 1")
    if n > 36500:
        raise ValueError("每年复利次数过大")
    rate = a / 100
    return ((1 + rate / n) ** n - 1) * 100


def convert(value, kind: str = "annual_pct", **opts) -> dict:
    """任意口径 → 全口径对照表（SPEC 3.7-16）。"""
    annual = normalize_to_annual(
        value, kind, min=opts.get("min"), max=opts.get("max"), lpr1y=opts.get("lpr1y", DEFAULT_LPR_1Y)
    )
    if annual < 0:
        raise ValueError("换算出的年化利率不能为负数")
    return {
        "annualPct": _r6(annual),
        "monthlyPct": _r6(annual / 12),
        "dailyPct": _r6(annual / DAY_BASIS),
        "monthlyFen": _r6(annual / 12),
        "annualFen": _r6(annual / 10),
        "monthlyLi": _r6(annual / 12 / 0.1),
        "annualLi": _r6(annual),
        "monthlyHao": _r6(annual / 12 / 0.01),
        "dailyWan": _r6(annual / 100 / DAY_BASIS * 10000),
        "basisPoints": _r6(annual * 100),
        "kind": kind,
        "inputValue": None if value is None else _r6(value),
    }


# ======================================================================================
# 七、利率数据（SPEC 第 6 节）
# ======================================================================================
GROUPS = [
    {"id": "official", "title": "官方口径（央行/银行）", "desc": "LPR、存款挂牌、房贷、公积金、信用卡等官方或银行公布口径"},
    {"id": "customary", "title": "民间叫法（分/厘/毫/日息万几）", "desc": "月息几分几厘、日息万几等口语，按 365 天基准换算"},
    {"id": "deposit", "title": "存款/理财", "desc": "货币基金 7 日年化、银行理财业绩基准、国债等"},
    {"id": "loan", "title": "贷款/房贷", "desc": "经营贷、消费贷、车贷与住房贷款常见利率"},
    {"id": "online_loan", "title": "网贷/消费金融", "desc": "主流平台日息区间，实际以授信合同为准"},
]

#: 内置最小数据集（≥15 条代表性利率，schema 与 data/rates.json 完全一致）。
#: data/rates.json 缺失、损坏或仍是占位内容时自动启用，保证软件开箱可用。
BUILTIN_RATES = {
    "meta": {
        "version": 1,
        "updated": "2026-10-23",
        "currency": "CNY",
        "lpr": {"1y": 3.0, "5y": 3.5},
        "judicial_cap_multiple": 4,
        "disclaimer": "内置最小数据集，仅供估算参考；实际利率以金融机构合同为准。",
        "sources": [{"title": "中国人民银行", "url": "https://www.pbc.gov.cn/", "note": "LPR 与基准利率"}],
        "builtin": True,
    },
    "groups": GROUPS,
    "rates": [
        {
            "id": "lpr-1y", "group": "official", "name": "LPR（1年期）",
            "aliases": ["LPR", "贷款市场报价利率", "一年期LPR"],
            "kind": "annual_pct", "value": 3.0, "display": "3.00% 年化",
            "asOf": "2026-10-23", "note": "全国银行间同业拆借中心公布的贷款市场报价利率（1年期）。",
            "warning": None, "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "lpr-5y", "group": "official", "name": "LPR（5年期以上）",
            "aliases": ["LPR5年", "五年期LPR", "房贷LPR"],
            "kind": "annual_pct", "value": 3.5, "display": "3.50% 年化",
            "asOf": "2026-10-23", "note": "5 年期以上 LPR，房贷利率的主要定价基准。",
            "warning": None, "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "lpr-1y-plus-60bp", "group": "official", "name": "LPR + 60 基点（1年期）",
            "aliases": ["加基点", "BP", "LPR加点"],
            "kind": "lpr_plus_bp", "value": 60, "display": "3.60% 年化",
            "asOf": "2026-10-23", "note": "1 个基点 = 0.01%。60BP 即在 LPR 基础上加 0.60%。",
            "warning": None, "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "lpr-1y-x1-1", "group": "official", "name": "LPR 的 1.1 倍（1年期）",
            "aliases": ["LPR倍数", "上浮10%"],
            "kind": "lpr_multiple", "value": 1.1, "display": "3.30% 年化",
            "asOf": "2026-10-23", "note": "历史浮动利率常用「LPR×倍数」表述。",
            "warning": None, "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "deposit-1y", "group": "official", "name": "银行 1 年期定存挂牌",
            "aliases": ["定期存款", "一年定存", "存款利率"],
            "kind": "annual_pct", "value": 1.1, "display": "1.10% 年化",
            "asOf": "2026-10-23", "note": "大型银行 1 年期整存整取挂牌利率参考值。",
            "warning": None, "source": "https://www.icbc.com.cn/",
        },
        {
            "id": "housing-fund-5y", "group": "official", "name": "住房公积金贷款（5年以上）",
            "aliases": ["公积金", "公积金贷款", "首套公积金"],
            "kind": "annual_pct", "value": 2.6, "display": "2.60% 年化",
            "asOf": "2026-10-23", "note": "5 年以上公积金贷款基准利率，各地可上浮。",
            "warning": None, "source": "https://www.mohurd.gov.cn/",
        },
        {
            "id": "credit-card-overdue", "group": "official", "name": "信用卡透支（日息万分之五）",
            "aliases": ["信用卡", "日息万5", "万分之五"],
            "kind": "daily_wan", "value": 5, "display": "日息万5 ≈ 18.25% 年化",
            "asOf": "2026-10-23", "note": "信用卡透支利息通常按日息万分之五计收。",
            "warning": "年化约 18.25%，高于多数消费贷。", "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "judicial-24", "group": "customary", "name": "综合融资成本红线 24%",
            "aliases": ["24%", "红线", "司法保护上限"],
            "kind": "annual_pct", "value": 24.0, "display": "24.00% 年化",
            "asOf": "2026-10-23", "note": "民间借贷综合融资成本常见的监管参考红线。",
            "warning": "超过 24% 需警惕。", "source": "https://www.court.gov.cn/",
        },
        {
            "id": "judicial-36", "group": "customary", "name": "高利贷口径 36%",
            "aliases": ["36%", "高利贷", "四倍LPR上限"],
            "kind": "annual_pct", "value": 36.0, "display": "36.00% 年化",
            "asOf": "2026-10-23", "note": "超过 36% 通常被认定为高利贷口径。",
            "warning": "超过 36% 属于高利贷区间。", "source": "https://www.court.gov.cn/",
        },
        {
            "id": "custom-monthly-1fen", "group": "customary", "name": "月息 1 分",
            "aliases": ["月息1分", "一分利", "月一分"],
            "kind": "monthly_fen", "value": 1.0, "display": "月息1分 ≈ 12.00% 年化",
            "asOf": "2026-10-23", "note": "「月息1分」= 1%/月 = 12%/年；若理解成「年息1分」则只有 10%/年，务必确认口径。",
            "warning": "「1分」是月息还是年息，结果差 20%，签约前要问清。", "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "custom-monthly-5li", "group": "customary", "name": "月息 5 厘",
            "aliases": ["月息5厘", "五厘", "0.5分"],
            "kind": "monthly_li", "value": 5.0, "display": "月息5厘 = 0.5%/月 ≈ 6.00% 年化",
            "asOf": "2026-10-23", "note": "1 厘 = 0.1%/月，5 厘即 0.5%/月。",
            "warning": None, "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "custom-monthly-5hao", "group": "customary", "name": "月息 5 毫",
            "aliases": ["月息5毫", "五毫", "0.05%/月"],
            "kind": "monthly_hao", "value": 5.0, "display": "月息5毫 = 0.05%/月 ≈ 0.60% 年化",
            "asOf": "2026-10-23", "note": "1 毫 = 0.01%/月，5 毫即 0.05%/月。",
            "warning": None, "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "custom-daily-3-li", "group": "customary", "name": "日息万3（万三）",
            "aliases": ["日息万3", "万三", "0.03%/日"],
            "kind": "daily_wan", "value": 3, "display": "日息万3 ≈ 10.95% 年化",
            "asOf": "2026-10-23", "note": "1 万本金每天 3 元利息，年化 = 3×365/100 = 10.95%。",
            "warning": None, "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "deposit-moneyfund-7d", "group": "deposit", "name": "货币基金 7 日年化",
            "aliases": ["余额宝", "货币基金", "7日年化", "活期理财"],
            "kind": "annual_pct", "value": 1.35, "display": "1.35% 年化",
            "asOf": "2026-10-23", "note": "7 日年化收益率是近 7 天收益折算的年化，会波动。",
            "warning": None, "source": "https://www.amac.org.cn/",
        },
        {
            "id": "deposit-3y-treasury", "group": "deposit", "name": "储蓄国债（3年期）",
            "aliases": ["国债", "储蓄国债", "三年国债"],
            "kind": "annual_pct", "value": 2.38, "display": "2.38% 年化",
            "asOf": "2026-10-23", "note": "储蓄国债（电子式）票面利率参考值。",
            "warning": None, "source": "https://www.mof.gov.cn/",
        },
        {
            "id": "loan-mortgage-5y", "group": "loan", "name": "首套房贷（LPR 基准）",
            "aliases": ["房贷", "按揭", "住房贷款", "首套房贷"],
            "kind": "annual_pct", "value": 3.5, "display": "3.50% 年化",
            "asOf": "2026-10-23", "note": "按 5 年期以上 LPR 计算的房贷利率参考。",
            "warning": None, "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "loan-biz-1y", "group": "loan", "name": "经营贷（1年期）",
            "aliases": ["经营贷", "企业贷", "小微企业贷"],
            "kind": "annual_pct", "value": 3.45, "display": "3.45% 年化",
            "asOf": "2026-10-23", "note": "银行小微企业普惠型经营贷利率参考区间下限附近。",
            "warning": None, "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "loan-consumer", "group": "loan", "name": "银行消费贷",
            "aliases": ["消费贷", "信用贷", "个人消费贷款"],
            "kind": "annual_pct", "value": 5.5, "display": "5.50% 年化",
            "asOf": "2026-10-23", "note": "银行个人消费贷款常见年化区间中值。",
            "warning": None, "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "loan-car", "group": "loan", "name": "车贷（3年期）",
            "aliases": ["车贷", "汽车贷款", "购车分期"],
            "kind": "annual_pct", "value": 4.5, "display": "4.50% 年化",
            "asOf": "2026-10-23", "note": "新车分期名义年化参考值，注意另有手续费。",
            "warning": None, "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "online-common-range", "group": "online_loan", "name": "主流网贷日息区间（万2~万6）",
            "aliases": ["网贷", "消费金融", "日息区间", "万2-万6"],
            "kind": "range_daily_wan", "min": 2.0, "max": 6.0, "display": "日息万2~万6 ≈ 7.30%~21.90% 年化",
            "asOf": "2026-10-23", "note": "取区间中值万4，折算年化 = 4×365/100 = 14.60%。",
            "warning": "区间上限年化已接近 22%，务必看清综合成本。", "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "online-platform-a", "group": "online_loan", "name": "某头部平台（日息万3.5）",
            "aliases": ["借呗", "花呗分期", "头部平台"],
            "kind": "daily_wan", "value": 3.5, "display": "日息万3.5 ≈ 12.78% 年化",
            "asOf": "2026-10-23", "note": "平台日息因人而异，以实际授信页面展示为准。",
            "warning": None, "source": "https://www.pbc.gov.cn/",
        },
        {
            "id": "online-platform-b", "group": "online_loan", "name": "消费金融公司（年化区间 7.2%~24%）",
            "aliases": ["消费金融", "消金", "持牌机构"],
            "kind": "range_annual_pct", "min": 7.2, "max": 24.0, "display": "7.20%~24.00% 年化",
            "asOf": "2026-10-23", "note": "取区间中值 15.60%；持牌消费金融公司常见定价区间。",
            "warning": "区间上限触及 24% 综合融资成本红线。", "source": "https://www.cbirc.gov.cn/",
        },
    ],
}


def _rate_paths():
    """按优先级给出 rates.json 的候选路径（兼容 PyInstaller 单文件模式）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    paths = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        paths.append(os.path.join(meipass, "data", "rates.json"))
        paths.append(os.path.join(meipass, "rates.json"))
    paths.append(os.path.join(here, "..", "data", "rates.json"))
    paths.append(os.path.join(here, "data", "rates.json"))
    return [os.path.normpath(p) for p in paths]


def _dataset_is_usable(data) -> bool:
    """判断 rates.json 是否是「有内容」的数据集（排除占位/空文件）。"""
    if not isinstance(data, dict):
        return False
    rates = data.get("rates")
    if not isinstance(rates, list) or len(rates) < 5:
        return False
    for rate in rates:
        if not isinstance(rate, dict):
            continue
        if str(rate.get("id", "")).startswith("placeholder"):
            continue
        if rate.get("name") and rate.get("kind"):
            return True
    return False


def load_rates():
    """读取 data/rates.json；返回 ``(dataset, source_description)``。

    失败时返回内置最小数据集，source 说明原因，界面据此提示用户。
    """
    for path in _rate_paths():
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if _dataset_is_usable(data):
            data.setdefault("meta", {})
            data["meta"]["builtin"] = False
            return data, f"data/rates.json（{len(data['rates'])} 条） · {path}"
    return json.loads(json.dumps(BUILTIN_RATES)), "内置最小数据集（未找到可用的 data/rates.json）"


def get_rate_dataset():
    """兼容用法：只要数据集。"""
    return load_rates()[0]


def _dataset_lpr(dataset) -> float:
    try:
        value = float((dataset.get("meta") or {}).get("lpr", {}).get("1y", DEFAULT_LPR_1Y))
    except (TypeError, ValueError):
        return DEFAULT_LPR_1Y
    return value if math.isfinite(value) and value >= 0 else DEFAULT_LPR_1Y


def build_rate_options(dataset) -> list:
    """把 rates 数组展开成界面用的下拉选项（含分组前缀与折算后的年化）。"""
    lpr1y = _dataset_lpr(dataset)
    group_titles = {g.get("id"): g.get("title", g.get("id", "")) for g in dataset.get("groups", []) if isinstance(g, dict)}
    order = {g.get("id"): index for index, g in enumerate(dataset.get("groups", [])) if isinstance(g, dict)}
    options = []
    for rate in dataset.get("rates", []):
        if not isinstance(rate, dict):
            continue
        gid = rate.get("group", "")
        if str(rate.get("id", "")).startswith("placeholder"):
            continue
        kind = rate.get("kind", "annual_pct")
        try:
            annual = normalize_to_annual(
                rate.get("value"), kind, min=rate.get("min"), max=rate.get("max"), lpr1y=lpr1y
            )
        except (ValueError, TypeError):
            continue
        short = GROUP_SHORT.get(gid, "")
        prefix = f"[{short}] " if short else ""
        aliases = [str(a) for a in (rate.get("aliases") or []) if a]
        options.append(
            {
                "id": rate.get("id", ""),
                "group": gid,
                "groupTitle": group_titles.get(gid, gid),
                "groupOrder": order.get(gid, 99),
                "name": str(rate.get("name", "")),
                "label": f"{prefix}{rate.get('name', '')}",
                "aliases": aliases,
                "kind": kind,
                "kindLabel": KIND_LABELS.get(kind, kind),
                "value": rate.get("value"),
                "min": rate.get("min"),
                "max": rate.get("max"),
                "annual": annual,
                "display": rate.get("display") or f"{annual:.2f}% 年化",
                "asOf": rate.get("asOf", ""),
                "note": rate.get("note", ""),
                "warning": rate.get("warning"),
                "source": rate.get("source", ""),
            }
        )
    options.sort(key=lambda item: (item["groupOrder"], item["annual"]))
    return options


# ======================================================================================
# 八、界面工具
# ======================================================================================
def _pick_font(candidates, fallback="TkDefaultFont"):
    try:
        available = set(tkfont.families())
    except Exception:  # pragma: no cover
        return fallback
    for name in candidates:
        if name in available:
            return name
    return fallback


def fmt_money(value, sign: bool = False) -> str:
    """金额格式化：``¥1,234.56``；``sign=True`` 时正数带 ``+``。"""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(amount):
        return "—"
    text = f"{abs(amount):,.2f}"
    if amount < 0:
        return f"-¥{text}"
    if sign and amount > 0:
        return f"+¥{text}"
    return f"¥{text}"


def fmt_pct(value, digits: int = 2, sign: bool = False) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(amount):
        return "—"
    prefix = "+" if sign and amount > 0 else ""
    return f"{prefix}{amount:,.{digits}f}%"


def fmt_num(value, digits: int = 4) -> str:
    """自由数字：去掉多余的 0，最多保留 digits 位小数。"""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(amount):
        return ""
    text = f"{amount:.{digits}f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def parse_number(text, name: str = "输入"):
    """解析输入框数字：容忍千分位、¥、空格与中文全角。"""
    if text is None:
        raise ValueError(f"请输入{name}")
    cleaned = str(text).strip()
    for token in (",", "，", "¥", "￥", " ", "\u00a0"):
        cleaned = cleaned.replace(token, "")
    cleaned = cleaned.replace("%", "")
    if not cleaned:
        raise ValueError(f"请输入{name}")
    try:
        value = float(cleaned)
    except ValueError as exc:
        raise ValueError(f"{name}必须是数字") from exc
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{name}不能是 NaN 或无穷大")
    return value


_CN_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_CN_UNITS = ("", "拾", "佰", "仟")
_CN_SECTIONS = ("", "万", "亿", "万亿")


def cn_upper_amount(amount) -> str:
    """中文大写金额，如 ``10000.5`` → ``壹万元伍角``。"""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(value) or value < 0:
        return ""
    integer = int(round(value * 100)) // 100
    cents = int(round(value * 100)) % 100
    if integer == 0 and cents == 0:
        return "零元整"
    sections = []
    section_index = 0
    rest = integer
    while rest > 0:
        piece = rest % 10000
        if piece:
            text = ""
            zero_pending = False
            for offset in range(4):
                digit = piece // (10 ** offset) % 10
                if digit == 0:
                    if text:
                        zero_pending = True
                    continue
                if zero_pending:
                    text = "零" + text
                    zero_pending = False
                text = _CN_DIGITS[digit] + _CN_UNITS[offset] + text
            sections.append(text + _CN_SECTIONS[section_index])
        else:
            if sections and not sections[-1].startswith("零"):
                sections.append("零")
        rest //= 10000
        section_index += 1
    head = "".join(reversed(sections)).lstrip("零") or "零"
    tail = ""
    if cents == 0:
        tail = "整"
    else:
        jiao, fen = cents // 10, cents % 10
        if jiao:
            tail += f"{_CN_DIGITS[jiao]}角"
        elif fen:
            tail += "零"
        if fen:
            tail += f"{_CN_DIGITS[fen]}分"
    return f"{head}元{tail}"


# ======================================================================================
# 九、无头自检（python app.py --selftest）
# ======================================================================================
class _Recorder:
    """收集自检断言。"""

    def __init__(self):
        self.checks = []

    def close(self, name, actual, expected, tol=0.0, spec="", note="") -> bool:
        try:
            ok = abs(float(actual) - float(expected)) <= abs(tol) + 1e-9
        except (TypeError, ValueError):
            ok = False
        self.checks.append(
            {
                "name": name,
                "spec": spec,
                "expected": expected,
                "actual": actual,
                "tolerance": tol,
                "pass": bool(ok),
                "note": note,
            }
        )
        return ok

    def truth(self, name, condition, detail="", spec="") -> bool:
        ok = bool(condition)
        self.checks.append(
            {"name": name, "spec": spec, "expected": "真", "actual": "真" if ok else "假", "pass": ok, "note": detail}
        )
        return ok

    @property
    def passed(self):
        return sum(1 for item in self.checks if item["pass"])

    @property
    def failed(self):
        return [item for item in self.checks if not item["pass"]]


def run_selftest(verbose: bool = False) -> dict:
    """跑完 SPEC 第 7 节全部公式验收用例，返回 JSON 友好的报告。"""
    rec = _Recorder()
    dataset, source = load_rates()
    options = build_rate_options(dataset)

    # ---- 验收 2：每日利息 ----
    r = daily_interest(10000, 3.65)
    rec.close("本金10000/年化3.65% 每日利息", r["daily"], 1.00, 1e-9, "验收2")
    rec.close("本金10000/年化3.65% 每月利息", r["monthly"], 30.42, 0.005, "验收2")
    rec.close("本金10000/年化3.65% 每年利息", r["annual"], 365.00, 1e-9, "验收2")
    r = daily_interest(10000, 7.3)
    rec.close("本金10000/年化7.30% 每日利息", r["daily"], 2.00, 1e-9, "验收2")
    r = daily_interest(10000, 3.65, 30)
    rec.close("本金10000/3.65%/30天 期间利息", r["periodInterest"], 30.00, 0.005, "验收2")

    # ---- 对比 ----
    cmp = compare_rates(10000, 3.65, 7.3)
    rec.close("A/B 每日差额", cmp["diffDaily"], 1.00, 0.005, "验收2")
    rec.close("A/B 每年差额", cmp["diffAnnual"], 365.00, 0.005, "验收2")
    rec.close("A/B 倍数", cmp["ratio"], 2.0, 0.005, "验收2")
    rec.truth("A/B 谁更高", cmp["better"] == "b", f"better={cmp['better']}", "验收2")

    # ---- 验收 3：100 万 / 4.9% / 30 年 等额本息 ----
    loan = equal_installment(1000000, 4.9, 360)
    rec.close("100万/4.9%/30年 等额本息 月供", loan["payment"], 5307.27, 5307.27 * 0.005, "验收3")
    rec.close("100万/4.9%/30年 总利息", loan["totalInterest"], 910600, 910600 * 0.02, "验收3")
    rec.close(
        "100万/4.9%/30年 总利息=总还款-本金",
        loan["totalInterest"],
        loan["totalRepayment"] - 1000000,
        0.01,
        "验收3",
    )
    rec.close(
        "100万/4.9%/30年 总还款=月供×359+末期",
        loan["totalRepayment"],
        loan["payment"] * 359 + loan["schedule"][-1]["principal"] + loan["schedule"][-1]["interest"],
        0.01,
        "验收3",
    )

    # ---- 验收 4：Σ本金 / Σ利息 闭合 ----
    for label, months, method in (
        ("等额本息 36 期", 36, "equal_installment"),
        ("等额本金 36 期", 36, "equal_principal"),
        ("先息后本 12 期", 12, "interest_first"),
        ("到期还本付息 12 期", 12, "bullet"),
    ):
        res = loan_schedule(50000, 5.6, months, method)
        sched = res["schedule"]
        sum_principal = round(sum(row["principal"] for row in sched), 2)
        sum_interest = round(sum(row["interest"] for row in sched), 2)
        sum_payment = round(sum(row["payment"] for row in sched), 2)
        rec.close(f"{label} Σ每期本金", sum_principal, 50000, 0.005, "验收4")
        rec.close(f"{label} Σ每期利息", sum_interest, res["totalInterest"], 0.005, "验收4")
        rec.close(f"{label} Σ每期月供", sum_payment, res["totalPayment"], 0.005, "验收4")
        rec.close(f"{label} 末期剩余本金", sched[-1]["remaining"], 0.0, 0.005, "验收4")
        rec.close(
            f"{label} 总还款=Σ每期还款额",
            res["totalRepayment"],
            sum_payment,
            0.005,
            "验收4",
        )
        rec.truth(
            f"{label} 各期 本金+利息=还款额",
            all(abs(row["payment"] - (row["principal"] + row["interest"])) < 0.005 for row in sched),
            f"{len(sched)} 期",
            "验收4",
        )

    # 等额本息零利率
    zero = equal_installment(12000, 0, 12)
    rec.close("零利率等额本息 月供", zero["payment"], 1000.0, 0.005, "验收4")
    rec.close("零利率等额本息 总利息", zero["totalInterest"], 0.0, 0.005, "验收4")

    # 等额本金 / 先息后本 / bullet 关键值
    ep = equal_principal(12000, 12, 12)
    rec.close("等额本金 首期月供", ep["schedule"][0]["payment"], 1120.0, 0.005, "3.3")
    rec.close("等额本金 末期月供", ep["schedule"][-1]["payment"], 1010.0, 0.005, "3.3")
    rec.close("等额本金 总利息", ep["totalInterest"], 780.0, 0.005, "3.3")
    if1 = interest_first(10000, 12, 12)
    rec.close("先息后本 总利息", if1["totalInterest"], 1200.0, 0.005, "3.3")
    rec.close("先息后本 末期还款", if1["schedule"][-1]["payment"], 10100.0, 0.005, "3.3")
    bl = bullet(10000, 12, 12)
    rec.close("到期还本付息 总利息", bl["totalInterest"], 1200.0, 0.005, "3.3")
    rec.close("到期还本付息 末期还款", bl["schedule"][-1]["payment"], 11200.0, 0.005, "3.3")

    summary = schedule_summary(loan["schedule"])
    rec.close("汇总 总利息", summary["totalInterest"], loan["totalInterest"], 0.005, "3.7-10")
    rec.close("汇总 期数", summary["months"], 360, 0.0, "3.7-10")

    # ---- 验收 5：手续费 → 真实年化 ----
    apr = apr_from_fee(10000, 0.6, 12)
    rec.close("月费率0.6%×12期 真实年化", apr["aprAnnual"], 13.0, 0.9, "验收5", "SPEC 要求 13.0%~13.9%")
    rec.truth(
        "真实年化落在 12%~15% 区间",
        12.0 < apr["aprAnnual"] < 15.0,
        f"aprAnnual={apr['aprAnnual']:.4f}%",
        "验收5",
    )
    rec.close("名义年化 = 月费率×12", apr["aprSimple"], 7.2, 1e-6, "验收5")
    rec.close("总手续费", apr["totalFee"], 720.0, 0.005, "验收5")
    rec.close("总还款", apr["totalPayment"], 10720.0, 0.005, "验收5")
    rec.close("零手续费真实年化", apr_from_fee(10000, 0.0, 12)["aprAnnual"], 0.0, 0.005, "验收5")

    # ---- 验收 6：网贷 日息万5 ----
    daily = daily_payment(10000, 18.25, 30)
    rec.close("网贷 每日利息", daily["dailyInterest"], 5.00, 0.005, "验收6")
    rec.close("网贷 30天总利息", daily["totalInterest"], 150.00, 0.005, "验收6")
    ol = online_loan(10000, 18.25, 30, "interest_first")
    rec.close("网贷(先息后本) 每日利息", ol["dailyInterest"], 5.00, 0.005, "验收6")
    rec.close("网贷(先息后本) 总利息", ol["totalInterest"], 150.00, 0.005, "验收6")
    rec.close("网贷(先息后本) 总还款", ol["totalPayment"], 10150.00, 0.005, "验收6")
    ol_eq = online_loan(10000, 18.25, 30, "equal_installment_daily")
    rec.close(
        "网贷(每日等额本息) Σ本金",
        round(sum(row["principal"] for row in ol_eq["schedule"]), 2),
        10000,
        0.01,
        "3.7-12",
    )
    rec.close("网贷(每日等额本息) 末期剩余", ol_eq["schedule"][-1]["remaining"], 0.0, 0.005, "3.7-12")

    # ---- 口径换算表（SPEC 第 6 节） ----
    kind_cases = [
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
    for args, expected in kind_cases:
        got = normalize_to_annual(*args)
        rec.close(f"口径换算 {args[1]}", got, expected, 1e-9, "第6节")
    rec.close("区间口径 range_annual_pct", normalize_to_annual(None, "range_annual_pct", min=7.2, max=24.0), 15.6, 1e-9, "第6节")
    rec.close("区间口径 range_daily_wan", normalize_to_annual(None, "range_daily_wan", min=2.0, max=6.0), 14.6, 1e-9, "第6节")

    # 注意：比率统一保留 6 位小数（SPEC 3 节），故容差取 1e-6
    bd = breakdown(3.65)
    rec.close("breakdown 月利率", bd["monthlyPct"], 3.65 / 12, 1e-6, "3.7-2")
    rec.close("breakdown 日利率", bd["dailyPct"], 3.65 / DAY_BASIS, 1e-6, "3.7-2")

    # ---- 折算工具 ----
    rec.close("irr 年金", irr([-1000, 250, 250, 250, 250, 250]), 0.0793, 0.002, "3.7-13")
    rec.close("effective_annual(12,12)", effective_annual(12, 12), 12.6825, 0.005, "3.7-15")
    rec.close("effective_annual(12,1)", effective_annual(12, 1), 12.0, 1e-6, "3.7-15")
    cv = convert(3.65, "annual_pct")
    rec.close("convert 日息万几", cv["dailyWan"], 1.0, 1e-6, "3.7-16")
    rec.close("convert 基点", cv["basisPoints"], 365.0, 1e-6, "3.7-16")
    rec.close("convert 月息分", cv["monthlyFen"], 3.65 / 12, 1e-6, "3.7-16")
    rec.close("convert 年息分", cv["annualFen"], 0.365, 1e-6, "3.7-16")
    rec.close("convert 月息厘", cv["monthlyLi"], 3.65 / 12 / 0.1, 1e-6, "3.7-16")

    # ---- 边界与异常 ----
    bad_inputs = [
        ("本金为 0", lambda: daily_interest(0, 3.65)),
        ("本金为负", lambda: daily_interest(-1, 3.65)),
        ("年化为负", lambda: daily_interest(10000, -1)),
        ("年化为 NaN", lambda: daily_interest(float("nan"), 3.65)),
        ("月数为 0", lambda: equal_installment(10000, 5, 0)),
        ("未知还款方式", lambda: loan_schedule(10000, 5, 12, "nope")),
    ]
    for label, fn in bad_inputs:
        try:
            fn()
            raised = False
        except (ValueError, ZeroDivisionError):
            raised = True
        rec.truth(f"非法输入抛错：{label}", raised, "已抛 ValueError", "3.6")

    # ---- 数据与界面 ----
    rec.truth("内置利率数据集 ≥ 15 条", len(BUILTIN_RATES["rates"]) >= 15, f"{len(BUILTIN_RATES['rates'])} 条", "桌面版5")
    rec.truth("利率下拉选项可用", len(options) >= 15, f"{len(options)} 个选项", "桌面版5")
    rec.truth(
        "内置数据集 5 个分组齐全",
        {g["id"] for g in BUILTIN_RATES["groups"]} == {"official", "customary", "deposit", "loan", "online_loan"},
        "official/customary/deposit/loan/online_loan",
        "第6节",
    )
    rec.truth("tkinter 可用（图形界面）", TK_AVAILABLE, "可用" if TK_AVAILABLE else "不可用，仅能使用 --selftest", "桌面版5")
    rec.truth("大写金额转换", cn_upper_amount(10000.5) == "壹万元伍角", cn_upper_amount(10000.5), "桌面版")

    failed = rec.failed
    report = {
        "ok": not failed,
        "app": "利息计算器桌面版",
        "version": __version__,
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "dayBasis": DAY_BASIS,
        "dataSource": source,
        "rateCount": len(options),
        "gui": {"tkinter": TK_AVAILABLE, "instantiated": False},
        "summary": {"total": len(rec.checks), "passed": rec.passed, "failed": len(failed)},
        "failures": [item["name"] for item in failed],
        "checks": rec.checks,
    }
    if verbose:
        for item in rec.checks:
            flag = "OK  " if item["pass"] else "FAIL"
            print(f"[{flag}] {item['name']}  期望={item['expected']} 实际={item['actual']}", file=sys.stderr)
    return report


# ======================================================================================
# 十、图形界面
# ======================================================================================
_TkBase = tk.Tk if TK_AVAILABLE else object  # type: ignore[misc]


class App(_TkBase):  # type: ignore[misc,valid-type]
    """利息计算器主窗口：单窗口 + ttk.Notebook 五个页签（SPEC 第 5 节）。"""

    PAD = 8
    WIN_W, WIN_H = 1180, 800
    MIN_W, MIN_H = 1024, 700

    #: 亮色系配色（胜出用绿、落败用红、风险提示用橙/红）
    C_BETTER = "#1b7f3b"
    C_WORSE = "#b3261e"
    C_EQUAL = "#5f6368"
    C_HINT = "#5f6368"
    C_WARN = "#ef6c00"
    C_DANGER = "#c62828"
    C_OK = "#2e7d32"
    C_INFO = "#1565c0"

    def __init__(self, dataset=None, source: str = ""):
        if not TK_AVAILABLE:  # pragma: no cover
            raise RuntimeError("当前 Python 缺少 tkinter，无法启动图形界面")
        super().__init__()
        if dataset is None:
            dataset, source = load_rates()
        self.dataset = dataset
        self.data_source = source or "内置最小数据集"
        self.rate_options = build_rate_options(dataset)
        self.lpr1y = _dataset_lpr(dataset)

        self.title("利息计算器 · 桌面版")
        self.minsize(self.MIN_W, self.MIN_H)
        self.geometry(f"{self.WIN_W}x{self.WIN_H}")
        self._debounce_ids = {}
        self._setup_fonts()
        self._setup_style()
        self._build_layout()
        self._refresh_interest()
        self._refresh_loan()
        self._refresh_online()
        self._refresh_convert()
        self._refresh_catalog()

    # ---------------------------------------------------------------- 基础样式
    def _setup_fonts(self):
        ui = _pick_font(["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", "Noto Sans CJK SC"])
        mono = _pick_font(["Cascadia Mono", "Consolas", "SF Mono", "DejaVu Sans Mono", "Courier New"])
        self.font_ui = (ui, 10)
        self.font_ui_bold = (ui, 10, "bold")
        self.font_small = (ui, 9)
        self.font_title = (ui, 16, "bold")
        self.font_h2 = (ui, 11, "bold")
        self.font_metric = (ui, 15, "bold")
        self.font_mono = (mono, 10)
        self.option_add("*Font", self.font_ui)

    def _setup_style(self):
        style = ttk.Style(self)
        for theme in ("vista", "clam", "default"):
            try:
                if theme in style.theme_names():
                    style.theme_use(theme)
                    break
            except tk.TclError:  # pragma: no cover
                continue
        style.configure(".", font=self.font_ui)
        style.configure("TNotebook.Tab", padding=(18, 8), font=self.font_ui_bold)
        style.configure("TLabelframe", padding=self.PAD)
        style.configure("TLabelframe.Label", font=self.font_ui_bold)
        style.configure("Treeview", rowheight=26, font=self.font_mono, fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=self.font_ui_bold)
        style.configure("Metric.TLabel", font=self.font_metric)
        style.configure("Title.TLabel", font=self.font_title)
        style.configure("Hint.TLabel", font=self.font_small, foreground=self.C_HINT)
        style.configure("Accent.TButton", font=self.font_ui_bold)

    # ---------------------------------------------------------------- 布局骨架
    def _build_layout(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(self.PAD * 2, self.PAD, self.PAD * 2, 0))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="利息计算器", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="纯本地计算，不上传任何数据 · 365 天基准 · 金额精确到分",
            style="Hint.TLabel",
        ).grid(row=0, column=1, sticky="w", padx=(self.PAD * 2, 0))
        ttk.Label(header, text=f"利率数据：{self.data_source}", style="Hint.TLabel").grid(row=0, column=2, sticky="e")

        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=self.PAD, pady=self.PAD)

        self.tab_interest = ttk.Frame(self.notebook, padding=self.PAD)
        self.tab_loan = ttk.Frame(self.notebook, padding=self.PAD)
        self.tab_online = ttk.Frame(self.notebook, padding=self.PAD)
        self.tab_convert = ttk.Frame(self.notebook, padding=self.PAD)
        self.tab_catalog = ttk.Frame(self.notebook, padding=self.PAD)
        for frame, text in (
            (self.tab_interest, "利息计算"),
            (self.tab_loan, "贷款计算"),
            (self.tab_online, "网贷计算"),
            (self.tab_convert, "利率换算"),
            (self.tab_catalog, "利率大全"),
        ):
            self.notebook.add(frame, text=f"  {text}  ")

        self.build_interest_tab(self.tab_interest)
        self.build_loan_tab(self.tab_loan)
        self.build_online_tab(self.tab_online)
        self.build_convert_tab(self.tab_convert)
        self.build_catalog_tab(self.tab_catalog)

        self.status_var = tk.StringVar(value="就绪")
        status = ttk.Frame(self, padding=(self.PAD * 2, 0, self.PAD * 2, self.PAD))
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var, style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(status, text=f"v{__version__} · Python {sys.version.split()[0]}", style="Hint.TLabel").grid(
            row=0, column=1, sticky="e"
        )

    # ---------------------------------------------------------------- 通用小部件
    def _metric_card(self, parent, title: str, column: int, row: int = 0, width: int = 18):
        """汇总卡片：标题 + 大字数值，返回用于更新数值的 StringVar。"""
        frame = ttk.LabelFrame(parent, text=title, padding=(self.PAD, 6))
        frame.grid(row=row, column=column, sticky="nsew", padx=(0, self.PAD), pady=(0, self.PAD))
        value = tk.StringVar(value="—")
        ttk.Label(frame, textvariable=value, style="Metric.TLabel").grid(row=0, column=0, sticky="w")
        parent.columnconfigure(column, weight=1)
        return value

    def _make_tree(self, parent, columns, headings, widths, anchors=None, height=10):
        wrapper = ttk.Frame(parent)
        wrapper.columnconfigure(0, weight=1)
        wrapper.rowconfigure(0, weight=1)
        tree = ttk.Treeview(wrapper, columns=columns, show="headings", height=height, selectmode="browse")
        for index, key in enumerate(columns):
            anchor = (anchors or {}).get(key, "center")
            tree.heading(key, text=headings[index])
            tree.column(key, width=widths[index], anchor=anchor, stretch=(index == len(columns) - 1))
        ybar = ttk.Scrollbar(wrapper, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ybar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        return wrapper, tree

    def _rate_labels(self):
        return [option["label"] for option in self.rate_options]

    def _option_by_label(self, label):
        for option in self.rate_options:
            if option["label"] == label:
                return option
        return None

    def _debounce(self, key: str, callback, delay: int = 140):
        previous = self._debounce_ids.get(key)
        if previous:
            try:
                self.after_cancel(previous)
            except tk.TclError:  # pragma: no cover
                pass
        self._debounce_ids[key] = self.after(delay, callback)

    def _copy(self, text: str, tip: str = "已复制到剪贴板"):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_var.set(tip)
        except tk.TclError:  # pragma: no cover
            self.status_var.set("复制失败：剪贴板不可用")

    def _export_csv(self, default_name: str, headers, rows, text_month_variants=None):
        """通用 CSV 导出（带 BOM，Excel 打开中文不乱码）。"""
        if not rows:
            messagebox.showinfo("导出 CSV", "当前没有可导出的数据，请先完成一次计算。", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出 CSV",
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(headers)
                writer.writerows(rows)
        except OSError as exc:
            messagebox.showerror("导出失败", f"写入文件失败：{exc}", parent=self)
            return
        self.status_var.set(f"已导出：{path}")

    def _set_combobox(self, combo, var, text: str):
        """把年化数值同步到下拉框：能匹配到方案就选中，否则清空选择。"""
        target = None
        try:
            value = float(text)
        except (TypeError, ValueError):
            value = None
        if value is not None:
            for option in self.rate_options:
                if abs(option["annual"] - value) < 1e-9:
                    target = option["label"]
                    break
        var.set(target or "")

    # ==================================================================
    # 页签 1：利息计算
    # ==================================================================
    def build_interest_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        # --- 本金 ---
        principal_box = ttk.LabelFrame(parent, text="本金", padding=(self.PAD, 6))
        principal_box.grid(row=0, column=0, sticky="ew")
        principal_box.columnconfigure(1, weight=1)
        self.var_principal = tk.StringVar(value="10000")
        entry_principal = ttk.Entry(principal_box, textvariable=self.var_principal, font=self.font_mono, width=22)
        entry_principal.grid(row=0, column=0, sticky="w")
        ttk.Label(principal_box, text="元", style="Hint.TLabel").grid(row=0, column=1, sticky="w", padx=(4, 0))
        self.var_principal_cn = tk.StringVar(value="")
        ttk.Label(principal_box, textvariable=self.var_principal_cn, style="Hint.TLabel").grid(
            row=0, column=2, sticky="e"
        )
        self.var_principal.trace_add("write", lambda *_: self._debounce("interest", self._refresh_interest))

        # --- A / B 并排收益率 ---
        matrix = ttk.Frame(parent)
        matrix.grid(row=1, column=0, sticky="ew", pady=(self.PAD, 0))
        for column in (0, 1):
            matrix.columnconfigure(column, weight=1, uniform="rate")
        self._build_rate_card(matrix, column=0, prefix="a", title="收益率 A")
        self._build_rate_card(matrix, column=1, prefix="b", title="收益率 B")

        # --- 结果 ---
        result_box = ttk.LabelFrame(parent, text="对比结果", padding=(self.PAD, 6))
        result_box.grid(row=2, column=0, sticky="nsew", pady=(self.PAD, 0))
        for column in range(4):
            result_box.columnconfigure(column, weight=1)

        self.var_badge = tk.StringVar(value="")
        self.lbl_badge = tk.Label(
            result_box,
            textvariable=self.var_badge,
            font=self.font_h2,
            bg=self.C_EQUAL,
            fg="#ffffff",
            padx=12,
            pady=8,
            anchor="center",
        )
        self.lbl_badge.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, self.PAD))

        self.var_daily_a = self._metric_card(result_box, "A 每日利息", 0, row=1)
        self.var_daily_b = self._metric_card(result_box, "B 每日利息", 1, row=1)
        self.var_winner = self._metric_card(result_box, "谁更高", 2, row=1)
        self.var_ratio = self._metric_card(result_box, "倍数（B÷A）", 3, row=1)

        diff_box = ttk.Frame(result_box)
        diff_box.grid(row=2, column=0, columnspan=4, sticky="ew")
        for column in range(4):
            diff_box.columnconfigure(column, weight=1)
        self.var_diff_daily = self._diff_cell(diff_box, "每日差额", 0)
        self.var_diff_monthly = self._diff_cell(diff_box, "每月差额", 1)
        self.var_diff_annual = self._diff_cell(diff_box, "每年差额", 2)
        self.var_diff_period = self._diff_cell(diff_box, "期间差额", 3)

        # --- 持有期间与计息口径（位于「对比结果」之后，只影响上方期间提示与下方「累计收益」） ---
        period_box = ttk.LabelFrame(parent, text="持有期间与计息口径", padding=(self.PAD, 6))
        period_box.grid(row=3, column=0, sticky="ew", pady=(self.PAD, 0))
        period_box.columnconfigure(4, weight=1)
        ttk.Label(period_box, text="持有天数：").grid(row=0, column=0, sticky="w")
        self.var_days_choice = tk.StringVar(value="30")
        combo_days = ttk.Combobox(
            period_box,
            textvariable=self.var_days_choice,
            state="readonly",
            width=10,
            values=["7", "30", "90", "365", "自定义"],
        )
        combo_days.grid(row=0, column=1, sticky="w", padx=(0, self.PAD))
        combo_days.bind("<<ComboboxSelected>>", lambda _e: self._on_days_choice())
        self.var_custom_days = tk.StringVar(value="30")
        self.entry_custom_days = ttk.Entry(period_box, textvariable=self.var_custom_days, width=8, font=self.font_mono)
        self.entry_custom_days.grid(row=0, column=2, sticky="w", padx=(0, self.PAD))
        ttk.Label(period_box, text="天", style="Hint.TLabel").grid(row=0, column=3, sticky="w")
        self.var_period_hint = tk.StringVar(value="")
        ttk.Label(period_box, textvariable=self.var_period_hint, style="Hint.TLabel").grid(
            row=0, column=4, sticky="w", padx=(self.PAD, 0)
        )
        self.var_compound = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            period_box,
            text="复利口径（按日滚动）",
            variable=self.var_compound,
            command=self._refresh_interest,
        ).grid(row=0, column=5, sticky="e")

        self.var_custom_days.trace_add("write", lambda *_: self._debounce("interest", self._refresh_interest))
        self.var_compound.trace_add("write", lambda *_: self._debounce("interest", self._refresh_interest))
        self._on_days_choice(silent=True)

    def _build_rate_card(self, parent, column: int, prefix: str, title: str):
        box = ttk.LabelFrame(parent, text=title, padding=(self.PAD, 6))
        box.grid(row=0, column=column, sticky="nsew", padx=(0, self.PAD) if column == 0 else (self.PAD, 0))
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="选择方案").grid(row=0, column=0, sticky="w")
        var_label = tk.StringVar(value="")
        combo = ttk.Combobox(box, textvariable=var_label, state="readonly", values=self._rate_labels(), width=34)
        combo.grid(row=0, column=1, sticky="ew", padx=(self.PAD, self.PAD))
        ttk.Button(box, text="[?]", width=3, command=lambda p=prefix: self._show_rate_note(p)).grid(row=0, column=2, sticky="e")
        combo.bind("<<ComboboxSelected>>", lambda _e, p=prefix: self._on_rate_selected(p))

        ttk.Label(box, text="年化利率").grid(row=1, column=0, sticky="w", pady=(6, 0))
        var_annual = tk.StringVar(value="3.65" if prefix == "a" else "7.3")
        entry = ttk.Entry(box, textvariable=var_annual, font=self.font_mono, width=16)
        entry.grid(row=1, column=1, sticky="w", padx=(self.PAD, 4), pady=(6, 0))
        ttk.Label(box, text="%", style="Hint.TLabel").grid(row=1, column=2, sticky="w", pady=(6, 0))

        var_note = tk.StringVar(value="")
        ttk.Label(box, textvariable=var_note, style="Hint.TLabel", wraplength=430, justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(4, 0)
        )

        setattr(self, f"var_rate_label_{prefix}", var_label)
        setattr(self, f"var_annual_{prefix}", var_annual)
        setattr(self, f"var_note_{prefix}", var_note)
        setattr(self, f"combo_rate_{prefix}", combo)
        var_annual.trace_add("write", lambda *_: self._on_annual_typed(prefix))
        self._sync_combo_from_annual(prefix)

    def _diff_cell(self, parent, title: str, column: int):
        frame = ttk.Frame(parent, padding=(0, 4))
        frame.grid(row=0, column=column, sticky="nsew", padx=(0, self.PAD))
        ttk.Label(frame, text=title, style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        value = tk.StringVar(value="—")
        ttk.Label(frame, textvariable=value, font=("TkFixedFont", 10, "bold")).grid(row=1, column=0, sticky="w")
        return value

    # --- 交互 ---
    def _on_days_choice(self, silent: bool = False):
        choice = self.var_days_choice.get()
        custom = choice == "自定义"
        self.entry_custom_days.configure(state="normal" if custom else "readonly")
        if not custom:
            self.var_custom_days.set(choice)
        if not silent:
            self._refresh_interest()

    def _current_days(self) -> int:
        choice = self.var_days_choice.get()
        raw = self.var_custom_days.get() if choice == "自定义" else choice
        try:
            days = int(round(parse_number(raw, "天数")))
        except ValueError:
            days = 365
        return max(1, min(days, 36500))

    def _on_rate_selected(self, prefix: str):
        option = self._option_by_label(getattr(self, f"var_rate_label_{prefix}").get())
        if not option:
            return
        getattr(self, f"var_annual_{prefix}").set(fmt_num(option["annual"], 6))
        note = option["note"] or option["display"]
        if option.get("warning"):
            note = f"⚠ {option['warning']} {note}"
        getattr(self, f"var_note_{prefix}").set(note)
        self._refresh_interest()

    def _on_annual_typed(self, prefix: str):
        grid_guard = getattr(self, "_syncing", False)
        if not grid_guard:
            self._syncing = True
            try:
                self._sync_combo_from_annual(prefix)
            finally:
                self._syncing = False
        self._debounce("interest", self._refresh_interest)

    def _sync_combo_from_annual(self, prefix: str):
        combo = getattr(self, f"combo_rate_{prefix}")
        var_label = getattr(self, f"var_rate_label_{prefix}")
        text = getattr(self, f"var_annual_{prefix}").get()
        try:
            value = float(text)
        except (TypeError, ValueError):
            var_label.set("")
            return
        self._set_combobox(combo, var_label, text)
        option = self._option_by_label(var_label.get())
        if option:
            note = option["note"] or option["display"]
            if option.get("warning"):
                note = f"⚠ {option['warning']} {note}"
            getattr(self, f"var_note_{prefix}").set(note)
        elif value == value:  # 手填数值
            getattr(self, f"var_note_{prefix}").set("手动填写：按年化利率计算。")

    def _show_rate_note(self, prefix: str):
        option = self._option_by_label(getattr(self, f"var_rate_label_{prefix}").get())
        if not option:
            messagebox.showinfo("利率说明", "当前为手动填写的年化利率，没有附加说明。", parent=self)
            return
        detail = [
            f"名称：{option['name']}",
            f"分组：{option['groupTitle']}",
            f"口径：{option['kindLabel']}",
            f"显示：{option['display']}",
            f"折合年化：{option['annual']:.4f}%",
            f"更新日期：{option['asOf'] or '未标注'}",
            f"说明：{option['note'] or '无'}",
        ]
        if option.get("warning"):
            detail.append(f"⚠ 提示：{option['warning']}")
        if option.get("source"):
            detail.append(f"来源：{option['source']}")
        messagebox.showinfo("利率说明", "\n".join(detail), parent=self)

    def _refresh_interest(self):
        self._debounce_ids.pop("interest", None)
        try:
            principal = parse_number(self.var_principal.get(), "本金")
        except ValueError as exc:
            self.var_principal_cn.set(str(exc))
            return
        self.var_principal_cn.set(cn_upper_amount(principal))
        try:
            annual_a = parse_number(self.var_annual_a.get(), "A 的年化利率")
            annual_b = parse_number(self.var_annual_b.get(), "B 的年化利率")
        except ValueError:
            return
        days = self._current_days()
        compound = bool(self.var_compound.get())
        try:
            result = compare_rates(principal, annual_a, annual_b, days, compound=compound)
        except ValueError as exc:
            self.var_badge.set(str(exc))
            return

        self.var_daily_a.set(fmt_money(result["a"]["daily"]))
        self.var_daily_b.set(fmt_money(result["b"]["daily"]))
        self.var_diff_daily.set(fmt_money(result["diffDaily"], sign=True))
        self.var_diff_monthly.set(fmt_money(result["diffMonthly"], sign=True))
        self.var_diff_annual.set(fmt_money(result["diffAnnual"], sign=True))
        self.var_diff_period.set(fmt_money(result["diffPeriod"], sign=True))
        self.var_ratio.set("—" if result["ratio"] is None else f"{result['ratio']:.4f} 倍")
        self.var_period_hint.set(
            f"按 {days} 天{('、复利' if compound else '、单利')}计：A 到期 {fmt_money(result['a']['periodInterest'])}，"
            f"B 到期 {fmt_money(result['b']['periodInterest'])}"
        )

        better = result["better"]
        if better == "b":
            self.var_winner.set("B 更高")
            self.var_badge.set(f"B 比 A 每年多赚 {fmt_money(result['diffAnnual'])}（每日多 {fmt_money(result['diffDaily'])}）")
            self.lbl_badge.configure(bg=self.C_BETTER)
        elif better == "a":
            self.var_winner.set("A 更高")
            self.var_badge.set(f"A 比 B 每年多赚 {fmt_money(-result['diffAnnual'])}（每日多 {fmt_money(-result['diffDaily'])}）")
            self.lbl_badge.configure(bg=self.C_BETTER)
        else:
            self.var_winner.set("两者相同")
            self.var_badge.set("A 与 B 的年化利率相同，收益无差异")
            self.lbl_badge.configure(bg=self.C_EQUAL)

    # ==================================================================
    # 页签 2：贷款计算
    # ==================================================================
    def build_loan_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        form = ttk.LabelFrame(parent, text="贷款参数", padding=(self.PAD, 6))
        form.grid(row=0, column=0, sticky="ew")
        for column in range(6):
            form.columnconfigure(column, weight=1)

        ttk.Label(form, text="贷款本金（元）").grid(row=0, column=0, sticky="w")
        self.var_loan_principal = tk.StringVar(value="1000000")
        ttk.Entry(form, textvariable=self.var_loan_principal, font=self.font_mono, width=18).grid(
            row=1, column=0, sticky="ew", padx=(0, self.PAD)
        )

        ttk.Label(form, text="年化利率（%）").grid(row=0, column=1, sticky="w")
        self.var_loan_annual = tk.StringVar(value="4.9")
        ttk.Entry(form, textvariable=self.var_loan_annual, font=self.font_mono, width=14).grid(
            row=1, column=1, sticky="ew", padx=(0, self.PAD)
        )

        ttk.Label(form, text="期限").grid(row=0, column=2, sticky="w")
        term_frame = ttk.Frame(form)
        term_frame.grid(row=1, column=2, sticky="ew", padx=(0, self.PAD))
        self.var_loan_term = tk.StringVar(value="30")
        ttk.Entry(term_frame, textvariable=self.var_loan_term, font=self.font_mono, width=8).grid(row=0, column=0, sticky="w")
        self.var_loan_unit = tk.StringVar(value="年")
        combo_unit = ttk.Combobox(
            term_frame, textvariable=self.var_loan_unit, state="readonly", width=4, values=["月", "年"]
        )
        combo_unit.grid(row=0, column=1, sticky="w", padx=(4, 0))
        combo_unit.bind("<<ComboboxSelected>>", lambda _e: self._refresh_loan())

        ttk.Label(form, text="还款方式").grid(row=0, column=3, sticky="w")
        self.var_loan_method = tk.StringVar(value=LOAN_METHOD_LABELS["equal_installment"])
        combo_method = ttk.Combobox(
            form,
            textvariable=self.var_loan_method,
            state="readonly",
            width=18,
            values=[LOAN_METHOD_LABELS[key] for key in LOAN_METHODS],
        )
        combo_method.grid(row=1, column=3, sticky="ew", padx=(0, self.PAD))
        combo_method.bind("<<ComboboxSelected>>", lambda _e: self._refresh_loan())

        ttk.Label(form, text="快速选择方案").grid(row=0, column=4, sticky="w")
        self.var_loan_rate_label = tk.StringVar(value="")
        combo_rate = ttk.Combobox(
            form, textvariable=self.var_loan_rate_label, state="readonly", width=30, values=self._rate_labels()
        )
        combo_rate.grid(row=1, column=4, sticky="ew", padx=(0, self.PAD))
        combo_rate.bind("<<ComboboxSelected>>", lambda _e: self._on_loan_rate_selected())

        button_frame = ttk.Frame(form)
        button_frame.grid(row=1, column=5, sticky="e")
        ttk.Button(button_frame, text="重新计算", command=self._refresh_loan).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(button_frame, text="复制结果", command=self._copy_loan).grid(row=0, column=1, padx=(0, 4))
        ttk.Button(button_frame, text="导出 CSV", command=self._export_loan).grid(row=0, column=2)

        cards = ttk.Frame(parent)
        cards.grid(row=1, column=0, sticky="ew", pady=(self.PAD, 0))
        self.var_loan_payment = self._metric_card(cards, "每月还款", 0)
        self.var_loan_interest = self._metric_card(cards, "总利息", 1)
        self.var_loan_total = self._metric_card(cards, "总还款", 2)
        self.var_loan_ratio = self._metric_card(cards, "利息占比", 3)
        self.var_loan_last = self._metric_card(cards, "末期还款 / 期数", 4)

        detail = ttk.LabelFrame(parent, text="逐期明细", padding=(self.PAD, 6))
        detail.grid(row=2, column=0, sticky="nsew", pady=(self.PAD, 0))
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(1, weight=1)

        self.loan_bar = tk.Canvas(detail, height=26, highlightthickness=0, bd=0)
        self.loan_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.loan_bar.bind("<Configure>", lambda _e: self._draw_loan_bar())

        wrapper, self.loan_tree = self._make_tree(
            detail,
            columns=("period", "payment", "principal", "interest", "remaining"),
            headings=("期数", "月供（元）", "本金（元）", "利息（元）", "剩余本金（元）"),
            widths=(90, 150, 150, 150, 170),
            anchors={"period": "center", "payment": "e", "principal": "e", "interest": "e", "remaining": "e"},
            height=12,
        )
        wrapper.grid(row=1, column=0, sticky="nsew")
        self.loan_rows = []
        self.loan_ratio = (0.0, 1.0)
        self.var_loan_hint = tk.StringVar(value="")
        ttk.Label(detail, textvariable=self.var_loan_hint, style="Hint.TLabel").grid(row=2, column=0, sticky="w", pady=(6, 0))

        for var in (self.var_loan_principal, self.var_loan_annual, self.var_loan_term):
            var.trace_add("write", lambda *_: self._debounce("loan", self._refresh_loan))

    def _on_loan_rate_selected(self):
        option = self._option_by_label(self.var_loan_rate_label.get())
        if option:
            self.var_loan_annual.set(fmt_num(option["annual"], 6))
            self._refresh_loan()

    def _loan_months(self) -> int:
        term = parse_number(self.var_loan_term.get(), "期限")
        if term <= 0:
            raise ValueError("期限必须大于 0")
        months = int(round(term * 12)) if self.var_loan_unit.get() == "年" else int(round(term))
        if months < 1:
            raise ValueError("期限至少 1 个月")
        if months > 1200:
            raise ValueError("期限最多 1200 个月")
        return months

    def _loan_method_key(self) -> str:
        label = self.var_loan_method.get()
        for key, text in LOAN_METHOD_LABELS.items():
            if text == label:
                return key
        return "equal_installment"

    def _refresh_loan(self):
        self._debounce_ids.pop("loan", None)
        try:
            principal = parse_number(self.var_loan_principal.get(), "贷款本金")
            annual = parse_number(self.var_loan_annual.get(), "年化利率")
            months = self._loan_months()
            method = self._loan_method_key()
            result = loan_schedule(principal, annual, months, method)
            summary = schedule_summary(result["schedule"])
        except ValueError as exc:
            self.var_loan_hint.set(f"⚠ {exc}")
            self.loan_tree.delete(*self.loan_tree.get_children())
            self.loan_rows = []
            return

        method_label = LOAN_METHOD_LABELS[method]
        first = result["schedule"][0]["payment"]
        last_row = result["schedule"][-1]
        last = last_row["payment"]
        # 「还多少」要含本金：最后一期的本金在 schedule.principal 里单独记录
        last_total = ROUND(last_row["payment"] + last_row["principal"])
        if method in ("equal_installment", "bullet"):
            self.var_loan_payment.set(fmt_money(result["payment"]))
        else:
            self.var_loan_payment.set(f"{fmt_money(first)} → {fmt_money(last)}")
        self.var_loan_interest.set(fmt_money(result["totalInterest"]))
        self.var_loan_total.set(fmt_money(result["totalRepayment"]))
        ratio = 0.0 if result["totalRepayment"] == 0 else result["totalInterest"] / result["totalRepayment"]
        self.var_loan_ratio.set(f"{ratio * 100:.2f}%")
        self.var_loan_last.set(f"{fmt_money(last_total)} / {result['months']} 期")
        self.var_loan_hint.set(
            f"{method_label} · 年化 {fmt_pct(result['annualPct'], 4)} · {result['months']} 期 · "
            f"Σ每期本金 {fmt_money(sum(row['principal'] for row in result['schedule']))}（已结平，末期含本金）"
        )

        self.loan_ratio = (result["totalRepayment"] - result["totalInterest"], result["totalInterest"])
        self._draw_loan_bar()

        self.loan_tree.delete(*self.loan_tree.get_children())
        self.loan_rows = []
        for row in result["schedule"]:
            values = (
                row["period"],
                fmt_money(row["payment"]),
                fmt_money(row["principal"]),
                fmt_money(row["interest"]),
                fmt_money(row["remaining"]),
            )
            self.loan_tree.insert("", "end", values=values)
            self.loan_rows.append(
                {
                    "期数": row["period"],
                    "月供": f'{row["payment"]:.2f}',
                    "本金": f'{row["principal"]:.2f}',
                    "利息": f'{row["interest"]:.2f}',
                    "剩余本金": f'{row["remaining"]:.2f}',
                }
            )
        self.status_var.set(
            f"贷款计算完成：{method_label}，{result['months']} 期，总利息 {fmt_money(result['totalInterest'])}"
        )

    def _draw_loan_bar(self):
        canvas = getattr(self, "loan_bar", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = max(canvas.winfo_width(), 10)
        height = max(canvas.winfo_height(), 10)
        principal_part, interest_part = self.loan_ratio
        total = principal_part + interest_part
        if total <= 0:
            canvas.create_rectangle(0, 0, width, height, fill="#e0e0e0", outline="")
            return
        split = int(width * interest_part / total)
        canvas.create_rectangle(0, 0, split, height, fill="#e57373", outline="")
        canvas.create_rectangle(split, 0, width, height, fill="#64b5f6", outline="")
        canvas.create_text(
            8,
            height / 2,
            text=f"利息 {fmt_money(interest_part)}（{interest_part / total * 100:.1f}%）",
            anchor="w",
            fill="#7f1d1d",
        )
        canvas.create_text(
            width - 8,
            height / 2,
            text=f"本金 {fmt_money(principal_part)}（{principal_part / total * 100:.1f}%）",
            anchor="e",
            fill="#0d3c61",
        )

    def _copy_loan(self):
        if not self.loan_rows:
            self.status_var.set("没有可复制的结果，请先完成一次计算")
            return
        lines = ["期数\t月供\t本金\t利息\t剩余本金"]
        for row in self.loan_rows:
            lines.append(f"{row['期数']}\t{row['月供']}\t{row['本金']}\t{row['利息']}\t{row['剩余本金']}")
        self._copy("\n".join(lines), "已复制贷款明细到剪贴板")

    def _export_loan(self):
        headers = ["期数", "月供（元）", "本金（元）", "利息（元）", "剩余本金（元）"]
        rows = [[row["期数"], row["月供"], row["本金"], row["利息"], row["剩余本金"]] for row in self.loan_rows]
        self._export_csv("贷款还款计划.csv", headers, rows)

    # ==================================================================
    # 页签 3：网贷计算
    # ==================================================================
    def build_online_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        form = ttk.LabelFrame(parent, text="借款参数", padding=(self.PAD, 6))
        form.grid(row=0, column=0, sticky="ew")
        for column in range(5):
            form.columnconfigure(column, weight=1)

        ttk.Label(form, text="借款本金（元）").grid(row=0, column=0, sticky="w")
        self.var_online_principal = tk.StringVar(value="10000")
        ttk.Entry(form, textvariable=self.var_online_principal, font=self.font_mono, width=16).grid(
            row=1, column=0, sticky="ew", padx=(0, self.PAD)
        )

        ttk.Label(form, text="平台 / 产品（网贷分组）").grid(row=0, column=1, sticky="w")
        self.var_online_platform = tk.StringVar(value="")
        self.combo_online_platform = ttk.Combobox(
            form, textvariable=self.var_online_platform, state="readonly", width=34, values=self._online_loan_labels()
        )
        self.combo_online_platform.grid(row=1, column=1, sticky="ew", padx=(0, self.PAD))
        self.combo_online_platform.bind("<<ComboboxSelected>>", lambda _e: self._on_online_platform_selected())

        ttk.Label(form, text="年化利率（%，可手填）").grid(row=0, column=2, sticky="w")
        self.var_online_annual = tk.StringVar(value="18.25")
        ttk.Entry(form, textvariable=self.var_online_annual, font=self.font_mono, width=14).grid(
            row=1, column=2, sticky="ew", padx=(0, self.PAD)
        )

        ttk.Label(form, text="借款天数").grid(row=0, column=3, sticky="w")
        self.var_online_days = tk.StringVar(value="30")
        ttk.Entry(form, textvariable=self.var_online_days, font=self.font_mono, width=10).grid(
            row=1, column=3, sticky="ew", padx=(0, self.PAD)
        )

        ttk.Label(form, text="还款方式").grid(row=0, column=4, sticky="w")
        self.var_online_method = tk.StringVar(value=ONLINE_LOAN_METHOD_LABELS["interest_first"])
        combo_method = ttk.Combobox(
            form,
            textvariable=self.var_online_method,
            state="readonly",
            width=20,
            values=[ONLINE_LOAN_METHOD_LABELS[key] for key in ONLINE_LOAN_METHODS],
        )
        combo_method.grid(row=1, column=4, sticky="ew")
        combo_method.bind("<<ComboboxSelected>>", lambda _e: self._refresh_online())

        # 风险提示条
        self.var_risk = tk.StringVar(value="")
        self.lbl_risk = tk.Label(
            parent,
            textvariable=self.var_risk,
            font=self.font_h2,
            bg=self.C_OK,
            fg="#ffffff",
            padx=12,
            pady=8,
            anchor="w",
        )
        self.lbl_risk.grid(row=1, column=0, sticky="ew", pady=(self.PAD, 0))

        cards = ttk.Frame(parent)
        cards.grid(row=2, column=0, sticky="ew", pady=(self.PAD, 0))
        self.var_online_daily_interest = self._metric_card(cards, "每日利息", 0)
        self.var_online_daily_payment = self._metric_card(cards, "每日还款", 1)
        self.var_online_total_interest = self._metric_card(cards, "总利息", 2)
        self.var_online_total_payment = self._metric_card(cards, "总还款", 3)
        self.var_online_apr = self._metric_card(cards, "实际年化（IRR）", 4)

        detail = ttk.LabelFrame(parent, text="还款明细", padding=(self.PAD, 6))
        detail.grid(row=3, column=0, sticky="nsew", pady=(self.PAD, 0))
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(0, weight=1)
        wrapper, self.online_tree = self._make_tree(
            detail,
            columns=("period", "payment", "principal", "interest", "remaining"),
            headings=("天数", "当日还款（元）", "本金（元）", "利息（元）", "剩余本金（元）"),
            widths=(90, 150, 150, 150, 170),
            anchors={"period": "center", "payment": "e", "principal": "e", "interest": "e", "remaining": "e"},
            height=10,
        )
        wrapper.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Frame(detail)
        bar.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        bar.columnconfigure(0, weight=1)
        self.var_online_hint = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.var_online_hint, style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(bar, text="复制结果", command=self._copy_online).grid(row=0, column=1, padx=(self.PAD, 4))
        ttk.Button(bar, text="导出 CSV", command=self._export_online).grid(row=0, column=2)
        self.online_rows = []

        for var in (self.var_online_principal, self.var_online_annual, self.var_online_days):
            var.trace_add("write", lambda *_: self._debounce("online", self._refresh_online))

        labels = self._online_loan_labels()
        if labels:
            self.var_online_platform.set(labels[0])
            self._on_online_platform_selected(refresh=False)

    def _online_loan_labels(self):
        return [option["label"] for option in self.rate_options if option["group"] == "online_loan"]

    def _on_online_platform_selected(self, refresh: bool = True):
        option = self._option_by_label(self.var_online_platform.get())
        if not option:
            return
        self.var_online_annual.set(fmt_num(option["annual"], 6))
        if refresh:
            self._refresh_online()

    def _online_method_key(self) -> str:
        label = self.var_online_method.get()
        for key, text in ONLINE_LOAN_METHOD_LABELS.items():
            if text == label:
                return key
        return "interest_first"

    def _refresh_online(self):
        self._debounce_ids.pop("online", None)
        try:
            principal = parse_number(self.var_online_principal.get(), "借款本金")
            annual = parse_number(self.var_online_annual.get(), "年化利率")
            days = int(round(parse_number(self.var_online_days.get(), "借款天数")))
            if days < 1:
                raise ValueError("借款天数必须大于 0")
            if days > 36500:
                raise ValueError("借款天数不能超过 36500")
            method = self._online_method_key()
            result = online_loan(principal, annual, days, method)
            daily = daily_payment(principal, annual, days)
        except ValueError as exc:
            self.var_online_hint.set(f"⚠ {exc}")
            return

        self.var_online_daily_interest.set(fmt_money(result["dailyInterest"]))
        self.var_online_daily_payment.set(fmt_money(result["dailyPayment"]))
        self.var_online_total_interest.set(fmt_money(result["totalInterest"]))
        self.var_online_total_payment.set(fmt_money(result["totalPayment"]))

        # 实际年化（IRR）：按真实现金流折算
        # 注意：网贷现金流是「按天」的，所以求出的 IRR 是「日 IRR」，
        # 必须按 365 次复利折算年化，否则会严重低估真实成本。
        flows = [result["principal"]]
        for row in result["schedule"]:
            flows.append(-row["payment"])
        try:
            daily_irr = irr(flows)
            annual_irr = ((1 + daily_irr) ** DAY_BASIS - 1) * 100
        except (ValueError, OverflowError):
            annual_irr = float(annual)
        self.var_online_apr.set(fmt_pct(annual_irr, 2))

        self.var_online_hint.set(
            f"{ONLINE_LOAN_METHOD_LABELS[result['method']]} · {days} 天 · 名义年化 {fmt_pct(annual, 2)} · "
            f"按天计息每日 {fmt_money(daily['dailyInterest'])}"
        )

        # 风险提示条
        if annual > 36:
            self.var_risk.set(
                f"⚠ 高风险：综合年化 {annual:.2f}% 已超过 36% 高利贷口径，远超法律保护范围，建议立即停止借款。"
            )
            self.lbl_risk.configure(bg=self.C_DANGER)
        elif annual > 24:
            self.var_risk.set(
                f"⚠ 注意：综合年化 {annual:.2f}% 已超过 24% 综合融资成本红线，请核实是否含各类服务费。"
            )
            self.lbl_risk.configure(bg=self.C_WARN)
        else:
            self.var_risk.set(f"✓ 综合年化 {annual:.2f}%，未超过 24% 综合融资成本红线（仍需核对合同综合成本）。")
            self.lbl_risk.configure(bg=self.C_OK)

        self.online_tree.delete(*self.online_tree.get_children())
        self.online_rows = []
        schedule = result["schedule"]
        # 明细最多展示前 200 天，避免超长借款卡顿；完整数据可导出 CSV
        for row in schedule[:200]:
            self.online_tree.insert(
                "",
                "end",
                values=(
                    row["day"],
                    fmt_money(row["payment"]),
                    fmt_money(row["principal"]),
                    fmt_money(row["interest"]),
                    fmt_money(row["remaining"]),
                ),
            )
        for row in schedule:
            self.online_rows.append(
                {
                    "天数": row["day"],
                    "当日还款": f'{row["payment"]:.2f}',
                    "本金": f'{row["principal"]:.2f}',
                    "利息": f'{row["interest"]:.2f}',
                    "剩余本金": f'{row["remaining"]:.2f}',
                }
            )
        if len(schedule) > 200:
            self.var_online_hint.set(self.var_online_hint.get() + f"（明细表仅显示前 200 天，共 {len(schedule)} 天，可导出 CSV）")

    def _copy_online(self):
        if not self.online_rows:
            self.status_var.set("没有可复制的结果，请先完成一次计算")
            return
        lines = ["天数\t当日还款\t本金\t利息\t剩余本金"]
        for row in self.online_rows:
            lines.append(f"{row['天数']}\t{row['当日还款']}\t{row['本金']}\t{row['利息']}\t{row['剩余本金']}")
        self._copy("\n".join(lines), "已复制网贷明细到剪贴板")

    def _export_online(self):
        headers = ["天数", "当日还款（元）", "本金（元）", "利息（元）", "剩余本金（元）"]
        rows = [
            [row["天数"], row["当日还款"], row["本金"], row["利息"], row["剩余本金"]] for row in self.online_rows
        ]
        self._export_csv("网贷还款明细.csv", headers, rows)

    # ==================================================================
    # 页签 4：利率换算
    # ==================================================================
    def build_convert_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        form = ttk.LabelFrame(parent, text="输入任一口径，自动换算全口径", padding=(self.PAD, 6))
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(3, weight=1)
        ttk.Label(form, text="数值").grid(row=0, column=0, sticky="w")
        self.var_convert_value = tk.StringVar(value="3.65")
        ttk.Entry(form, textvariable=self.var_convert_value, font=self.font_mono, width=16).grid(
            row=1, column=0, sticky="w", padx=(0, self.PAD)
        )
        ttk.Label(form, text="口径").grid(row=0, column=1, sticky="w")
        self.var_convert_kind = tk.StringVar(value=KIND_LABELS["annual_pct"])
        combo_kind = ttk.Combobox(
            form,
            textvariable=self.var_convert_kind,
            state="readonly",
            width=28,
            values=[KIND_LABELS[key] for key in KIND_LABELS],
        )
        combo_kind.grid(row=1, column=1, sticky="w", padx=(0, self.PAD))
        combo_kind.bind("<<ComboboxSelected>>", lambda _e: self._refresh_convert())
        ttk.Button(form, text="换算", command=self._refresh_convert).grid(row=1, column=2, sticky="w")
        self.var_convert_hint = tk.StringVar(value="")
        ttk.Label(form, textvariable=self.var_convert_hint, style="Hint.TLabel").grid(
            row=1, column=3, sticky="w", padx=(self.PAD, 0)
        )

        grid = ttk.LabelFrame(parent, text="10 种口径对照", padding=(self.PAD, 6))
        grid.grid(row=1, column=0, sticky="ew", pady=(self.PAD, 0))
        for column in range(5):
            grid.columnconfigure(column, weight=1)
        self.convert_vars = {}
        items = [
            ("annualPct", "年化利率", "%"),
            ("monthlyPct", "月利率", "%"),
            ("dailyPct", "日利率", "%"),
            ("dailyWan", "日息（万几）", ""),
            ("basisPoints", "基点（BP）", ""),
            ("monthlyFen", "月息（分）", ""),
            ("annualFen", "年息（分）", ""),
            ("monthlyLi", "月息（厘）", ""),
            ("annualLi", "年息（厘）", ""),
            ("monthlyHao", "月息（毫）", ""),
        ]
        for index, (key, title, unit) in enumerate(items):
            row, column = divmod(index, 5)
            cell = ttk.Frame(grid, padding=(0, 6))
            cell.grid(row=row, column=column, sticky="nsew", padx=(0, self.PAD))
            ttk.Label(cell, text=title, style="Hint.TLabel").grid(row=0, column=0, sticky="w")
            value = tk.StringVar(value="—")
            ttk.Label(cell, textvariable=value, font=self.font_mono).grid(row=1, column=0, sticky="w")
            self.convert_vars[key] = value

        lower = ttk.Frame(parent)
        lower.grid(row=2, column=0, sticky="nsew", pady=(self.PAD, 0))
        lower.columnconfigure(0, weight=3, uniform="lower")
        lower.columnconfigure(1, weight=2, uniform="lower")
        lower.rowconfigure(0, weight=1)

        trap = ttk.LabelFrame(lower, text="「月息 vs 年息」—— 1 分是多少？小心口径陷阱", padding=(self.PAD, 6))
        trap.grid(row=0, column=0, sticky="nsew", padx=(0, self.PAD))
        trap.columnconfigure(0, weight=1)
        trap.rowconfigure(0, weight=1)
        wrapper, self.trap_tree = self._make_tree(
            trap,
            columns=("call", "monthly", "annual", "note"),
            headings=("民间叫法", "按月息理解（年化）", "按年息理解（年化）", "说明"),
            widths=(120, 170, 170, 340),
            anchors={"call": "center", "monthly": "e", "annual": "e", "note": "w"},
            height=8,
        )
        wrapper.grid(row=0, column=0, sticky="nsew")
        self._fill_trap_table()

        calc = ttk.LabelFrame(lower, text="手续费 → 真实年化（IRR）", padding=(self.PAD, 6))
        calc.grid(row=0, column=1, sticky="nsew")
        calc.columnconfigure(1, weight=1)
        self.var_fee_principal = tk.StringVar(value="10000")
        self.var_fee_monthly = tk.StringVar(value="0.6")
        self.var_fee_months = tk.StringVar(value="12")
        for row_index, (label, var) in enumerate(
            (("贷款本金（元）", self.var_fee_principal), ("月费率（%）", self.var_fee_monthly), ("分期期数（月）", self.var_fee_months))
        ):
            ttk.Label(calc, text=label).grid(row=row_index, column=0, sticky="w", pady=2)
            ttk.Entry(calc, textvariable=var, font=self.font_mono, width=14).grid(
                row=row_index, column=1, sticky="w", padx=(self.PAD, 0), pady=2
            )
        ttk.Button(calc, text="计算真实年化", command=self._refresh_fee).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(6, 6)
        )
        self.var_fee_result = tk.StringVar(value="—")
        ttk.Label(calc, textvariable=self.var_fee_result, style="Accent.TLabel", wraplength=320, justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w"
        )

        self.var_convert_value.trace_add("write", lambda *_: self._debounce("convert", self._refresh_convert))
        self._refresh_convert()

    def _fill_trap_table(self):
        rows = [
            ("月息 1 分", "12.00%", "10.00%", "1 分 = 1%/月（年化 12%）或 10%/年，差 2 个百分点"),
            ("月息 1 分 5 厘", "18.00%", "15.00%", "1.5%/月 vs 15%/年，签约前必须问清口径"),
            ("月息 5 厘", "6.00%", "5.00%", "0.5%/月 ≈ 6%/年，是常见的民间表述"),
            ("月息 1 毫", "0.12%", "0.10%", "1 毫 = 0.01%/月，多用于极低利率的精算"),
            ("日息 1 万", "365.00%", "365.00%", "日息万1 = 0.01%/日，年化高达 365%，属于违法高利贷"),
            ("日息 5 万", "1825.00%", "1825.00%", "注意区分「万5」（0.05%/日，年化 18.25%）"),
        ]
        for row in rows:
            self.trap_tree.insert("", "end", values=row)

    def _convert_kind_key(self) -> str:
        label = self.var_convert_kind.get()
        for key, text in KIND_LABELS.items():
            if text == label:
                return key
        return "annual_pct"

    def _refresh_convert(self):
        self._debounce_ids.pop("convert", None)
        kind = self._convert_kind_key()
        try:
            value = parse_number(self.var_convert_value.get(), "换算数值")
            if kind in RANGE_KINDS:
                raise ValueError("区间口径请在上方直接查看折算年化，本例请选择具体口径")
            result = convert(value, kind)
        except ValueError as exc:
            self.var_convert_hint.set(f"⚠ {exc}")
            for var in self.convert_vars.values():
                var.set("—")
            return
        self.var_convert_hint.set(
            f"{KIND_LABELS[kind]} = 年化 {result['annualPct']:.4f}%（LPR 1年期按 {self.lpr1y}% 折算）"
        )
        self.convert_vars["annualPct"].set(f"{result['annualPct']:.6f} %")
        self.convert_vars["monthlyPct"].set(f"{result['monthlyPct']:.6f} %")
        self.convert_vars["dailyPct"].set(f"{result['dailyPct']:.6f} %")
        self.convert_vars["dailyWan"].set(f"{result['dailyWan']:.4f} 万")
        self.convert_vars["basisPoints"].set(f"{result['basisPoints']:.0f} BP")
        self.convert_vars["monthlyFen"].set(f"{result['monthlyFen']:.4f} 分")
        self.convert_vars["annualFen"].set(f"{result['annualFen']:.4f} 分")
        self.convert_vars["monthlyLi"].set(f"{result['monthlyLi']:.4f} 厘")
        self.convert_vars["annualLi"].set(f"{result['annualLi']:.4f} 厘")
        self.convert_vars["monthlyHao"].set(f"{result['monthlyHao']:.4f} 毫")

    def _refresh_fee(self):
        try:
            principal = parse_number(self.var_fee_principal.get(), "贷款本金")
            fee = parse_number(self.var_fee_monthly.get(), "月费率")
            months = int(round(parse_number(self.var_fee_months.get(), "分期期数")))
            result = apr_from_fee(principal, fee, months)
        except ValueError as exc:
            self.var_fee_result.set(f"⚠ {exc}")
            return
        self.var_fee_result.set(
            f"名义年化 {result['aprSimple']:.2f}% → 真实年化 {result['aprAnnual']:.2f}%\n"
            f"月 IRR {result['monthlyIrr'] * 100:.4f}% · 总手续费 {fmt_money(result['totalFee'])} · "
            f"总还款 {fmt_money(result['totalPayment'])}"
        )

    # ==================================================================
    # 页签 5：利率大全
    # ==================================================================
    def build_catalog_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        top = ttk.Frame(parent)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="搜索（名称/别名/口语）").grid(row=0, column=0, sticky="w")
        self.var_catalog_search = tk.StringVar(value="")
        ttk.Entry(top, textvariable=self.var_catalog_search, width=36).grid(
            row=0, column=1, sticky="w", padx=(self.PAD, self.PAD)
        )
        ttk.Button(top, text="搜索", command=self._refresh_catalog).grid(row=0, column=2, sticky="w", padx=(0, 4))
        ttk.Button(top, text="清空", command=self._clear_catalog_search).grid(row=0, column=3, sticky="w", padx=(0, self.PAD))
        ttk.Button(top, text="用这个方案填入「利息计算」", command=self._apply_selected_rate).grid(
            row=0, column=4, sticky="e"
        )
        self.var_catalog_hint = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.var_catalog_hint, style="Hint.TLabel").grid(
            row=0, column=5, sticky="e", padx=(self.PAD, 0)
        )

        detail = ttk.LabelFrame(parent, text="利率数据（来自 data/rates.json，失败时使用内置最小数据集）", padding=(self.PAD, 6))
        detail.grid(row=1, column=0, sticky="nsew", pady=(self.PAD, 0))
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(0, weight=1)
        wrapper, self.catalog_tree = self._make_tree(
            detail,
            columns=("group", "name", "aliases", "kind", "annual", "asOf", "note"),
            headings=("分组", "名称", "别名", "口径", "年化（%）", "更新日期", "说明"),
            widths=(80, 220, 200, 130, 110, 110, 420),
            anchors={"group": "center", "name": "w", "aliases": "w", "kind": "center", "annual": "e", "asOf": "center", "note": "w"},
            height=16,
        )
        wrapper.grid(row=0, column=0, sticky="nsew")
        self.catalog_tree.bind("<Double-1>", lambda _e: self._apply_selected_rate())
        self.var_catalog_search.trace_add("write", lambda *_: self._debounce("catalog", self._refresh_catalog, 200))

    def _clear_catalog_search(self):
        self.var_catalog_search.set("")
        self._refresh_catalog()

    def _filtered_options(self):
        keyword = self.var_catalog_search.get().strip().lower()
        if not keyword:
            return list(self.rate_options)
        tokens = [token for token in keyword.split() if token]
        matched = []
        for option in self.rate_options:
            haystack = " ".join(
                [
                    option["name"],
                    " ".join(option["aliases"]),
                    option["groupTitle"],
                    option["kindLabel"],
                    option["display"],
                    option["note"],
                ]
            ).lower()
            if all(token in haystack for token in tokens):
                matched.append(option)
        return matched

    def _refresh_catalog(self):
        self._debounce_ids.pop("catalog", None)
        options = self._filtered_options()
        self.catalog_tree.delete(*self.catalog_tree.get_children())
        self._catalog_options = options
        for option in options:
            self.catalog_tree.insert(
                "",
                "end",
                iid=option["id"] or option["label"],
                values=(
                    GROUP_SHORT.get(option["group"], option["group"]),
                    option["name"],
                    "、".join(option["aliases"][:3]),
                    option["kindLabel"],
                    f"{option['annual']:.4f}",
                    option["asOf"],
                    option["note"],
                ),
            )
        self.var_catalog_hint.set(f"共 {len(options)} 条 / 全部 {len(self.rate_options)} 条（双击可直接填入）")

    def _apply_selected_rate(self):
        selection = self.catalog_tree.selection()
        if not selection:
            self.status_var.set("请先在「利率大全」里选中一行")
            return
        option = None
        for candidate in getattr(self, "_catalog_options", []):
            if (candidate["id"] or candidate["label"]) == selection[0]:
                option = candidate
                break
        if option is None:
            return
        self.notebook.select(0)
        self.var_annual_a.set(fmt_num(option["annual"], 6))
        self.var_rate_label_a.set(option["label"])
        self.var_note_a.set(option["note"] or option["display"])
        self._refresh_interest()
        self.status_var.set(f"已把「{option['name']}」填入收益率 A：年化 {option['annual']:.4f}%")

    # ---------------------------------------------------------------- 关闭
    def destroy(self):  # pragma: no cover - GUI 生命周期
        for job in list(self._debounce_ids.values()):
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        super().destroy()


# ======================================================================================
# 十一、入口
# ======================================================================================
def _print_json(payload: dict, output: str | None = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output:
        try:
            with open(output, "w", encoding="utf-8") as handle:
                handle.write(text + "\n")
        except OSError as exc:  # pragma: no cover
            print(f"写入报告失败：{exc}", file=sys.stderr)
    print(text)


def _run_gui(dataset, source) -> int:
    try:
        app = App(dataset=dataset, source=source)
    except Exception as exc:  # tk.TclError 及其它 Tk 初始化失败
        is_tcl = TK_AVAILABLE and isinstance(exc, tk.TclError)
        title = "无法启动图形界面" if is_tcl else "图形界面初始化失败"
        print(f"[{title}] {exc}", file=sys.stderr)
        if is_tcl:
            print(
                "原因：当前运行环境没有可用的显示器（无头环境/远程会话/DISPLAY 未设置）。\n"
                "解决：\n"
                "  1) 在有桌面的 Windows / macOS / Linux 上双击运行，或执行 python app.py；\n"
                "  2) 只想验证公式，请用无头自检：python app.py --selftest\n"
                "以下自动执行一次无头自检，确认计算引擎正常：",
                file=sys.stderr,
            )
        report = run_selftest(verbose=False)
        summary = report["summary"]
        print(
            f"自检结果：{summary['passed']}/{summary['total']} 通过，{summary['failed']} 失败（ok={report['ok']}）",
            file=sys.stderr,
        )
        return 0 if report["ok"] else 1

    app.mainloop()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.py",
        description="利息计算器 · 桌面版（纯标准库 Tkinter，零第三方依赖）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python app.py                 启动图形界面\n"
            "  python app.py --selftest      无头自检，输出 JSON 并退出（0=全部通过）\n"
            "  python app.py --selftest -o report.json\n"
        ),
    )
    parser.add_argument("--selftest", action="store_true", help="无头自检：跑完所有公式验收用例并输出 JSON")
    parser.add_argument("--verbose", action="store_true", help="自检时把每条断言同时打印到 stderr")
    parser.add_argument("-o", "--output", default=None, help="把自检报告写入指定文件")
    parser.add_argument("--version", action="version", version=f"利息计算器桌面版 {__version__}")
    args = parser.parse_args(argv)

    if args.selftest:
        report = run_selftest(verbose=args.verbose)
        _print_json(report, args.output)
        return 0 if report["ok"] else 1

    dataset, source = load_rates()
    if not TK_AVAILABLE:
        print("当前 Python 缺少 tkinter，无法启动图形界面。", file=sys.stderr)
        print("请使用 --selftest 验证计算引擎：python app.py --selftest", file=sys.stderr)
        return 1
    return _run_gui(dataset, source)


if __name__ == "__main__":
    sys.exit(main())
