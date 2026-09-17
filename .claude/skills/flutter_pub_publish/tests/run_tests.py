#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flutter_pub_publish 的回归测试。

    python3 tests/run_tests.py [--only 组名,组名] [-v]

改过 scripts/ 里任何一个文件后跑一遍。全绿再交。

它守的是什么：这个 skill 的价值全在"结论可信"上——说 PASS 就真的检查过了，
说 FAIL 就真的有问题。**最危险的不是漏检，是假绿灯**：一个没跑起来的命令
被当成通过、一个属于隔壁包的 tag 被算到这个包头上、一个读错的 pubspec
驱动了版本判断。这些都不会报错，只会让人放心地发出去一个错东西。
所以下面的断言里，"命令失败时必须是 SKIP 而不是 PASS"这类占了一多半。

不需要真的装 Dart/Flutter：假 SDK 精确伪造退出码与输出，把真实环境里
难以按需复现的情形（命令不存在、源码语法错误、SDK 装坏）变成可重复的用例。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, HERE)
sys.path.insert(0, SCRIPTS)

import fixtures as F  # noqa

PASSED, FAILED, SKIPPED = [], [], []
VERBOSE = False


def check(label, ok, detail=""):
    if ok:
        PASSED.append(label)
        if VERBOSE:
            print("    ✓ %s" % label)
    else:
        FAILED.append((label, detail))
        print("    ✗ %s" % label)
        for line in str(detail).splitlines():
            print("        %s" % line)


def skip(label, why):
    SKIPPED.append((label, why))
    print("    - %s（跳过：%s）" % (label, why))


def run_preflight(pkg, only, env=None, extra=None):
    """跑 preflight，返回 {检查项 id: 结果}。用子进程跑，测的是真实 CLI 路径。"""
    out_json = tempfile.mktemp(suffix=".json")
    cmd = [sys.executable, os.path.join(SCRIPTS, "preflight.py"), pkg,
           "--only", only, "--no-net", "--json", out_json] + (extra or [])
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run(cmd, capture_output=True, text=True, env=e, timeout=300)
    if not os.path.isfile(out_json):
        return {}, p.stdout + p.stderr
    with open(out_json, encoding="utf-8") as f:
        data = json.load(f)
    os.unlink(out_json)
    return {r["id"]: r for r in data["results"]}, p.stdout + p.stderr


def status_of(res, cid):
    return res.get(cid, {}).get("status", "<缺失>")


def sdk_env(bindir, mode, name="", version="", log=None):
    e = {"PATH": bindir + os.pathsep + os.environ.get("PATH", ""),
         "FAKE_MODE": mode, "FAKE_PKG_NAME": name, "FAKE_PKG_VERSION": version}
    if log:
        e["FAKE_LOG"] = log
    return e


# ==========================================================================
# 组：pubspec 解析

