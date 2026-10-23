# 利息计算器 · 项目规范（SPEC）

> 本文件是仓库内唯一的产品/技术规范。所有代码、测试、文档必须与本文一致。
> 语言：界面全中文。货币：人民币（CNY）。日期基准：2026-10。

## 1. 目标

一个开源的「利息计算器」，同时交付 **桌面软件** 和 **静态网址（GitHub Pages）**，核心能力：

1. **每日利息计算**：输入本金，下面并排两个收益率输入框做对比，自动判断哪个高、差多少。
2. **收益率选项要全**：官方口径 + 民间叫法（分/厘/毫/日息万几/7日年化/万份收益/基点/倍数），全部内置可选，也可以手填。
3. **贷款计算**：多少是利息、多少是本金、要还多久——输出逐期明细表（每期本金/利息/剩余本金）。
4. **网贷计算**：网贷每天要还多少钱、每日利息多少；内置主流平台利率区间，可一键套用。

## 2. 目录结构（硬性约束）

```
lixi-calculator/
├─ index.html                 # 网页版唯一入口（GitHub Pages 根路径）
├─ manifest.webmanifest       # PWA：可安装到手机/桌面
├─ sw.js                      # Service Worker：离线可用
├─ icon.svg                   # 图标（矢量）
├─ css/app.css                # 全部样式（响应式、数字等宽、表格移动端横向滚动）
├─ js/
│  ├─ finance.js              # ★唯一公式实现，纯函数，UMD 双端共用（浏览器 window.LixiFinance / Node module.exports）
│  ├─ rates.js                # 读取 data/rates.json 的 kind→年化换算 + 下拉分组 + 搜索别名
│  ├─ ui.js                   # DOM 绑定、渲染、事件
│  └─ main.js                 # 入口（加载 data/rates.json，失败降级为内置最小数据集）
├─ data/rates.json            # 利率数据（由 rates-researcher 维护；schema 见第 6 节）
├─ desktop/
│  ├─ app.py                  # Tkinter 桌面软件（单一可执行入口，零第三方依赖）
│  └─ build.ps1               # PyInstaller 打包脚本（可选增强，失败不影响交付）
├─ tests/
│  ├─ test_finance.py         # Python 单测：公式与验收用例（python -m unittest 可跑）
│  └─ test_finance.mjs        # Node 单测：用 node --test 跑，验证 JS/Py 结果一致
├─ tools/
│  ├─ validate_rates.py       # 校验 data/rates.json schema 与数值
│  └─ build_desktop.py        # 调用 PyInstaller 打包（可选）
├─ docs/
│  ├─ 利率大全.md             # 利率知识 + 各平台利率一览（rates-researcher 维护）
│  ├─ 使用说明.md             # 图文使用说明
│  └─ 发布到GitHub.md         # 上传/开 Pages/发 Release 的步骤
├─ README.md
├─ SPEC.md
├─ LICENSE                    # MIT
└─ .github/workflows/deploy.yml  # push 到 main 自动部署 GitHub Pages
```

**角色边界（不要越界改动）**

| 目录/文件 | 负责人 |
|---|---|
| `js/**` `css/**` `index.html` `manifest.webmanifest` `sw.js` `icon.svg` | web-builder |
| `desktop/**` | desktop-builder |
| `data/rates.json` `docs/利率大全.md` | rates-researcher |
| `README.md` `docs/使用说明.md` `docs/发布到GitHub.md` `LICENSE` `.github/**` | Lead |
| `tests/**` | Lead（构建者只读） |

## 3. 核心公式（必须两端完全一致，写在 finance.js / app.py 里）

所有计算使用 **365 天/年**（`DAY_BASIS = 365`），金额四舍五入到 **分（2 位）**，比率保留 6 位小数。

### 3.1 利率归一化
`normalizeToAnnual(rate, kind)` 把任意口径换算成年化利率（%）。kind 定义见第 6 节。
另外提供 `breakdown(annualPct)` → `{ annualPct, monthlyPct, dailyPct }`

### 3.2 每日利息（首页核心）
- `daily = principal * annualPct / 100 / 365`
- `monthly = principal * annualPct / 100 / 12`
- `annual = principal * annualPct / 100`
- 支持「单利」与「复利」口径：**复利按「日」为计息周期**，日利率 = `annualPct/100/365`，
  终值 = `principal * ((1 + 日利率)^days - 1)`。复利结果必须恒 ≥ 单利（测试断言）。
  ⚠️ 历史 bug：曾误写为 `(1 + annualPct/100)^(days/365)`（把「年」当周期），
  导致复利小于单利、且 365 天时退化成单利。已修复并有回归测试保护。
