#!/usr/bin/env python3
"""校验生成的 README 与源码/pubspec 对得上。

用法:
    python3 scan_api.py <pkg> --json /tmp/api.json      # 先跑扫描拿事实
    python3 verify_readme.py <pkg> --api /tmp/api.json
    python3 verify_readme.py <pkg> --api /tmp/api.json --api /tmp/被再导出的包.json

不传 README 文件名时，自动校验 pkg 根目录下所有 README*.md（一般就该这样用）。

它查的是「能机械查的」那部分：编造的类名、写错的方法名、和 pubspec 对不上的
版本与依赖、把 @internal/@protected 成员当公开用法写、指向不存在文件的 import。
✗ 必须修掉；⚠ 要看一眼确认是不是真问题。语气、结构好不好，机器判断不了，那部分靠人看。
"""

import argparse
import json
import os
import re
import sys
from collections import Counter

DART_FENCE = re.compile(r'```(?:dart|flutter)?\s*\n(.*?)```', re.S)
YAML_FENCE = re.compile(r'```(?:yaml|yml)\s*\n(.*?)```', re.S)
ANY_FENCE = re.compile(r'```[a-zA-Z]*\s*\n(.*?)```', re.S)

# 这些是 Flutter/Dart SDK 或极常见的名字，不参与"包内符号"检查
COMMON_OK = {
    'Widget', 'State', 'StatelessWidget', 'StatefulWidget', 'BuildContext', 'Key', 'GlobalKey',
    'MaterialApp', 'Scaffold', 'AppBar', 'Text', 'Column', 'Row', 'Center', 'Container',
    'ElevatedButton', 'TextButton', 'ListView', 'PageView', 'TabBarView', 'Navigator',
    'MaterialPageRoute', 'ChangeNotifier', 'ValueNotifier', 'Stream', 'StreamController',
    'Future', 'List', 'Map', 'Set', 'String', 'int', 'double', 'bool', 'void', 'Object',
    'Enum', 'Duration', 'Timer', 'Color', 'Colors', 'Theme', 'ThemeData', 'Icon', 'Icons',
    'SizedBox', 'Padding', 'EdgeInsets', 'Provider', 'ChangeNotifierProvider', 'Consumer',
    'Selector', 'RouteObserver', 'ModalRoute', 'PageRoute', 'Route', 'RouteAware',
    'WidgetsBinding', 'WidgetsBindingObserver', 'AppLifecycleState', 'TickerProvider',
    'AnimationController', 'SingleTickerProviderStateMixin', 'TabController', 'PageController',
    'DateTime', 'Exception', 'Error', 'Function', 'Iterable', 'Uri', 'RegExp', 'StringBuffer',
    'debugPrint', 'runApp', 'setState', 'print',
}