def group_pubspec(tmp):
    import pubspec as P
    ok, problems = P.selftest()
    check("内置严格解析器自检（%d 接受 + %d 拒绝）" % (len(P.CORPUS), len(P.REJECT_CORPUS)),
          ok, "\n".join(problems))

    pkg = F.make_package(os.path.join(tmp, "pp"), "pp", "1.2.3", flutter=False)
    data, meta = P.load(os.path.join(pkg, "pubspec.yaml"))
    check("解析出正确的 name/version",
          data.get("name") == "pp" and str(data.get("version")) == "1.2.3",
          "得到 %r / %r" % (data.get("name"), data.get("version")))

    # 旁路核对：解析器说谎时必须被拦下
    real = P.parse_strict
    P.selftest, P.parse_strict = (lambda: (True, [])), (
        lambda t: dict(real(t), **{"version": "9.9.9"}))
    try:
        P.load(os.path.join(pkg, "pubspec.yaml"))
        check("解析器读串行时被旁路核对拦下", False, "没拦住")
    except P.PubspecParseError as e:
        check("解析器读串行时被旁路核对拦下", "不一致" in str(e), str(e))
    finally:
        P.parse_strict = real

    # 不担保的语法必须硬失败，不能降级
    anchor = F.make_package(os.path.join(tmp, "anchor"), "anchor", "1.0.0", flutter=False)
    F._w(os.path.join(anchor, "pubspec.yaml"),
         "name: anchor\ndescription: %s\nversion: 1.0.0\n"
         "common: &c\n  sdk: ^3.5.0\nenvironment: *c\n" % F.LONG_DESC)
    noyaml = os.path.join(tmp, "noyaml")
    os.makedirs(noyaml, exist_ok=True)
    F._w(os.path.join(noyaml, "yaml.py"), 'raise ImportError("blocked for testing")\n')
    res, _ = run_preflight(anchor, "meta", env={"PYTHONPATH": noyaml})
    check("无 PyYAML + 锚点 pubspec → PKG.parser 硬失败（不是 WARN）",
          status_of(res, "PKG.parser") == "FAIL", status_of(res, "PKG.parser"))
    check("解析失败时不产出任何元数据结论",
          "VER.semver" not in res and "DEP.path_git" not in res,
          "仍然产出了：%s" % sorted(res))

    # 同一个包，有无 PyYAML 结论必须一致
    a, _ = run_preflight(pkg, "meta")
    b, _ = run_preflight(pkg, "meta", env={"PYTHONPATH": noyaml})
    diff = [k for k in a if status_of(a, k) != status_of(b, k)]
    check("有/无 PyYAML 时逐项结论一致", not diff,
          "差异项：%s" % diff)


# ==========================================================================
# 组：format —— 2026-09 的 bug 就在这里

def group_format(tmp):
    pkg = F.make_package(os.path.join(tmp, "fmt"), "fmt", "1.0.0", flutter=True)
    bind = F.make_fake_sdk(tmp)
    log = os.path.join(tmp, "calls.log")

    cases = [
        ("Flutter 包 · 格式干净 → PASS", "clean", "PASS"),
        ("Flutter 包 · 2 个文件不一致 → FAIL", "unformatted", "FAIL"),
        ("Flutter 包 · 源码语法错误致 formatter 失败 → SKIP（不是 FAIL）",
         "fmt_syntax_error", "SKIP"),
    ]
    for label, mode, want in cases:
        res, _ = run_preflight(pkg, "format", env=sdk_env(bind, mode, log=log))
        check(label, status_of(res, "CODE.format") == want,
              "实得 %s：%s" % (status_of(res, "CODE.format"),
                             res.get("CODE.format", {}).get("detail", "")))

    res, _ = run_preflight(pkg, "format", env=sdk_env(bind, "unformatted"))
    d = res.get("CODE.format", {})
    check("FAIL 时列出具体文件名",
          "client.dart" in d.get("detail", "") and "2 个文件" in d.get("detail", ""),
          d.get("detail"))
    check("格式问题标记为可自动修（auto）", d.get("fix") == "auto", d.get("fix"))

    res, _ = run_preflight(pkg, "format", env=sdk_env(bind, "fmt_syntax_error"))
    check("命令失败时不标成 auto（否则 AI 会去修一个不存在的格式问题）",
          res.get("CODE.format", {}).get("fix") == "manual",
          res.get("CODE.format", {}).get("fix"))

    # 核心回归：绝不能调用 flutter format
    if os.path.isfile(log):
        os.unlink(log)
    for mode in ("clean", "unformatted", "fmt_syntax_error"):
        run_preflight(pkg, "format", env=sdk_env(bind, mode, log=log))
    calls = open(log).read() if os.path.isfile(log) else ""
    check("从不调用 `flutter format`（该子命令在现代 Flutter 里已被移除）",
          "flutter format" not in calls,
          "实际调用记录：\n" + calls)

    # dart 不在 PATH 上，但在 flutter 旁边
    only_f = os.path.join(tmp, "onlyflutter")
    os.makedirs(only_f, exist_ok=True)
    link = os.path.join(only_f, "flutter")
    if os.path.lexists(link):
        os.unlink(link)
    os.symlink(os.path.join(bind, "flutter"), link)
    env = {"PATH": only_f + os.pathsep + "/usr/bin" + os.pathsep + "/bin",
           "FAKE_MODE": "unformatted"}
    res, _ = run_preflight(pkg, "format", env=env)
    check("PATH 上只有 flutter 时，能在它旁边找到 dart",
          status_of(res, "CODE.format") == "FAIL",
          "实得 %s：%s" % (status_of(res, "CODE.format"),
                         res.get("CODE.format", {}).get("detail", "")))

    # 什么都没有 → SKIP，不是 PASS
    empty = os.path.join(tmp, "nosdk")
    os.makedirs(empty, exist_ok=True)
    res, _ = run_preflight(pkg, "format", env={"PATH": empty})
    check("找不到任何 SDK → SKIP（不是 PASS）",
          status_of(res, "CODE.format") == "SKIP", status_of(res, "CODE.format"))