- 计息基准 365 / 360 可切换，影响日利率折算（`daily = principal*annualPct/100/basis`），
  复利同样用 `日利率 = annualPct/100/basis`。
- 双收益率对比：`diffDaily = daily2 - daily1`；`better` = `'a' | 'b' | 'equal'`；同时给出 `diffAnnual`、`ratio`（倍数）、以及等额年化差异。

### 3.3 贷款分期
函数签名（JS 与 Python 名称一致）：
- `equalInstallment(principal, annualPct, months)` → 等额本息
  - 月利率 `i = annualPct/100/12`；`i==0` 时 `payment = principal/months`
  - `payment = principal * i * (1+i)^months / ((1+i)^months - 1)`
  - 每期利息 = 上期剩余本金 × i；每期本金 = payment - 利息
  - **最后一期强制结平**：本金 = 剩余本金（消除浮点误差），保证 Σ本金 == principal
  - 返回 `{ method:'equal_installment', payment, months, totalPayment, totalInterest, schedule:[{period, payment, principal, interest, remaining}] }`
- `equalPrincipal(principal, annualPct, months)` → 等额本金
  - 每期本金 = principal/months；利息 = 剩余本金 × i；payment 递减；最后一期结平
- `interestFirst(principal, annualPct, months)` → 先息后本
  - 每期 payment = principal*i，最后一期 payment = principal + principal*i
- `bullet(principal, annualPct, months)` → 到期一次还本付息（单利，按月计息）
- 通用：`scheduleSummary(schedule)` → `{ totalPayment, totalInterest, firstPayment, lastPayment }`
- 统一入口 `loanSchedule(principal, annualPct, months, method)`，method ∈ `equal_installment|equal_principal|interest_first|bullet`

### 3.4 网贷 / 日还款
- `dailyPayment(principal, annualPct, days)` → `{ dailyInterest, dailyPrincipal, dailyPayment, totalDays, totalPayment, totalInterest }`
  - 按天计息、按天还本：`dailyInterest = principal * annualPct/100/365`；`dailyPrincipal = principal/days`
- `onlineLoan(principal, annualPct, days, method)` 支持 `interest_first`（到期还本，每日只还息）、`equal_installment_daily`（每日等额本息，`i = annualPct/100/365`）
- `platformToAnnual(rate, kind)` 复用 `normalizeToAnnual`
- 需要输出：每日利息、每日还款、总利息、总还款、多少天

### 3.5 折算工具
- `aprFromFee(principal, monthlyFeePct, months)` → 分期手续费口径换算真实年化（IRR）
  - 逐月现金流：`+principal`（t=0），`-principal/months - principal*monthlyFeePct/100`（t=1..months）
  - 用二分法求月 IRR（区间 [-0.99, 1]），年化 = `((1+irr)^12 - 1)*100`，同时给 `aprSimple = monthlyFeePct*12`
- `irr(cashflows)` 通用 IRR（二分法，100 次迭代，精度 1e-10）
- `effectiveAnnual(annualPct, compoundsPerYear)` → 有效年利率 `((1+r/n)^n - 1)*100`
- `convert(amount, fromKind, fromValue, toKind)` → 各口径互转

### 3.6 精度与边界
- 本金允许 0.01 ~ 1e12；月数 1 ~ 1200；年化 0 ~ 1000%
- 负利率/NaN/Infinity 必须抛错或返回 `{error:'...'}`（两端同一行为，单测覆盖）
- 所有函数 **纯函数、无副作用**，便于单测与双端一致性对比

## 3.7 API 契约（精确定义，测试按此断言，字段名不得改动）

> 本节优先级高于第 3 节其它小节的模糊描述。JS 用驼峰，Python 用同名 snake_case。
> 所有函数为纯函数；非法输入（NaN/Infinity/本金<=0/月数<=0/年化<0）抛 `Error` / `ValueError`。
> 返回值中的金额字段一律已四舍五入到分（2 位）。

