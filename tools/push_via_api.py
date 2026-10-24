#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 GitHub REST API 把本地目录推送到已有仓库（不需要 git，不需要 github.com）。

适用场景：`github.com` 连不上（无法 git push / 无法设备码登录），
但 `api.github.com` 可用。

用法：
    set GITHUB_TOKEN=ghp_xxx
    python tools/push_via_api.py --owner Shen200608 --repo daily-interest-loan-calculator

特性：
- 自动读取远端当前分支头，以增量方式提交（不会丢历史）
- 只上传内容有变化的文件（先比对远端 tree 的 blob sha）
- 网络不稳时每个请求都会重试
- 只处理受 git 跟踪的文件（遵守 .gitignore，不会传 dist/exe/临时文件）
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
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
UA = "lixi-pusher/1.0"


def api(method: str, path: str, token: str, payload=None, retries: int = 5, timeout: int = 60):
    url = path if path.startswith("http") else API + path
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": UA,
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    last = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            if e.code < 500 and e.code != 429:
                return e.code, raw
            last = f"HTTP {e.code}: {raw[:200]}"
        except Exception as e:
            last = str(e)
        wait = min(attempt * 3, 15)
        print(f"  · 请求失败（第 {attempt} 次），{wait}s 后重试: {last}", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"{method} {url} 重试 {retries} 次仍失败: {last}")


def git_blob_sha(path: str) -> str:
    """按 git blob 规则计算 sha：sha1('blob <len>\\0' + content)。"""
    with open(path, "rb") as fh:
        content = fh.read()
    header = b"blob %d\x00" % len(content)
    return hashlib.sha1(header + content).hexdigest()


def tracked_files(root: str) -> list[str]:
    """用 git 列出受跟踪文件（遵守 .gitignore），再补上未跟踪但未被忽略的新文件。"""
    git = os.environ.get("LIXI_GIT", "git")
    try:
        out = subprocess.run(
            [git, "-C", root, "ls-files", "-co", "--exclude-standard"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        files = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        if files:
            return sorted(set(files))
    except Exception as e:
        print(f"  ! git ls-files 失败（{e}），回退为遍历目录")
    # 回退：遍历，跳过明显的产物目录
    skip_dirs = {".git", "__pycache__", "node_modules", "dist", "build", "shots"}
    skip_ext = {".pyc", ".exe", ".log", ".tmp", ".zip"}
    result = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in filenames:
            if os.path.splitext(name)[1].lower() in skip_ext:
                continue
            full = os.path.join(dirpath, name)
            result.append(os.path.relpath(full, root).replace("\\", "/"))
    return sorted(result)


def main(argv=None) -> int:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="用 REST API 推送到 GitHub 仓库")
    ap.add_argument("--owner", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--source", default=here)
    ap.add_argument("--message", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.source)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token and not args.dry_run:
        print("缺少 GITHUB_TOKEN 环境变量", file=sys.stderr)
        return 1

    files = tracked_files(root)
    print(f"本地文件 {len(files)} 个")
    if args.dry_run:
        for f in files:
            print("  ", f)
        return 0

    # 1) 校验身份
    st, me = api("GET", "/user", token)
    if st != 200:
        print(f"token 无效: HTTP {st} {me}", file=sys.stderr)
        return 1
    print(f"已认证: {me.get('login')}")

    # 2) 远端分支头
    parent_sha = None
    remote_blobs: dict[str, str] = {}
    st, ref = api("GET", f"/repos/{args.owner}/{args.repo}/git/ref/heads/{args.branch}", token)
    if st == 200 and isinstance(ref, dict):
        parent_sha = ref.get("object", {}).get("sha")
        print(f"远端分支 {args.branch} 头部: {parent_sha[:7] if parent_sha else '-'}")
        st2, tree = api(
            "GET",
            f"/repos/{args.owner}/{args.repo}/git/trees/{parent_sha}?recursive=1",
            token,
        )
        if st2 == 200 and isinstance(tree, dict):
            remote_blobs = {
                item["path"]: item["sha"]
                for item in tree.get("tree", [])
                if item.get("type") == "blob"
            }
            print(f"远端现有文件 {len(remote_blobs)} 个")

    # 3) 算出需要上传的文件
    to_upload = []
    for rel in files:
        full = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            continue
        local_sha = git_blob_sha(full)
        if remote_blobs.get(rel) == local_sha:
            continue
        to_upload.append((rel, full, local_sha))
    print(f"需要更新 {len(to_upload)} 个文件（其余未变化，跳过）")
    for rel, _, _ in to_upload:
        print(f"  + {rel}")
    if not to_upload:
        print("没有内容变化，无需提交。")
        return 0

    # 4) 上传 blob
    tree_items = []
    for i, (rel, full, _sha) in enumerate(to_upload, 1):
        with open(full, "rb") as fh:
            content = fh.read()
        st, blob = api(
            "POST",
            f"/repos/{args.owner}/{args.repo}/git/blobs",
            token,
            {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
        )
        if st not in (200, 201) or not isinstance(blob, dict):
            print(f"上传 {rel} 失败: HTTP {st} {blob}", file=sys.stderr)
            return 1
        tree_items.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        if i % 5 == 0 or i == len(to_upload):
            print(f"  已上传 {i}/{len(to_upload)}", flush=True)

    # 5) 建 tree（base_tree 保留未改动文件）
    tree_payload: dict = {"tree": tree_items}
    if parent_sha:
        base = _base_tree_sha(token, args.owner, args.repo, parent_sha)
        if base:
            tree_payload["base_tree"] = base
    st, new_tree = api(
        "POST",
        f"/repos/{args.owner}/{args.repo}/git/trees",
        token,
        tree_payload,
    )
    if st not in (200, 201) or not isinstance(new_tree, dict):
        print(f"创建 tree 失败: HTTP {st} {new_tree}", file=sys.stderr)
        return 1

    # 6) 建 commit
    payload = {"message": args.message or "chore: 更新", "tree": new_tree["sha"]}
    if parent_sha:
        payload["parents"] = [parent_sha]
    st, commit = api("POST", f"/repos/{args.owner}/{args.repo}/git/commits", token, payload)
    if st not in (200, 201) or not isinstance(commit, dict):
        print(f"创建 commit 失败: HTTP {st} {commit}", file=sys.stderr)
        return 1

    # 7) 移动分支
    if parent_sha:
        st, res = api(
            "PATCH",
            f"/repos/{args.owner}/{args.repo}/git/refs/heads/{args.branch}",
            token,
            {"sha": commit["sha"], "force": False},
        )
    else:
        st, res = api(
            "POST",
            f"/repos/{args.owner}/{args.repo}/git/refs",
            token,
            {"ref": f"refs/heads/{args.branch}", "sha": commit["sha"]},
        )
    if st not in (200, 201):
        print(f"更新分支失败: HTTP {st} {res}", file=sys.stderr)
        return 1

    print(f"\n✓ 推送成功")
    print(f"  提交: {commit['sha'][:7]}")
    print(f"  仓库: https://github.com/{args.owner}/{args.repo}")
    print(f"  Pages 约 1 分钟后自动重新部署")
    return 0


def _base_tree_sha(token: str, owner: str, repo: str, commit_sha: str | None) -> str | None:
    if not commit_sha:
        return None
    st, c = api("GET", f"/repos/{owner}/{repo}/git/commits/{commit_sha}", token)
    if st == 200 and isinstance(c, dict):
        return c.get("tree", {}).get("sha")
    return None


if __name__ == "__main__":
    sys.exit(main())
