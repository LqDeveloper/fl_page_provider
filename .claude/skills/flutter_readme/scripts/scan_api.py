#!/usr/bin/env python3
"""扫描一个 Flutter package，打出写 README 所需的全部事实。

用法:
    python3 scan_api.py <pkg路径> [--json <输出路径>] [--full-doc]

它不做判断，只搬事实：pubspec 元信息、环境约束、平台判定依据、依赖分类、
导出链、公开 API 签名（含 dartdoc 首段与 @protected/@internal 等标注）、
example 里的真实用法。所有条目都带 `文件:行号`，方便回源核对。
"""

import argparse
import json
import os
import re
import sys
from collections import OrderedDict

# ---------------------------------------------------------------- 基础工具


def read(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return ''


def rel(path, root):
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


# ---------------------------------------------------------------- pubspec

DEP_SDK = {'flutter', 'flutter_test', 'flutter_localizations', 'flutter_driver',
           'integration_test', 'flutter_web_plugins', 'sky_engine'}


def _strip_comment(line):
    """去掉行尾注释，但不碰引号里的 #。"""
    out = []
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == '\\' and quote == '"' and i + 1 < len(line):
                i += 1
                out.append(line[i])
            elif ch == quote:
                quote = None
        else:
            if ch in '"\'':
                quote = ch
                out.append(ch)
            elif ch == '#' and (i == 0 or line[i - 1] in ' \t'):
                break
            else:
                out.append(ch)
        i += 1
    return ''.join(out).rstrip()


def _scalar(text):
    """把一个标量文本转成值。数字一律保留成字符串——`version: 1.0` 被转成
    float 会让"安装片段版本号与 pubspec 一致"这类校验平白出错。"""
    v = text.strip()
    if v == '':
        return None
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        inner = v[1:-1]
        return inner.replace('\\"', '"').replace('\\\\', '\\') if v[0] == '"' else inner
    if v.startswith('[') and v.endswith(']'):
        return [_scalar(x) for x in v[1:-1].split(',') if x.strip()]
    if v.startswith('{') and v.endswith('}'):
        d = {}
        for part in v[1:-1].split(','):
            k, sep, val = part.partition(':')
            if sep:
                d[k.strip()] = _scalar(val)
        return d
    if v in ('null', '~'):
        return None
    if v == 'true':
        return True
    if v == 'false':
        return False
    return v


def _tokenize_yaml(raw):
    """按行切成 {indent, text, block} —— block 是折叠/字面块标量已经合好的值。"""
    tokens = []
    src = raw.replace('\r\n', '\n').split('\n')
    i = 0
    while i < len(src):
        line = _strip_comment(src[i])
        if not line.strip():
            i += 1
            continue
        indent = len(line) - len(line.lstrip(' '))
        text = line.strip()
        m = re.match(r'^([^:]+):\s*([|>])([-+]?)\s*$', text)
        if m:
            key = m.group(1).strip()
            style = m.group(2)
            i += 1
            buf = []
            while i < len(src):
                nxt = src[i]
                if not nxt.strip():
                    buf.append('')
                    i += 1
                    continue
                if len(nxt) - len(nxt.lstrip(' ')) <= indent:
                    break
                buf.append(nxt.strip())
                i += 1
            while buf and buf[-1] == '':
                buf.pop()
            value = '\n'.join(buf) if style == '|' else ' '.join(x for x in buf if x)
            tokens.append({'indent': indent, 'text': key + ':', 'block': value})
            continue
        tokens.append({'indent': indent, 'text': text, 'block': None})
        i += 1
    return tokens


def _parse_yaml(tokens, i, indent):
    """递归解析同一缩进层级，返回 (值, 下一个下标)。"""
    if i < len(tokens) and (tokens[i]['text'] == '-' or tokens[i]['text'].startswith('- ')):
        items = []
        while i < len(tokens) and tokens[i]['indent'] == indent and \
                (tokens[i]['text'] == '-' or tokens[i]['text'].startswith('- ')):
            body = tokens[i]['text'][1:].strip()
            i += 1
            if body and ':' in body and body[0] not in '"\'[{':
                k, _sep, v = body.partition(':')
                items.append({k.strip(): _scalar(v)})
            else:
                items.append(_scalar(body))
        return items, i

    mapping = OrderedDict()
    while i < len(tokens) and tokens[i]['indent'] == indent:
        tok = tokens[i]
        if tok['text'].startswith('- '):
            break
        key, sep, val = tok['text'].partition(':')
        if not sep:  # 解析不了的行，跳过但记下来
            UNPARSED.append(tok['text'])
            i += 1
            continue
        key = key.strip().strip('"\'')
        if tok['block'] is not None:
            mapping[key] = tok['block']
            i += 1
            continue
        i += 1
        if val.strip():
            mapping[key] = _scalar(val)
            continue
        if i < len(tokens) and tokens[i]['indent'] > indent:
            mapping[key], i = _parse_yaml(tokens, i, tokens[i]['indent'])
        elif i < len(tokens) and tokens[i]['indent'] == indent and \
                (tokens[i]['text'] == '-' or tokens[i]['text'].startswith('- ')):
            # 列表项与键同缩进，也是合法 YAML
            mapping[key], i = _parse_yaml(tokens, i, indent)
        else:
            mapping[key] = None
    return mapping, i


UNPARSED = []


def load_pubspec(pkg):
    """解析 pubspec.yaml。

    这里刻意不用 PyYAML：pubspec 只用到 YAML 的一小块子集，自带解析器意味着
    在任何机器上行为都一样，不会因为某台机器少装一个库就悄悄退化成空结果；
    顺带还能让 `version: 1.0` 保持字符串而不是被转成 float。
    """
    path = os.path.join(pkg, 'pubspec.yaml')
    raw = read(path)
    del UNPARSED[:]
    tokens = _tokenize_yaml(raw)
    data, _ = _parse_yaml(tokens, 0, tokens[0]['indent'] if tokens else 0)
    if not isinstance(data, dict) or 'name' not in data:
        sys.exit('✗ 解析 %s 失败：没读到 name 字段。\n'
                 '  这个 pubspec 可能用了不常见的 YAML 写法。请把文件内容贴出来，'
                 '或者先手工确认它是有效的 pubspec。' % path)
    return raw, data


def dep_entries(section):
    """把 dependencies 段落转成 [(名字, 约束描述, 类型)]。"""
    out = []
    if not isinstance(section, dict):
        return out
    for name, spec in section.items():
        if isinstance(spec, str):
            out.append((name, spec, 'hosted'))
        elif isinstance(spec, dict):
            if 'sdk' in spec:
                out.append((name, 'sdk: %s' % spec['sdk'], 'sdk'))
            elif 'path' in spec:
                out.append((name, 'path: %s' % spec['path'], 'path'))
            elif 'git' in spec:
                out.append((name, 'git: %s' % json.dumps(spec['git'], ensure_ascii=False), 'git'))
            elif 'hosted' in spec:
                out.append((name, 'hosted %s  version: %s' % (spec.get('hosted'), spec.get('version', '(any)')), 'hosted'))
            else:
                out.append((name, json.dumps(spec, ensure_ascii=False), 'hosted'))
        elif spec is None:
            out.append((name, '(any)', 'hosted'))
        else:
            out.append((name, str(spec), 'hosted'))
    return out


# ---------------------------------------------------------------- Dart 预处理

_STR_RE = re.compile(r"""r?'''|r?\"\"\"|r?'|r?\"""")


def strip_code(lines):
    """返回与 lines 等长的列表：每行去掉注释和字符串字面量后的代码。

    用于安全地数花括号 / 找声明关键字，不会被注释和字符串里的符号骗到。
    """
    out = []
    in_block = False
    in_multi = None  # ''' 或 """
    for line in lines:
        buf = []
        i = 0
        n = len(line)
        while i < n:
            if in_block:
                idx = line.find('*/', i)
                if idx < 0:
                    i = n
                else:
                    in_block = False
                    i = idx + 2
                continue
            if in_multi:
                idx = line.find(in_multi, i)
                if idx < 0:
                    i = n
                else:
                    i = idx + 3
                    in_multi = None
                continue
            ch = line[i]
            if ch == '/' and i + 1 < n and line[i + 1] == '/':
                break
            if ch == '/' and i + 1 < n and line[i + 1] == '*':
                in_block = True
                i += 2
                continue
            if ch in '\'"':
                triple = line[i:i + 3]
                if triple in ("'''", '"""'):
                    in_multi = triple
                    i += 3
                    continue
                quote = ch
                i += 1
                while i < n:
                    if line[i] == '\\':
                        i += 2
                        continue
                    if line[i] == quote:
                        i += 1
                        break
                    i += 1
                buf.append('""')
                continue
            buf.append(ch)
            i += 1
        out.append(''.join(buf))
    return out


def depth_map(code_lines):
    """每行开始处的花括号深度。"""
    depths = []
    d = 0
    for line in code_lines:
        depths.append(d)
        d += line.count('{') - line.count('}')
    return depths


# ---------------------------------------------------------------- Dart 声明解析

TOP_DECL_RE = re.compile(
    r'^\s*(?:abstract\s+|base\s+|final\s+|sealed\s+|interface\s+|mixin\s+)*'
    r'(class|mixin|enum|extension(?:\s+type)?|typedef)\s+(\w+)'
)
TOP_VAR_FUNC_RE = re.compile(r'^\s*(?:external\s+)?(?:const|final|late)?\s*[\w<>,\s\?\[\]]*?\b(\w+)\s*(\(|=)')
ANNOTATION_RE = re.compile(r'^\s*@(\w+)')
DOC_RE = re.compile(r'^\s*///\s?(.*)$')

MEMBER_SKIP = {'if', 'for', 'while', 'switch', 'return', 'assert', 'try', 'catch',
               'else', 'do', 'case', 'default', 'break', 'continue', 'yield', 'await'}


def collect_doc_and_annotations(lines, idx):
    """向上收集紧邻的 dartdoc 与注解。"""
    doc = []
    anns = []
    i = idx - 1
    while i >= 0:
        line = lines[i]
        m = DOC_RE.match(line)
        if m:
            doc.append(m.group(1).rstrip())
            i -= 1
            continue
        a = ANNOTATION_RE.match(line)
        if a:
            anns.append(line.strip())
            i -= 1
            continue
        if line.strip() == '' and (doc or anns):
            i -= 1
            continue
        break
    doc.reverse()
    anns.reverse()
    return doc, anns


def signature_at(lines, code_lines, idx):
    """从第 idx 行起拼出声明签名（最多 14 行）。

    终止符是 `{` / `;` / `=>`，但只在圆括号外才算数——Dart 的命名参数
    `({required this.x})` 里也有花括号，按字面找第一个 `{` 会把签名截断。
    """
    parts = []
    paren = 0
    for j in range(idx, min(idx + 14, len(lines))):
        code = code_lines[j]
        cut = None
        k = 0
        while k < len(code):
            ch = code[k]
            if ch == '(':
                paren += 1
            elif ch == ')':
                paren -= 1
            elif paren <= 0:
                if ch in '{;':
                    cut = k
                    break
                if code.startswith('=>', k):
                    cut = k
                    break
            k += 1
        parts.append(lines[j][:cut] if cut is not None else lines[j])
        end = j
        if cut is not None:
            break
    sig = ' '.join(p.strip() for p in parts)
    sig = re.sub(r'\s+', ' ', sig).strip().rstrip(',')
    return sig, end


def parse_members(lines, code_lines, depths, start, end, owner):
    """解析类/mixin/extension 体内 depth==1 的成员声明。"""
    members = []
    base_depth = depths[start]
    for i in range(start + 1, end):
        if depths[i] != base_depth + 1:
            continue
        code = code_lines[i]
        stripped = code.strip()
        if not stripped or stripped.startswith('}'):
            continue
        first = re.match(r'^\s*(\w+)', code)
        if first and first.group(1) in MEMBER_SKIP:
            continue
        # 成员声明的形状：以 ( 结尾的方法 / get / set / 字段
        m = re.search(r'\b(\w+)\s*(?:<[^<>]*>)?\s*\(', code)
        is_field = False
        name = None
        if m and '=' not in code.split('(')[0]:
            name = m.group(1)
        else:
            fm = re.match(r'^\s*(?:static\s+|final\s+|const\s+|late\s+|covariant\s+)*'
                          r'[\w<>,\s\?\[\]\.]+?\b(\w+)\s*(?:=|;)', code)
            if fm:
                name = fm.group(1)
                is_field = True
        if not name:
            gm = re.search(r'\b(?:get|set)\s+(\w+)', code)
            if gm:
                name = gm.group(1)
            else:
                continue
        if name in MEMBER_SKIP:
            continue
        doc, anns = collect_doc_and_annotations(lines, i)
        sig, _end = signature_at(lines, code_lines, i)
        head = code.split('(')[0]
        if re.match(r'^\s*(?:static\s+|covariant\s+)*(?:final|const|late)\b', head) and code.rstrip().endswith(';'):
            is_field = True
        if is_field:
            sig = lines[i].strip().rstrip(';')
        kind = 'field'
        if re.search(r'\bget\s+%s\b' % re.escape(name), code):
            kind = 'getter'
        elif re.search(r'\bset\s+%s\b' % re.escape(name), code):
            kind = 'setter'
        elif m and not is_field:
            kind = 'ctor' if name == owner or sig.strip().startswith(owner + '.') or re.match(r'^\s*(const\s+)?%s\s*[\(\.]' % re.escape(owner), code) else 'method'
        members.append({
            'name': name,
            'kind': kind,
            'line': i + 1,
            'signature': sig,
            'doc': doc,
            'annotations': anns,
            'public': not name.startswith('_'),
        })
    return members


def parse_dart(path, root):
    text = read(path)
    lines = text.split('\n')
    code_lines = strip_code(lines)
    depths = depth_map(code_lines)
    decls = []
    exports = []
    imports = []
    parts = []

    skip_until = -1
    for i, code in enumerate(code_lines):
        if i <= skip_until:
            continue
        s = code.strip()
        if s.startswith('export '):
            m = re.search(r"""export\s+['"]([^'"]+)['"](.*)""", lines[i])
            if m:
                exports.append({'uri': m.group(1), 'line': i + 1, 'show_hide': m.group(2).strip().rstrip(';')})
            continue
        if s.startswith('import '):
            m = re.search(r"""import\s+['"]([^'"]+)['"]""", lines[i])
            if m:
                imports.append(m.group(1))
            continue
        if s.startswith('part '):
            m = re.search(r"""part\s+(?:of\s+)?['"]([^'"]+)['"]""", lines[i])
            if m:
                parts.append(m.group(1))
            continue
        if depths[i] != 0:
            continue
        m = TOP_DECL_RE.match(code)
        if m:
            kind, name = m.group(1), m.group(2)
            doc, anns = collect_doc_and_annotations(lines, i)
            sig, sig_end = signature_at(lines, code_lines, i)
            skip_until = sig_end
            # 找出类体范围
            end = len(lines)
            for j in range(i, len(lines)):
                if '{' in code_lines[j]:
                    for k in range(j + 1, len(lines)):
                        if depths[k] == 0 and code_lines[k].strip():
                            end = k
                            break
                    else:
                        end = len(lines)
                    break
                if ';' in code_lines[j]:
                    end = j + 1
                    break
            members = []
            if kind in ('class', 'mixin', 'extension', 'extension type', 'enum'):
                members = parse_members(lines, code_lines, depths, i, end, name)
            enum_values = []
            if kind == 'enum':
                body = '\n'.join(code_lines[i:end])
                head = body.split('{', 1)[-1]
                head = head.split(';', 1)[0]
                for tok in re.findall(r'\b([a-z_]\w*)\b\s*(?:\([^)]*\))?\s*(?:,|$)', head):
                    if tok not in ('final', 'const', 'this', 'return'):
                        enum_values.append(tok)
            decls.append({
                'kind': kind,
                'name': name,
                'file': rel(path, root),
                'line': i + 1,
                'signature': sig,
                'doc': doc,
                'annotations': anns,
                'members': members,
                'enum_values': enum_values,
                'public': not name.startswith('_'),
            })
            continue
        # 顶层函数 / 常量
        if s and not s.startswith('@') and not s.startswith('//') and not s.startswith('library'):
            fm = re.match(r'^\s*(?:external\s+)?[\w<>,\s\?\[\]\.]+?\b(\w+)\s*(?:<[^<>]*>)?\s*\(', code)
            vm = re.match(r'^\s*(?:const|final)\s+[\w<>,\s\?\[\]\.]*?\b(\w+)\s*=', code)
            name = None
            kind = None
            if fm:
                name, kind = fm.group(1), 'function'
            elif vm:
                name, kind = vm.group(1), 'const'
            if name and name not in MEMBER_SKIP:
                doc, anns = collect_doc_and_annotations(lines, i)
                _sig, sig_end = signature_at(lines, code_lines, i)
                skip_until = sig_end
                decls.append({
                    'kind': kind,
                    'name': name,
                    'file': rel(path, root),
                    'line': i + 1,
                    'signature': _sig,
                    'doc': doc,
                    'annotations': anns,
                    'members': [],
                    'enum_values': [],
                    'public': not name.startswith('_'),
                })

    return {
        'file': rel(path, root),
        'abs': path,
        'lines': len(lines),
        'exports': exports,
        'imports': imports,
        'parts': parts,
        'decls': decls,
    }


# ---------------------------------------------------------------- 导出链


def resolve_export_chain(pkg, pkg_name):
    """从 lib/<pkg_name>.dart 出发，递归展开 export，返回 (入口, 有序文件列表, 外部再导出)。"""
    lib = os.path.join(pkg, 'lib')
    entry = os.path.join(lib, pkg_name + '.dart')
    if not os.path.isfile(entry):
        cands = [f for f in sorted(os.listdir(lib)) if f.endswith('.dart')] if os.path.isdir(lib) else []
        entry = os.path.join(lib, cands[0]) if cands else None
    chain = OrderedDict()
    external = []
    if not entry or not os.path.isfile(entry):
        return None, chain, external

    def walk(path):
        if path in chain:
            return
        info = parse_dart(path, pkg)
        chain[path] = info
        for ex in info['exports']:
            uri = ex['uri']
            if uri.startswith('package:') or uri.startswith('dart:'):
                external.append({'uri': uri, 'from': info['file'], 'line': ex['line'],
                                 'show_hide': ex['show_hide']})
                continue
            target = os.path.normpath(os.path.join(os.path.dirname(path), uri))
            if os.path.isfile(target):
                walk(target)
            else:
                external.append({'uri': uri, 'from': info['file'], 'line': ex['line'],
                                 'show_hide': ex['show_hide'], 'missing': True})

    walk(entry)
    return entry, chain, external


# ---------------------------------------------------------------- 平台判定

PLATFORM_SIGNALS = [
    ('dart:io', re.compile(r"""import\s+['"]dart:io['"]""")),
    ('dart:html / dart:js', re.compile(r"""import\s+['"]dart:(?:html|js|js_interop|js_util)['"]""")),
    ('dart:ffi', re.compile(r"""import\s+['"]dart:ffi['"]""")),
    ('MethodChannel', re.compile(r'\bMethodChannel\s*\(')),
    ('EventChannel', re.compile(r'\bEventChannel\s*\(')),
    ('Platform.is*', re.compile(r'\bPlatform\.(isAndroid|isIOS|isMacOS|isWindows|isLinux|isFuchsia)\b')),
    ('defaultTargetPlatform', re.compile(r'\bdefaultTargetPlatform\b')),
    ('kIsWeb', re.compile(r'\bkIsWeb\b')),
]


def platform_evidence(pkg):
    hits = []
    lib = os.path.join(pkg, 'lib')
    for dirpath, _dirs, files in os.walk(lib):
        for fn in files:
            if not fn.endswith('.dart'):
                continue
            p = os.path.join(dirpath, fn)
            lines = read(p).split('\n')
            for i, line in enumerate(lines):
                if line.strip().startswith('//'):
                    continue
                for label, rx in PLATFORM_SIGNALS:
                    if rx.search(line):
                        hits.append((label, '%s:%d' % (rel(p, pkg), i + 1), line.strip()[:110]))
    native_dirs = [d for d in ('android', 'ios', 'macos', 'windows', 'linux', 'web')
                   if os.path.isdir(os.path.join(pkg, d))]
    return hits, native_dirs


# ---------------------------------------------------------------- example 用法


def example_usage(pkg, pkg_name):
    usages = []
    for base in ('example/lib', 'example'):
        root = os.path.join(pkg, base)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            if '/build/' in dirpath or '/.dart_tool' in dirpath:
                continue
            for fn in sorted(files):
                if not fn.endswith('.dart'):
                    continue
                p = os.path.join(dirpath, fn)
                text = read(p)
                if 'package:%s/' % pkg_name not in text:
                    continue
                usages.append({'file': rel(p, pkg), 'lines': text.count('\n') + 1})
        break
    return usages


# ---------------------------------------------------------------- 输出


def first_doc_line(doc):
    for d in doc:
        if d.strip():
            return d.strip()
    return ''


ANN_FLAGS = ('@internal', '@protected', '@visibleForTesting', '@Deprecated', '@deprecated',
             '@experimental', '@mustCallSuper', '@override', '@immutable', '@factory', '@nonVirtual')


def flags_of(anns):
    out = []
    joined = ' '.join(anns)
    for f in ANN_FLAGS:
        if f in joined:
            out.append(f)
    return out


SELFTEST_YAML = '''\
name: demo_pkg
description: >-
  A folded description that
  spans two lines.
version: 1.0
homepage: https://example.com/a#b
topics:
  - flutter
  - state-management
environment:
  sdk: ^3.1.0
  flutter: ">=3.13.0"   # 行尾注释
dependencies:
  flutter:
    sdk: flutter
  provider: ^6.1.5+1
  local_pkg:
    path: ../local_pkg
dev_dependencies:
  flutter_test:
    sdk: flutter
flutter:
  plugin:
    platforms:
      android:
        package: com.example.demo
false_friends:
  quoted: "a # not a comment"
  literal: |
    line one
    line two
'''


def selftest():
    """不依赖任何 package 就能验证 pubspec 解析器是否正常。"""
    del UNPARSED[:]
    tokens = _tokenize_yaml(SELFTEST_YAML)
    data, _ = _parse_yaml(tokens, 0, 0)
    checks = [
        ('name', data.get('name'), 'demo_pkg'),
        ('version 保持字符串', repr(data.get('version')), repr('1.0')),
        ('折叠块标量', data.get('description'), 'A folded description that spans two lines.'),
        ('带 # 的 URL 不被截断', data.get('homepage'), 'https://example.com/a#b'),
        ('列表', data.get('topics'), ['flutter', 'state-management']),
        ('环境 sdk', (data.get('environment') or {}).get('sdk'), '^3.1.0'),
        ('引号值 + 行尾注释', (data.get('environment') or {}).get('flutter'), '>=3.13.0'),
        ('sdk 依赖', (data.get('dependencies') or {}).get('flutter'), {'sdk': 'flutter'}),
        ('普通依赖', (data.get('dependencies') or {}).get('provider'), '^6.1.5+1'),
        ('path 依赖', (data.get('dependencies') or {}).get('local_pkg'), {'path': '../local_pkg'}),
        ('三层嵌套 plugin', (((data.get('flutter') or {}).get('plugin') or {})
                             .get('platforms') or {}).get('android'),
         {'package': 'com.example.demo'}),
        ('引号里的 #', (data.get('false_friends') or {}).get('quoted'), 'a # not a comment'),
        ('字面块标量', (data.get('false_friends') or {}).get('literal'), 'line one\nline two'),
    ]
    bad = 0
    for label, got, want in checks:
        ok = got == want
        if not ok:
            bad += 1
        print('%s %-24s got=%r' % ('✓' if ok else '✗', label, got))
        if not ok:
            print('   want=%r' % (want,))
    if UNPARSED:
        print('✗ 有未解析的行: %s' % UNPARSED)
        bad += 1
    print('\n%s' % ('全部通过。' if not bad else '%d 项失败。' % bad))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    ap.add_argument('pkg')
    ap.add_argument('--json', help='同时把结构化结果写到这个路径（给 verify_readme.py 用）')
    ap.add_argument('--full-doc', action='store_true', help='打出完整 dartdoc 而不是首行')
    args = ap.parse_args()

    pkg = os.path.abspath(args.pkg.rstrip('/'))
    if not os.path.isfile(os.path.join(pkg, 'pubspec.yaml')):
        sys.exit('✗ %s 下没有 pubspec.yaml，这不是一个 package 根目录' % pkg)

    raw, spec = load_pubspec(pkg)
    pkg_name = spec.get('name') or os.path.basename(pkg)
    out = []
    w = out.append
    if UNPARSED:
        w('⚠ pubspec.yaml 里有 %d 行没能解析，下面的信息可能不全，自己去文件里核对一眼：' % len(UNPARSED))
        for line in UNPARSED[:10]:
            w('    %s' % line)
        w('')

    # ---------- 1. 元信息
    w('=' * 78)
    w('包元信息  (%s)' % pkg)
    w('=' * 78)
    w('name         : %s' % pkg_name)
    w('version      : %s' % spec.get('version', '(未声明)'))
    desc = spec.get('description', '')
    w('description  : %s' % (' '.join(str(desc).split()) if desc else '(未声明)'))
    for key in ('homepage', 'repository', 'issue_tracker', 'documentation'):
        if spec.get(key):
            w('%-13s: %s' % (key, spec[key]))
    if spec.get('topics'):
        w('topics       : %s' % ', '.join(map(str, spec['topics'])))
    if spec.get('publish_to'):
        w('publish_to   : %s  ← 私有包，不发 pub.dev，安装方式要写 git/path 依赖' % spec['publish_to'])
    for f in ('LICENSE', 'LICENSE.md', 'CHANGELOG.md'):
        p = os.path.join(pkg, f)
        w('%-13s: %s' % (f, '有 (%d 字节)' % os.path.getsize(p) if os.path.isfile(p) else '无'))
    ch = read(os.path.join(pkg, 'CHANGELOG.md'))
    if ch:
        head = [l for l in ch.split('\n')[:6] if l.strip()]
        w('CHANGELOG 头 : %s' % ' / '.join(head[:3]))
    for f in ('README.md', 'README_zh.md', 'README_CN.md', 'README-zh.md'):
        p = os.path.join(pkg, f)
        if os.path.isfile(p):
            w('已有 %-9s: %d 字节，%d 行  ← 会被覆盖，先看一眼里面有没有值得保留的事实' %
              (f, os.path.getsize(p), read(p).count('\n') + 1))

    # ---------- 2. 环境约束
    w('')
    w('=' * 78)
    w('环境约束（照抄 pubspec，不要自己换算）')
    w('=' * 78)
    env = spec.get('environment') or {}
    w('sdk (Dart)   : %s' % env.get('sdk', '(未声明)'))
    w('flutter      : %s' % env.get('flutter', '(未声明)'))
    sdk_c = str(env.get('sdk', ''))
    m = re.search(r'(\d+)\.(\d+)\.(\d+)', sdk_c)
    if m and not env.get('flutter'):
        w('提示         : 只声明了 Dart 约束。README 的 Flutter 下限应说明"由 Dart %s 反推"，'
          '不要凭空写一个 Flutter 版本号。' % m.group(0))
    elif m and env.get('flutter'):
        w('提示         : Dart 与 Flutter 两个约束同时存在时，实际下限取两者中更严格的那个。'
          '若二者对应关系明显不一致（如 Dart 3.10 配 Flutter >=3.0.0），')
        w('               在 README 里按"Dart 约束为准"写，并在注意事项里提一句这个不一致。')

    # ---------- 3. 平台
    w('')
    w('=' * 78)
    w('平台判定依据（结论自己下，别抄别的包）')
    w('=' * 78)
    fl = spec.get('flutter') or {}
    plugin = fl.get('plugin') if isinstance(fl, dict) else None
    if plugin:
        w('pubspec 声明了 flutter.plugin —— 这是插件包，平台支持以此为准：')
        w(json.dumps(plugin, ensure_ascii=False, indent=2))
    else:
        w('pubspec 没有 flutter.plugin 段 —— 不是平台插件包。')
    hits, native_dirs = platform_evidence(pkg)
    w('平台相关目录 : %s' % (', '.join(native_dirs) if native_dirs else '无（android/ios/... 目录都不存在）'))
    if hits:
        w('平台相关代码线索（%d 处）:' % len(hits))
        seen = {}
        for label, loc, snippet in hits:
            seen.setdefault(label, []).append((loc, snippet))
        for label, items in seen.items():
            w('  · %s —— %d 处' % (label, len(items)))
            for loc, snippet in items[:4]:
                w('      %s   %s' % (loc, snippet))
            if len(items) > 4:
                w('      ... 还有 %d 处' % (len(items) - 4))
    else:
        w('lib/ 下没有 dart:io / dart:html / dart:ffi / MethodChannel / Platform.is 等平台相关调用。')
        w('→ 纯 Dart/Flutter 实现，Flutter 支持的平台它都支持。可写"全平台"，')
        w('   但要注明"未做平台特定实现，实际以宿主 Flutter 版本支持的平台为准"，别去编"已在 xx 上测试通过"。')

    # ---------- 4. 依赖
    w('')
    w('=' * 78)
    w('依赖（README 的第三方依赖章节只写下面标 [第三方] 的那些）')
    w('=' * 78)
    deps = dep_entries(spec.get('dependencies'))
    devs = dep_entries(spec.get('dev_dependencies'))
    third = []
    if not deps:
        w('dependencies : 无')
    for name, constraint, kind in deps:
        tag = '[SDK内置]' if (name in DEP_SDK or kind == 'sdk') else '[第三方]'
        if tag == '[第三方]':
            third.append((name, constraint, kind))
        w('  %-9s %-26s %s' % (tag, name, constraint))
    w('')
    w('dev_dependencies（README 正文不写，最多在"参与贡献"里带一句）:')
    for name, constraint, kind in devs:
        w('  %-9s %-26s %s' % ('[SDK内置]' if (name in DEP_SDK or kind == 'sdk') else '[第三方]', name, constraint))
    if not devs:
        w('  无')
    w('')
    if third:
        w('→ 需要在 README「第三方依赖」章节逐个说明的共 %d 个：%s' %
          (len(third), ', '.join(n for n, _, _ in third)))
        w('  每个要写：做什么用的 / 版本约束（照抄上面）/ 本包在哪里用到它（给出 lib 下的文件:行号）。')
        w('  用途不要靠猜——下面「依赖使用位置」列出了每个依赖在 lib/ 里被 import 的地方。')
    else:
        w('→ 没有第三方依赖。README 的依赖章节要如实写"零第三方依赖"，这本身是个卖点。')

    # 依赖使用位置
    if third:
        w('')
        w('依赖使用位置（lib/ 内）:')
        lib_dir = os.path.join(pkg, 'lib')
        for name, _c, _k in third:
            locs = []
            for dirpath, _d, files in os.walk(lib_dir):
                for fn in files:
                    if not fn.endswith('.dart'):
                        continue
                    p = os.path.join(dirpath, fn)
                    for i, line in enumerate(read(p).split('\n')):
                        if re.search(r"""import\s+['"]package:%s/""" % re.escape(name), line) or \
                           re.search(r"""export\s+['"]package:%s/""" % re.escape(name), line):
                            locs.append('%s:%d' % (rel(p, pkg), i + 1))
            w('  %-24s %s' % (name, ', '.join(locs) if locs else '⚠ lib/ 里没有 import —— 可能是间接依赖或已废弃，写之前先确认'))

    # ---------- 5. 导出链
    entry, chain, external = resolve_export_chain(pkg, pkg_name)
    w('')
    w('=' * 78)
    w('导出面（README 只该介绍这里面的东西）')
    w('=' * 78)
    if not entry:
        w('⚠ 找不到 lib/%s.dart 入口文件。' % pkg_name)
    else:
        w('入口文件     : %s' % rel(entry, pkg))
        w('导出链覆盖   : %d 个文件' % len(chain))
        for p, info in chain.items():
            pub = [d for d in info['decls'] if d['public']]
            w('  %-52s %3d 行  公开声明 %d' % (info['file'], info['lines'], len(pub)))
        if external:
            w('')
            w('再导出的外部内容（使用者 import 本包后能直接拿到，README 要说明这层关系）:')
            for e in external:
                flag = '  ⚠ 路径不存在' if e.get('missing') else ''
                w('  %s   来自 %s:%d %s%s' % (e['uri'], e['from'], e['line'], e['show_hide'], flag))

    # lib 下未被导出的文件
    lib_dir = os.path.join(pkg, 'lib')
    all_lib = []
    for dirpath, _d, files in os.walk(lib_dir):
        for fn in files:
            if fn.endswith('.dart'):
                all_lib.append(os.path.join(dirpath, fn))
    unexported = [p for p in sorted(all_lib) if p not in chain]
    if unexported:
        w('')
        w('lib/ 下未进入导出链的文件（内部实现，README 不要介绍）:')
        for p in unexported:
            w('  %s' % rel(p, pkg))

    # ---------- 6. 公开 API
    w('')
    w('=' * 78)
    w('公开 API 清单')
    w('=' * 78)
    w('标注含义：@internal / @protected / @visibleForTesting 的成员不是给使用者调的，')
    w('README 里不要写成公开用法；@protected 的钩子可以写成"子类里覆写"，别写成"外部调用"。')
    w('')
    api_index = {}
    for p, info in chain.items():
        pubs = [d for d in info['decls'] if d['public']]
        if not pubs:
            continue
        w('-' * 78)
        w('文件 %s' % info['file'])
        for d in pubs:
            fl2 = flags_of(d['annotations'])
            w('')
            w('  %s %s   (%s:%d)%s' % (d['kind'], d['name'], info['file'], d['line'],
                                       '  ' + ' '.join(fl2) if fl2 else ''))
            w('    签名: %s' % d['signature'])
            if d['doc']:
                if args.full_doc:
                    for line in d['doc']:
                        w('    ///  %s' % line)
                else:
                    w('    doc : %s' % first_doc_line(d['doc']))
            else:
                w('    doc : （无 dartdoc —— README 里这个 API 的说明得靠读实现，别照着名字编）')
            if d['enum_values']:
                w('    枚举值: %s' % ', '.join(d['enum_values']))
            pub_members = [m for m in d['members'] if m['public']]
            if pub_members:
                for m in pub_members:
                    mf = flags_of(m['annotations'])
                    tag = ('  ' + ' '.join(mf)) if mf else ''
                    w('      · [%s] %s   L%d%s' % (m['kind'], m['signature'], m['line'], tag))
                    md = first_doc_line(m['doc'])
                    if md:
                        w('           %s' % md)
            api_index[d['name']] = {
                'kind': d['kind'],
                'file': info['file'],
                'line': d['line'],
                'members': [m['name'] for m in d['members'] if m['public']],
                'internal_members': [m['name'] for m in d['members']
                                     if any(f in ' '.join(m['annotations'])
                                            for f in ('@internal', '@protected', '@visibleForTesting'))],
                'enum_values': d['enum_values'],
                'annotations': d['annotations'],
            }

    # ---------- 7. example
    w('')
    w('=' * 78)
    w('example 里的真实用法（写示例代码的第一手来源）')
    w('=' * 78)
    usages = example_usage(pkg, pkg_name)
    if usages:
        w('example 中 import 了本包的文件，共 %d 个。这些是能跑通的真实用法，' % len(usages))
        w('写 README 示例时优先读这些文件、按它们的写法改编，而不是自己凭 API 名字造：')
        for u in usages:
            w('  %-52s %d 行' % (u['file'], u['lines']))
    else:
        w('没有 example，或 example 里没有 import 本包。')
        w('→ 示例代码只能基于 API 签名自己写。写完务必逐行核对：每个类名、')
        w('  每个参数名、每个必填参数，都要能在上面的「公开 API 清单」里找到。')

    # ---------- 8. 下一步
    w('')
    w('=' * 78)
    w('接下来')
    w('=' * 78)
    w('1. 读 references/readme-template.md 拿章节骨架。')
    w('2. 挑 3–6 个"核心能力"深入写；其余 API 用表格一行带过。别每个类都写一大节。')
    w('3. 示例代码优先改编自 example/；没有 example 就严格照 API 签名写。')
    w('4. 写完跑 scripts/verify_readme.py 校验，通过了再交。')

    text = '\n'.join(out)
    print(text)

    if args.json:
        payload = {
            'pkg': pkg,
            'name': pkg_name,
            'version': spec.get('version'),
            'environment': env,
            'dependencies': [{'name': n, 'constraint': c, 'kind': k} for n, c, k in deps],
            'dev_dependencies': [{'name': n, 'constraint': c, 'kind': k} for n, c, k in devs],
            'third_party': [n for n, _, _ in third],
            'entry': rel(entry, pkg) if entry else None,
            'export_chain': [info['file'] for info in chain.values()],
            'external_exports': external,
            'api': api_index,
            'all_symbols': sorted(api_index.keys()),
        }
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print('\n[已写出结构化结果 → %s]' % args.json, file=sys.stderr)


if __name__ == '__main__':
    main()