```
常量
  DAY_BASIS = 365
  ROUND(x) -> number            // Math.round(x*100)/100

1) normalizeToAnnual(value, kind, opts?) -> number   // 返回年化百分数，如 3.65
   opts = { lpr1y?:3.0, min?:number, max?:number }
   kind 换算表见第 6 节。range_annual_pct 用 opts.min/opts.max 取中值；
   range_daily_wan 用 opts.min/opts.max 取中值再 *365/100。
   注意「日息万5」= 0.05%/日 = 年化 18.25%：`annual = v/10000*100*365 = v*365/100`。
   value 为 null/undefined 时，range_* 必须用 min/max，其它 kind 抛错。

2) breakdown(annualPct) -> { annualPct, monthlyPct, dailyPct }
   monthlyPct = annualPct/12, dailyPct = annualPct/365

3) dailyInterest(principal, annualPct, days = 365) -> {
     principal, annualPct, days,
     daily,            // 每日利息 = principal*annualPct/100/365，2 位
     monthly,          // 每月利息 = principal*annualPct/100/12，2 位
     annual,           // 每年利息 = principal*annualPct/100，2 位
     periodInterest    // 期间利息 = principal*annualPct/100*days/365，2 位
   }

4) compareRates(principal, annualPctA, annualPctB, days = 365) -> {
     a: { annualPct, daily, monthly, annual, periodInterest },
     b: { 同上 },
     diffDaily,        // b.daily - a.daily，2 位，可为负
     diffMonthly, diffAnnual, diffPeriod,
     better,           // 'a' | 'b' | 'equal'（按年化比较；相等用 'equal'）
     higherAnnualPct, lowerAnnualPct,
     ratio             // b.daily / a.daily；a.daily===0 时为 null
   }

5) equalInstallment(principal, annualPct, months) -> {
     method: 'equal_installment', principal, annualPct, months,
     monthlyRate,      // annualPct/100/12
     payment,          // 每期还款额（固定，最后一期也用这个数）
     totalPayment, totalInterest,   // 2 位
     schedule: [ { period, payment, principal, interest, remaining } ]  // remaining 为期末剩余本金
   }
   **末期口径（唯一权威定义）**：每期 payment 恒等于 pay，最后一期也不例外。
   - 每期 interest = 上期 remaining × monthlyRate
   - 每期 principal = payment - interest，但最后一期 principal = 上期 remaining（强制结平）
   - 最后一期 interest = payment - principal（即把浮点尾差吸收进最后一期利息，而不是改月供）
   约束：Σschedule.principal === principal（误差 < 0.01）
        Σschedule.interest === totalInterest
        Σschedule.payment === totalPayment === payment × months
        schedule[last].remaining === 0
        schedule[i].payment === schedule[i].principal + schedule[i].interest

6) equalPrincipal(principal, annualPct, months) -> 同上结构
     method:'equal_principal'，payment 字段 = 首期还款额，每期 payment 递减。
     每期 principal 恒为 principal/months（最后一期用剩余本金结平），interest = 上期 remaining × monthlyRate，
     payment = principal + interest（这里不强制固定月供，末期自然递减）。

7) interestFirst(principal, annualPct, months) -> 同上结构
     method:'interest_first'，每期 payment = 月利息，最后一期 payment = 本金 + 月利息

8) bullet(principal, annualPct, months) -> 同上结构
     method:'bullet'，最后一期一次还本付息（单利，按月计息：interest = principal*monthlyRate*months）

9) loanSchedule(principal, annualPct, months, method) -> 按 method 分派
     method ∈ 'equal_installment' | 'equal_principal' | 'interest_first' | 'bullet'

10) scheduleSummary(schedule) -> { months, totalPayment, totalInterest, firstPayment, lastPayment, avgPayment }
     当 schedule 原样传入（避免重复计算）；也可直接对某个 schedule 数组调用。

11) dailyPayment(principal, annualPct, days) -> {
      principal, annualPct, days,
      dailyInterest,   // principal*annualPct/100/365
      dailyPrincipal,  // principal/days
      dailyPayment,    // 二者之和
      totalPayment, totalInterest
    }

12) onlineLoan(principal, annualPct, days, method) -> {
      method,          // 'interest_first' | 'equal_installment_daily'
      principal, annualPct, days,
      dailyInterest,   // 首日利息
      dailyPayment,    // 首日还款额
      totalInterest, totalPayment,
      schedule: [ { day, payment, principal, interest, remaining } ]
    }
    'interest_first'：每天只还利息，最后一天还本金；totalInterest = dailyInterest*days
    'equal_installment_daily'：日利率 i = annualPct/100/365，按日等额本息，最后一天结平

13) irr(cashflows) -> number   // 每期内部收益率（小数，如 0.0082）
      二分法，区间 [-0.999999, 10]，200 次迭代，收敛精度 1e-12；无解抛错

14) aprFromFee(principal, monthlyFeePct, months) -> {
      monthlyIrr,      // 小数
      aprAnnual,       // 真实年化百分数 = ((1+monthlyIrr)^12 - 1)*100
      aprSimple,       // monthlyFeePct*12（名义年化）
      totalFee,        // principal*monthlyFeePct/100*months
      totalPayment
    }

15) effectiveAnnual(annualPct, compoundsPerYear) -> number  // ((1+r/n)^n - 1)*100

16) convert(value, kind, opts?) -> 年化百分数 + 全口径表
      { annualPct, monthlyPct, dailyPct,
        monthlyFen, annualFen, monthlyLi, annualLi, monthlyHao,
        dailyWan, basisPoints }
      monthlyFen = annualPct/12        （每月几「分」息）
      annualFen  = annualPct/10        （每年几「分」息）
      monthlyLi  = annualPct/12/0.1    （每月几「厘」息）
      annualLi   = annualPct          （每年几「厘」息）
      monthlyHao = annualPct/12/0.01   （每月几「毫」息）
      dailyWan   = annualPct/100/365*10000  （日息万几）
      basisPoints = annualPct*100
```