def load(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


def dominant_prefix(symbols):
    """找出包内符号的共同前缀（如 Fl / Gx / Aw），用来判断"这看起来像本包的类"。"""
    caps = [s for s in symbols if s[:1].isupper()]
    if len(caps) < 3:
        return None
    counter = Counter()
    for s in caps:
        for n in (2, 3, 4):
            if len(s) > n and s[n].isupper():
                counter[s[:n]] += 1
                break
    if not counter:
        return None
    prefix, hits = counter.most_common(1)[0]
    if hits >= max(3, int(len(caps) * 0.5)):
        return prefix
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pkg')
    ap.add_argument('readmes', nargs='*')
    ap.add_argument('--api', required=True, action='append',
                    help='scan_api.py --json 生成的文件。若本包再导出了别的包，'
                         '用第二个 --api 把那个包的 json 也传进来，否则它的符号会被当成"编的"。')
    args = ap.parse_args()

    pkg = os.path.abspath(args.pkg.rstrip('/'))
    api = json.load(open(args.api[0], encoding='utf-8'))
    extra = [json.load(open(p2, encoding='utf-8')) for p2 in args.api[1:]]
    symbols = set(api['all_symbols'])
    own_symbols = set(symbols)
    members = {}
    internal = {}
    for src in [api] + extra:
        for name, info in src['api'].items():
            symbols.add(name)
            members.setdefault(name, set()).update(set(info['members']) | set(info.get('enum_values') or []))
            internal.setdefault(name, set()).update(set(info.get('internal_members') or []))
    prefix = dominant_prefix(own_symbols)
    reexports = [e['uri'] for e in (api.get('external_exports') or [])
                 if e['uri'].startswith('package:')]

    files = args.readmes
    if not files:
        files = [os.path.join(pkg, f) for f in sorted(os.listdir(pkg))
                 if re.match(r'^README.*\.md$', f, re.I)]
    if not files:
        sys.exit('✗ 没找到任何 README*.md')

    errors = 0
    warns = 0
    per_file_sections = {}

    for path in files:
        if not os.path.isfile(path):
            print('✗ 文件不存在: %s' % path)
            errors += 1
            continue
        text = load(path)
        name = os.path.basename(path)
        print('=' * 74)
        print('校验 %s  (%d 行)' % (name, text.count('\n') + 1))
        print('=' * 74)

        sections = re.findall(r'^(#{2,3})\s+(.+)$', text, re.M)
        per_file_sections[name] = [s[1].strip() for s in sections]

        # ---- 0. 篇幅 ----
        n_types = len(api['all_symbols'])
        nlines = text.count('\n') + 1
        if n_types <= 8:
            lo, hi = 180, 380
        elif n_types <= 20:
            lo, hi = 300, 560
        else:
            lo, hi = 380, 720
        if nlines > hi * 1.15:
            print('✗ 篇幅 %d 行，超出 %d 个导出类型对应的上限 %d 行约 %d%%。'
                  % (nlines, n_types, hi, round((nlines / hi - 1) * 100)))
            print('   README 的目标是十分钟接入，不是覆盖一切。压缩办法：把展开的小节砍到 3–6 个'
                  '（其余进速查表）、每段示例控制在 15–40 行、删掉从 dartdoc 整段搬来的内容。')
            errors += 1
        elif nlines > hi:
            print('⚠ 篇幅 %d 行，略超建议上限 %d 行（%d 个导出类型）。' % (nlines, hi, n_types))
            warns += 1
        elif nlines < lo:
            print('⚠ 篇幅只有 %d 行，%d 个导出类型通常写不完（建议 %d–%d 行）。'
                  % (nlines, n_types, lo, hi))
            warns += 1
        else:
            print('✓ 篇幅 %d 行，落在 %d 个导出类型对应的 %d–%d 行区间内' % (nlines, n_types, lo, hi))

        # ---- 1. 结构 ----
        needed = {
            '安装 / install': r'(?i)(安装|install|getting started|快速开始|quick start)',
            '环境 / 版本要求': r'(?i)(环境要求|版本|requirement|compatib|支持的平台|platform|sdk)',
            '依赖说明': r'(?i)(依赖|dependenc)',
            'API / 用法': r'(?i)(api|用法|使用|usage|示例|example)',
            '注意事项 / 避坑': r'(?i)(注意|限制|坑|caveat|note|faq|troubleshoot)',
        }
        missing = [label for label, rx in needed.items() if not re.search(rx, text)]
        if missing:
            print('⚠ 可能缺少章节: %s' % '、'.join(missing))
            warns += 1
        else:
            print('✓ 结构：安装/版本/依赖/用法/注意事项 都能找到对应内容')

        # ---- 2. 版本与安装片段 ----
        pkg_name = api['name']
        ver = str(api.get('version') or '')
        install_hits = re.findall(r'%s\s*:\s*\^?([0-9][\w\.\+\-]*)' % re.escape(pkg_name), text)
        if ver:
            bad = [v for v in install_hits if not v.startswith(ver.split('+')[0].rsplit('.', 1)[0])
                   and v != ver]
            if install_hits and bad:
                print('✗ 安装片段里的版本 %s 与 pubspec 的 version: %s 对不上' % (', '.join(sorted(set(bad))), ver))
                errors += 1
            elif install_hits:
                print('✓ 安装版本号与 pubspec version (%s) 一致' % ver)
            else:
                print('⚠ 没找到 `%s: ^%s` 形式的安装片段，使用者不知道该写什么版本' % (pkg_name, ver))
                warns += 1

        env = api.get('environment') or {}
        for key, label in (('sdk', 'Dart SDK'), ('flutter', 'Flutter')):
            c = str(env.get(key) or '')
            if not c:
                continue
            nums = re.findall(r'\d+\.\d+(?:\.\d+)?', c)
            if nums and not any(n in text for n in nums):
                print('⚠ %s 约束 `%s` 的版本号在文中没出现，版本要求可能写得不准' % (label, c))
                warns += 1

        # ---- 3. 依赖章节 ----
        third = api.get('third_party') or []
        if third:
            miss = [d for d in third if d not in text]
            if miss:
                print('✗ 第三方依赖漏写: %s（pubspec 里有，README 里找不到）' % ', '.join(miss))
                errors += 1
            else:
                print('✓ %d 个第三方依赖都在 README 里出现: %s' % (len(third), ', '.join(third)))
            # 版本约束是否照抄
            for d in api['dependencies']:
                if d['name'] in DEP_SDK_NAMES or d['kind'] == 'sdk':
                    continue
                con = d['constraint']
                m = re.search(r'\d+\.\d+\.\d+', con)
                if m and d['name'] in text and m.group(0) not in text:
                    print('⚠ %s 的版本约束 `%s` 没在 README 中出现（依赖表里最好照抄约束）'
                          % (d['name'], con))
                    warns += 1
        else:
            if re.search(r'(?i)第三方依赖|third[- ]party', text) and not re.search(r'(?i)零第三方|no third|无第三方|不依赖任何第三方', text):
                print('⚠ 本包没有第三方依赖，但 README 有依赖章节——确认没有编出依赖来')
                warns += 1

        # 编造的依赖：yaml 代码块里出现的、pubspec 里没有的包名
        declared = {d['name'] for d in api['dependencies']} | {d['name'] for d in api['dev_dependencies']}
        declared.add(pkg_name)
        for block in YAML_FENCE.findall(text):
            for dep in re.findall(r'^\s{2,}([a-z_][a-z0-9_]*)\s*:\s*[\^>~\d]', block, re.M):
                if dep not in declared and dep not in DEP_SDK_NAMES:
                    print('⚠ yaml 示例里出现了 pubspec 中没有的包 `%s`（若是使用者自己要加的依赖，请在正文说明）' % dep)
                    warns += 1

        # ---- 4. 代码块里的包内符号 ----
        code = '\n'.join(DART_FENCE.findall(text)) or '\n'.join(ANY_FENCE.findall(text))
        if not code.strip():
            print('⚠ 没有 dart 代码块——"可直接运行的示例"这条要求没满足')
            warns += 1
        else:
            unknown = set()
            if prefix:
                # 前缀后必须紧跟大写字母，否则 `Flow`、`Float` 这类 SDK 名字会被误判
                for ident in set(re.findall(r'\b%s[A-Z][A-Za-z0-9_]*\b' % prefix, code)):
                    if ident not in symbols and ident not in COMMON_OK:
                        unknown.add(ident)
            if unknown and reexports:
                print('⚠ 示例里这些符号在已知导出面里找不到: %s' % ', '.join(sorted(unknown)))
                print('   本包再导出了 %s —— 如果它们来自那里就没问题。' % ', '.join(reexports))
                print('   要机器确认的话：对那个包也跑一次 scan_api.py --json，然后 --api 传两个文件。')
                warns += 1
            elif unknown:
                print('✗ 示例里用了本包不存在的符号（很可能是编的）: %s' % ', '.join(sorted(unknown)))
                print('   本包实际导出的符号: %s' % ', '.join(sorted(own_symbols)))
                errors += 1
            elif prefix:
                print('✓ 示例中所有 `%s*` 符号都能在导出面里找到' % prefix)

            # 成员调用检查
            bad_members = []
            internal_used = []
            for owner, member in re.findall(r'\b([A-Z][A-Za-z0-9_]*)\.([a-z_][A-Za-z0-9_]*)\b', code):
                if owner not in members:
                    continue
                if member in ('instance', 'of', 'values', 'name', 'index', 'toString', 'hashCode', 'runtimeType'):
                    continue
                if member not in members[owner]:
                    bad_members.append('%s.%s' % (owner, member))
                elif member in internal.get(owner, ()):
                    internal_used.append('%s.%s' % (owner, member))
            if bad_members:
                print('✗ 示例里调用了不存在的成员: %s' % ', '.join(sorted(set(bad_members))))
                errors += 1
            else:
                print('✓ 示例中对本包类型的成员调用都能对上签名')
            if internal_used:
                print('⚠ 示例里用到了标了 @internal/@protected/@visibleForTesting 的成员: %s' % ', '.join(sorted(set(internal_used))))
                print('   这些不是给使用者调的。@protected 的钩子请写成"在子类里覆写"，不要写成外部调用。')
                warns += 1

            # import 路径
            for uri in set(re.findall(r"""import\s+['"]package:([^'"]+)['"]""", code)):
                p, _, sub = uri.partition('/')
                if p == pkg_name:
                    if sub != pkg_name + '.dart' and not os.path.isfile(os.path.join(pkg, 'lib', sub)):
                        print('✗ 示例 import 了不存在的路径: package:%s' % uri)
                        errors += 1
                elif p not in declared and p not in DEP_SDK_NAMES:
                    print('⚠ 示例 import 了非依赖包 package:%s（使用者需要自己加依赖，正文里说明了吗）' % p)
                    warns += 1

        # ---- 5. 未导出的内部类被当公开 API 介绍 ----
        internal_files = set()
        for line in text.split('\n'):
            for f in re.findall(r'lib/src/[\w/]+\.dart', line):
                internal_files.add(f)
        not_exported = [f for f in internal_files if f not in api.get('export_chain', [])]
        if not_exported:
            print('⚠ 文中提到了未进入导出链的文件: %s（使用者 import 不到，别当公开 API 介绍）'
                  % ', '.join(sorted(not_exported)))
            warns += 1

    # ---- 6. 双语一致性 ----
    if len(per_file_sections) >= 2:
        names = list(per_file_sections)
        counts = {n: len(v) for n, v in per_file_sections.items()}
        print('=' * 74)
        print('双语一致性')
        print('=' * 74)
        for n in names:
            print('  %-16s %d 个二级/三级标题' % (n, counts[n]))
        lo, hi = min(counts.values()), max(counts.values())
        if hi - lo > 1:
            print('✗ 两份 README 的章节数差 %d，内容没对齐（应是同一份文档的两种语言，不是两份不同的文档）' % (hi - lo))
            errors += 1
        else:
            print('✓ 章节数一致')
        for n in names:
            body = load([p for p in files if os.path.basename(p) == n][0])
            others = [x for x in names if x != n]
            if not any(o in body for o in others):
                print('⚠ %s 里没有指向 %s 的语言切换链接' % (n, '/'.join(others)))
                warns += 1

    print()
    print('=' * 74)
    if errors:
        print('结果：%d 个必须修（✗），%d 个待确认（⚠）。修完再跑一次。' % (errors, warns))
        sys.exit(1)
    print('结果：0 个必须修，%d 个待确认（⚠）。机械校验通过。' % warns)
    print('注意：结构是否清晰、示例是否真的可运行、说明是否讲清楚了——这些机器判断不了，交付前自己再读一遍。')


DEP_SDK_NAMES = {'flutter', 'flutter_test', 'flutter_localizations', 'flutter_driver',
                 'integration_test', 'flutter_web_plugins', 'sky_engine'}

if __name__ == '__main__':
    main()
