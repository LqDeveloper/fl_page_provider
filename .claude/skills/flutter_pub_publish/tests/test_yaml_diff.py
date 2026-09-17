#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内置严格解析器 vs PyYAML 差分测试。

自检只能证明解析器符合"我写下的期望"。真正要回答的问题是：
它对真实 pubspec 的理解，和公认正确的 YAML 实现是否一致。
所以这里拿 PyYAML 当基准做逐字段比对，外加随机组合生成的 pubspec。
"""
import os
import random
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "scripts"))
import pubspec as P  # noqa


def norm(v):
    return P._norm(v)


def check(label, text, expect_reject=False):
    """返回 (状态, 说明)。状态 ∈ ok / mismatch / wrongly_rejected / wrongly_accepted / yaml_bad"""
    try:
        y = yaml.safe_load(text)
        y_ok = isinstance(y, dict)
    except Exception as e:
        y, y_ok, y_err = None, False, e

    try:
        s = P.parse_strict(text)
        s_ok, s_err = True, None
    except P.PubspecParseError as e:
        s, s_ok, s_err = None, False, e
    except Exception as e:
        return "crash", "内置解析器崩溃（不是 PubspecParseError）: %r" % e

    if expect_reject:
        if s_ok:
            return "wrongly_accepted", "本该拒绝却接受了"
        return "ok", ""

    if not y_ok:
        return "yaml_bad", "PyYAML 自己也读不成映射，跳过"
    if not s_ok:
        return "wrongly_rejected", "PyYAML 能读，内置拒绝了：%s" % s_err
    if norm(y) != norm(s):
        return "mismatch", "PyYAML=%r\n    内置  =%r" % (norm(y), norm(s))
    return "ok", ""


# ---------------------------------------------------------------- 真实形态语料

REAL = {
"provider 风格": """
name: provider
description: A wrapper around InheritedWidget to make them easier to use and more reusable.
version: 6.1.2
repository: https://github.com/rrousselGit/provider
issue_tracker: https://github.com/rrousselGit/provider/issues

environment:
  sdk: ">=3.0.0 <4.0.0"
  flutter: ">=3.0.0"

dependencies:
  collection: ^1.15.0
  flutter:
    sdk: flutter
  nested: ^1.0.0

dev_dependencies:
  flutter_test:
    sdk: flutter
  mockito: ^5.0.0
""",

"插件包带全平台": """
name: camera_plus
description: >-
  A Flutter plugin for controlling the camera on Android, iOS, macOS and web,
  with support for still capture and video recording.
version: 0.10.5+9
repository: https://github.com/x/camera_plus/tree/main/packages/camera_plus
environment:
  sdk: ^3.4.0
  flutter: ">=3.22.0"
dependencies:
  flutter:
    sdk: flutter
  camera_platform_interface: ^2.7.0
  stream_transform: ^2.1.0
flutter:
  plugin:
    platforms:
      android:
        package: io.flutter.plugins.camera
        pluginClass: CameraPlugin
      ios:
        pluginClass: CameraPlugin
      macos:
        pluginClass: CameraPlugin
        sharedDarwinSource: true
      web:
        pluginClass: CameraPlugin
        fileName: camera_web.dart
""",

"带 assets 与 fonts": """
name: design_kit
description: Shared design tokens, icon set and font faces for our Flutter apps.
version: 2.3.1
homepage: https://example.com
environment:
  sdk: ^3.5.0
flutter:
  uses-material-design: true
  assets:
    - assets/icons/
    - assets/images/logo.png
    - path: assets/themed/
      flavors:
        - dark
  fonts:
    - family: Inter
      fonts:
        - asset: fonts/Inter-Regular.ttf
        - asset: fonts/Inter-Bold.ttf
          weight: 700
        - asset: fonts/Inter-Italic.ttf
          style: italic
    - family: JetBrainsMono
      fonts:
        - asset: fonts/JBMono.ttf
""",

"dependency_overrides + path": """
name: app_shell
description: Internal application shell, not published.
version: 0.0.1
publish_to: 'none'
environment:
  sdk: ^3.5.0
dependencies:
  flutter:
    sdk: flutter
  fl_core:
    path: ../fl_core
  fl_net:
    git:
      url: https://github.com/x/fl_net.git
      ref: v1.2.0
      path: packages/fl_net