## 3.8 两端一致性

`tests/test_finance.py` 与 `tests/test_finance.mjs` 用**同一组固定用例和同一个期望值表**，
所以只要两端都按 3.7 实现，结果必然一致。任何一端偏离 3.7 都会让测试变红——以 3.7 为准改代码，不要改测试。

## 4. 网页版（index.html）交互规范

单页、零外部依赖、离线可用（`file://` 双击也能跑）。顶部导航 + 5 个标签页：

### Tab 1「利息计算」
- 本金输入（千分位显示，支持中文大写金额提示）
- 两个收益率卡片并排（A / B），每个卡片 = 「选择利率方案」下拉（分组 + 别名可搜索）+ 「年化利率%」输入框，二者双向联动
- 显示：A 每日利息 / B 每日利息 / 差额（每日、每月、每年）/ 谁更高（高亮胜负色 + 「B 比 A 每年多赚 ¥X」）
- 期间选择：7 天 / 30 天 / 90 天 / 1 年 / 自定义天数 → 显示累计收益与到期本息
- 复利开关、日历天/360 天口径切换（口径切换影响所有计算，需在结果区提示当前口径）

### Tab 2「贷款计算」
- 本金、年化利率（可从下拉选，也可手填）、期限（月/年切换）
- 还款方式：等额本息 / 等额本金 / 先息后本 / 到期一次还本付息
- 汇总卡片：月供、总利息、总还款、利息占比（用环形或条形可视化，纯 CSS）
- 明细表：期数 / 月供 / 本金 / 利息 / 剩余本金，支持导出 CSV
- 「利息 vs 本金」堆叠条：直观显示总还款中多少是利息

### Tab 3「网贷计算」
- 本金、平台利率（从 `online_loan` 分组选，自动带出日息/年化区间中值）、借款天数或期数
- 还款方式：每日还息到期还本 / 每日等额本息
- 汇总：每日利息、每日还款、总利息、总还款、实际年化（含 IRR 提示）
- 明细表（按天/按期，默认按月聚合并显示前若干期 + 折叠全部）
- 醒目风险提示条：超过 24% 综合融资成本红线 / 36% 高利贷口径时高亮红色警告

### Tab 4「利率换算」
- 输入任一口径 → 同时输出 年/月/日/万几/分/厘/毫/基点 共 10 种表示
- 内置「分/厘/毫」民间叫法对照表（月息 vs 年息两种解释都给出，防止「月息1分」陷阱）
- 手续费→真实年化（IRR）小工具

### Tab 5「利率大全」
- 直接读 `data/rates.json` 渲染分组表格：名称、别名、口径、年化、asOf、说明、来源链接
- 顶部搜索框（可搜别名/口语），点击「用这个」跳转到 Tab 1 并填入

通用：
- 深色模式自适应（`prefers-color-scheme`），纯 CSS 变量
- 所有金额 `Intl.NumberFormat('zh-CN', {style:'currency',currency:'CNY'})`
- 响应式：手机单列、桌面双列
- 无网络/JSON 加载失败 → 用内置最小数据集并提示
- 打印友好（`@media print`）
- 隐私：纯前端计算，不上传任何数据（页面需注明）

## 5. 桌面版（desktop/app.py）交互规范

