#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试用的 fixture：假 package、假 monorepo、假 SDK。

全部造在临时目录里，不碰任何真实工程。
"""
import os
import shutil
import stat
import subprocess

# --------------------------------------------------------------------------
# 假 SDK
#
# 沙箱/CI 里通常没有 Dart/Flutter SDK，但 check_format 和 check_analyze 的分支
# 逻辑完全由「退出码 + 标准输出」决定，这两样可以精确伪造。用假 SDK 才能稳定地
# 覆盖到"命令不存在""源码语法错误""SDK 装坏了"这些真实但难以按需复现的情形。
#
# flutter 的 stub 刻意复刻了现代 Flutter 的真实行为：**没有 format 子命令**，
# 且 analyze 不认 --format=machine。preflight 一旦退回去用 flutter 跑这两件事，
# 测试就会失败——这正是 2026-09 那个 bug 的形状。

DART_STUB = r'''#!/bin/bash
[ -n "$FAKE_LOG" ] && echo "dart $*" >> "$FAKE_LOG"
sub="$1"; shift
case "$sub" in
format)
  case "$FAKE_MODE" in
    unformatted)
      echo "Changed lib/src/client.dart"
      echo "Changed lib/src/model.dart"
      echo "Formatted 12 files (2 changed) in 0.33 seconds."
      exit 1 ;;
    fmt_syntax_error)
      echo "Could not format because the source could not be parsed:" >&2
      echo "line 42, column 3 of lib/src/broken.dart: Expected to find ';'." >&2
      exit 65 ;;
    *) echo "Formatted 12 files (0 changed) in 0.31 seconds."; exit 0 ;;
  esac ;;
analyze)
  case "$FAKE_MODE" in
    analyze_issues)
      echo "INFO|LINT|prefer_const_constructors|$PWD/lib/a.dart|10|5|3|Use const."
      echo "WARNING|STATIC_WARNING|UNUSED_IMPORT|$PWD/lib/b.dart|2|1|20|Unused import."
      exit 1 ;;
    analyze_errors)
      echo "ERROR|COMPILE_TIME_ERROR|UNDEFINED_METHOD|$PWD/lib/a.dart|7|9|4|Undefined method."
      exit 2 ;;
    analyze_broken)
      echo "Could not find a file named \"pubspec.yaml\"" >&2
      exit 64 ;;
    *) exit 0 ;;
  esac ;;
pub)
  case "$1|$FAKE_MODE" in
    "publish|dryrun_ok")
      echo "Publishing $FAKE_PKG_NAME $FAKE_PKG_VERSION to https://pub.dev:"
      echo "Total compressed archive size: 41 KB."
      echo "Package has 0 warnings."
      exit 0 ;;
    "publish|dryrun_identity_mismatch")
      echo "Publishing wrong_name 9.9.9 to https://pub.dev:"
      echo "Package has 0 warnings."
      exit 0 ;;
    "publish|dryrun_warn")
      echo "Publishing $FAKE_PKG_NAME $FAKE_PKG_VERSION to https://pub.dev:"
      echo "Package validation found the following potential issue:" >&2
      echo "* Package has no example." >&2
      echo "Package has 1 warning." >&2
      exit 65 ;;
    *) exit 0 ;;
  esac ;;
test) echo "All tests passed!"; exit 0 ;;
*) echo "Unknown dart command: $sub" >&2; exit 64 ;;
esac
'''

FLUTTER_STUB = r'''#!/bin/bash
[ -n "$FAKE_LOG" ] && echo "flutter $*" >> "$FAKE_LOG"
sub="$1"; shift
case "$sub" in
format)
  # 现代 Flutter 没有这个子命令。preflight 若退回来用它，就该在这里炸掉。
  echo "Could not find a command named \"format\"." >&2
  exit 64 ;;
analyze)
  for a in "$@"; do
    if [ "$a" = "--format=machine" ]; then
      echo "Could not find an option named \"--format\"." >&2
      exit 64
    fi
  done
  echo "No issues found!"; exit 0 ;;
pub) exit 0 ;;
test) echo "All tests passed!"; exit 0 ;;
*) echo "Unknown flutter command: $sub" >&2; exit 64 ;;
esac
'''


def make_fake_sdk(root, with_dart=True, with_flutter=True):
    """造假 SDK，返回 bin 目录。"""
    b = os.path.join(root, "fakesdk", "bin")
    shutil.rmtree(os.path.dirname(b), ignore_errors=True)
    os.makedirs(b)
    if with_dart:
        _write_exe(os.path.join(b, "dart"), DART_STUB)
    if with_flutter:
        _write_exe(os.path.join(b, "flutter"), FLUTTER_STUB)
    return b


def _write_exe(path, body):
    with open(path, "w") as f:
        f.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# --------------------------------------------------------------------------
# 假 package

GOOD_PUBSPEC = """name: {name}
description: {desc}
version: {version}
repository: https://github.com/example/{name}
environment:
  sdk: ^3.5.0
{flutter_env}dependencies:
{deps}"""

LONG_DESC = ("A Flutter state lifecycle helper that binds controller disposal to "
             "widget lifetime, preventing leaked timers and stream subscriptions.")


def make_package(path, name, version="1.0.0", flutter=True, desc=LONG_DESC,
                 path_deps=None, complete=True, changelog_version=None,
                 publish_to=None):
    """造一个（默认）体检全过的包。complete=False 则缺 README/LICENSE/example。"""
    os.makedirs(os.path.join(path, "lib"), exist_ok=True)
    deps = "  flutter:\n    sdk: flutter\n" if flutter else "  meta: ^1.9.0\n"
    for dn, dp in (path_deps or {}).items():
        deps += "  %s:\n    path: %s\n" % (dn, dp)
    body = GOOD_PUBSPEC.format(
        name=name, desc=desc, version=version, deps=deps,
        flutter_env='  flutter: ">=3.24.0"\n' if flutter else "")
    if publish_to:
        body += "publish_to: %s\n" % publish_to
    _w(os.path.join(path, "pubspec.yaml"), body)
    _w(os.path.join(path, "lib", "%s.dart" % name), "class %s {}\n" % name.title())
    cv = changelog_version or version
    _w(os.path.join(path, "CHANGELOG.md"),
       "## %s\n\n* 新增 autoDispose()，widget 销毁时自动释放注册的 controller。\n" % cv)
    if complete:
        _w(os.path.join(path, "README.md"),
           "# %s\n\n" % name + "Real documentation describing the public API. " * 10)
        _w(os.path.join(path, "LICENSE"),
           "MIT License\n\n" + "Permission is hereby granted, free of charge. " * 5)
        os.makedirs(os.path.join(path, "example", "lib"), exist_ok=True)
        _w(os.path.join(path, "example", "lib", "main.dart"), "void main() {}\n")
    return path


def make_app(path, name):
    """应用工程：有 lib/main.dart，没有导出入口。不该出现在候选列表里。"""
    os.makedirs(os.path.join(path, "lib"), exist_ok=True)
    _w(os.path.join(path, "pubspec.yaml"),
       "name: %s\ndescription: An internal application that is never published to pub.dev.\n"
       "version: 0.0.1+12\nenvironment:\n  sdk: ^3.5.0\n"
       "dependencies:\n  flutter:\n    sdk: flutter\n" % name)
    _w(os.path.join(path, "lib", "main.dart"), "void main() {}\n")
    return path


def make_monorepo(root, with_git=True):
    """packages/{fl_core,fl_net,fl_ui} + apps/demo + fl_ui/example。

    依赖链 fl_core ← fl_net ← fl_ui，用来验发布顺序；apps/demo 与 example
    用来验"不可发布"的识别；git 部分用来验检查范围有没有漏到隔壁包。
    """
    os.makedirs(root, exist_ok=True)
    _w(os.path.join(root, "melos.yaml"), "name: test_mono\npackages:\n  - packages/**\n")
    p = lambda *a: os.path.join(root, *a)
    make_package(p("packages", "fl_core"), "fl_core", "1.2.0", flutter=False)
    make_package(p("packages", "fl_net"), "fl_net", "0.4.1", flutter=False,
                 path_deps={"fl_core": "../fl_core"})
    make_package(p("packages", "fl_ui"), "fl_ui", "2.0.0", flutter=True,
                 path_deps={"fl_net": "../fl_net"})
    make_app(p("apps", "demo"), "demo_app")
    make_package(p("packages", "fl_ui", "example"), "fl_ui_example", "1.0.0",
                 complete=False, publish_to="none")
    if with_git and shutil.which("git"):
        _git(root, ["init", "-q"])
        _git(root, ["config", "user.email", "t@example.com"])
        _git(root, ["config", "user.name", "T"])
        _git(root, ["add", "-A"])
        _git(root, ["commit", "-qm", "init"])
        _git(root, ["tag", "fl_core-v1.1.0"])
        # 属于别的包的裸 tag：子目录包不该拿它给自己定罪
        _git(root, ["tag", "v1.2.0"])
        _git(root, ["tag", "fl_net-v0.4.1"])
    return root


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _git(cwd, args):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)


def git_commit(root, msg):
    _git(root, ["add", "-A"])
    _git(root, ["commit", "-qm", msg])


def touch(path, line):
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