# ==========================================================================
# 组：analyze

def group_analyze(tmp):
    pkg = F.make_package(os.path.join(tmp, "an"), "an", "1.0.0", flutter=True)
    bind = F.make_fake_sdk(tmp)
    log = os.path.join(tmp, "an_calls.log")

    for label, mode, want in [
            ("零问题 → PASS", "clean", "PASS"),
            ("有 info + warning → FAIL（用户要求 info 也阻断）", "analyze_issues", "FAIL"),
            ("有 error → FAIL", "analyze_errors", "FAIL"),
            ("命令没跑成 → SKIP（不是凭空捏造的零问题）", "analyze_broken", "SKIP")]:
        res, _ = run_preflight(pkg, "analyze", env=sdk_env(bind, mode, log=log))
        check("analyze · " + label, status_of(res, "CODE.analyze") == want,
              "实得 %s：%s" % (status_of(res, "CODE.analyze"),
                             res.get("CODE.analyze", {}).get("detail", "")))

    res, _ = run_preflight(pkg, "analyze", env=sdk_env(bind, "analyze_issues"))
    d = res.get("CODE.analyze", {}).get("detail", "")
    check("FAIL 时给出 ERROR/WARNING/INFO 计数与样例",
          "WARNING 1" in d and "INFO 1" in d and "prefer_const_constructors" in d, d)
    check("诊断路径不是一长串 ../../..", "../.." not in d, d)

    if os.path.isfile(log):
        os.unlink(log)
    for mode in ("clean", "analyze_issues", "analyze_broken"):
        run_preflight(pkg, "analyze", env=sdk_env(bind, mode, log=log))
    calls = open(log).read() if os.path.isfile(log) else ""
    check("从不用 flutter 跑 analyze（flutter analyze 不认 --format=machine）",
          "flutter analyze" not in calls, "实际调用记录：\n" + calls)


# ==========================================================================
# 组：git 范围 —— 只校验要发的包，不看隔壁

