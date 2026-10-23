# 利息计算器 · 桌面版

Windows 上双击就能用的「利息计算器」桌面软件。**纯 Python 标准库**（tkinter + ttk），
零第三方依赖，公式与网页版 `js/finance.js` 完全一致。

## 1. 运行

### 需要什么

- **Python 3.9 或更高版本**（3.9+，推荐 3.12）
- 安装 Python 时请勾选 **Add Python to PATH**
- 官方安装包默认包含 tkinter，无需额外安装

### 怎么启动

```bat
cd desktop
python app.py
```

或者直接**双击 `app.py`**（若已关联 Python）也可以。

> 没有任何第三方依赖，**不需要 `pip install` 任何东西**。

### 命令行参数

```bat
python app.py                  :: 启动图形界面
python app.py --selftest       :: 无头自检：跑完全部公式验收用例，输出 JSON，全部通过则退出码 0
python app.py --selftest -o report.json
python app.py --version
```

`--selftest` 适合在没有显示器的服务器/CI 上验证计算引擎，覆盖 SPEC 第 7 节验收 2/3/4/5/6 的数值。

## 2. 五个页签

| 页签 | 能做什么 |
|---|---|
| **利息计算** | 输入本金，A/B 两套收益率并排对比：每日/每月/每年/期间差额、谁更高（颜色高亮）、累计天数 7/30/90/365/自定义、单利/复利切换 |
| **贷款计算** | 等额本息 / 等额本金 / 先息后本 / 到期一次还本付息；汇总卡片 + 逐期明细（期数/月供/本金/利息/剩余本金）+ 利息占比条 + 导出 CSV |
| **网贷计算** | 选平台自动带出年化，每日利息/每日还款/总利息/总还款/实际年化(IRR)，超 24% 橙色、超 36% 红色风险提示条 |
| **利率换算** | 任一口径 → 年/月/日/万几/分/厘/毫/基点 共 10 种；「月息 vs 年息」1 分陷阱对照表；手续费 → 真实年化(IRR) |
| **利率大全** | 渲染 `data/rates.json` 全部分组，支持搜索名称/别名，双击或用按钮填入「利息计算」 |

利率下拉框按分组加前缀，如 `[官方] LPR（1年期）`；旁边的 `[?]` 按钮显示该条目的口径、年化、更新日期、说明与来源。

## 3. 打包成免安装 exe（可选）

> 这一步**只是可选增强**。不打包也能用，「有 Python 就能跑」。

PyInstaller 不在标准库里，需要你自己手动安装（本仓库的脚本不会替你 `pip install`）：

```bat
python -m pip install pyinstaller
powershell -ExecutionPolicy Bypass -File desktop\build.ps1
```

产物：**`desktop/dist/LixiCalculator.exe`**，双击即用，目标机器无需安装 Python。

常用参数：

```bat
.\desktop\build.ps1                     :: 默认名 LixiCalculator
.\desktop\build.ps1 -Name LixiCalc      :: 自定义产物名 -> desktop/dist/LixiCalc.exe
.\desktop\build.ps1 -OneDir             :: 目录版，启动更快
.\desktop\build.ps1 -SkipSelftest       :: 跳过打包前自检
.\desktop\build.ps1 -Python "C:\Python312\python.exe"
```

脚本行为：

- 打包前自动跑一次 `--selftest`，不通过就中止（避免发布算错的版本）
- 自动把 `data/rates.json` 一起打进 exe（运行时从 `sys._MEIPASS` 读取）
- **中间产物全部丢到系统临时目录并自动清理**（`--workpath`/`--specpath` 均指向 `%TEMP%`），
  仓库里只留下 `desktop/dist/LixiCalculator.exe`，不会产生 `pyinstaller-build/` 或 `*.spec` 垃圾
- **未安装 PyInstaller 时打印中文提示后 `exit 0`**，不影响源码运行

## 4. 数据与隐私

- 启动时优先读取 `desktop/../data/rates.json`（打包后读 `sys._MEIPASS/data/rates.json`）
- 文件缺失/损坏/仍是占位内容时，**自动回退到内置最小数据集**（25 条代表性利率，schema 与 `rates.json` 一致），界面顶部会标明当前数据来源
- 所有计算都在本机内存里完成，**不联网、不上传任何数据**

## 5. 公式约定

与 `js/finance.js` 同一套契约（SPEC 第 3.7 节）：

- 计息基准 **365 天/年**（`DAY_BASIS = 365`）
- 金额四舍五入到 **分**，比率保留 **6 位小数**
- 贷款每期：利息 = 上期剩余本金 × 月利率；本金 = 月供 − 利息
- **最后一期强制结平**：本金 = 当期剩余本金，月供保持不变、差额吸收进末期利息
- 因此恒有：`Σ每期本金 == 本金`、`Σ每期利息 == 总利息`、`Σ每期还款额 == 总还款`

核心函数（模块级，可直接 `from app import ...` 单测，import 不会启动 GUI）：

```
DAY_BASIS, ROUND, normalize_to_annual, breakdown, daily_interest, compare_rates,
equal_installment, equal_principal, interest_first, bullet, loan_schedule,
schedule_summary, daily_payment, online_loan, irr, apr_from_fee, effective_annual, convert
```

返回字段名沿用 JS 的驼峰写法（`daily` / `periodInterest` / `totalPayment` / `aprAnnual` …），
便于和网页版逐字段对账。

## 6. 常见问题

**双击没反应 / 闪退？**
用命令行 `python app.py` 运行，就能看到具体报错。

**提示「无法启动图形界面」或 `TclError`？**
当前环境没有可用显示器（无头服务器、远程会话、WSL 无桌面）。此时可以改用
`python app.py --selftest` 验证计算引擎；或在与桌面同一会话的 Windows 上运行。

**中文显示成方块？**
程序会自动在 `Microsoft YaHei UI` → `Microsoft YaHei` → `PingFang SC` → `Segoe UI` 之间回退。
若系统缺少中文字体，请安装微软雅黑字体。

**窗口太小 / 想放大？**
最小尺寸 1024×700，可自由拉伸，各页签会自动铺满。

**导出的 CSV 用 Excel 打开乱码？**
文件已带 UTF-8 BOM，请用 Excel 2016 及以上版本打开；WPS 亦可。

## 7. 开发自检

```bat
python -m py_compile desktop\app.py
python desktop\app.py --selftest
python tests\test_finance.py
```
