#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 git 历史取出「上次发布以来的真实改动」，供起草 CHANGELOG 条目。

这个脚本存在的唯一理由：CHANGELOG 是使用者判断「要不要升级」的依据，
编造出来的条目比空着更糟。所以条目必须从真实 commit 和真实 diff 推导。

只读：不写 CHANGELOG，不改任何文件。输出给 AI 看，由 AI 归纳成人话。

用法：
    python3 changelog_draft.py <pkg路径> [--since <tag或commit>]

不指定 --since 时，自动找上一个版本 tag（v1.2.3 / 1.2.3 形式，取版本号最大的）。
"""
import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import pubspec as _pubspec
except ImportError:
    sys.stderr.write("致命：同目录下找不到 pubspec.py，请 cp -r 整个 skill 目录重装。\n")
    sys.exit(2)

VER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def git(args, cwd, timeout=60):
    try:
        p = subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                           text=True, timeout=timeout, errors="replace")
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as e:
        return 1, "", str(e)


def pubspec_version(pkg):
    """取待发版本号。走和 preflight 同一套可信解析，避免两个脚本对同一份
    pubspec 得出不同的版本号——那会让"按改动性质定版本号"这一步基于错的起点。"""
    p = os.path.join(pkg, "pubspec.yaml")
    if not os.path.isfile(p):
        return None
    try:
        data, _ = _pubspec.load(p)
        v = data.get("version")
        return str(v).strip() if v is not None else None
    except _pubspec.PubspecParseError as e:
        print("⚠ pubspec 未能可信解析：%s" % e)
        print("  版本号显示为「未知」。下面的 commit 与 diff 仍然有效，")
        print("  但定版本号前请先解决这个问题。\n")
        return None


def pubspec_name(pkg):
    p = os.path.join(pkg, "pubspec.yaml")
    if not os.path.isfile(p):
        return None
    try:
        data, _ = _pubspec.load(p)
        n = data.get("name")
        return str(n).strip() if n else None
    except _pubspec.PubspecParseError:
        return None


def last_release_tag(pkg, name, in_subdir):
    """找"上一个发布 tag"，作为 commit 区间的起点。

    在 monorepo 里这一步最容易出错：`git tag --list` 给的是**整个仓库**的 tag，
    直接挑版本号最大的会挑中隔壁包的 `v1.2.0`。起点错了，下面列出的 commit
    就是别的包的改动，据此写出来的 CHANGELOG 会把不属于这一版的东西写进去——
    而 CHANGELOG 正是使用者判断要不要升级的依据。

    所以：包在仓库根上时，裸 tag 就是它的；包在子目录里时，只认带包名的 tag。
    """
    rc, out, _ = git(["tag", "--list"], pkg)
    if rc != 0:
        return None, ""
    tags = out.split()

    def best_of(cands):
        b, bk = None, None
        for t, key in cands:
            if bk is None or key > bk:
                b, bk = t, key
        return b

    if name:
        pref = []
        for t in tags:
            for sep in ("-v", "-", "/v", "_v", "@v", "@"):
                head = name + sep
                if t.startswith(head):
                    m = VER_RE.match(t[len(head):])
                    if m:
                        pref.append((t, tuple(int(x) for x in m.groups())))
                    break
        hit = best_of(pref)
        if hit:
            return hit, "本包专属 tag"

    if in_subdir:
        bare = [t for t in tags if VER_RE.match(t)]
        note = ("；仓库里有裸 tag（%s 等）但本包在子目录下，无法确定它们属于本包，故不采用"
                % bare[0]) if bare else ""
        return None, "没找到本包专属 tag%s" % note

    bare = [(t, tuple(int(x) for x in VER_RE.match(t).groups()))
            for t in tags if VER_RE.match(t)]
    hit = best_of(bare)
    return (hit, "仓库根即本包，裸 tag 即本包的 tag") if hit else (None, "仓库里没有版本 tag")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pkg")
    ap.add_argument("--since", default=None, help="起点 tag 或 commit；不给则自动找上一个版本 tag")
    a = ap.parse_args()
    pkg = os.path.abspath(a.pkg)

    rc, root, err = git(["rev-parse", "--show-toplevel"], pkg)
    if rc != 0:
        print("不是 git 仓库，无法从历史推导改动。")
        print("→ 这种情况下不要凭空写 CHANGELOG。让用户口述这一版改了什么，")
        print("  或者只写你从 diff/代码里能确证的内容。")
        return 1

    ver = pubspec_version(pkg)
    name = pubspec_name(pkg)
    rel = os.path.relpath(pkg, root) or "."
    in_subdir = rel != "."
    # 所有 git 查询都用 `-- <rel>` 限定在本包目录下：隔壁包的 commit 不该出现在
    # 这个包的 CHANGELOG 里，哪怕它们在同一个仓库同一个分支上。
    scope = [] if not in_subdir else ["--", rel]

    if a.since:
        since, since_why = a.since, "命令行指定"
    else:
        since, since_why = last_release_tag(pkg, name, in_subdir)

    print("=" * 72)
    print("package : %s%s" % (pkg, ("  [%s]" % name) if name else ""))
    print("待发版本: %s" % (ver or "(未读到)"))
    print("对比起点: %s  —— %s" % (since or "(取全部历史)", since_why))
    if in_subdir:
        print("统计范围: 仅 %s 下的改动（同仓库其他包的 commit 不计入）" % rel)
    print("=" * 72)

    rng = ["%s..HEAD" % since] if since else []

    print("\n--- commit 列表（这是唯一的事实来源）---")
    # cwd 必须是仓库根：scope 里的路径是相对仓库根的，若从 pkg 目录下跑，
    # `-- packages/fl_core` 会被当成 pkg/packages/fl_core 而匹配不到任何东西，
    # 结果是"0 个 commit"——一份静默的空 CHANGELOG，比报错更难发现。
    rc, out, err = git(["log", "--no-merges", "--pretty=format:%h  %ad  %s", "--date=short"]
                       + rng + scope, root, timeout=90)
    if out:
        print(out)
        n = len(out.splitlines())
    else:
        n = 0
        print("(区间内没有 commit%s)" % ("，说明这个版本还没有任何改动" if since else ""))
    print("\n共 %d 个 commit" % n)

    print("\n--- 改动文件统计 ---")
    rc, out, _ = git(["diff", "--stat"] + ([since + "..HEAD"] if since else []) + scope,
                     root, timeout=90)
    print(out or "(无)")

    print("\n--- 公开 API 面的增删（lib/ 下 export / 顶层 class / 顶层函数的增减行）---")
    rc, out, _ = git(["diff", "-U0"] + ([since + "..HEAD"] if since else [])
                     + ["--", os.path.join(rel, "lib") if in_subdir else "lib"],
                     root, timeout=120)
    api = []
    for line in (out or "").splitlines():
        if line.startswith(("+++", "---")):
            continue
        if not line.startswith(("+", "-")):
            continue
        body = line[1:].strip()
        if re.match(r"^(export\s|abstract\s+class\s|class\s|mixin\s|enum\s|extension\s"
                    r"|typedef\s|[A-Za-z_<>?\[\], ]+\s+\w+\s*\()", body):
            api.append(line[0] + " " + body[:140])
    if api:
        for l in api[:80]:
            print(l)
        if len(api) > 80:
            print("... 还有 %d 行未列出" % (len(api) - 80))
    else:
        print("(未检出公开 API 面的明显增删)")

    print("\n" + "=" * 72)
    print("""写 CHANGELOG 时守住三条：

1. 每一条都能对应上面某个 commit 或某段 diff。对不上就不写。
2. 写「使用者视角的变化」，不是 commit message 的搬运。
   "fix: null check in _parse" → "修复 响应体缺字段时 parseResponse 抛异常"。
3. 破坏性变更（上面 API 面出现 `-` 开头的 export / 类 / 方法签名）必须单独用
   BREAKING 标出，并说明迁移方式——使用者升级失败大多数栽在这里。

拿不准某个 commit 对使用者意味着什么，就去读那个 commit 的 diff，别猜。""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
