#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本项目发布到 GitHub（只用 REST API，不需要安装 git）。

为什么用 API 而不是 git：某些网络环境下 `github.com` 网页/`git clone` 极慢或不通，
但 `api.github.com` 可用。本脚本通过 Git Data API 一次性提交整个目录树。

用法
----
    set GITHUB_TOKEN=ghp_xxxxxxxx
    python tools/publish_to_github.py --repo lixi-calculator

    # 私有仓库 + 指定 owner
    python tools/publish_to_github.py --repo lixi-calculator --owner myname --private

    # 只创建仓库不做提交
    python tools/publish_to_github.py --repo lixi-calculator --no-commit

Token 权限
----------
- 经典 PAT：勾选 `repo`（公开仓库也建议勾选，因为要启用 Pages 需要 repo 权限）
- Fine-grained PAT：Repository permissions → Contents: Read and write、Pages: Read and write、
  Metadata: Read-only；若仓库还不存在，需要在账号级允许创建仓库（或先手动建好空仓库）

退出码：0 成功，1 失败
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

API = "https://api.github.com"
USER_AGENT = "lixi-calculator-publisher/1.0"

# 不提交的东西
SKIP_DIRS = {".git", "__pycache__", "node_modules", "dist", "build", ".venv", "venv", ".pytest_cache"}
SKIP_EXT = {".pyc", ".pyo", ".exe", ".log", ".tmp"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str, what: str):
        super().__init__(f"{what} 失败 (HTTP {status}): {body[:400]}")
        self.status = status
        self.body = body


