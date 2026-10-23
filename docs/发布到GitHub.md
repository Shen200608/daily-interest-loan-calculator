# 发布到 GitHub（含免费网址）

本文档给你两种发布方式。**推荐 A**（一条命令，不用装 git），B 适合你本地已经有 git 且网络通畅的情况。

发布后你会得到：

| 东西 | 地址形式 |
|---|---|
| 源码仓库 | `https://github.com/<用户名>/lixi-calculator` |
| **在线网址** | `https://<用户名>.github.io/lixi-calculator/` |
| 桌面软件下载 | 仓库右侧 **Releases** 里下载 `LixiCalculator.exe` |

---

## 方式 A：用仓库自带的脚本（推荐，不需要 git）

如果你的网络访问 `github.com` 很慢但 `api.github.com` 能用，这是最省事的方式。

### 1. 生成令牌

1. 登录 GitHub → 右上角头像 → **Settings**
2. 左侧最下方 → **Developer settings**
3. **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**
4. Note 随便填（如 `lixi-calculator`），Expiration 选 30 天即可
5. 勾选权限：**`repo`**（必需）、**`workflow`**（想让它自动部署才需要）
6. 生成后**立刻复制**那串 `ghp_...`（关掉页面就再也看不到了）

### 2. 运行脚本

在项目根目录打开 PowerShell：

```powershell
$env:GITHUB_TOKEN = 'ghp_你复制的那串'
python tools\publish_to_github.py --repo lixi-calculator
```

想先看看会传哪些文件：

```powershell
python tools\publish_to_github.py --repo lixi-calculator --dry-run
```

常用参数：

| 参数 | 作用 |
|---|---|
| `--repo 名字` | 仓库名（必填） |
| `--owner 账号` | 传到组织而不是个人账号时用 |
| `--private` | 建私有仓库（私有仓库不启用 Pages） |
| `--no-pages` | 只传代码，不启用 Pages |
| `--branch main` | 目标分支，默认 `main` |

脚本会自动：建仓库 → 上传全部文件 → 建一次 commit → 启用 GitHub Pages → 打印网址。

> ⚠️ 如果你是第一次用 Fine-grained 令牌，可能没有「创建仓库」权限。此时先到网页手动建一个空仓库（**不要**勾选 README/.gitignore），再跑脚本即可。

---

## 方式 B：本地 git

```bash
cd lixi-calculator
git init
git add .
git commit -m "feat: 利息/贷款/网贷计算器（网页版 + 桌面版）"
git branch -M main

# 先在 GitHub 网页上建一个空仓库（不要初始化 README）
git remote add origin https://github.com/<用户名>/lixi-calculator.git
git push -u origin main
```

> 如果 `git push` 卡住或 `github.com` 超时，用方式 A。

---

## 开启在线网址（GitHub Pages）

仓库里已经有 `.github/workflows/deploy.yml`，会自动跑测试并部署。

发布后按这个顺序设置一次：

1. 仓库 → **Settings** → 左侧 **Pages**
2. **Build and deployment** → **Source** 选 **GitHub Actions**（不是 "Deploy from a branch"）
3. 仓库 → **Actions** 标签页 → 如果提示 Actions 未启用，点 **I understand my workflows, go ahead and enable them**
4. 等 1~3 分钟，`https://<用户名>.github.io/<仓库名>/` 就能访问了

> 想用最简单的方式？Pages 的 Source 选 **Deploy from a branch** → 分支 `main`、目录 `/ (root)`，也能直接出网址（只是不会自动跑测试）。

---

## 发布桌面软件 exe（可选）

GitHub 单个 Release 附件上限 2GB，我们的 exe 只有十几 MB，完全没问题。

1. 在本机打包：
   ```powershell
   cd desktop
   powershell -ExecutionPolicy Bypass -File build.ps1
   ```
   产物在 `dist\LixiCalculator.exe`
2. 仓库 → **Releases** → **Draft a new release**
3. Tag 填 `v1.0.0`，标题填「v1.0.0 首个版本」
4. 把 `dist\LixiCalculator.exe` 拖进附件区
5. **Publish release**

用户下载后双击即可运行，**不需要安装 Python**（PyInstaller 已把解释器打进去）。

> 有些浏览器/杀毒软件会对未签名的 exe 报警，这是正常现象，说明「仅从本项目 Releases 下载」即可。
> 未签名的 exe 也可能被 SmartScreen 拦截：点「更多信息」→「仍要运行」。

---

## 更新已发布的版本

```powershell
# 方式 A：再跑一次脚本即可（会在原分支上追加一次提交）
$env:GITHUB_TOKEN = 'ghp_xxx'
python tools\publish_to_github.py --repo lixi-calculator

# 方式 B：
git add . && git commit -m "update rates" && git push
```

更新利率数据后建议：

```powershell
python tools\validate_rates.py data\rates.json
node --test tests\test_finance.mjs
python tests\test_finance.py
```

---

## 常见问题

**Q：`https://<用户名>.github.io/<仓库>/` 打不开 / 404**
- Pages 首次构建要 1~3 分钟，先等一会儿
- Settings → Pages 里看有没有绿色成功提示
- 仓库是 **private** 的话，免费账号不能开 Pages，需要改公开：Settings → General → 最下方 Change visibility

**Q：页面能打开但利率数据不全**
- 线上版本能正常读取 `data/rates.json`
- 只有 `file://` 直接双击打开时才会降级成内置数据（这是浏览器安全限制）

**Q：Action 跑失败了**
- 看 Actions 里的日志。常见原因是 `tools/validate_rates.py` 校验没通过（数据填错了）
- 本地先跑一遍 `python tools\validate_rates.py data\rates.json` 排查

**Q：令牌会不会泄漏？**
- 脚本只从环境变量读 `GITHUB_TOKEN`，不写进任何文件，不会被提交
- `--dry-run` 只列文件名，不使用令牌
- 用完后建议到 Settings → Developer settings 里把令牌删掉