- 纯 Tkinter + ttk，**不能用任何第三方库**（保证用户双击 `python app.py` 就能跑）
- 单窗口 + `ttk.Notebook` 5 个页签，与网页版一致：利息计算 / 贷款计算 / 网贷计算 / 利率换算 / 利率大全
- 字体：中文可用的 `Microsoft YaHei UI`（缺省回退），数字用等宽显示
- 利率下拉用 `ttk.Combobox`（只读，按 group 加前缀如 `[官方] LPR（1年期）`），旁边有 `[?]` 提示显示 note
- 结果用 `ttk.Treeview` 表格 + 汇总 Label；支持「复制结果」「导出 CSV」
- 启动时尝试读取同目录 `../data/rates.json`，失败用内置最小数据集
- `python desktop/app.py` 必须能直接运行；无显示环境不应崩溃（捕获 TclError 给出提示）
- 代码结构：`App(tk.Tk)` 类 + 每个 tab 一个 `build_*_tab()` 方法；计算全部调用 `desktop/finance_core.py`？**不要**——桌面版必须与 `js/finance.js` 公式一致，用 `desktop/app.py` 内自带同名函数，并与 `tests/test_finance.py` 的用例对齐。

## 6. data/rates.json Schema

见 `docs/利率大全.md` 与文件本身。关键约定：

```json
{
  "meta": { "version": 1, "updated": "YYYY-MM-DD", "lpr": {"1y": 3.0, "5y": 3.5},
            "judicial_cap_multiple": 4, "disclaimer": "…", "sources": [{"title":"","url":"","note":""}] },
  "groups": [ { "id": "official|customary|deposit|loan|online_loan", "title": "…", "desc": "…" } ],
  "rates": [ {
      "id": "唯一id", "group": "official", "name": "显示名", "aliases": ["…"],
      "kind": "annual_pct|monthly_pct|daily_pct|monthly_fen|annual_fen|monthly_li|annual_li|monthly_hao|daily_wan|per10k_yuan|lpr_plus_bp|lpr_multiple|range_annual_pct|range_daily_wan",
      "value": 3.0, "min": null, "max": null,
      "display": "3.00% 年化", "asOf": "YYYY-MM-DD", "note": "…", "warning": null, "source": "https://…"
  } ]
}
```

kind → 年化(%) 换算（**两端必须一致**）：
| kind | 公式 |
|---|---|
| annual_pct | `v` |
| monthly_pct | `v*12` |
| daily_pct | `v*365` |
| monthly_fen | `v*12` （1分=1%/月） |
| annual_fen | `v*10` （1分=10%/年） |
| monthly_li | `v*0.1*12` （1厘=0.1%/月） |
| annual_li | `v*1` （1厘=1%/年） |
| monthly_hao | `v*0.01*12` （1毫=0.01%/月） |
| daily_wan | `v*365/100` （万5 = 0.05%/日 → 18.25%/年） |
| per10k_yuan | `v/10000*365` |
| lpr_plus_bp | `meta.lpr['1y'] + v/100` |
| lpr_multiple | `meta.lpr['1y']*v` |
| range_annual_pct | `(min+max)/2`（区间取中值，同时保留 min/max 供展示） |
| range_daily_wan | `((min+max)/2)*365/100` |

## 7. 验收标准（Lead 会用这些跑测试）

1. `python tests/test_finance.py` 全绿；`node --test tests/test_finance.mjs` 全绿；两端对同一组输入输出一致（差异 < 0.01 元）。
2. 本金 10000、年化 3.65% → 每日利息 **1.00 元**；年化 7.3% → 每日 **2.00 元**。
3. 本金 100 万、年化 4.9%、30 年等额本息 → 月供约 **5307.27**；总利息约 **91.06 万**（容差 ±0.5%）。
4. 等额本息任意参数下 `Σ每期本金 == principal`（误差 < 0.01）；`Σ每期利息 == totalInterest`。
5. `aprFromFee(10000, 0.6, 12)` 真实年化约 **13.0%~13.9%**。
6. 网贷：本金 10000、日息万 5、30 天 → 每日利息 **5.00 元**（若按 365：`10000*0.0005=5`），30 天总利息 150 元。
7. `python tools/validate_rates.py data/rates.json` 通过，且 `rates` 条目 ≥ 45。
8. 网页 `index.html` 用 `file://` 直接打开无报错（控制台零 error），5 个页签均可交互。
9. `python desktop/app.py` 能启动并完成一次计算（无头环境用 `--selftest` 参数跑完所有公式后 exit 0）。
10. 所有面向用户的文案是中文，无 TODO/占位文本。