def group_git(tmp):
    if not shutil.which("git"):
        skip("git 范围检查", "环境里没有 git")
        return
    mono = F.make_monorepo(os.path.join(tmp, "mono"))
    core = os.path.join(mono, "packages", "fl_core")
    ui = os.path.join(mono, "packages", "fl_ui")

    F.touch(os.path.join(ui, "lib", "fl_ui.dart"), "// 隔壁包脏了")
    res, _ = run_preflight(core, "git")
    check("隔壁包有未提交改动，不影响本包 GIT.clean",
          status_of(res, "GIT.clean") == "PASS",
          "实得 %s：%s" % (status_of(res, "GIT.clean"),
                         res.get("GIT.clean", {}).get("detail", "")))
    check("仓库里有属于隔壁包的裸 tag v1.2.0，不算本包（fl_core 1.2.0）的冲突",
          status_of(res, "GIT.tag") == "PASS",
          res.get("GIT.tag", {}).get("detail", ""))
    check("但会把那个裸 tag 作为提示列出来",
          "v1.2.0" in res.get("GIT.tag", {}).get("detail", ""),
          res.get("GIT.tag", {}).get("detail", ""))

    F.touch(os.path.join(core, "lib", "fl_core.dart"), "// 本包脏了")
    res, _ = run_preflight(core, "git")
    check("本包自己有未提交改动 → FAIL",
          status_of(res, "GIT.clean") == "FAIL", status_of(res, "GIT.clean"))
    check("FAIL 详情里只列本包的文件",
          "fl_ui" not in res.get("GIT.clean", {}).get("detail", ""),
          res.get("GIT.clean", {}).get("detail", ""))

    net = os.path.join(mono, "packages", "fl_net")   # 0.4.1，且已有 fl_net-v0.4.1
    res, _ = run_preflight(net, "git")
    check("本包专属 tag 已存在 → FAIL",
          status_of(res, "GIT.tag") == "FAIL",
          res.get("GIT.tag", {}).get("detail", ""))

    # 包就在仓库根上时，裸 tag 仍然算它的
    solo = F.make_package(os.path.join(tmp, "solo"), "solo", "1.0.0", flutter=False)
    F._git(solo, ["init", "-q"]); F._git(solo, ["config", "user.email", "t@e.com"])
    F._git(solo, ["config", "user.name", "T"]); F.git_commit(solo, "init")
    F._git(solo, ["tag", "v1.0.0"])
    res, _ = run_preflight(solo, "git")
    check("包在仓库根上时，裸 tag v1.0.0 仍算冲突",
          status_of(res, "GIT.tag") == "FAIL",
          res.get("GIT.tag", {}).get("detail", ""))


# ==========================================================================
# 组：find_packages —— 选包

def group_packages(tmp):
    def fp(path, *extra):
        p = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "find_packages.py"), path] + list(extra),
            capture_output=True, text=True, timeout=120)
        return p.stdout + p.stderr

    mono = F.make_monorepo(os.path.join(tmp, "mono2"), with_git=False)
    out = fp(mono)
    check("monorepo 列出 3 个候选包",
          "候选可发布 3" in out, out[:600])
    check("应用工程被排除且说明原因",
          "应用工程" in fp(mono, "--all"), "")
    check("publish_to: none 的 example 被排除",
          "publish_to: none" in fp(mono, "--all"), "")
    check("给出发布顺序 fl_core → fl_net → fl_ui",
          "fl_core  →  fl_net  →  fl_ui" in out, out[out.find("发布顺序"):][:200])
    check("多候选时明确要求让用户选定",
          "必须让用户选定一个" in out, out[-400:])

    solo = F.make_package(os.path.join(tmp, "solo2"), "solo2", "1.0.0", flutter=False)
    out = fp(solo)
    check("单个候选时提示可直接开工",
          "只有一个候选" in out and "不必等回复" in out, out[-300:])

    app = F.make_app(os.path.join(tmp, "apponly"), "just_app")
    out = fp(app)
    check("只有应用工程时报零候选并交回用户",
          "没有找到任何候选可发布的包" in out, out[-300:])

    out = fp(os.path.join(tmp, "notdart"))
    os.makedirs(os.path.join(tmp, "notdart"), exist_ok=True)
    out = fp(os.path.join(tmp, "notdart"))
    check("非 Dart 目录给出可操作提示",
          "没找到任何 pubspec.yaml" in out, out[:300])

    cyc = os.path.join(tmp, "cyc")
    F.make_package(os.path.join(cyc, "a"), "pkg_a", "1.0.0", flutter=False,
                   path_deps={"pkg_b": "../b"})
    F.make_package(os.path.join(cyc, "b"), "pkg_b", "1.0.0", flutter=False,
                   path_deps={"pkg_a": "../a"})
    check("循环依赖被指出而不是给一个错的顺序",
          "循环依赖" in fp(cyc), fp(cyc)[-400:])


# ==========================================================================
# 组：changelog 取材范围

