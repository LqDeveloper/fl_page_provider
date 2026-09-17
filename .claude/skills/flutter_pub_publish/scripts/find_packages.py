#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清点一棵目录树里有哪些 package，用来回答"这次到底发哪个"。

为什么要一个脚本而不是一句 find：发错包和发错版本一样不可撤销，而"发错包"
最常见的成因不是粗心，是**信息不足下的默认推断**——一句 `find` 只给出一串路径，
看不出哪个是应用工程、哪个已经标了不发布、哪个还依赖着尚未发布的兄弟包。
人在这种列表面前只能猜，猜错了没有回头路。

所以这里一次把决策需要的事实都摆出来：名字、版本、类型、是否可发布、
包之间的 path 依赖，以及由此得出的发布先后顺序。

只读。不修改任何文件，不触发任何发布动作。

用法：
    python3 find_packages.py <目录> [--json out.json] [--all]

默认只列**候选可发布包**并把不可发布的归到一张说明表里；`--all` 平铺全部。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import pubspec as _pubspec
except ImportError:
    sys.stderr.write("致命：同目录下找不到 pubspec.py，请 cp -r 整个 skill 目录重装。\n")
    sys.exit(2)

SKIP_DIRS = {".git", ".dart_tool", "build", "node_modules", ".symlinks",
             ".idea", ".vscode", "Pods", ".fvm", ".melos_tool"}


def _w(s):
    """显示宽度。中日韩字符在等宽终端里占两列，len() 只算一列——不补这个差，
    含中文的表头会把整张表挤歪，而这张表正是用户选包的依据，看不清就选不准。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def _pad(s, width):
    s = str(s)
    return s + " " * max(0, width - _w(s))


def find_pubspecs(root, max_depth=6):
    out = []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        if "pubspec.yaml" in filenames:
            out.append(dirpath)
    return sorted(out)


def classify(path, data, parse_error):
    """判断这个目录是什么，以及能不能发到 pub.dev。

    返回 (kind, publishable, reason)。kind 只用于给人看，publishable 决定它
    会不会出现在候选列表里。宁可把可疑的标成"需确认"也不要悄悄过滤掉——
    过滤掉的东西人看不见，也就无从纠正。
    """
    if parse_error:
        return "读不了", None, "pubspec 无法可信解析：%s" % parse_error

    publish_to = str(data.get("publish_to") or "").strip()
    if publish_to and publish_to != "null":
        return "私有", False, "pubspec 里有 publish_to: %s" % publish_to

    has_lib = os.path.isdir(os.path.join(path, "lib"))
    lib_files = []
    if has_lib:
        lib_files = [f for f in os.listdir(os.path.join(path, "lib"))
                     if f.endswith(".dart")]
    name = str(data.get("name") or "").strip()

    # example 目录里的包几乎总是宿主包的示例工程，不是要发的东西
    parts = os.path.normpath(path).split(os.sep)
    if "example" in parts[-2:]:
        return "示例工程", False, "位于 example/ 下"

    if os.path.isfile(os.path.join(path, "lib", "main.dart")):
        entry = "%s.dart" % name
        if entry not in lib_files:
            return "应用工程", False, "有 lib/main.dart 且没有 lib/%s 导出入口" % entry
        return "应用工程?", None, "同时有 lib/main.dart 和导出入口，需确认"

    if not has_lib:
        return "无 lib/", None, "没有 lib/ 目录，可能不是库包"

    deps = data.get("dependencies")
    is_flutter = isinstance(deps, dict) and "flutter" in deps
    return ("Flutter 包" if is_flutter else "Dart 包"), True, ""


def local_deps(data):
    """返回 {依赖名: 'path'|'git'}，即那些指向本地/仓库而非 pub.dev 的依赖。"""
    out = {}
    for block in ("dependencies", "dev_dependencies", "dependency_overrides"):
        d = data.get(block)
        if not isinstance(d, dict):
            continue
        for k, v in d.items():
            if isinstance(v, dict):
                if "path" in v:
                    out[k] = "path"
                elif "git" in v:
                    out.setdefault(k, "git")
    return out


def publish_order(pkgs):
    """按包间 path 依赖做拓扑排序：被依赖的排前面。

    这不是为了自动连发（skill 一次只发一个），而是为了在人选包时把顺序摆出来。
    顺序搞错的后果不是发布失败，而是**发出去了但别人装不上**——因为它的
    dependencies 里指向了一个 pub.dev 上还不存在的包。这种错误只能靠再发一版修。
    """
    by_name = {p["name"]: p for p in pkgs if p["name"]}
    indeg = {n: 0 for n in by_name}
    edges = {n: set() for n in by_name}
    for p in pkgs:
        if not p["name"]:
            continue
        for dep in p["local_deps"]:
            if dep in by_name and dep != p["name"]:
                if p["name"] not in edges[dep]:
                    edges[dep].add(p["name"])
                    indeg[p["name"]] += 1
    order, queue = [], sorted([n for n, d in indeg.items() if d == 0])
    while queue:
        n = queue.pop(0)
        order.append(n)
        for m in sorted(edges[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    cycle = [n for n in by_name if n not in order]
    return order, sorted(cycle)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--json", default=None)
    ap.add_argument("--all", action="store_true", help="连同不可发布的一起平铺")
    a = ap.parse_args()

    root = os.path.abspath(a.root)
    dirs = find_pubspecs(root)
    if not dirs:
        print("在 %s 下没找到任何 pubspec.yaml。" % root)
        print("→ 这个目录不是 Dart/Flutter 工程，确认一下路径。")
        return 1

    pkgs = []
    for d in dirs:
        data, err = {}, None
        try:
            data, _ = _pubspec.load(os.path.join(d, "pubspec.yaml"))
        except _pubspec.PubspecParseError as e:
            err = str(e).splitlines()[0]
        kind, publishable, reason = classify(d, data, err)
        pkgs.append({
            "path": d,
            "rel": os.path.relpath(d, root),
            "name": str(data.get("name") or "").strip(),
            "version": str(data.get("version") or "").strip(),
            "kind": kind,
            "publishable": publishable,
            "reason": reason,
            "local_deps": local_deps(data),
        })

    workspace = []
    for f in ("melos.yaml", "pubspec_overrides.yaml"):
        if os.path.isfile(os.path.join(root, f)):
            workspace.append(f)
    root_ps = os.path.join(root, "pubspec.yaml")
    if os.path.isfile(root_ps):
        try:
            rd, _ = _pubspec.load(root_ps)
            if rd.get("workspace"):
                workspace.append("pub workspace（根 pubspec 有 workspace:）")
        except _pubspec.PubspecParseError:
            pass

    cand = [p for p in pkgs if p["publishable"] is True]
    unsure = [p for p in pkgs if p["publishable"] is None]
    no = [p for p in pkgs if p["publishable"] is False]

    print("=" * 78)
    print("目录：%s" % root)
    if workspace:
        print("形态：monorepo（检出 %s）" % "、".join(workspace))
    print("共找到 %d 个 pubspec.yaml：候选可发布 %d，需确认 %d，不可发布 %d"
          % (len(pkgs), len(cand), len(unsure), len(no)))
    print("=" * 78)

    show = cand + unsure + (no if a.all else [])
    if show:
        nw = max([_w(p["name"] or "(无名)") for p in show] + [_w("包名")])
        vw = max([_w(p["version"] or "(无)") for p in show] + [_w("版本")])
        kw = max([_w(p["kind"]) for p in show] + [_w("类型")])

        def row(mark, p):
            return "%s %s %s %s %s" % (
                _pad(mark, 3), _pad(p["name"] or "(无名)", nw),
                _pad(p["version"] or "(无)", vw), _pad(p["kind"], kw), p["rel"])

        print("\n%s %s %s %s %s" % (_pad("#", 3), _pad("包名", nw),
                                    _pad("版本", vw), _pad("类型", kw), "路径"))
        print("-" * 78)
        for i, p in enumerate(cand, 1):
            print(row(str(i), p))
        for p in unsure:
            print(row("?", p))
            print("      ↳ 需确认：%s" % p["reason"])
        if a.all:
            for p in no:
                print(row("×", p))
                print("      ↳ 不可发布：%s" % p["reason"])

    if no and not a.all:
        print("\n已排除 %d 个不可发布的目录（%s）。加 --all 看明细。"
              % (len(no), "、".join(sorted({p["kind"] for p in no}))))

    # 包间依赖与发布顺序
    inter = [(p["name"], dep, kind) for p in pkgs for dep, kind in p["local_deps"].items()
             if dep in {q["name"] for q in pkgs if q["name"]}]
    if inter:
        print("\n--- 包之间的本地依赖 ---")
        for who, dep, kind in sorted(inter):
            print("  %s  依赖  %s  (%s:)" % (who, dep, kind))
        order, cycle = publish_order(pkgs)
        rel = [n for n in order if n in {p["name"] for p in cand + unsure}]
        if rel:
            print("\n发布顺序（被依赖的必须先发）：")
            print("  " + "  →  ".join(rel))
        if cycle:
            print("\n⚠ 这几个包之间存在循环依赖，无法确定顺序：%s" % "、".join(cycle))
        print("""
