#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pubspec.yaml 的可信读取。

为什么单独一个模块：发布决策（版本号该不该发、依赖里有没有 path 依赖）全都建立在
"我读懂了 pubspec"这个前提上。一个**可能读错但不声张**的解析器比读不出来危险得多——
读不出来会停下，读错了会带着错误结论一路走到 `dart pub publish`。

所以这里只允许三种结局：

1. **PyYAML 在场** —— 用它，权威。若内置解析器也在场则做差分比对，不一致就抛错。
2. **PyYAML 缺席，内置严格解析器当场通过自检** —— 用它。自检是每次运行都真跑一遍
   `CORPUS` 里的 22 个真实 pubspec 形态并逐字段比对期望值，不是"相信它没问题"。
3. **其余情况**（自检不过、遇到不支持的 YAML 语法、两个解析器结论不一致）—— 抛
   `PubspecParseError`，由调用方转成硬失败。**不降级、不猜、不 WARN 了事。**

内置解析器覆盖的是 pubspec 实际会用到的 YAML 子集：块映射（可嵌套）、块序列、
单/双引号与裸标量、块标量（`|` `>` 及其 `-` `+` 变体）、注释、简单流式写法。
遇到锚点/别名/标签/合并键/多文档/复杂键/制表符缩进一律抛错——这些语法 pubspec 里
几乎不出现，一旦出现说明这份文件超出了我能担保的范围，那就该停下让人装 PyYAML。
"""

import re

__all__ = ["PubspecParseError", "load", "parse_strict", "selftest",
           "raw_top_level_scalar"]


class PubspecParseError(Exception):
    """pubspec 无法被可信地读取。调用方必须把它当作硬失败，不得降级继续。"""


# --------------------------------------------------------------------------
# 标量

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\",
            "/": "/", "0": "\0", "b": "\b", "f": "\f", "'": "'"}


def _strip_comment(s):
    """去掉行尾注释。`#` 只有在行首或前面是空白时才起注释作用，且不能在引号内。"""
    out = []
    quote = None
    i = 0
    while i < len(s):
        c = s[i]
        if quote:
            if quote == '"' and c == "\\" and i + 1 < len(s):
                out.append(c)
                out.append(s[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            out.append(c)
        else:
            if c in "\"'":
                quote = c
                out.append(c)
            elif c == "#" and (not out or out[-1] in " \t"):
                break
            else:
                out.append(c)
        i += 1
    if quote:
        raise PubspecParseError("引号没有闭合：%s" % s.strip()[:80])
    return "".join(out).rstrip()


def _unescape_double(s):
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                i += 2
                continue
            if nxt == "u" and i + 5 < len(s) + 1:
                try:
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            raise PubspecParseError("不认识的转义序列 \\%s" % nxt)
        out.append(s[i])
        i += 1
    return "".join(out)


def _scalar(raw, lineno):
    """把一段值文本解析成标量。裸标量一律保留为字符串——本工具关心的字段
    （name / version / description / repository）都是字符串，把 `1.2` 变成 float
    再 str() 回来只会丢掉尾零。"""
    s = raw.strip()
    if s == "":
        return ""
    if s[0] == '"':
        if len(s) < 2 or s[-1] != '"':
            raise PubspecParseError("第 %d 行双引号没有闭合" % lineno)
        return _unescape_double(s[1:-1])
    if s[0] == "'":
        if len(s) < 2 or s[-1] != "'":
            raise PubspecParseError("第 %d 行单引号没有闭合" % lineno)
        return s[1:-1].replace("''", "'")
    if s[0] in "&*":
        raise PubspecParseError(
            "第 %d 行用了 YAML 锚点/别名（%s），内置解析器不支持" % (lineno, s[:20]))
    if s.startswith("!"):
        raise PubspecParseError("第 %d 行用了 YAML 标签（%s），内置解析器不支持"
                                % (lineno, s[:20]))
    if s[0] == "{":
        return _flow_map(s, lineno)
    if s[0] == "[":
        return _flow_seq(s, lineno)
    if s in ("null", "~"):
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    return s


def _split_flow(body, lineno):
    """按顶层逗号切分流式内容，不切引号内和嵌套括号内的逗号。"""
    parts, buf, depth, quote = [], [], 0, None
    for c in body:
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
            continue
        if c in "\"'":
            quote = c
            buf.append(c)
        elif c in "{[":
            depth += 1
            buf.append(c)
        elif c in "}]":
            depth -= 1
            buf.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
    if quote:
        raise PubspecParseError("第 %d 行流式写法里引号没闭合" % lineno)
    if depth != 0:
        raise PubspecParseError("第 %d 行流式写法括号不配对" % lineno)
    if "".join(buf).strip():
        parts.append("".join(buf))
    return parts


def _flow_map(s, lineno):
    if not s.endswith("}"):
        raise PubspecParseError("第 %d 行流式映射没有闭合（跨行流式写法不支持）" % lineno)
    out = {}
    for item in _split_flow(s[1:-1], lineno):
        if not item.strip():
            continue
        if ":" not in item:
            raise PubspecParseError("第 %d 行流式映射里 %r 缺冒号" % (lineno, item.strip()))
        k, _, v = item.partition(":")
        out[_scalar(k, lineno)] = _scalar(v, lineno)
    return out


def _flow_seq(s, lineno):
    if not s.endswith("]"):
        raise PubspecParseError("第 %d 行流式序列没有闭合（跨行流式写法不支持）" % lineno)
    return [_scalar(x, lineno) for x in _split_flow(s[1:-1], lineno) if x.strip()]


# --------------------------------------------------------------------------
# 块解析

_KEY_RE = re.compile(r"^(\?|[^:\s].*?|'(?:[^']|'')*'|\"(?:[^\"\\]|\\.)*\")\s*:(\s|$)")
_BLOCK_SCALAR_RE = re.compile(r"^([|>])([+-]?)(\d*)$")


class _Lines(object):
    """带缩进信息的行游标。空行与整行注释在进入时就被剔除，但行号保留以便报错。"""

    def __init__(self, text):
        self.items = []
        self.raw = text.splitlines()
        for n, raw in enumerate(self.raw, 1):
            if raw.strip() == "" or raw.lstrip().startswith("#"):
                continue
            stripped_leading = raw[:len(raw) - len(raw.lstrip(" \t"))]
            if "\t" in stripped_leading:
                raise PubspecParseError("第 %d 行用制表符缩进，YAML 不允许" % n)
            content = _strip_comment(raw)
            if content.strip() == "":
                continue
            indent = len(content) - len(content.lstrip(" "))
            self.items.append((n, indent, content.strip(), raw))
        self.i = 0

    def peek(self):
        return self.items[self.i] if self.i < len(self.items) else None

    def next(self):
        it = self.items[self.i]
        self.i += 1
        return it

    def eof(self):
        return self.i >= len(self.items)


def _raw_indent(raw):
    return len(raw) - len(raw.lstrip(" "))


def _read_block_scalar(lines, header, parent_indent, lineno):
    """读 `|` / `>` 及变体后面的缩进块。用原始行（含空行），不能用过滤后的游标。"""
    m = _BLOCK_SCALAR_RE.match(header)
    if not m:
        raise PubspecParseError("第 %d 行块标量头 %r 无法识别" % (lineno, header))
    style, chomp = m.group(1), m.group(2)
    if m.group(3):
        raise PubspecParseError("第 %d 行块标量指定了显式缩进，内置解析器不支持" % lineno)

    body, idx = [], lineno  # lineno 是 1-based，raw[lineno] 即下一行
    block_indent = None
    while idx < len(lines.raw):
        raw = lines.raw[idx]
        if raw.strip() == "":
            body.append("")
            idx += 1
            continue
        ind = _raw_indent(raw)
        if ind <= parent_indent:
            break
        if block_indent is None:
            block_indent = ind
        if ind < block_indent:
            break
        body.append(raw[block_indent:])
        idx += 1

    # 把游标推进到块之后
    while not lines.eof() and lines.peek()[0] <= idx:
        lines.next()

    while body and body[-1] == "":
        body.pop()
    if style == "|":
        text = "\n".join(body)
        text = text + "\n" if body else ""
    else:  # `>` 折叠：空行变换行，其余行用空格连接
        chunks, cur = [], []
        for ln in body:
            if ln.strip() == "":
                chunks.append(" ".join(cur))
                cur = []
            else:
                cur.append(ln.strip())
        chunks.append(" ".join(cur))
        text = "\n".join(chunks)
        text = text + "\n" if body else ""
    if chomp == "-":
        text = text.rstrip("\n")
    return text


def _parse_node(lines, indent):
    """解析缩进 >= indent 的一个块，返回 dict 或 list。"""
    nxt = lines.peek()
    if nxt is None:
        return None
    if nxt[2].startswith("- ") or nxt[2] == "-":
        return _parse_seq(lines, nxt[1])
    return _parse_map(lines, nxt[1])


def _parse_seq(lines, indent):
    out = []
    while not lines.eof():
        lineno, ind, content, _ = lines.peek()
        if ind < indent:
            break
        if ind > indent:
            raise PubspecParseError("第 %d 行缩进异常（序列项对不齐）" % lineno)
        if not (content.startswith("- ") or content == "-"):
            break
        lines.next()
        rest = content[1:].strip()
        if rest == "":
            child = _parse_node(lines, indent + 1)
            out.append(child)
        elif _KEY_RE.match(rest):
            # `- key: value` —— 序列项本身是个映射，键的有效缩进是 indent+2
            sub = _inline_map_item(lines, rest, indent + 2, lineno)
            out.append(sub)
        else:
            out.append(_scalar(rest, lineno))
    return out


def _inline_map_item(lines, first, child_indent, lineno):
    m = _KEY_RE.match(first)
    key = _scalar(m.group(1), lineno)
    val_text = first[m.end(1):].lstrip()
    if val_text.startswith(":"):
        val_text = val_text[1:].strip()
    d = {}
    if val_text == "":
        d[key] = _parse_node(lines, child_indent) if (
            not lines.eof() and lines.peek()[1] >= child_indent) else None
    elif _BLOCK_SCALAR_RE.match(val_text):
        d[key] = _read_block_scalar(lines, val_text, child_indent - 1, lineno)
    else:
        d[key] = _scalar(val_text, lineno)
    # 同一个序列项下的后续键
    while not lines.eof():
        ln2, ind2, content2, _ = lines.peek()
        if ind2 != child_indent or not _KEY_RE.match(content2):
            break
        rest = _parse_map(lines, child_indent)
        d.update(rest)
        break
    return d


def _parse_map(lines, indent):
    out = {}
    while not lines.eof():
        lineno, ind, content, _ = lines.peek()
        if ind < indent:
            break
        if ind > indent:
            raise PubspecParseError("第 %d 行缩进异常（映射键对不齐，上一个键的缩进是 %d）"
                                    % (lineno, indent))
        if content.startswith("- "):
            break
        if content.startswith("<<"):
            raise PubspecParseError("第 %d 行用了 YAML 合并键 `<<`，内置解析器不支持" % lineno)
        if content.startswith("? "):
            raise PubspecParseError("第 %d 行用了 YAML 复杂键 `?`，内置解析器不支持" % lineno)
        m = _KEY_RE.match(content)
        if not m:
            raise PubspecParseError("第 %d 行既不是键值对也不是序列项：%r"
                                    % (lineno, content[:80]))
        lines.next()
        key = _scalar(m.group(1), lineno)
        val_text = content[m.end(1):].lstrip()
        if val_text.startswith(":"):
            val_text = val_text[1:].strip()

        if val_text == "":
            child = lines.peek()
            if child is not None and child[1] > ind:
                out[key] = _parse_node(lines, child[1])
            else:
                out[key] = None
        elif _BLOCK_SCALAR_RE.match(val_text):
            out[key] = _read_block_scalar(lines, val_text, ind, lineno)
        else:
            out[key] = _scalar(val_text, lineno)
    return out


def parse_strict(text):
    """内置严格解析器。看不懂就抛 PubspecParseError，绝不猜。"""
    docs = [l for l in text.splitlines() if l.strip() in ("---", "...")]
    body = text
    if len(docs) > 1 or (docs and text.strip().splitlines()[0].strip() not in ("---",)):
        if len(docs) > 1:
            raise PubspecParseError("这份 YAML 有多个文档（`---` 分隔），pubspec 不该这样")
    if text.strip().startswith("---"):
        body = text.strip()[3:]
    lines = _Lines(body)
    if lines.eof():
        raise PubspecParseError("pubspec 是空的")
    data = _parse_node(lines, lines.peek()[1])
    if not lines.eof():
        ln = lines.peek()[0]
        raise PubspecParseError("第 %d 行之后还有解析不掉的内容" % ln)
    if not isinstance(data, dict):
        raise PubspecParseError("pubspec 顶层不是映射")
    return data


# --------------------------------------------------------------------------
# 顶层字段的独立读取：给最关键的两个字段加一道旁路交叉验证

_TOP_RE_TMPL = r"^%s:[ \t]*(.*?)[ \t]*$"


def raw_top_level_scalar(text, key):
    """不经过任何解析器，直接用正则从原文取顶层标量字段。

    只用于 name / version 这两个决定发布身份的字段——它们在真实 pubspec 里
    永远是顶格的单行标量。取到的值拿去和解析结果比对，两边不一致就说明
    解析器读串了行，这比事后发现发错版本便宜得多。
    """
    m = re.search(_TOP_RE_TMPL % re.escape(key), text, re.M)
    if not m:
        return None
    v = _strip_comment(m.group(1)).strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v or None


# --------------------------------------------------------------------------
# 自检语料：每次运行都真跑一遍，不是"相信它没问题"

CORPUS = [
    ("最小包",
     "name: foo\nversion: 1.0.0\n",
     {"name": "foo", "version": "1.0.0"}),

    ("典型 Flutter 包",
     "name: fl_core\n"
     "description: A helper package.\n"
     "version: 1.4.2\n"
     "repository: https://github.com/x/y\n"
     "environment:\n"
     "  sdk: ^3.5.0\n"
     "  flutter: \">=3.24.0\"\n"
     "dependencies:\n"
     "  flutter:\n"
     "    sdk: flutter\n"
     "  provider: ^6.1.0\n"
     "dev_dependencies:\n"
     "  flutter_test:\n"
     "    sdk: flutter\n",
     {"name": "fl_core", "description": "A helper package.", "version": "1.4.2",
      "repository": "https://github.com/x/y",
      "environment": {"sdk": "^3.5.0", "flutter": ">=3.24.0"},
      "dependencies": {"flutter": {"sdk": "flutter"}, "provider": "^6.1.0"},
      "dev_dependencies": {"flutter_test": {"sdk": "flutter"}}}),

    ("path 依赖",
     "name: a\nversion: 0.1.0\n"
     "dependencies:\n"
     "  fl_core:\n"
     "    path: ../fl_core\n",
     {"name": "a", "version": "0.1.0",
      "dependencies": {"fl_core": {"path": "../fl_core"}}}),

    ("git 依赖带嵌套",
     "name: a\nversion: 0.1.0\n"
     "dependencies:\n"
     "  pkg:\n"
     "    git:\n"
     "      url: https://github.com/x/y.git\n"
     "      ref: main\n",
     {"name": "a", "version": "0.1.0",
      "dependencies": {"pkg": {"git": {"url": "https://github.com/x/y.git",
                                       "ref": "main"}}}}),

    ("折叠块标量 >-",
     "name: a\nversion: 1.0.0\n"
     "description: >-\n"
     "  A Flutter state lifecycle helper that binds controller\n"
     "  disposal to widget lifetime.\n"
     "repository: https://x.com\n",
     {"name": "a", "version": "1.0.0",
      "description": "A Flutter state lifecycle helper that binds controller "
                     "disposal to widget lifetime.",
      "repository": "https://x.com"}),

    # 折叠块里的空行走的是另一条分支（空行变换行、其余行用空格连接）。
    # 少了这条用例，"把连接符从空格改成空串"这类 bug 能溜过自检——实测溜过一次，故补。
    ("折叠块含空行",
     "name: a\nversion: 1.0.0\n"
     "description: >-\n"
     "  first para line one\n"
     "  first para line two\n"
     "\n"
     "  second para\n",
     {"name": "a", "version": "1.0.0",
      "description": "first para line one first para line two\nsecond para"}),

    ("字面块含空行",
     "name: a\nversion: 1.0.0\n"
     "description: |\n"
     "  line one\n"
     "\n"
     "  line three\n",
     {"name": "a", "version": "1.0.0",
      "description": "line one\n\nline three\n"}),

    ("折叠块不带 chomp（保留尾换行）",
     "name: a\nversion: 1.0.0\n"
     "description: >\n"
     "  wrapped one\n"
     "  wrapped two\n",
     {"name": "a", "version": "1.0.0",
      "description": "wrapped one wrapped two\n"}),

    ("字面块标量 |",
     "name: a\nversion: 1.0.0\n"
     "description: |\n"
     "  line one\n"
     "  line two\n"
     "homepage: https://x.com\n",
     {"name": "a", "version": "1.0.0",
      "description": "line one\nline two\n", "homepage": "https://x.com"}),

    ("行尾注释",
     "name: a  # the package name\n"
     "version: 1.0.0 # bump me\n"
     "description: has # inside? no\n",
     {"name": "a", "version": "1.0.0", "description": "has"}),

    ("引号里的井号不是注释",
     "name: a\nversion: 1.0.0\n"
     "description: \"color #ff0000 support\"\n",
     {"name": "a", "version": "1.0.0", "description": "color #ff0000 support"}),

    ("单引号与转义",
     "name: a\nversion: 1.0.0\n"
     "description: 'it''s fine'\n",
     {"name": "a", "version": "1.0.0", "description": "it's fine"}),

    ("双引号转义",
     "name: a\nversion: 1.0.0\n"
     "description: \"say \\\"hi\\\"\"\n",
     {"name": "a", "version": "1.0.0", "description": 'say "hi"'}),

    ("flutter 段带资源序列",
     "name: a\nversion: 1.0.0\n"
     "flutter:\n"
     "  assets:\n"
     "    - assets/a.png\n"
     "    - assets/b.png\n"
     "  uses-material-design: true\n",
     {"name": "a", "version": "1.0.0",
      "flutter": {"assets": ["assets/a.png", "assets/b.png"],
                  "uses-material-design": True}}),

    ("插件平台声明（深嵌套）",
     "name: a\nversion: 1.0.0\n"
     "flutter:\n"
     "  plugin:\n"
     "    platforms:\n"
     "      android:\n"
     "        package: com.x.y\n"
     "        pluginClass: YPlugin\n"
     "      ios:\n"
     "        pluginClass: YPlugin\n",
     {"name": "a", "version": "1.0.0",
      "flutter": {"plugin": {"platforms": {
          "android": {"package": "com.x.y", "pluginClass": "YPlugin"},
          "ios": {"pluginClass": "YPlugin"}}}}}),

    ("序列项是映射（fonts）",
     "name: a\nversion: 1.0.0\n"
     "flutter:\n"
     "  fonts:\n"
     "    - family: Roboto\n"
     "      fonts:\n"
     "        - asset: fonts/R.ttf\n"
     "    - family: Mono\n"
     "      fonts:\n"
     "        - asset: fonts/M.ttf\n"
     "          weight: 700\n",
     {"name": "a", "version": "1.0.0",
      "flutter": {"fonts": [
          {"family": "Roboto", "fonts": [{"asset": "fonts/R.ttf"}]},
          {"family": "Mono", "fonts": [{"asset": "fonts/M.ttf", "weight": "700"}]}]}}),

    ("publish_to none",
     "name: a\nversion: 1.0.0\npublish_to: none\n",
     {"name": "a", "version": "1.0.0", "publish_to": "none"}),

    ("publish_to 带引号",
     "name: a\nversion: 1.0.0\npublish_to: 'none'\n",
     {"name": "a", "version": "1.0.0", "publish_to": "none"}),

    ("版本带 build 号",
     "name: a\nversion: 1.0.0+3\n",
     {"name": "a", "version": "1.0.0+3"}),

    ("预发布版本",
     "name: a\nversion: 2.0.0-beta.1\n",
     {"name": "a", "version": "2.0.0-beta.1"}),

    ("空值键",
     "name: a\nversion: 1.0.0\ndependencies:\n",
     {"name": "a", "version": "1.0.0", "dependencies": None}),

    ("流式映射",
     "name: a\nversion: 1.0.0\nenvironment: {sdk: \">=3.0.0 <4.0.0\"}\n",
     {"name": "a", "version": "1.0.0",
      "environment": {"sdk": ">=3.0.0 <4.0.0"}}),

    ("流式序列",
     "name: a\nversion: 1.0.0\nfalse_secrets: [a.txt, b.txt]\n",
     {"name": "a", "version": "1.0.0", "false_secrets": ["a.txt", "b.txt"]}),

    ("整行注释与空行穿插",
     "# top comment\n\nname: a\n\n# mid\nversion: 1.0.0\n\ndependencies:\n"
     "  # dep comment\n  provider: ^6.0.0\n\n",
     {"name": "a", "version": "1.0.0", "dependencies": {"provider": "^6.0.0"}}),

    ("依赖约束含空格与引号",
     "name: a\nversion: 1.0.0\n"
     "dependencies:\n"
     "  http: \">=0.13.0 <2.0.0\"\n"
     "  meta: '^1.9.0'\n",
     {"name": "a", "version": "1.0.0",
      "dependencies": {"http": ">=0.13.0 <2.0.0", "meta": "^1.9.0"}}),
]

# 这些必须被拒绝。解析器对超出担保范围的语法保持沉默地"尽力而为"，
# 正是我们要消灭的行为——所以拒绝能力本身也纳入自检。
REJECT_CORPUS = [
    ("锚点", "name: a\nversion: 1.0.0\nx: &anchor v\ny: *anchor\n"),
    ("合并键", "name: a\nversion: 1.0.0\nbase: &b\n  k: v\nz:\n  <<: *b\n"),
    ("标签", "name: a\nversion: 1.0.0\nx: !!str 5\n"),
    ("制表符缩进", "name: a\nversion: 1.0.0\ndependencies:\n\tprovider: ^6.0.0\n"),
    ("多文档", "---\nname: a\nversion: 1.0.0\n---\nname: b\n"),
    ("缩进对不齐", "name: a\nversion: 1.0.0\ndependencies:\n  a: ^1.0.0\n   b: ^2.0.0\n"),
    ("引号未闭合", "name: a\nversion: 1.0.0\ndescription: \"unterminated\n"),
    ("跨行流式映射", "name: a\nversion: 1.0.0\nenvironment: {sdk: \">=3.0.0\",\n  flutter: x}\n"),
]


def selftest():
    """跑一遍语料。返回 (ok, 明细列表)。调用方在每次真正解析前都该跑。"""
    problems = []
    for label, text, expected in CORPUS:
        try:
            got = parse_strict(text)
        except PubspecParseError as e:
            problems.append("接受用例[%s] 抛错: %s" % (label, e))
            continue
        except Exception as e:  # noqa
            problems.append("接受用例[%s] 崩溃: %r" % (label, e))
            continue
        if got != expected:
            problems.append("接受用例[%s] 结果不符\n    期望 %r\n    实得 %r"
                            % (label, expected, got))
    for label, text in REJECT_CORPUS:
        try:
            parse_strict(text)
        except PubspecParseError:
            continue
        except Exception as e:  # noqa
            problems.append("拒绝用例[%s] 抛了非预期异常: %r" % (label, e))
            continue
        problems.append("拒绝用例[%s] 本该被拒绝，却被静默解析了" % label)
    return (not problems), problems


# --------------------------------------------------------------------------
# 对外入口

def _norm(v):
    """比较用的归一化：只比对本工具真正依赖的语义，忽略 YAML 的标量类型差异。

    PyYAML 会把 `version: 1.2` 读成 float、`weight: 700` 读成 int，内置解析器
    保留字符串。两者在本工具的用法下等价（一律 str() 后使用），所以比较前统一。
    """
    if isinstance(v, dict):
        return {str(k): _norm(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if v is None or isinstance(v, bool):
        return v
    return str(v)


def load(path):
    """读取并解析 pubspec.yaml。

    返回 (data, meta)。meta 含：
        parser      "pyyaml" | "strict"
        crosscheck  "两个解析器一致" | "仅 PyYAML" | "仅内置（自检通过）"
        detail      给人看的一句话

    任何不可信的情况都抛 PubspecParseError，不返回可疑结果。
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()

    ok, problems = selftest()
    strict_data = strict_err = None
    if ok:
        try:
            strict_data = parse_strict(text)
        except PubspecParseError as e:
            strict_err = e

    yaml_data = yaml_err = None
    try:
        import yaml as _yaml
        try:
            yaml_data = _yaml.safe_load(text)
            if not isinstance(yaml_data, dict):
                yaml_err = PubspecParseError("PyYAML 读出来的顶层不是映射")
                yaml_data = None
        except Exception as e:  # noqa
            yaml_err = PubspecParseError("PyYAML 解析失败：%s" % e)
    except ImportError:
        pass

    # 两个都在：必须一致，否则说明至少一个读错了，不能挑一个用
    if yaml_data is not None and strict_data is not None:
        if _norm(yaml_data) != _norm(strict_data):
            raise PubspecParseError(
                "两个解析器对这份 pubspec 的理解不一致，无法判定哪个是对的。\n"
                "  PyYAML : %r\n  内置   : %r\n"
                "在弄清楚之前不要据此做发布决定。"
                % (_norm(yaml_data), _norm(strict_data)))
        data = yaml_data
        meta = {"parser": "pyyaml", "crosscheck": "两个解析器结果一致",
                "detail": "PyYAML 解析，内置严格解析器交叉验证通过"}
    elif yaml_data is not None:
        data = yaml_data
        meta = {"parser": "pyyaml", "crosscheck": "仅 PyYAML",
                "detail": "PyYAML 解析（内置解析器%s）"
                          % ("自检未通过" if not ok else "拒绝了这份文件：%s" % strict_err)}
        if strict_err is not None:
            meta["detail"] = ("PyYAML 解析；内置严格解析器拒绝了这份文件（%s），"
                              "说明它用了内置解析器不担保的 YAML 语法" % strict_err)
    elif strict_data is not None:
        data = strict_data
        meta = {"parser": "strict", "crosscheck": "仅内置（自检通过）",
                "detail": "未装 PyYAML；内置严格解析器已在本次运行中通过 %d 条接受用例 "
                          "+ %d 条拒绝用例的自检" % (len(CORPUS), len(REJECT_CORPUS))}
    else:
        if not ok:
            raise PubspecParseError(
                "内置严格解析器自检未通过，不能用它来读 pubspec：\n  - %s\n"
                "请安装 PyYAML（pip3 install pyyaml）后重跑。"
                % "\n  - ".join(problems))
        raise PubspecParseError(
            "无法可信地解析 pubspec.yaml：%s\n"
            "这份文件用了内置严格解析器不担保的 YAML 语法。"
            "请安装 PyYAML（pip3 install pyyaml）后重跑，或简化 pubspec 的写法。"
            % (strict_err or yaml_err))

    # 最后一道：name / version 这两个决定发布身份的字段，用不经解析器的正则旁路核对
    for key in ("name", "version"):
        raw = raw_top_level_scalar(text, key)
        parsed = data.get(key)
        if raw is None and parsed is None:
            continue
        if raw is None or parsed is None or str(parsed).strip() != raw:
            raise PubspecParseError(
                "字段 %s 的解析结果与原文直读不一致（解析得 %r，原文 %r）。"
                "这通常意味着解析器读串了行——在弄清楚之前不要发布。"
                % (key, parsed, raw))

    return data, meta


if __name__ == "__main__":
    import json
    import sys
    ok, problems = selftest()
    print("自检：%s（%d 接受 / %d 拒绝）"
          % ("通过" if ok else "未通过", len(CORPUS), len(REJECT_CORPUS)))
    for p in problems:
        print("  ✗", p)
    if len(sys.argv) > 1:
        d, m = load(sys.argv[1])
        print("\n解析器：%s\n说明：%s\n" % (m["parser"], m["detail"]))
        print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
    sys.exit(0 if ok else 1)