def group_changelog(tmp):
    if not shutil.which("git"):
        skip("changelog 取材范围", "环境里没有 git")
        return
    mono = F.make_monorepo(os.path.join(tmp, "mono3"))
    core = os.path.join(mono, "packages", "fl_core")
    ui = os.path.join(mono, "packages", "fl_ui")

    F.touch(os.path.join(core, "lib", "fl_core.dart"), "// core 改动")
    F.touch(os.path.join(ui, "lib", "fl_ui.dart"), "// ui 也改了")
    F.git_commit(mono, "feat: 同时改了 core 和 ui")
    F.touch(os.path.join(ui, "lib", "fl_ui.dart"), "// 只改 ui")
    F.git_commit(mono, "fix: 只改了 ui")

    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "changelog_draft.py"), core],
                       capture_output=True, text=True, timeout=120)
    out = p.stdout + p.stderr
    check("起点取本包专属 tag（不是隔壁包的裸 v1.2.0）",
          "fl_core-v1.1.0" in out and "本包专属 tag" in out, out[:600])
    # 先确认清单确实取到了东西，否则下面"隔壁 commit 不出现"会因为清单是空的而空过。
    # 空清单是个真实的失效模式（git 路径限定写错就会这样），它比多列几条更危险：
    # 结果是一份看似合理的空 CHANGELOG。
    check("本包的 commit 确实被取到了（防止清单空过）",
          "同时改了 core 和 ui" in out and "共 1 个 commit" in out,
          out[out.find("commit 列表"):][:400])
    check("只改隔壁包的 commit 不出现在本包清单里",
          "只改了 ui" not in out, out[out.find("commit 列表"):][:400])
    check("同时改了两个包的 commit 出现，但文件统计只列本包的文件",
          "同时改了 core 和 ui" in out and "fl_ui" not in out.split("改动文件统计")[1][:300],
          out[out.find("改动文件统计"):][:300])

    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "changelog_draft.py"), ui],
                       capture_output=True, text=True, timeout=120)
    out = p.stdout + p.stderr
    check("没有专属 tag 时说明为何不采用仓库里的裸 tag",
          "无法确定它们属于本包" in out, out[:600])
    check("fl_ui 的清单里能看到它自己的两个 commit",
          "只改了 ui" in out and "同时改了 core 和 ui" in out,
          out[out.find("commit 列表"):][:400])


# ==========================================================================
# 组：dryrun 与包身份

def group_dryrun(tmp):
    pkg = F.make_package(os.path.join(tmp, "dr"), "dr", "1.0.0", flutter=False)
    bind = F.make_fake_sdk(tmp)
    res, _ = run_preflight(pkg, "dryrun", env=sdk_env(bind, "dryrun_ok", "dr", "1.0.0"))
    check("dry-run 零告警 → PASS",
          status_of(res, "PUB.dry_run") == "PASS",
          res.get("PUB.dry_run", {}).get("detail", ""))
    check("pub 自述的包名版本与 pubspec 一致 → PUB.identity PASS",
          status_of(res, "PUB.identity") == "PASS",
          res.get("PUB.identity", {}).get("detail", ""))

    res, _ = run_preflight(pkg, "dryrun",
                           env=sdk_env(bind, "dryrun_identity_mismatch", "dr", "1.0.0"))
    check("pub 说要发的是别的包 → PUB.identity FAIL",
          status_of(res, "PUB.identity") == "FAIL",
          res.get("PUB.identity", {}).get("detail", ""))

    res, _ = run_preflight(pkg, "dryrun", env=sdk_env(bind, "dryrun_warn", "dr", "1.0.0"))
    check("dry-run 有告警 → FAIL",
          status_of(res, "PUB.dry_run") == "FAIL",
          res.get("PUB.dry_run", {}).get("detail", ""))


# ==========================================================================
# 组：meta 各项