dependency_overrides:
  meta: ^1.10.0
""",

"hosted 依赖": """
name: private_pkg
version: 1.0.0
description: Uses a private pub server for one of its dependencies, otherwise normal.
environment:
  sdk: ^3.5.0
dependencies:
  internal_sdk:
    hosted:
      name: internal_sdk
      url: https://pub.internal.example.com
    version: ^2.0.0
""",

"字面块描述 + 尾注释": """
name: block_desc          # 包名
version: 3.0.0-dev.2      # 预发布
description: |
  First line of the description.
  Second line, kept verbatim.

  Fourth line after a blank one.
repository: https://github.com/x/y
environment:
  sdk: ^3.5.0
""",

"折叠块 + chomp": """
name: folded
version: 1.0.0
description: >-
  This description is folded onto one line and the trailing newline
  is stripped because of the minus chomping indicator.
environment:
  sdk: ^3.5.0
""",

"executables + platforms": """
name: cli_tool
version: 4.1.0
description: A command line tool for generating boilerplate, published as a pure Dart package.
environment:
  sdk: ^3.5.0
executables:
  gen: generator
  gen_all:
platforms:
  linux:
  macos:
  windows:
dependencies:
  args: ^2.4.0
""",

"topics + screenshots + funding": """
name: rich_meta
version: 1.1.0
description: Package exercising the newer pubspec metadata fields that pub.dev renders.
repository: https://github.com/x/y
topics:
  - ui
  - animation
screenshots:
  - description: The main screen
    path: doc/main.png
  - description: Settings
    path: doc/settings.png
funding:
  - https://github.com/sponsors/x