def request(
    method: str,
    url: str,
    token: str,
    payload: dict | None = None,
    retries: int = 4,
    timeout: int = 60,
) -> tuple[int, dict | list | str]:
    """带重试的 GitHub API 请求。返回 (status, decoded_body)。"""
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                status = resp.status
                return status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            # 4xx 不重试（除 429 限流），5xx / 网络错误重试
            if exc.code < 500 and exc.code != 429:
                return exc.code, raw
            last_err = ApiError(exc.code, raw, f"{method} {url}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = exc
        wait = min(2 ** attempt, 20)
        print(f"  · 第 {attempt} 次请求失败，{wait}s 后重试 … ({last_err})")
        time.sleep(wait)
    raise RuntimeError(f"{method} {url} 重试 {retries} 次仍失败: {last_err}")


def collect_files(root: str) -> list[tuple[str, bytes]]:
    """收集要提交的文件 (仓库内相对路径, 内容)。"""
    out: list[tuple[str, bytes]] = []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name in SKIP_FILES:
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in SKIP_EXT:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            if rel.startswith(".git/") or "/.git/" in rel:
                continue
            try:
                with open(full, "rb") as fh:
                    out.append((rel, fh.read()))
            except OSError as exc:
                print(f"  ! 跳过无法读取的文件 {rel}: {exc}")
    out.sort(key=lambda x: x[0])
    return out


def main(argv: list[str]) -> int:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description="用 GitHub REST API 发布本项目")
    parser.add_argument("--repo", required=True, help="仓库名，例如 lixi-calculator")
    parser.add_argument("--owner", default=None, help="账号名；默认取 token 对应的登录用户")
    parser.add_argument("--private", action="store_true", help="创建为私有仓库")
    parser.add_argument("--source", default=here, help="要发布的本地目录（默认项目根）")
    parser.add_argument("--branch", default="main", help="分支名，默认 main")
    parser.add_argument("--message", default="", help="提交信息")
    parser.add_argument("--description", default="", help="仓库描述")
    parser.add_argument("--no-commit", action="store_true", help="只创建仓库，不推送文件")
    parser.add_argument("--no-pages", action="store_true", help="不启用 GitHub Pages")
    parser.add_argument("--dry-run", action="store_true", help="只列出将要提交的文件")
    args = parser.parse_args(argv[1:])

    files = collect_files(args.source)
    print(f"待提交文件 {len(files)} 个（来自 {os.path.abspath(args.source)}）")
    total = sum(len(c) for _, c in files)
    print(f"总大小 {total / 1024:.1f} KB")
    if args.dry_run:
        for rel, content in files:
            print(f"  {len(content):>9,}  {rel}")
        return 0

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token:
        print(
            "缺少令牌。请先设置环境变量再运行：\n"
            "  PowerShell:  $env:GITHUB_TOKEN='ghp_xxx'\n"
            "  CMD:         set GITHUB_TOKEN=ghp_xxx\n"
            "Token 在 https://github.com/settings/tokens 生成（经典令牌勾选 repo）。",
            file=sys.stderr,
        )
        return 1

    # 1) 身份
    status, body = request("GET", f"{API}/user", token)
    if status != 200 or not isinstance(body, dict):
        print(f"令牌无效或无法访问 API：HTTP {status} {body}", file=sys.stderr)
        return 1
    login = body.get("login", "")
    owner = args.owner or login
    print(f"已认证为 {login}，目标仓库 {owner}/{args.repo}")

    # 2) 创建仓库
    status, body = request("GET", f"{API}/repos/{owner}/{args.repo}", token)
    if status == 200 and isinstance(body, dict):
        print(f"仓库已存在：{body.get('html_url')}")
        default_branch = body.get("default_branch") or args.branch
    else:
        payload = {
            "name": args.repo,
            "description": args.description or "利息/贷款/网贷计算器 · 本金与双收益率对比、还款明细、日息换算",
            "private": bool(args.private),
            "has_issues": True,
            "has_wiki": False,
            "auto_init": False,
        }
        status, body = request("POST", f"{API}/user/repos" if not args.owner else f"{API}/orgs/{args.owner}/repos", token, payload)
        if status not in (200, 201):
            print(f"创建仓库失败：HTTP {status} {body}", file=sys.stderr)
            return 1
        print(f"仓库已创建：{body.get('html_url')}")
        default_branch = args.branch

    if args.no_commit:
        print("按 --no-commit 跳过文件提交。")
        return 0

    # 3) 读取现有分支头（若仓库已有内容）
    base_tree_sha = None
    parent_sha = None
    status, ref = request("GET", f"{API}/repos/{owner}/{args.repo}/git/ref/heads/{args.branch}", token)
    if status == 200 and isinstance(ref, dict):
        parent_sha = ref.get("object", {}).get("sha")
        if parent_sha:
            status, commit = request("GET", f"{API}/repos/{owner}/{args.repo}/git/commits/{parent_sha}", token)
            if status == 200 and isinstance(commit, dict):
                base_tree_sha = commit.get("tree", {}).get("sha")
            print(f"已有分支 {args.branch}，将在其之上提交")

    # 4) 上传 blob
    print(f"上传 {len(files)} 个文件 …")
    tree_items = []
    for i, (rel, content) in enumerate(files, 1):
        payload = {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"}
        status, blob = request("POST", f"{API}/repos/{owner}/{args.repo}/git/blobs", token, payload)
        if status not in (200, 201) or not isinstance(blob, dict):
            print(f"上传 {rel} 失败：HTTP {status} {blob}", file=sys.stderr)
            return 1
        tree_items.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        if i % 10 == 0 or i == len(files):
            print(f"  {i}/{len(files)}")

    # 5) 建 tree
    tree_payload: dict = {"tree": tree_items}
    if base_tree_sha:
        tree_payload["base_tree"] = base_tree_sha
    status, tree = request("POST", f"{API}/repos/{owner}/{args.repo}/git/trees", token, tree_payload)
    if status not in (200, 201) or not isinstance(tree, dict):
        print(f"创建 tree 失败：HTTP {status} {tree}", file=sys.stderr)
        return 1

    # 6) 建 commit
    message = args.message or "feat: 利息/贷款/网贷计算器（网页版 + 桌面版）"
    commit_payload: dict = {"message": message, "tree": tree["sha"]}
    if parent_sha:
        commit_payload["parents"] = [parent_sha]
    status, commit = request("POST", f"{API}/repos/{owner}/{args.repo}/git/commits", token, commit_payload)
    if status not in (200, 201) or not isinstance(commit, dict):
        print(f"创建 commit 失败：HTTP {status} {commit}", file=sys.stderr)
        return 1

    # 7) 移动分支指针
    ref_path = f"{API}/repos/{owner}/{args.repo}/git/refs/heads/{args.branch}"
    if parent_sha:
        status, res = request("PATCH", ref_path, token, {"sha": commit["sha"], "force": False})
    else:
        status, res = request("POST", f"{API}/repos/{owner}/{args.repo}/git/refs", token, {"ref": f"refs/heads/{args.branch}", "sha": commit["sha"]})
    if status not in (200, 201):
        print(f"更新分支失败：HTTP {status} {res}", file=sys.stderr)
        return 1
    print(f"已提交：{commit['sha'][:10]}  分支 {args.branch}")

    # 8) 设为默认分支（新建仓库时 API 已经把 main 设为默认，这里兜底）
    request("PATCH", f"{API}/repos/{owner}/{args.repo}", token, {"default_branch": args.branch})

    # 9) 启用 Pages
    pages_url = None
    if not args.no_pages and not args.private:
        status, pages = request(
            "POST",
            f"{API}/repos/{owner}/{args.repo}/pages",
            token,
            {"source": {"branch": args.branch, "path": "/"}},
        )
        if status in (200, 201, 204):
            print("GitHub Pages 已启用（首次部署需要 1~3 分钟）")
        elif status == 409:
            status, pages = request(
                "PUT",
                f"{API}/repos/{owner}/{args.repo}/pages",
                token,
                {"source": {"branch": args.branch, "path": "/"}},
            )
            print("GitHub Pages 已更新" if status in (200, 204) else f"Pages 配置返回 HTTP {status}")
        else:
            print(f"Pages 启用失败（不影响仓库内容）：HTTP {status} {str(pages)[:200]}")
            print("  可手动到 Settings → Pages → Source 选择 'Deploy from a branch' → main / (root)")
        try:
            status, info = request("GET", f"{API}/repos/{owner}/{args.repo}/pages", token)
            if status == 200 and isinstance(info, dict):
                pages_url = info.get("html_url")
        except Exception:
            pass

    html = f"https://github.com/{owner}/{args.repo}"
    print("\n完成 ✓")
    print(f"  仓库地址: {html}")
    print(f"  网页地址: {pages_url or f'https://{owner}.github.io/{args.repo}/ （Pages 构建中，请稍后刷新）'}")
    print("\n提示：本仓库还配置了 .github/workflows/deploy.yml，")
    print("      以后每次 push 到 main 都会自动跑测试并重新部署 Pages。")
    print("      Action 首次运行需要在 Settings → Actions → General 允许 GitHub Actions。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
