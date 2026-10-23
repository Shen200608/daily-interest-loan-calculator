#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 data/rates.json 的结构与数值合法性。

用法:
    python tools/validate_rates.py [data/rates.json]

退出码: 0 = 通过, 1 = 有错误
"""
from __future__ import annotations

import json
import os
import sys

# Windows 控制台默认可能是 cp1252/cp936，强制 UTF-8 输出，避免打印中文时 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

VALID_KINDS = {
    "annual_pct",
    "monthly_pct",
    "daily_pct",
    "monthly_fen",
    "annual_fen",
    "monthly_li",
    "annual_li",
    "monthly_hao",
    "daily_wan",
    "per10k_yuan",
    "lpr_plus_bp",
    "lpr_multiple",
    "range_annual_pct",
    "range_daily_wan",
}
RANGE_KINDS = {"range_annual_pct", "range_daily_wan"}
REQUIRED_GROUP_IDS = {"official", "customary", "deposit", "loan", "online_loan"}
REQUIRED_RATE_FIELDS = ("id", "group", "name", "aliases", "kind", "display", "asOf", "note", "source")
MIN_RATES = 45


def normalize(kind: str, value, opts: dict) -> float:
    """kind -> 年化百分数（与 SPEC 第 6 节一致）。"""
    lpr1y = float(opts.get("lpr1y", 3.0))
    if kind == "annual_pct":
        return float(value)
    if kind == "monthly_pct":
        return float(value) * 12
    if kind == "daily_pct":
        return float(value) * 365
    if kind == "monthly_fen":
        return float(value) * 12
    if kind == "annual_fen":
        return float(value) * 10
    if kind == "monthly_li":
        return float(value) * 0.1 * 12
    if kind == "annual_li":
        return float(value)
    if kind == "monthly_hao":
        return float(value) * 0.01 * 12
    if kind == "daily_wan":
        return float(value) * 365 / 100
    if kind == "per10k_yuan":
        return float(value) / 10000 * 365
    if kind == "lpr_plus_bp":
        return lpr1y + float(value) / 100
    if kind == "lpr_multiple":
        return lpr1y * float(value)
    if kind == "range_annual_pct":
        return (float(opts["min"]) + float(opts["max"])) / 2
    if kind == "range_daily_wan":
        return (float(opts["min"]) + float(opts["max"])) / 2 * 365 / 100
    raise ValueError(f"未知 kind: {kind}")


def main(argv: list[str]) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    path = argv[1] if len(argv) > 1 else os.path.join(here, "..", "data", "rates.json")
    path = os.path.abspath(path)
    errors: list[str] = []
    warnings: list[str] = []

    if not os.path.exists(path):
        print(f"[FAIL] 找不到文件: {path}")
        return 1

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        if raw.lstrip().startswith("\ufeff"):
            errors.append("文件带 UTF-8 BOM，请保存为无 BOM 的 UTF-8")
            raw = raw.lstrip("\ufeff")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[FAIL] JSON 解析失败: {exc}")
        return 1

    # ---- meta ----
    meta = data.get("meta")
    if not isinstance(meta, dict):
        errors.append("缺少 meta 对象")
        meta = {}
    lpr = meta.get("lpr") or {}
    lpr1y = lpr.get("1y")
    if not isinstance(lpr1y, (int, float)):
        errors.append("meta.lpr['1y'] 缺失或不是数字")
        lpr1y = 3.0
    for key in ("version", "updated", "currency", "judicial_cap_multiple", "disclaimer"):
        if key not in meta:
            errors.append(f"meta 缺少字段: {key}")
    if not meta.get("sources"):
        warnings.append("meta.sources 为空，建议补充数据来源链接")
    else:
        for i, src in enumerate(meta["sources"]):
            if not isinstance(src, dict) or not src.get("url"):
                errors.append(f"meta.sources[{i}] 缺少 url")

    # ---- groups ----
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        errors.append("缺少 groups 数组")
        groups = []
    group_ids = set()
    for i, g in enumerate(groups):
        if not isinstance(g, dict):
            errors.append(f"groups[{i}] 不是对象")
            continue
        for key in ("id", "title", "desc"):
            if not g.get(key):
                errors.append(f"groups[{i}] 缺少 {key}")
        if g.get("id"):
            if g["id"] in group_ids:
                errors.append(f"groups id 重复: {g['id']}")
            group_ids.add(g["id"])
    for need in sorted(REQUIRED_GROUP_IDS - group_ids):
        errors.append(f"缺少必需的 group: {need}")

    # ---- rates ----
    rates = data.get("rates")
    if not isinstance(rates, list):
        errors.append("缺少 rates 数组")
        rates = []

    ids: dict[str, int] = {}
    per_group: dict[str, int] = {}
    for i, r in enumerate(rates):
        where = f"rates[{i}]"
        if not isinstance(r, dict):
            errors.append(f"{where} 不是对象")
            continue
        rid = r.get("id")
        if not rid:
            errors.append(f"{where} 缺少 id")
        else:
            where = f"rates[{i}]({rid})"
            if rid in ids:
                errors.append(f"{where} id 与 rates[{ids[rid]}] 重复")
            ids[rid] = i

        for key in REQUIRED_RATE_FIELDS:
            if key in ("aliases",):
                continue
            if r.get(key) in (None, ""):
                errors.append(f"{where} 缺少字段 {key}")
        aliases = r.get("aliases")
        if not isinstance(aliases, list) or not aliases:
            errors.append(f"{where} aliases 必须是非空数组")
        elif len(aliases) < 2:
            warnings.append(f"{where} aliases 只有 {len(aliases)} 个，建议 2 个以上")

        gid = r.get("group")
        if gid not in group_ids:
            errors.append(f"{where} group '{gid}' 不在 groups 中")
        per_group[gid] = per_group.get(gid, 0) + 1

        kind = r.get("kind")
        if kind not in VALID_KINDS:
            errors.append(f"{where} 非法 kind: {kind!r}")
            continue

        try:
            if kind in RANGE_KINDS:
                mn, mx = r.get("min"), r.get("max")
                if mn is None or mx is None:
                    errors.append(f"{where} 区间类条目必须提供 min 和 max")
                    continue
                if "value" not in r or r.get("value") is not None:
                    errors.append(f"{where} 区间类条目不要写 value")
                if float(mn) > float(mx):
                    errors.append(f"{where} min({mn}) 大于 max({mx})")
                annual = normalize(kind, None, {"min": mn, "max": mx, "lpr1y": lpr1y})
            else:
                if r.get("value") is None:
                    errors.append(f"{where} 非区间类条目必须提供 value")
                    continue
                annual = normalize(kind, r["value"], {"lpr1y": lpr1y})
        except (TypeError, ValueError, KeyError) as exc:
            errors.append(f"{where} 换算失败: {exc}")
            continue

        if annual < 0:
            errors.append(f"{where} 换算出的年化为负数: {annual}")
        if annual > 1000:
            errors.append(f"{where} 换算出的年化异常高 ({annual:.2f}%)，请检查单位")
        if annual == 0 and rid not in ("stub",):
            warnings.append(f"{where} 换算出的年化为 0")

        src = r.get("source") or ""
        if src and not str(src).startswith("http"):
            warnings.append(f"{where} source 看起来不是 URL: {src}")

    if len(rates) < MIN_RATES:
        errors.append(f"rates 条目数 {len(rates)} < {MIN_RATES}（用户要求「选项要全」）")

    # ---- 输出 ----
    print(f"文件: {path}")
    print(f"条目数: {len(rates)}   分组: {len(groups)}")
    for gid in sorted(per_group, key=lambda k: (-per_group[k], k)):
        print(f"  - {gid:<14} {per_group[gid]:>3} 条")
    print(f"LPR(1年期): {lpr1y}%    司法保护上限: {lpr1y * float(meta.get('judicial_cap_multiple', 4)):.2f}%")

    if warnings:
        print(f"\n警告 {len(warnings)} 条:")
        for w in warnings[:30]:
            print(f"  ! {w}")
        if len(warnings) > 30:
            print(f"  ... 另有 {len(warnings) - 30} 条")

    if errors:
        print(f"\n错误 {len(errors)} 条:")
        for e in errors[:60]:
            print(f"  x {e}")
        if len(errors) > 60:
            print(f"  ... 另有 {len(errors) - 60} 条")
        print("\n[FAIL] 校验未通过")
        return 1

    print("\n[OK] 校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