def group_meta(tmp):
    good = F.make_package(os.path.join(tmp, "m_good"), "m_good", "1.0.0", flutter=False)
    res, _ = run_preflight(good, "meta")
    fails = [k for k, v in res.items() if v["status"] == "FAIL"]
    check("齐备的包 meta 组零 FAIL", not fails,
          "\n".join("%s: %s" % (k, res[k]["detail"]) for k in fails))

    bad = F.make_package(os.path.join(tmp, "m_bad"), "m_bad", "1.0.0",
                         flutter=False, desc="Too short.", complete=False,
                         changelog_version="0.9.0", path_deps={"x": "../x"})
    res, _ = run_preflight(bad, "meta")
    for cid, why in [("PKG.description", "描述过短"),
                     ("DOC.readme", "缺 README"),
                     ("DOC.license", "缺 LICENSE"),
                     ("DOC.example", "缺 example"),
                     ("DEP.path_git", "有 path 依赖"),
                     ("VER.changelog_match", "CHANGELOG 版本对不上")]:
        check("meta · %s → FAIL" % why, status_of(res, cid) == "FAIL",
              "实得 %s" % status_of(res, cid))

    pn = F.make_package(os.path.join(tmp, "m_pn"), "m_pn", "1.0.0", flutter=False,
                        publish_to="none")
    res, _ = run_preflight(pn, "meta")
    check("publish_to: none → FAIL", status_of(res, "PKG.publish_to") == "FAIL",
          status_of(res, "PKG.publish_to"))

    # 报告头必须复述包身份，防止 monorepo 里飘到隔壁包
    _, out = run_preflight(good, "meta")
    check("报告头复述包名与版本", "m_good 1.0.0" in out, out[:300])


GROUPS = [
    ("pubspec", "pubspec 可信解析", group_pubspec),
    ("meta", "meta 各检查项", group_meta),
    ("format", "CODE.format", group_format),
    ("analyze", "CODE.analyze", group_analyze),
    ("git", "git 检查范围", group_git),
    ("packages", "find_packages 选包", group_packages),
    ("changelog", "changelog 取材范围", group_changelog),
    ("dryrun", "dry-run 与包身份", group_dryrun),
]


def main():
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="逗号分隔的组名：%s"
                    % ",".join(g[0] for g in GROUPS))
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--keep", action="store_true", help="保留临时目录以便排查")
    a = ap.parse_args()
    VERBOSE = a.verbose
    want = [s.strip() for s in a.only.split(",") if s.strip()]

    for f in ("preflight.py", "pubspec.py", "changelog_draft.py", "find_packages.py"):
        if not os.path.isfile(os.path.join(SCRIPTS, f)):
            print("致命：找不到 scripts/%s —— 请在 skill 目录下运行本测试。" % f)
            return 2

    tmp = tempfile.mkdtemp(prefix="fpp_tests_")
    print("=" * 74)
    print("flutter_pub_publish 回归测试     临时目录: %s" % tmp)
    print("=" * 74)
    try:
        for key, title, fn in GROUPS:
            if want and key not in want:
                continue
            print("\n[%s] %s" % (key, title))
            try:
                fn(os.path.join(tmp, key))
            except Exception as e:  # noqa
                import traceback
                check("%s 组本身崩溃" % key, False, traceback.format_exc())

        # PyYAML 差分测试单独跑（需要 PyYAML；没有就跳过）
        if not want or "pubspec" in want:
            print("\n[yamldiff] 内置解析器 vs PyYAML 差分")
            try:
                import yaml  # noqa
                p = subprocess.run([sys.executable, os.path.join(HERE, "test_yaml_diff.py")],
                                   capture_output=True, text=True, timeout=300)
                tail = (p.stdout or "").strip().splitlines()[-1:] or ["(无输出)"]
                check("与 PyYAML 逐字段一致", p.returncode == 0,
                      (p.stdout or "") + (p.stderr or ""))
                if p.returncode == 0 and VERBOSE:
                    print("      %s" % tail[0])
            except ImportError:
                skip("与 PyYAML 差分", "环境里没有 PyYAML")
    finally:
        if not a.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print("\n临时目录已保留：%s" % tmp)

    print("\n" + "=" * 74)
    print("通过 %d / 失败 %d / 跳过 %d" % (len(PASSED), len(FAILED), len(SKIPPED)))
    if FAILED:
        print("\n失败项：")
        for label, _ in FAILED:
            print("  ✗ %s" % label)
    if SKIPPED:
        print("\n跳过项（不等于通过）：")
        for label, why in SKIPPED:
            print("  - %s：%s" % (label, why))
    print("=" * 74)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
