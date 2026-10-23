/*!
 * 利息计算器 · 公式核心
 * UMD：浏览器挂到 window.LixiFinance，Node 通过 module.exports 引入。
 * 纯函数、零依赖，与 SPEC.md 第 3 / 3.7 节完全一致（金额一律四舍五入到分）。
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.LixiFinance = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /** 计息基准天数（SPEC 第 3 节） */
  var DAY_BASIS = 365;
  /** 边界（SPEC 3.6） */
  var LIMITS = {
    principalMin: 0.01,
    principalMax: 1e12,
    monthsMin: 1,
    monthsMax: 1200,
    annualMin: 0,
    annualMax: 1000,
    daysMax: 36500
  };

  /* =========================== 基础工具 =========================== */

  /** 四舍五入到分：Math.round(x*100)/100 */
  function ROUND(x) {
    var n = Number(x);
    if (!isFinite(n)) throw new Error('数值无效，无法取整');
    return Math.round(n * 100) / 100;
  }

  /** 转为有限数字，否则抛错 */
  function num(value, label) {
    var n = typeof value === 'string' ? Number(value.replace(/[,\s]/g, '')) : Number(value);
    if (!isFinite(n)) throw new Error((label || '输入') + '不是有效数字');
    return n;
  }

  function checkPrincipal(value) {
    var v = num(value, '本金');
    if (v <= 0) throw new Error('本金必须大于 0');
    if (v < LIMITS.principalMin) throw new Error('本金不能小于 0.01 元');
    if (v > LIMITS.principalMax) throw new Error('本金不能超过 1 万亿元');
    return v;
  }

  function checkAnnual(value) {
    var v = num(value, '年化利率');
    if (v < 0) throw new Error('年化利率不能为负数');
    if (v > LIMITS.annualMax) throw new Error('年化利率不能超过 1000%');
    return v;
  }

  function checkMonths(value) {
    var v = Math.floor(num(value, '期数'));
    if (!(v >= LIMITS.monthsMin)) throw new Error('期数至少为 1 个月');
    if (v > LIMITS.monthsMax) throw new Error('期数不能超过 1200 个月');
    return v;
  }

  function checkDays(value) {
    var v = Math.floor(num(value, '天数'));
    if (!(v >= 1)) throw new Error('天数至少为 1 天');
    if (v > LIMITS.daysMax) throw new Error('天数不能超过 36500 天');
    return v;
  }

  /** 分（整数）为单位的精确求和，避免浮点累加误差 */
  function cents(value) {
    return Math.round(Number(value) * 100);
  }

  /* =========================== 3.1 利率归一化 =========================== */

  /** 支持的 kind 清单（与 SPEC 第 6 节一致） */
  var KINDS = [
    'annual_pct',
    'monthly_pct',
    'daily_pct',
    'monthly_fen',
    'annual_fen',
    'monthly_li',
    'annual_li',
    'monthly_hao',
    'daily_wan',
    'per10k_yuan',
    'lpr_plus_bp',
    'lpr_multiple',
    'range_annual_pct',
    'range_daily_wan'
  ];

  var RANGE_KINDS = { range_annual_pct: true, range_daily_wan: true };

  /**
   * 任意口径 → 年化利率（%）。
   * @param {number|null} value
   * @param {string} kind
   * @param {{lpr1y?:number,min?:number,max?:number}} [opts]
   */
  function normalizeToAnnual(value, kind, opts) {
    opts = opts || {};
    var lpr1y = opts.lpr1y == null ? 3.0 : num(opts.lpr1y, 'LPR');
    if (KINDS.indexOf(kind) < 0) throw new Error('未知的利率口径：' + kind);

    if (RANGE_KINDS[kind]) {
      if (opts.min == null || opts.max == null) throw new Error('区间类利率需要 min 与 max');
      var lo = num(opts.min, '区间下限');
      var hi = num(opts.max, '区间上限');
      if (lo < 0 || hi < 0) throw new Error('利率区间不能为负数');
      if (lo > hi) throw new Error('利率区间下限不能大于上限');
      var mid = (lo + hi) / 2;
      return kind === 'range_annual_pct' ? mid : (mid * DAY_BASIS) / 100;
    }

    if (value == null) throw new Error('缺少利率数值（kind=' + kind + '）');
    var v = num(value, '利率');
    // 只有「LPR 加点（BP）」允许负值（如 LPR-30BP 的浮动利差），其余口径不接受负利率
    if (v < 0 && kind !== 'lpr_plus_bp') throw new Error('利率不能为负数');

    var out;
    switch (kind) {
      case 'annual_pct':
        out = v;
        break;
      case 'monthly_pct':
        out = v * 12;
        break;
      case 'daily_pct':
        out = v * DAY_BASIS;
        break;
      case 'monthly_fen':
        out = v * 12;
        break;
      case 'annual_fen':
        out = v * 10;
        break;
      case 'monthly_li':
        out = v * 0.1 * 12;
        break;
      case 'annual_li':
        out = v;
        break;
      case 'monthly_hao':
        out = v * 0.01 * 12;
        break;
      // 日息万几：v/10000 为日利率小数，×365 为年利率小数，再 ×100 转百分数
      case 'daily_wan':
        out = (v * DAY_BASIS) / 100;
        break;
      // 万份收益（元/万份/天）：0.5 元/万份/天 → 1.825% 年化
      case 'per10k_yuan':
        out = (v * DAY_BASIS) / 100;
        break;
      case 'lpr_plus_bp':
        out = lpr1y + v / 100;
        break;
      case 'lpr_multiple':
        out = lpr1y * v;
        break;
      default:
        throw new Error('未知的利率口径：' + kind);
    }
    // 折算后的年化不允许为负（如 LPR-500BP 会算出负利率）
    if (out < 0) throw new Error('折算后的年化利率为负数，请检查输入');
    return out;
  }

  /** 年化 → 月/日 分解 */
  function breakdown(annualPct) {
    var a = checkAnnual(annualPct);
    return { annualPct: a, monthlyPct: a / 12, dailyPct: a / DAY_BASIS };
  }

  /* =========================== 3.2 每日利息 =========================== */

  /**
   * 每日/每月/每年/期间利息。
   * @param {number} principal
   * @param {number} annualPct
   * @param {number} [days=365]
   */
  function dailyInterest(principal, annualPct, days) {
    var p = checkPrincipal(principal);
    var a = checkAnnual(annualPct);
    var d = days == null ? DAY_BASIS : checkDays(days);
    var rate = a / 100;
    return {
      principal: ROUND(p),
      annualPct: a,
      days: d,
      daily: ROUND((p * rate) / DAY_BASIS),
      monthly: ROUND((p * rate) / 12),
      annual: ROUND(p * rate),
      periodInterest: ROUND((p * rate * d) / DAY_BASIS)
    };
  }

  /** 指定计息基准（365 / 360）下的每日利息，用于「日历天 / 360 天口径」切换 */
  function dailyInterestByBasis(principal, annualPct, days, basis, compound) {
    var p = checkPrincipal(principal);
    var a = checkAnnual(annualPct);
    var d = days == null ? 365 : checkDays(days);
    var b = num(basis, '计息基准');
    if (b !== 365 && b !== 360) throw new Error('计息基准只支持 365 或 360 天');
    var rate = a / 100;
    var daily = ROUND((p * rate) / b);
    var periodSimple = ROUND((p * rate * d) / b);
    // 复利必须以「日」为计息周期：日利率 = 年化 / 基准天数，终值 = P*(1+i)^d。
    // 旧实现误把「年」当周期写成 (1+年化)^(d/b)，导致复利反而小于单利。
    var periodCompound = ROUND(p * (Math.pow(1 + rate / b, d) - 1));
    return {
      principal: ROUND(p),
      annualPct: a,
      days: d,
      basis: b,
      daily: daily,
      monthly: ROUND((p * rate) / 12),
      annual: ROUND(p * rate),
      periodSimple: periodSimple,
      periodCompound: periodCompound,
      periodInterest: compound ? periodCompound : periodSimple,
      compoundGain: ROUND(periodCompound - periodSimple),
      endAmount: ROUND(p + (compound ? periodCompound : periodSimple))
    };
  }

  /** 复利分解：单利 / 复利 期间利息与差额 */
  function compoundInterest(principal, annualPct, days) {
    var p = checkPrincipal(principal);
    var a = checkAnnual(annualPct);
    var d = days == null ? DAY_BASIS : checkDays(days);
    var simple = ROUND((p * (a / 100) * d) / DAY_BASIS);
    // 按日复利：日利率 = 年化/365（见 dailyInterestByBasis 的同样修正）
    var compound = ROUND(p * (Math.pow(1 + a / 100 / DAY_BASIS, d) - 1));
    return {
      principal: ROUND(p),
      annualPct: a,
      days: d,
      simple: simple,
      compound: compound,
      diff: ROUND(compound - simple),
      simpleEnd: ROUND(p + simple),
      compoundEnd: ROUND(p + compound)
    };
  }

  /**
   * 双收益率对比（首页核心）。
   * @param {number} principal
   * @param {number} annualPctA
   * @param {number} annualPctB
   * @param {number} [days=365]
   */
  function compareRates(principal, annualPctA, annualPctB, days) {
    var p = checkPrincipal(principal);
    var a = checkAnnual(annualPctA);
    var b = checkAnnual(annualPctB);
    var d = days == null ? DAY_BASIS : checkDays(days);
    var A = dailyInterest(p, a, d);
    var B = dailyInterest(p, b, d);
    var better = A.periodInterest > B.periodInterest ? 'a' : A.periodInterest < B.periodInterest ? 'b' : 'equal';
    if (better === 'equal' && a !== b) {
      better = a < b ? 'b' : 'a';
    }
    var ratio = A.daily === 0 ? null : B.daily / A.daily;
    return {
      a: {
        annualPct: A.annualPct,
        daily: A.daily,
        monthly: A.monthly,
        annual: A.annual,
        periodInterest: A.periodInterest
      },
      b: {
        annualPct: B.annualPct,
        daily: B.daily,
        monthly: B.monthly,
        annual: B.annual,
        periodInterest: B.periodInterest
      },
      diffDaily: ROUND(B.daily - A.daily),
      diffMonthly: ROUND(B.monthly - A.monthly),
      diffAnnual: ROUND(B.annual - A.annual),
      diffPeriod: ROUND(B.periodInterest - A.periodInterest),
      better: better,
      higherAnnualPct: Math.max(a, b),
      lowerAnnualPct: Math.min(a, b),
      ratio: ratio == null ? null : Math.round(ratio * 10000) / 10000,
      days: d,
      principal: ROUND(p)
    };
  }

  /* =========================== 3.3 贷款分期 =========================== */

  function buildResult(method, P, annualPct, months, monthlyRate, payment, rows) {
    var totalPayC = 0;
    var totalIntC = 0;
    var totalPrinC = 0;
    for (var k = 0; k < rows.length; k++) {
      totalPayC += cents(rows[k].payment);
      totalIntC += cents(rows[k].interest);
      totalPrinC += cents(rows[k].principal);
    }
    return {
      method: method,
      principal: ROUND(P),
      annualPct: annualPct,
      months: months,
      monthlyRate: monthlyRate,
      payment: payment,
      totalPayment: totalPayC / 100,
      totalInterest: totalIntC / 100,
      totalPrincipal: totalPrinC / 100,
      schedule: rows
    };
  }

  /** 等额本息 */
  function equalInstallment(principal, annualPct, months) {
    var P = ROUND(checkPrincipal(principal));
    var a = checkAnnual(annualPct);
    var n = checkMonths(months);
    var i = a / 100 / 12;

    // ---- 零利率（免息分期）单独分支 ----
    // 若沿用「末期 interest = 月供 - 剩余本金」的公式，除不尽的残差会被当成利息，
    // 出现「免息却收利息」甚至「负利息 / 总还款 < 本金」的荒谬结果。
    // 这里改为按「分」做整数均分：利息恒为 0，尾差全部落到最后一期的本金上。
    if (i === 0) {
      var totalC = cents(P);
      var baseC = Math.floor(totalC / n);
      var remC = totalC % n;
      var rows0 = [];
      var left0 = totalC;
      for (var k0 = 1; k0 <= n; k0++) {
        var principalC0 = k0 === n ? left0 : baseC;
        left0 -= principalC0;
        rows0.push({
          period: k0,
          payment: principalC0 / 100,
          principal: principalC0 / 100,
          interest: 0,
          remaining: left0 / 100
        });
      }
      return buildResult('equal_installment', P, a, n, i, baseC / 100, rows0);
    }

    var f = Math.pow(1 + i, n);
    var payment = ROUND((P * i * f) / (f - 1));
    // 末期口径（SPEC 3.7 第 5 条唯一权威定义）：
    //   每期 payment 恒等于 pay，最后一期也不例外；
    //   最后一期 principal 用剩余本金强制结平，interest = pay - principal，
    //   即把浮点尾差吸收进末期利息，而不是改动月供。
    var payC = cents(payment);
    var remainingC = cents(P);
    var rows = [];
    for (var k = 1; k <= n; k++) {
      var interestC;
      var principalC;
      if (k === n) {
        // 末期：本金 = 上期剩余，利息 = 月供 - 本金
        principalC = remainingC;
        interestC = payC - principalC;
      } else {
        var rem = remainingC / 100;
        interestC = Math.round(rem * i * 100);
        principalC = payC - interestC;
        if (principalC < 0) principalC = 0;
        if (principalC > remainingC) principalC = remainingC;
      }
      remainingC -= principalC;
      if (k === n) remainingC = 0;
      rows.push({
        period: k,
        // 最后一期 payment 仍为 payC；前 n-1 期按定义也等于 payC
        payment: (principalC + interestC) / 100,
        principal: principalC / 100,
        interest: interestC / 100,
        remaining: remainingC / 100
      });
    }
    return buildResult('equal_installment', P, a, n, i, payment, rows);
  }

  /** 等额本金 */
  function equalPrincipal(principal, annualPct, months) {
    var P = ROUND(checkPrincipal(principal));
    var a = checkAnnual(annualPct);
    var n = checkMonths(months);
    var i = a / 100 / 12;
    var baseC = Math.round((P / n) * 100);
    var remainingC = cents(P);
    var rows = [];
    for (var k = 1; k <= n; k++) {
      var rem = remainingC / 100;
      var interestC = Math.round(rem * i * 100);
      var principalC = k === n ? remainingC : Math.min(baseC, remainingC);
      remainingC -= principalC;
      if (k === n) remainingC = 0;
      rows.push({
        period: k,
        payment: (principalC + interestC) / 100,
        principal: principalC / 100,
        interest: interestC / 100,
        remaining: remainingC / 100
      });
    }
    return buildResult('equal_principal', P, a, n, i, rows.length ? rows[0].payment : 0, rows);
  }

  /** 先息后本 */
  function interestFirst(principal, annualPct, months) {
    var P = ROUND(checkPrincipal(principal));
    var a = checkAnnual(annualPct);
    var n = checkMonths(months);
    var i = a / 100 / 12;
    var monthIntC = Math.round(P * i * 100);
    var remainingC = cents(P);
    var rows = [];
    for (var k = 1; k <= n; k++) {
      var principalC = k === n ? remainingC : 0;
      remainingC -= principalC;
      if (k === n) remainingC = 0;
      rows.push({
        period: k,
        payment: (principalC + monthIntC) / 100,
        principal: principalC / 100,
        interest: monthIntC / 100,
        remaining: remainingC / 100
      });
    }
    return buildResult('interest_first', P, a, n, i, monthIntC / 100, rows);
  }

  /** 到期一次还本付息（单利、按月计息） */
  function bullet(principal, annualPct, months) {
    var P = ROUND(checkPrincipal(principal));
    var a = checkAnnual(annualPct);
    var n = checkMonths(months);
    var i = a / 100 / 12;
    var totalIntC = Math.round(P * i * n * 100);
    var remainingC = cents(P);
    var rows = [];
    for (var k = 1; k <= n; k++) {
      if (k === n) {
        var principalC = remainingC;
        remainingC = 0;
        rows.push({
          period: k,
          payment: (principalC + totalIntC) / 100,
          principal: principalC / 100,
          interest: totalIntC / 100,
          remaining: 0
        });
      } else {
        rows.push({ period: k, payment: 0, principal: 0, interest: 0, remaining: remainingC / 100 });
      }
    }
    var result = buildResult('bullet', P, a, n, i, 0, rows);
    result.payment = result.schedule.length ? result.schedule[result.schedule.length - 1].payment : 0;
    return result;
  }

  /** 统一入口 */
  function loanSchedule(principal, annualPct, months, method) {
    switch (method) {
      case 'equal_installment':
        return equalInstallment(principal, annualPct, months);
      case 'equal_principal':
        return equalPrincipal(principal, annualPct, months);
      case 'interest_first':
        return interestFirst(principal, annualPct, months);
      case 'bullet':
        return bullet(principal, annualPct, months);
      default:
        throw new Error('未知的还款方式：' + method);
    }
  }

  /** 汇总 */
  function scheduleSummary(schedule) {
    if (!Array.isArray(schedule) || schedule.length === 0) {
      throw new Error('还款计划为空');
    }
    var payC = 0;
    var intC = 0;
    var prinC = 0;
    for (var k = 0; k < schedule.length; k++) {
      payC += cents(schedule[k].payment);
      intC += cents(schedule[k].interest);
      prinC += cents(schedule[k].principal);
    }
    var n = schedule.length;
    return {
      months: n,
      totalPayment: payC / 100,
      totalInterest: intC / 100,
      totalPrincipal: prinC / 100,
      firstPayment: ROUND(schedule[0].payment),
      lastPayment: ROUND(schedule[n - 1].payment),
      avgPayment: n ? ROUND(payC / 100 / n) : 0
    };
  }

  /* =========================== 3.4 网贷 / 日还款 =========================== */

  /** 按天计息、按天还本 */
  function dailyPayment(principal, annualPct, days) {
    var P = ROUND(checkPrincipal(principal));
    var a = checkAnnual(annualPct);
    var d = checkDays(days);
    var dailyIntC = Math.round((P * a) / 100 / DAY_BASIS * 100);
    var dailyPrinC = Math.round((P / d) * 100);
    var totalIntC = dailyIntC * d;
    return {
      principal: P,
      annualPct: a,
      days: d,
      dailyInterest: dailyIntC / 100,
      dailyPrincipal: dailyPrinC / 100,
      dailyPayment: (dailyIntC + dailyPrinC) / 100,
      totalPrincipal: ROUND(P),
      totalPayment: (cents(P) + totalIntC) / 100,
      totalInterest: totalIntC / 100
    };
  }

  /** 网贷还款：每日还息到期还本 / 每日等额本息 */
  function onlineLoan(principal, annualPct, days, method) {
    var P = ROUND(checkPrincipal(principal));
    var a = checkAnnual(annualPct);
    var d = checkDays(days);
    var m = method || 'interest_first';
    var i = a / 100 / DAY_BASIS;
    var rows = [];
    var k;

    if (m === 'interest_first') {
      var dailyIntC = Math.round(P * i * 100);
      for (k = 1; k <= d; k++) {
        var last = k === d;
        rows.push({
          day: k,
          payment: (last ? cents(P) + dailyIntC : dailyIntC) / 100,
          principal: (last ? cents(P) : 0) / 100,
          interest: dailyIntC / 100,
          remaining: (last ? 0 : cents(P)) / 100
        });
      }
      var totalIntC = dailyIntC * d;
      return {
        method: 'interest_first',
        principal: P,
        annualPct: a,
        days: d,
        dailyInterest: dailyIntC / 100,
        dailyPayment: dailyIntC / 100,
        totalInterest: totalIntC / 100,
        totalPayment: (cents(P) + totalIntC) / 100,
        monthlyRate: i * 30,
        schedule: rows
      };
    }

    if (m !== 'equal_installment_daily') throw new Error('未知的网贷还款方式：' + m);

    var payment;
    if (i === 0) {
      payment = ROUND(P / d);
    } else {
      var f = Math.pow(1 + i, d);
      payment = ROUND((P * i * f) / (f - 1));
    }
    var payC = cents(payment);
    var remainingC = cents(P);
    var payTotalC = 0;
    var intTotalC = 0;
    for (k = 1; k <= d; k++) {
      var rem = remainingC / 100;
      var interestC = Math.round(rem * i * 100);
      var principalC;
      if (k === d) {
        principalC = remainingC;
      } else {
        principalC = payC - interestC;
        if (principalC < 0) principalC = 0;
        if (principalC > remainingC) principalC = remainingC;
      }
      remainingC -= principalC;
      if (k === d) remainingC = 0;
      payTotalC += principalC + interestC;
      intTotalC += interestC;
      rows.push({
        day: k,
        payment: (principalC + interestC) / 100,
        principal: principalC / 100,
        interest: interestC / 100,
        remaining: remainingC / 100
      });
    }
    return {
      method: 'equal_installment_daily',
      principal: P,
      annualPct: a,
      days: d,
      dailyInterest: rows[0].interest,
      dailyPayment: rows[0].payment,
      totalInterest: intTotalC / 100,
      totalPayment: payTotalC / 100,
      monthlyRate: i * 30,
      schedule: rows
    };
  }

  /** 平台利率 → 年化（复用 normalizeToAnnual） */
  function platformToAnnual(rate, kind, opts) {
    if (rate && typeof rate === 'object') {
      var r = rate;
      return normalizeToAnnual(r.kind === 'range_annual_pct' || r.kind === 'range_daily_wan' ? null : r.value, r.kind, {
        lpr1y: r.lpr1y,
        min: r.min,
        max: r.max
      });
    }
    return normalizeToAnnual(rate, kind, opts);
  }

  /* =========================== 3.5 折算工具 =========================== */

  /** 通用 IRR（二分法，区间 [-0.999999, 10]） */
  function irr(cashflows) {
    if (!Array.isArray(cashflows) || cashflows.length < 2) throw new Error('现金流至少需要 2 期');
    var cf = [];
    for (var k = 0; k < cashflows.length; k++) {
      var v = num(cashflows[k], '现金流');
      cf.push(v);
    }
    var hasPos = false;
    var hasNeg = false;
    for (var j = 0; j < cf.length; j++) {
      if (cf[j] > 0) hasPos = true;
      if (cf[j] < 0) hasNeg = true;
    }
    if (!hasPos || !hasNeg) throw new Error('现金流必须同时包含正负值，IRR 无解');

    function npv(rate) {
      var sum = 0;
      for (var t = 0; t < cf.length; t++) sum += cf[t] / Math.pow(1 + rate, t);
      return sum;
    }

    var lo = -0.999999;
    var hi = 10;
    var flo = npv(lo);
    var fhi = npv(hi);
    if (flo * fhi > 0) throw new Error('在给定区间内找不到 IRR');
    var mid = 0;
    for (var it = 0; it < 200; it++) {
      mid = (lo + hi) / 2;
      var fm = npv(mid);
      if (Math.abs(fm) < 1e-12) break;
      if (flo * fm <= 0) {
        hi = mid;
        fhi = fm;
      } else {
        lo = mid;
        flo = fm;
      }
      if (hi - lo < 1e-12) break;
    }
    return mid;
  }

  /** 分期手续费 → 真实年化 */
  function aprFromFee(principal, monthlyFeePct, months) {
    var P = checkPrincipal(principal);
    var fee = num(monthlyFeePct, '月费率');
    if (fee < 0) throw new Error('手续费率不能为负数');
    if (fee > 100) throw new Error('手续费率不能超过 100%');
    var n = checkMonths(months);
    var perMonth = P / n + (P * fee) / 100;
    var flows = [P];
    for (var k = 1; k <= n; k++) flows.push(-perMonth);
    var monthlyIrr = irr(flows);
    var totalFeeC = Math.round((P * fee * n) / 100 * 100);
    var totalFee = totalFeeC / 100;
    return {
      principal: P,
      monthlyFeePct: fee,
      months: n,
      monthlyPayment: ROUND(perMonth),
      monthlyIrr: monthlyIrr,
      aprAnnual: Math.round(((Math.pow(1 + monthlyIrr, 12) - 1) * 100) * 1e6) / 1e6,
      aprSimple: Math.round(fee * 12 * 1e6) / 1e6,
      totalFee: totalFee,
      totalPayment: ROUND(P + totalFee)
    };
  }

  /** 有效年利率 */
  function effectiveAnnual(annualPct, compoundsPerYear) {
    var a = checkAnnual(annualPct);
    var n = num(compoundsPerYear == null ? 12 : compoundsPerYear, '复利次数');
    if (!(n >= 1)) throw new Error('每年复利次数至少为 1');
    var r = a / 100;
    return Math.round((Math.pow(1 + r / n, n) - 1) * 100 * 1e6) / 1e6;
  }

  /** 名义 → 有效年化（含差额），供界面提示复利影响 */
  function effectiveTable(annualPct) {
    var a = checkAnnual(annualPct);
    return {
      annualPct: a,
      monthly: effectiveAnnual(a, 12),
      daily: effectiveAnnual(a, DAY_BASIS),
      quarterly: effectiveAnnual(a, 4),
      semiannual: effectiveAnnual(a, 2)
    };
  }

  /**
   * 全口径换算。
   * @param {number|null} value
   * @param {string} kind
   * @param {{lpr1y?:number,min?:number,max?:number}} [opts]
   */
  function convert(value, kind, opts) {
    var annualPct = normalizeToAnnual(value, kind, opts);
    var monthlyPct = annualPct / 12;
    var r6 = function (x) {
      return Math.round(x * 1e6) / 1e6;
    };
    return {
      annualPct: r6(annualPct),
      monthlyPct: r6(monthlyPct),
      dailyPct: r6(annualPct / DAY_BASIS),
      monthlyFen: r6(annualPct / 12),
      annualFen: r6(annualPct / 10),
      monthlyLi: r6(annualPct / 12 / 0.1),
      annualLi: r6(annualPct),
      monthlyHao: r6(annualPct / 12 / 0.01),
      dailyWan: r6((annualPct / 100 / DAY_BASIS) * 10000),
      basisPoints: r6(annualPct * 100)
    };
  }

  /* =========================== 对外 API =========================== */

  return {
    DAY_BASIS: DAY_BASIS,
    LIMITS: LIMITS,
    ROUND: ROUND,
    KINDS: KINDS,
    RANGE_KINDS: RANGE_KINDS,
    normalizeToAnnual: normalizeToAnnual,
    platformToAnnual: platformToAnnual,
    breakdown: breakdown,
    dailyInterest: dailyInterest,
    dailyInterestByBasis: dailyInterestByBasis,
    compoundInterest: compoundInterest,
    compareRates: compareRates,
    equalInstallment: equalInstallment,
    equalPrincipal: equalPrincipal,
    interestFirst: interestFirst,
    bullet: bullet,
    loanSchedule: loanSchedule,
    scheduleSummary: scheduleSummary,
    dailyPayment: dailyPayment,
    onlineLoan: onlineLoan,
    irr: irr,
    aprFromFee: aprFromFee,
    effectiveAnnual: effectiveAnnual,
    effectiveTable: effectiveTable,
    convert: convert
  };
});