注意：path/git 依赖发不到 pub.dev。上面每个"依赖 X"的包，在发布前都必须先把
那条依赖换成 X 在 pub.dev 上的版本号约束——也就是说 X 得先发。顺序错了不会
发布失败，而是发出去了但别人装不上，只能再发一版修。""")

    print("\n" + "=" * 78)
    if len(cand) == 1 and not unsure:
        p = cand[0]
        print("只有一个候选：%s %s（%s）" % (p["name"], p["version"], p["rel"]))
        print("→ 可以直接说一句\"我给 %s %s 走发布检查\"就开始，不必等回复。"
              % (p["name"], p["version"]))
    elif len(cand) + len(unsure) == 0:
        print("没有找到任何候选可发布的包。")
        print("→ 把上面的排除原因摆给用户，问清楚他想发的是哪个。")
    else:
        print("有 %d 个候选。**必须让用户选定一个再往下走**，不要默认推断。"
              % (len(cand) + len(unsure)))
        print("→ 把上面这张表交给用户，用 AskUserQuestion 让他选。")
        print("→ 没人回答就停在这里等：别处默认推断的代价是重跑一次，")
        print("  这里的代价是把错误的包永久发到公网。")
    print("=" * 78)

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"root": root, "workspace": workspace, "packages": pkgs,
                       "candidates": [p["name"] for p in cand]},
                      f, ensure_ascii=False, indent=2)
        print("JSON 已写入 %s" % a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
