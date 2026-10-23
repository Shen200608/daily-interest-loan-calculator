#!/usr/bin/env node
/**
 * 网页版（js/finance.js）公式验收测试（与 tests/test_finance.py 同一套用例）。
 *
 * 运行:
 *   node --test tests/test_finance.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

const F = require(path.join(ROOT, 'js', 'finance.js'));

const near = (actual, expected, delta, msg) =>
  assert.ok(
    Math.abs(Number(actual) - Number(expected)) <= delta,
    `${msg || ''} 期望 ${expected} ±${delta}，实际 ${actual}`
  );

test('常量 DAY_BASIS = 365', () => {
  assert.equal(F.DAY_BASIS, 365);
});

test('normalizeToAnnual 全口径换算', () => {
  const cases = [
    [[3.65, 'annual_pct'], 3.65],
    [[1.0, 'monthly_pct'], 12.0],
    [[0.05, 'daily_pct'], 18.25],
    [[1.0, 'monthly_fen'], 12.0],
    [[1.0, 'annual_fen'], 10.0],
    [[5.0, 'monthly_li'], 6.0],
    [[5.0, 'annual_li'], 5.0],
    [[5.0, 'monthly_hao'], 0.6],
    [[5.0, 'daily_wan'], 18.25],
    [[0.5, 'per10k_yuan'], 1.825],
    [[60.0, 'lpr_plus_bp'], 3.6],
    [[4.0, 'lpr_multiple'], 12.0],
  ];
  for (const [args, expected] of cases) {
    near(F.normalizeToAnnual(...args), expected, 1e-6, `kind=${args[1]}`);
  }
});

test('normalizeToAnnual 区间类用 min/max 取中值', () => {
  near(F.normalizeToAnnual(null, 'range_annual_pct', { min: 7.2, max: 24.0 }), 15.6, 1e-6);
  // 日息万2~万6，中值万4 → 年化 4*365/100 = 14.6%
  near(F.normalizeToAnnual(null, 'range_daily_wan', { min: 2.0, max: 6.0 }), 14.6, 1e-6);
});

test('breakdown', () => {
  const r = F.breakdown(3.65);
  near(r.annualPct, 3.65, 1e-6);
  near(r.monthlyPct, 3.65 / 12, 1e-6);
  near(r.dailyPct, 3.65 / 365, 1e-6);
});

test('复利必须以「日」为计息周期（防止 (1+年化)^(d/365) 的历史 bug）', () => {
  // 回归：旧实现把「年」当周期，导致复利反而小于单利，且 365 天时复利退化成单利。
  for (const [rate, days] of [[1.5, 30], [3.65, 30], [12, 30], [24, 30], [3.65, 365], [12, 90]]) {
    const c = F.compoundInterest(10000, rate, days);
    assert.ok(c.compound >= c.simple, `年化${rate}% ${days}天：复利(${c.compound})应 >= 单利(${c.simple})`);
    const expected = 10000 * (Math.pow(1 + rate / 100 / 365, days) - 1);
    near(c.compound, expected, 0.01, `年化${rate}% ${days}天复利`);
  }
  // 365 天复利必须严格大于单利（旧 bug 下两者相等）
  const y = F.compoundInterest(10000, 3.65, 365);
  near(y.compound, 371.72, 0.02);
  assert.ok(y.compound > y.simple + 6, '365 天复利应显著大于单利');
});

test('dailyInterestByBasis 的复利口径正确（365 / 360 基准）', () => {
  for (const basis of [365, 360]) {
    const r = F.dailyInterestByBasis(10000, 3.65, 30, basis, true);
    const s = F.dailyInterestByBasis(10000, 3.65, 30, basis, false);
    assert.ok(r.periodInterest >= s.periodInterest, `基准${basis}：复利应 >= 单利`);
    const expected = 10000 * (Math.pow(1 + 0.0365 / basis, 30) - 1);
    near(r.periodInterest, expected, 0.01, `基准${basis} 复利`);
    near(r.compoundGain, r.periodCompound - r.periodSimple, 0.01);
  }
  // 基准仍按 365/360 生效
  near(F.dailyInterestByBasis(10000, 3.65, 30, 360, false).daily, 1.01, 0.005);
  near(F.dailyInterestByBasis(10000, 3.65, 30, 365, false).daily, 1.0, 0.005);
});

test('持有天数只影响期间利息，不影响每日/每月/每年', () => {
  const base = F.dailyInterestByBasis(10000, 3.65, 7, 365, false);
  for (const d of [7, 30, 90, 365, 1000]) {
    const r = F.dailyInterestByBasis(10000, 3.65, d, 365, false);
    near(r.daily, base.daily, 1e-9, `${d}天 每日利息`);
    near(r.monthly, base.monthly, 1e-9, `${d}天 每月利息`);
    near(r.annual, base.annual, 1e-9, `${d}天 每年利息`);
    near(r.periodInterest, F.ROUND(10000 * 0.0365 * d / 365), 0.01, `${d}天 期间利息`);
  }
});

test('验收 2：本金 10000、3.65% → 每日 1.00；7.3% → 每日 2.00', () => {
  near(F.dailyInterest(10000, 3.65).daily, 1.0, 0.005);
  near(F.dailyInterest(10000, 7.3).daily, 2.0, 0.005);
  const r = F.dailyInterest(10000, 3.65);
  near(r.monthly, 30.42, 0.01);
  near(r.annual, 365.0, 0.01);
});

test('dailyInterest 期间利息', () => {
  const r = F.dailyInterest(10000, 3.65, 30);
  near(r.periodInterest, 30.0, 0.02);
});

test('dailyInterest 非法输入抛错', () => {
  assert.throws(() => F.dailyInterest(0, 3.65));
  assert.throws(() => F.dailyInterest(-1, 3.65));
  assert.throws(() => F.dailyInterest(10000, -1));
  assert.throws(() => F.dailyInterest(NaN, 3.65));
});

test('compareRates：B 更高', () => {
  const r = F.compareRates(10000, 3.65, 7.3);
  assert.equal(r.better, 'b');
  near(r.diffDaily, 1.0, 0.01);
  near(r.diffAnnual, 365.0, 0.01);
  near(r.ratio, 2.0, 0.01);
});

test('compareRates：A 更高 / 相等', () => {
  assert.equal(F.compareRates(10000, 12, 3.65).better, 'a');
  assert.equal(F.compareRates(10000, 5, 5).better, 'equal');
});

function checkInvariants(r, principal) {
  const sched = r.schedule;
  assert.ok(Array.isArray(sched) && sched.length > 0, 'schedule 应为非空数组');
  const sp = sched.reduce((a, x) => a + x.principal, 0);
  const si = sched.reduce((a, x) => a + x.interest, 0);
  const st = sched.reduce((a, x) => a + x.payment, 0);
  near(sp, principal, 0.02, 'Σ本金 应等于 principal');
  near(si, r.totalInterest, 0.02, 'Σ利息 应等于 totalInterest');
  near(st, r.totalPayment, 0.02, 'Σ月供 应等于 totalPayment');
  near(sched[sched.length - 1].remaining, 0, 0.02, '最后一期剩余本金应为 0');
  for (const row of sched) near(row.payment, row.principal + row.interest, 0.02, 'payment=本金+利息');
}

test('验收 3：100 万 / 4.9% / 30 年等额本息 ≈ 5307.27', () => {
  const r = F.equalInstallment(1000000, 4.9, 360);
  near(r.payment, 5307.27, 5307.27 * 0.005);
  near(r.totalInterest, 910600, 910600 * 0.02);
  checkInvariants(r, 1000000);
});

test('等额本息零利率', () => {
  const r = F.equalInstallment(12000, 0, 12);
  near(r.payment, 1000, 0.01);
  near(r.totalInterest, 0, 0.01);
  checkInvariants(r, 12000);
});

test('零利率免息分期不得出现「幻影利息」', () => {
  // 本金不能被期数整除到「分」时，旧实现会把取整残差当成利息，
  // 出现「免息却要付利息」甚至「总还款 < 本金」（负利息）。
  const cases = [
    [100, 7],
    [1000, 365],
    [5000, 24],
    [999.99, 7],
    [12000, 12],
    [0.01, 3],
  ];
  for (const [principal, months] of cases) {
    const r = F.equalInstallment(principal, 0, months);
    near(r.totalInterest, 0, 0.005, `${principal}/${months} 期利息应为 0`);
    near(r.totalPayment, principal, 0.005, `${principal}/${months} 期总还款应等于本金`);
    near(
      r.schedule.reduce((s, x) => s + x.principal, 0),
      principal,
      0.005,
      `${principal}/${months} 期 Σ本金应等于本金`
    );
    near(r.schedule[r.schedule.length - 1].remaining, 0, 0.005);
    for (const row of r.schedule) near(row.interest, 0, 0.005, '每期利息都应为 0');
  }
});

test('等额本金', () => {
  const r = F.equalPrincipal(12000, 12, 12);
  near(r.schedule[0].principal, 1000, 0.01);
  near(r.schedule[0].interest, 120, 0.01);
  near(r.schedule[0].payment, 1120, 0.01);
  near(r.schedule[11].payment, 1010, 0.01);
  near(r.totalInterest, 780, 0.02);
  checkInvariants(r, 12000);
});

test('先息后本', () => {
  const r = F.interestFirst(10000, 12, 12);
  near(r.totalInterest, 1200, 0.02);
  near(r.schedule[0].payment, 100, 0.01);
  near(r.schedule[11].payment, 10100, 0.01);
  checkInvariants(r, 10000);
});

test('到期一次还本付息', () => {
  const r = F.bullet(10000, 12, 12);
  near(r.totalInterest, 1200, 0.02);
  near(r.schedule[11].payment, 11200, 0.01);
  checkInvariants(r, 10000);
});

test('loanSchedule 分派', () => {
  for (const m of ['equal_installment', 'equal_principal', 'interest_first', 'bullet']) {
    const r = F.loanSchedule(50000, 8, 24, m);
    assert.equal(r.method, m);
    checkInvariants(r, 50000);
  }
});

test('scheduleSummary', () => {
  const r = F.loanSchedule(50000, 8, 24, 'equal_installment');
  const s = F.scheduleSummary(r.schedule);
  near(s.totalInterest, r.totalInterest, 0.02);
  near(s.totalPayment, r.totalPayment, 0.02);
  assert.equal(s.months, 24);
});

test('验收 6：网贷 日息万5 / 10000 / 30 天', () => {
  const r = F.dailyPayment(10000, 18.25, 30);
  near(r.dailyInterest, 5.0, 0.005);
  near(r.totalInterest, 150.0, 0.02);
});

test('onlineLoan 两种还款方式', () => {
  const a = F.onlineLoan(10000, 18.25, 30, 'interest_first');
  near(a.dailyInterest, 5.0, 0.005);
  near(a.totalInterest, 150.0, 0.02);
  near(a.totalPayment, 10150.0, 0.02);

  const b = F.onlineLoan(10000, 18.25, 30, 'equal_installment_daily');
  near(
    b.schedule.reduce((s, x) => s + x.principal, 0),
    10000,
    0.05
  );
  near(b.schedule[b.schedule.length - 1].remaining, 0, 0.02);
  assert.ok(b.totalInterest > 0);
});

test('验收 5：月费率 0.6% × 12 期真实年化 ≈ 13%', () => {
  const r = F.aprFromFee(10000, 0.6, 12);
  assert.ok(r.aprAnnual > 12 && r.aprAnnual < 15, `实际 ${r.aprAnnual}`);
  near(r.aprSimple, 7.2, 1e-6);
  near(r.totalFee, 720, 0.01);
  near(r.totalPayment, 10720, 0.01);
});

test('irr', () => {
  near(F.irr([-1000, 250, 250, 250, 250, 250]), 0.0793, 0.002);
});

test('effectiveAnnual', () => {
  near(F.effectiveAnnual(12, 12), 12.6825, 0.01);
  near(F.effectiveAnnual(12, 1), 12, 1e-6);
});

test('convert 全口径', () => {
  const r = F.convert(3.65, 'annual_pct');
  near(r.annualPct, 3.65, 1e-6);
  near(r.dailyWan, 1.0, 1e-6);
  near(r.basisPoints, 365, 1e-4);
  near(r.monthlyFen, 3.65 / 12, 1e-6);
  near(r.annualFen, 0.365, 1e-6);
  near(r.monthlyLi, 3.65 / 12 / 0.1, 1e-6);
});

test('利率数据文件可解析且条目充足', async () => {
  const fs = await import('node:fs');
  const p = path.join(ROOT, 'data', 'rates.json');
  assert.ok(fs.existsSync(p), 'data/rates.json 不存在');
  const data = JSON.parse(fs.readFileSync(p, 'utf8'));
  assert.ok(data.meta && data.groups && data.rates);
  assert.ok(data.rates.length >= 45, `条目数 ${data.rates.length} < 45`);
});