false_secrets:
  - /test/fixtures/*.pem
environment:
  sdk: ^3.5.0
""",

"空 dependencies 段": """
name: no_deps
version: 1.0.0
description: A package with an empty dependencies section, which is legal YAML and legal pub.
environment:
  sdk: ^3.5.0
dependencies:
dev_dependencies:
  test: ^1.24.0
""",

"引号里的特殊字符": """
name: quoted
version: 1.0.0
description: "Supports #hashtags, a: colon, and 'single quotes' inside a double-quoted scalar."
repository: "https://github.com/x/y"
environment:
  sdk: ">=3.0.0 <4.0.0"
""",

"CRLF 换行": "name: crlf\r\nversion: 1.0.0\r\ndescription: Windows line endings should not change how this file is understood.\r\nenvironment:\r\n  sdk: ^3.5.0\r\n",

"四空格缩进": """
name: four_space
version: 1.0.0
description: This package indents with four spaces instead of the conventional two.
environment:
    sdk: ^3.5.0
dependencies:
    flutter:
        sdk: flutter
    provider: ^6.0.0
""",

"以 --- 开头": """---
name: doc_marker
version: 1.0.0
description: This pubspec starts with an explicit YAML document start marker.
environment:
  sdk: ^3.5.0
""",
}

# 这些必须被内置解析器拒绝（PyYAML 能读，但超出内置解析器的担保范围）
MUST_REJECT = {
"锚点别名": """
name: anchors
version: 1.0.0
common: &common
  sdk: ^3.5.0
environment: *common
""",
"合并键": """
name: merge
version: 1.0.0
base: &b
  sdk: ^3.5.0
environment:
  <<: *b
""",
"标签": "name: tagged\nversion: 1.0.0\nx: !!int 5\n",
"制表符缩进": "name: tabs\nversion: 1.0.0\ndependencies:\n\tprovider: ^6.0.0\n",
"多文档": "---\nname: a\nversion: 1.0.0\n---\nname: b\nversion: 2.0.0\n",
}


def fuzz(n=400, seed=7):
    """随机拼装 pubspec 片段，看两个解析器会不会分道扬镳。"""
    rnd = random.Random(seed)
    frag = [
        "name: fz_{i}\n",
        "version: {maj}.{min}.{pat}\n",
        "description: Fuzz case number {i} exercising assorted pubspec shapes and spacing.\n",
        "repository: https://github.com/x/fz_{i}\n",
        "homepage: https://example.com/{i}\n",
        "environment:\n  sdk: ^3.{min}.0\n",
        "environment:\n  sdk: \">=3.0.0 <4.0.0\"\n  flutter: \">=3.19.0\"\n",
        "dependencies:\n  flutter:\n    sdk: flutter\n  provider: ^6.{min}.0\n",
        "dependencies:\n  http: \">=0.13.0 <2.0.0\"\n  meta: '^1.9.0'\n",
        "dependencies:\n  local:\n    path: ../local_{i}\n",
        "dev_dependencies:\n  test: ^1.24.0\n",
        "flutter:\n  uses-material-design: true\n  assets:\n    - assets/a{i}.png\n    - assets/b{i}.png\n",
        "flutter:\n  fonts:\n    - family: F{i}\n      fonts:\n        - asset: f/{i}.ttf\n          weight: {w}\n",
        "topics:\n  - t{i}\n  - ui\n",
        "description: >-\n  Folded description for case {i} that spans\n  two source lines.\n",
        "description: |\n  Literal line one for {i}.\n  Literal line two.\n",
        "publish_to: none\n",
        "executables:\n  tool{i}: main\n",
        "platforms:\n  android:\n  ios:\n",
        "screenshots:\n  - description: Shot {i}\n    path: doc/{i}.png\n",
        "# a standalone comment line\n",
        "\n",
    ]
    bad = []
    for i in range(n):
        k = rnd.randint(3, 9)
        picked = ["name: fz_{i}\n", "version: {maj}.{min}.{pat}\n"] + \
                 [rnd.choice(frag) for _ in range(k)]
        seen = set()
        body = []
        for f in picked:
            key = f.split(":")[0].strip()
            if key and not key.startswith("#") and key in seen:
                continue
            if key and not key.startswith("#"):
                seen.add(key)
            body.append(f.format(i=i, maj=rnd.randint(0, 3), min=rnd.randint(0, 9),
                                 pat=rnd.randint(0, 9), w=rnd.choice([400, 700])))
        text = "".join(body)
        st, msg = check("fuzz-%d" % i, text)
        if st not in ("ok", "yaml_bad"):
            bad.append((i, st, msg, text))
    return bad


def main():
    print("=" * 74)
    print("差分测试：内置严格解析器 vs PyYAML %s" % yaml.__version__)
    print("=" * 74)
    fails = 0

    print("\n[A] 真实形态语料（内置必须与 PyYAML 逐字段一致）")
    for label, text in REAL.items():
        st, msg = check(label, text)
        mark = "✓" if st == "ok" else "✗"
        print("  %s %s%s" % (mark, label, "" if st == "ok" else "  → %s: %s" % (st, msg)))
        if st != "ok":
            fails += 1

    print("\n[B] 必须被拒绝的语法（不能静默尽力而为）")
    for label, text in MUST_REJECT.items():
        st, msg = check(label, text, expect_reject=True)
        mark = "✓" if st == "ok" else "✗"
        print("  %s %s%s" % (mark, label, "" if st == "ok" else "  → %s" % msg))
        if st != "ok":
            fails += 1

    print("\n[C] 随机拼装 400 例")
    bad = fuzz()
    if not bad:
        print("  ✓ 400/400 与 PyYAML 一致")
    else:
        for i, st, msg, text in bad[:6]:
            print("  ✗ fuzz-%d %s: %s\n---\n%s---" % (i, st, msg, text))
        print("  共 %d 例不一致" % len(bad))
        fails += len(bad)

    print("\n[D] 内置自检语料本身也过一遍 PyYAML")
    for label, text, expected in P.CORPUS:
        try:
            y = yaml.safe_load(text)
        except Exception as e:
            print("  ✗ %s: PyYAML 读不了: %s" % (label, e)); fails += 1; continue
        if norm(y) != norm(expected):
            print("  ✗ %s: 我写的期望值和 PyYAML 不一致\n     期望 %r\n     PyYAML %r"
                  % (label, norm(expected), norm(y)))
            fails += 1
    if fails == 0:
        print("  ✓ %d 条期望值全部与 PyYAML 相符" % len(P.CORPUS))

    print("\n" + "=" * 74)
    print("差分测试：%s（%d 处不一致）" % ("通过" if fails == 0 else "未通过", fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
