#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flutter package 线索扫描器（只读，不修改任何文件）。

输出的是**待复核线索**，不是结论。正则无法理解语义，误报是预期内的——
每条线索都必须打开原文件确认后才能写进审计报告。

用法:
    python3 scan_package.py <package根目录>          # 有 pubspec.yaml 的那一层
    python3 scan_package.py <package根目录> --json   # 机器可读输出
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
from collections import defaultdict

# ---------------------------------------------------------------- 预处理

def blank_noise(src: str) -> str:
    """把注释和字符串字面量替换成等长空格，保留换行与所有偏移量。

    这样后续正则不会命中注释里的示例代码或字符串中的关键字，
    而行号/列号依然和原文件一一对应。
    """
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        # 行注释
        if c == '/' and i + 1 < n and src[i + 1] == '/':
            j = src.find('\n', i)
            j = n if j == -1 else j
            for k in range(i, j):
                out[k] = ' '
            i = j
            continue
        # 块注释
        if c == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2)
            j = n if j == -1 else j + 2
            for k in range(i, j):
                if out[k] != '\n':
                    out[k] = ' '
            i = j
            continue
        # 字符串（含 raw / 三引号）。
        # 注意：`${...}` 插值里是**真代码**（print('x ${jsonEncode(data)}') 这种很常见），
        # 把整个字符串抹白会让这些调用彻底隐身，所以插值区保留原样。
        # 保留的是成对花括号，match_block 的括号配对不受影响。
        if c in '\'"':
            quote = c
            triple = src[i:i + 3] == quote * 3
            term = quote * 3 if triple else quote
            for k in range(i, min(i + len(term), n)):
                out[k] = ' '
            j = i + len(term)
            while j < n:
                if src[j] == '\\' and not triple:
                    for k in range(j, min(j + 2, n)):
                        if out[k] != '\n':
                            out[k] = ' '
                    j += 2
                    continue
                if src[j:j + len(term)] == term:
                    for k in range(j, min(j + len(term), n)):
                        out[k] = ' '
                    j += len(term)
                    break
                if not triple and src[j] == '\n':
                    break
                if src[j] == '$' and j + 1 < n and src[j + 1] == '{':
                    depth, k = 0, j + 1
                    while k < n:
                        if src[k] == '{':
                            depth += 1
                        elif src[k] == '}':
                            depth -= 1
                            if depth == 0:
                                break
                        k += 1
                    out[j] = ' '            # 只抹掉 $，花括号和内部表达式原样保留
                    j = k + 1
                    continue
                if src[j] == '$' and j + 1 < n and (src[j + 1].isalpha() or src[j + 1] == '_'):
                    out[j] = ' '            # 简单插值 $name：保留标识符
                    k = j + 1
                    while k < n and (src[k].isalnum() or src[k] == '_' or src[k] == '.'):
                        k += 1
                    j = k
                    continue
                if out[j] != '\n':
                    out[j] = ' '
                j += 1
            i = j
            continue
        i += 1
    return ''.join(out)


def line_of(src: str, pos: int) -> int:
    return src.count('\n', 0, pos) + 1


def match_paren(src: str, open_pos: int):
    """从 src[open_pos] == '(' 起做圆括号配对，返回闭合位置（含）。找不到返回 -1。"""
    depth = 0
    for i in range(open_pos, len(src)):
        if src[i] == '(':
            depth += 1
        elif src[i] == ')':
            depth -= 1
            if depth == 0:
                return i
    return -1


METHOD_DECL = re.compile(
    r'\n[ \t]*(?:@override\s*\n\s*)?(?:static\s+|Future\s*<[^>]*>\s*|void\s+|[\w<>?, \[\]]+\s+)'
    r'(\w+)\s*\([^;{]*\)\s*(?:async\s*\*?\s*)?\{')


def method_ranges(body: str):
    """返回类体内每个方法的 (名字, 体起始, 体结束)，用来定位"某行属于哪个方法"。"""
    out = []
    for m in METHOD_DECL.finditer(body):
        name = m.group(1)
        if name in ('if', 'for', 'while', 'switch', 'catch', 'return'):
            continue
        end = match_block(body, m.end() - 1)
        if end != -1:
            out.append((name, m.end() - 1, end))
    return out


def enclosing_method(ranges, pos):
    best = None
    for name, s, e in ranges:
        if s <= pos <= e and (best is None or s > best[1]):
            best = (name, s, e)
    return best


def duration_ms(text: str):
    """从 Duration(...) 里估出毫秒数；认不出返回 None。"""
    m = re.search(r'Duration\s*\(\s*(\w+)\s*:\s*(\d+)', text)
    if not m:
        return None
    unit, n = m.group(1), int(m.group(2))
    return {'microseconds': n / 1000, 'milliseconds': n, 'seconds': n * 1000,
            'minutes': n * 60000, 'hours': n * 3600000, 'days': n * 86400000}.get(unit)


def match_block(src: str, open_pos: int):
    """从 src[open_pos] == '{' 起做花括号配对，返回闭合位置（含）。找不到返回 -1。"""
    depth = 0
    for i in range(open_pos, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return i
    return -1


# ---------------------------------------------------------------- 规则表

# 必须成对释放的资源: 构造函数名 -> 释放调用名
DISPOSABLES = {
    'AnimationController': 'dispose',
    'TextEditingController': 'dispose',
    'ScrollController': 'dispose',
    'PageController': 'dispose',
    'TabController': 'dispose',
    'FocusNode': 'dispose',
    'ValueNotifier': 'dispose',
    'ChangeNotifier': 'dispose',
    'StreamController': 'close',
    'OverlayEntry': 'remove',
    'ReceivePort': 'close',
    'CarouselController': 'dispose',
    'TransformationController': 'dispose',
    'VideoPlayerController': 'dispose',
    'WebViewController': 'dispose',
    'AudioPlayer': 'dispose',
    'CameraController': 'dispose',
}

# 只有"批量读写"才是真正阻塞 UI 线程的同步 IO。
# 注意：existsSync / statSync / lastModifiedSync 这类元数据操作，官方 lint 规则
# avoid_slow_async_io 反而**推荐**用同步版本（异步版在 dart:io 里更慢），
# 所以不能把它们当成"同步 IO 阻塞 UI"来报——那是把规范讲反了。
SYNC_IO = re.compile(
    r'\b\w*(?:readAsString|readAsBytes|readAsLines|writeAsString|writeAsBytes)Sync\s*\(')

SYNC_IO_META = re.compile(
    r'\b\w*(?:exists|stat|lastModified|length|type)Sync\s*\(')

HEAVY_MAIN_THREAD = re.compile(
    r'\b(jsonDecode|jsonEncode|json\.decode|json\.encode|utf8\.decode|utf8\.encode|'
    r'base64Decode|base64Encode|sha256\.convert|md5\.convert|gzip\.|inflate|deflate)\s*\(')

RENDER_COST = re.compile(r'\b(Opacity|BackdropFilter|ImageFiltered|ClipPath|ShaderMask)\s*\(')

DIRECT_IO_DEP = re.compile(
    r'\b(http\.(get|post|put|delete|patch)|Dio\s*\(|dio\.(get|post|put|delete)|'
    r'openDatabase\s*\(|SharedPreferences\.getInstance|Hive\.(box|openBox)|'
    r'FirebaseFirestore\.instance|HttpClient\s*\()')

# 一次网络调用的样子。宁可宽一点，后面都要 Read 原文复核。
NET_CALL = re.compile(
    r'\b(?:http|dio|_client|client|_dio|_http|api|_api|repository|_repository|service|_service)'
    r'\s*[.!?]*\s*(?:get|post|put|patch|delete|head|send|download|upload|request)\s*[<(]'
    # 前缀下划线的私有方法（_loadPhotos）很常见，\b 在 `_` 前不成立，这里用 lookbehind
    r'|(?<![A-Za-z0-9])_?(?:fetch|load|reload|refresh|query|search|sync|submit|upload|download)'
    r'\w*\s*\(')

# 限流/去重/退避的痕迹——出现这些说明作者已经想过并发问题
THROTTLE_HINT = re.compile(
    r'\b(Semaphore|semaphore|pool|Pool|chunk|batch|slice|sublist|take\s*\(|'
    r'concurrency|maxConcurrent|limit|throttle|debounce|Debouncer|CancelToken|'
    r'inFlight|_inflight|pending|backoff|retryDelay|maxConnectionsPerHost)\b')


# 结构归一化时保留的 token：Dart 关键字与最常见的 SDK / Flutter 标识符。
# 其余标识符一律替换成 `_`，于是"复制后改名"的代码块会归一到同一个形状。
STRUCT_KEEP = set('''
abstract as assert async await break case catch class const continue covariant default deferred do
dynamic else enum export extends extension external factory false final finally for get hide if
implements import in interface is late library mixin new null on operator part required rethrow
return sealed set show static super switch sync this throw true try typedef var void while with yield
int double num bool String List Map Set Iterable Future Stream Object Function Duration DateTime
Widget StatelessWidget StatefulWidget State BuildContext Key setState build initState dispose
override context widget child children super key value index length add remove clear map where
toList toString fromJson toJson json data id name type
'''.split())

_IDENT = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')
_NUM = re.compile(r'\b\d[\d._eE+-]*\b')


def normalized_lines(clean: str):
    """返回 [(行号, 字面文本, 结构文本)]，跳过空行和纯括号行。

    字面文本用来找逐字复制；结构文本把自定义标识符和数字抹平，
    用来找"复制一份再改个名字"的重复——后者在业务代码里其实更常见，
    也更危险：某一份修了 bug，其他几份没修，几个月后没人记得还有几份。
    """
    out = []
    for i, ln in enumerate(clean.splitlines(), 1):
        s = re.sub(r'\s+', ' ', ln.strip())
        if len(s) < 4 or s in ('{', '}', '});', '),', ');', '};'):
            continue
        # import / export / part 是声明，不是"可以封装掉的重复代码"
        if re.match(r'(import|export|part|library)\b', s):
            continue
        struct = _IDENT.sub(lambda m: m.group(0) if m.group(0) in STRUCT_KEEP else '_', s)
        struct = _NUM.sub('0', struct)
        out.append((i, s, struct))
    return out


def _scan_windows(norm_by_file, idx, window):
    buckets = defaultdict(list)
    for rel, lines in norm_by_file:
        for i in range(len(lines) - window + 1):
            chunk = tuple(t[idx] for t in lines[i:i + window])
            buckets[chunk].append((rel, lines[i][0], lines[i + window - 1][0]))
    groups = []
    for occ in buckets.values():
        # 同一文件内相邻窗口会彼此重叠，先合并成一处，避免"共 43 处"这种假象
        merged, last = [], {}
        for f, s, e in sorted(occ):
            prev = last.get(f)
            if prev is not None and s <= prev[2]:
                continue
            last[f] = (f, s, e)
            merged.append((f, s, e))
        if len(merged) >= 2:
            groups.append(merged)
    groups.sort(key=lambda o: (-len(o), o[0][0], o[0][1]))
    return groups


def _greedy_pick(groups, covered):
    """窗口逐行滑动会产生大量重叠的同一处重复，只保留最先出现的那个窗口。"""
    picked = []
    for occ in groups:
        if any((f, ln) in covered for f, s, e in occ for ln in range(s, e + 1)):
            continue
        for f, s, e in occ:
            covered.update((f, ln) for ln in range(s, e + 1))
        picked.append(occ)
    return picked


def find_duplicates(norm_by_file, window=6, struct_window=10):
    """两轮检测：先逐字重复，再在剩余代码上找结构重复（复制后改名）。

    返回 (逐字重复组, 结构重复组, 被重复覆盖的行数)。
    """
    covered = set()
    literal = _greedy_pick(_scan_windows(norm_by_file, 1, window), covered)
    structural = _greedy_pick(_scan_windows(norm_by_file, 2, struct_window), covered)
    return literal, structural, len(covered)


def analyse_timers(body, offset, clean, rel, cname, dispose_body, has_dispose, results):
    """Timer 专项：能不能停、会不会重复启动、回调里干了什么。

    Timer 同时踩内存、UI、网络三条线，所以单独查一遍：
      - 停不掉：返回值没被接住，或没在 dispose 里 cancel
      - 重复启动：没 cancel 旧的又建新的，于是 N 个 Timer 一起跑，
        setState 和网络请求都变成 N 倍——这类 bug 最隐蔽，因为每个单独看都对
      - 回调太重：周期性 setState 全页 rebuild，或周期性发请求
    """
    ranges = method_ranges(body)
    fields = set()

    for m in re.finditer(r'\bTimer\s*(\.\s*periodic|\.\s*run)?\s*\(', body):
        kind = (m.group(1) or '').replace(' ', '') or '一次性'
        periodic = kind == '.periodic'
        pos = m.end() - 1
        close = match_paren(body, pos)
        args = body[pos:close + 1] if close != -1 else body[pos:pos + 300]
        ln = line_of(clean, offset + m.start())
        meth = enclosing_method(ranges, m.start())
        mname = meth[0] if meth else '<类体>'

        # 返回值有没有被字段接住
        head = body[max(0, m.start() - 80):m.start()]
        fm = re.search(r'(\w+)\s*=\s*$', head.replace('await ', ''))
        field = fm.group(1) if fm else None
        if field:
            fields.add(field)

        if not field and periodic:
            results['timer'].append({
                'file': rel, 'line': ln, 'class': cname,
                'snippet': f'Timer{kind}(...) 返回值未接收',
                'note': f'在 {mname}() 里创建周期性 Timer 但没有保存返回值，'
                        f'**这个 Timer 永远无法 cancel**——只能等进程结束。必报'})

        # 重复启动：不是在 initState/构造里建的，且创建前没有 cancel 旧的
        if field and mname != 'initState':
            scope = body[meth[1]:m.start()] if meth else body[:m.start()]
            cancelled_first = re.search(
                re.escape(field) + r'\s*[?!]?\s*\.\s*cancel\s*\(', scope)
            if not cancelled_first:
                results['timer'].append({
                    'file': rel, 'line': ln, 'class': cname,
                    'snippet': f'{field} = Timer{kind}(...) in {mname}()',
                    'note': f'在 {mname}() 中创建 Timer，但这之前没有 {field}?.cancel()。'
                            f'{mname}() 若被调用多次（didUpdateWidget、重试、'
                            f'生命周期 resume、下拉刷新都可能），旧 Timer 不会停，'
                            f'变成 N 个 Timer 并行——setState 和网络请求都翻 N 倍。'
                            f'确认该方法的调用次数'})

        # 能不能停
        if field and not re.search(re.escape(field) + r'\s*[?!]?\s*\.\s*cancel\s*\(',
                                   dispose_body):
            results['timer'].append({
                'file': rel, 'line': ln, 'class': cname,
                'snippet': f'{field}.cancel() 不在 dispose 中',
                'note': ('该类没有 dispose()/close() 方法' if not has_dispose
                         else 'dispose() 中未见 cancel()')
                        + '。周期性 Timer 会在页面销毁后继续触发回调，'
                          '典型表现是 setState() called after dispose 崩溃 + 请求继续发'})

        # 回调里干了什么
        cb_setstate = 'setState' in args
        cb_net = bool(NET_CALL.search(args))
        ms = duration_ms(args)
        rate = f'{1000 / ms:.1f} 次/秒' if ms and ms > 0 else '周期未知'

        if periodic and cb_setstate:
            guarded = 'mounted' in args
            results['timer'].append({
                'file': rel, 'line': ln, 'class': cname,
                'snippet': f'周期 setState（{rate}）',
                'note': f'周期性 setState 会按 {rate} 触发整个 State 的 rebuild。'
                        + ('回调内未见 mounted 判断，销毁后触发必崩。' if not guarded else '')
                        + '若只有小部件要变，改用 ValueNotifier + ValueListenableBuilder 局部刷新'})
        if periodic and cb_net:
            results['timer'].append({
                'file': rel, 'line': ln, 'class': cname,
                'snippet': f'周期性发请求（{rate}）',
                'note': f'按 {rate} 发起请求：上一次没返回时下一次照发，弱网下持续堆积。'
                        f'改成"完成后再排下一次"（递归 Future.delayed），或加 in-flight 跳过'})
        if periodic and ms is not None and ms < 200:
            results['timer'].append({
                'file': rel, 'line': ln, 'class': cname,
                'snippet': f'周期仅 {ms:.0f}ms（{rate}）',
                'note': '高频周期任务。若回调涉及 setState / IO / 计算，'
                        '单帧预算 16.6ms 很容易被吃掉；确认回调实际开销'})

    # 递归自驱动的伪 Timer：停不掉也看不见
    for m in re.finditer(r'Future\s*\.\s*delayed\s*\(', body):
        close = match_paren(body, m.end() - 1)
        seg = body[m.start():close + 1] if close != -1 else body[m.start():m.start() + 300]
        meth = enclosing_method(ranges, m.start())
        if meth and re.search(r'(?<![A-Za-z0-9])' + re.escape(meth[0]) + r'\s*\(', seg):
            results['timer'].append({
                'file': rel, 'line': line_of(clean, offset + m.start()), 'class': cname,
                'snippet': f'{meth[0]}() 通过 Future.delayed 自我递归',
                'note': '用递归 Future.delayed 模拟轮询：没有 Timer 句柄，无法 cancel，'
                        '只能靠标志位停。确认有没有停止条件，以及销毁后会不会继续跑'})

    if len(fields) >= 2:
        results['timer'].append({
            'file': rel, 'line': line_of(clean, offset), 'class': cname,
            'snippet': f'同一个类持有 {len(fields)} 个 Timer: {", ".join(sorted(fields))}',
            'note': '多个周期任务并存，回调可能互相叠加。确认它们的周期和各自的停止路径'})


def analyse_concurrency(clean, rel, results):
    """网络请求并发相关的线索。

    并发失控的破坏力和数据量成正比：本地调试 3 条数据看不出问题，
    线上 500 条就同时打出 500 个请求——连接池排队、后端限流、超时重试雪崩。
    所以这里的线索几乎都要结合"这个集合运行时能有多大"来判断。
    """
    has_net = bool(NET_CALL.search(clean))

    # 1) Future.wait 对一个集合做无上限扇出
    for m in re.finditer(r'Future\s*\.\s*wait\s*\(', clean):
        seg = clean[m.start():m.start() + 320]
        if re.search(r'\.\s*map\s*\(|\bfor\s*\(', seg) and not THROTTLE_HINT.search(seg):
            results['net_concurrency'].append({
                'file': rel, 'line': line_of(clean, m.start()), 'snippet': 'Future.wait(...map...)',
                'note': '对整个集合一次性扇出，并发数 = 集合长度，无上限。'
                        '需确认该集合运行时最大有多少元素；不是常数就要分批或加并发闸门'})

    # 2) 列表 itemBuilder 里发请求（N+1：滚动即刷屏式请求）
    for m in re.finditer(r'itemBuilder\s*:', clean):
        # 只看 itemBuilder 这个闭包自己的函数体，别把后面的兄弟节点也算进来
        brace = clean.find('{', m.end())
        arrow = clean.find('=>', m.end())
        if brace != -1 and (arrow == -1 or brace < arrow) and brace - m.end() < 60:
            close = match_block(clean, brace)
            seg = clean[brace:close + 1] if close != -1 else clean[brace:brace + 400]
        else:
            seg = clean[m.end():m.end() + 250]
        if re.search(r'FutureBuilder|StreamBuilder', seg) or NET_CALL.search(seg):
            results['net_concurrency'].append({
                'file': rel, 'line': line_of(clean, m.start()), 'snippet': 'itemBuilder 内发起请求',
                'note': '每个可见 item 各发一次请求（N+1）。快速滚动时瞬间并发几十个，'
                        '且滑出屏幕后请求不会取消。应在上层一次性批量取数据后再渲染'})

    # 3) 循环里发请求且没有 await（fire-and-forget 并发风暴）
    for m in re.finditer(r'\b(?:for\s*\([^)]{0,120}\)|\.\s*forEach\s*\()\s*\{?', clean):
        body = clean[m.end():m.end() + 400]
        stop = body.find('\n  }')
        body = body if stop == -1 else body[:stop]
        if NET_CALL.search(body) and 'await' not in body and not THROTTLE_HINT.search(body):
            results['net_concurrency'].append({
                'file': rel, 'line': line_of(clean, m.start()), 'snippet': '循环内疑似未 await 的调用',
                'note': '循环里发起请求但没有 await：要么是无上限并发，要么是 fire-and-forget '
                        '（异常无人接管）。确认被调用方是否返回 Future'})

    # 4) 每次调用新建 client（连接无法复用，每次重新 TCP+TLS 握手）
    for m in re.finditer(r'^([ \t]+).*?=\s*(?:http\.Client|Dio|HttpClient)\s*\(', clean, re.M):
        if len(m.group(1).expandtabs(2)) >= 4:      # 缩进 >=4 基本可判定在方法体内
            results['net_concurrency'].append({
                'file': rel, 'line': line_of(clean, m.start()), 'snippet': '方法体内新建 client',
                'note': '疑似每次请求新建 client：连接池和 keep-alive 失效，每次都要重新握手，'
                        '且旧 client 未 close。应复用一个长生命周期实例'})

    # 5) Timer 相关的并发问题交给 analyse_timers 专项处理，这里不重复报

    # 6) 输入触发的请求没有防抖
    if has_net and re.search(r'onChanged\s*:', clean) and not THROTTLE_HINT.search(clean):
        m = re.search(r'onChanged\s*:', clean)
        results['net_concurrency'].append({
            'file': rel, 'line': line_of(clean, m.start()), 'snippet': 'onChanged + 网络调用',
            'note': '输入框变更可能直接触发请求，文件内未见 debounce/Timer 节流痕迹：'
                    '每敲一个字符发一个请求。需确认 onChanged 回调里到底做了什么'})

    # 7) 滚动分页没有 in-flight 守卫
    if re.search(r'addListener|onNotification|NotificationListener', clean) and has_net:
        if not re.search(r'_?(is)?(loading|fetching|busy|requesting|inFlight)\b', clean, re.I):
            m = re.search(r'addListener|onNotification|NotificationListener', clean)
            results['net_concurrency'].append({
                'file': rel, 'line': line_of(clean, m.start()), 'snippet': '滚动回调 + 网络调用',
                'note': '疑似滚动触底加载但没有 loading 守卫标志：滚动回调每帧都触发，'
                        '同一页会被重复请求多次。需确认加载入口有无去重'})

    # 8) 重试没有退避
    for m in re.finditer(r'\b(retry|_retry|attempt|reconnect)\w*\s*[({]', clean):
        seg = clean[max(0, m.start() - 200):m.start() + 300]
        if not re.search(r'backoff|Duration\s*\(|delay|pow\s*\(|maxRetr|attempts?\s*[<>=]', seg):
            results['net_concurrency'].append({
                'file': rel, 'line': line_of(clean, m.start()), 'snippet': m.group(0).strip(),
                'note': '疑似重试逻辑但附近未见延迟/退避/次数上限：'
                        '批量请求同时失败会同时重试，形成雪崩'})

    # 9) 拦截器里的耗时操作 —— 开销会乘以请求总数，且跑在 UI isolate 上
    for m in re.finditer(r'\b(onRequest|onResponse|onError)\s*\([^)]*\)\s*(?:async\s*)?\{', clean):
        hook = m.group(1)
        be = match_block(clean, m.end() - 1)
        if be == -1:
            continue
        body = clean[m.end() - 1:be + 1]
        ln = line_of(clean, m.start())
        heavy = []
        if re.search(r'\b(print|debugPrint)\s*\(', body) and \
                re.search(r'jsonEncode|\.data|\.body|toString\s*\(\s*\)', body):
            heavy.append('打印响应/请求体（每个请求一次完整序列化）')
        if HEAVY_MAIN_THREAD.search(body):
            heavy.append('编解码/哈希')
        if SYNC_IO.search(body):
            heavy.append('同步文件读写')
        if re.search(r'SharedPreferences\.getInstance|openDatabase|Hive\.(box|openBox)', body):
            heavy.append('每次请求都读存储')
        if re.search(r'\bfor\s*\(|\.\s*map\s*\(', body):
            heavy.append('循环/遍历')
        if heavy:
            results['net_concurrency'].append({
                'file': rel, 'line': ln, 'snippet': f'{hook}() 内: ' + '、'.join(heavy),
                'note': '拦截器是全局放大器：这里的开销乘以请求总数，且在 UI isolate 上执行。'
                        '逐行问"这行乘以一万次请求还能接受吗"'})
        if not re.search(r'handler\s*\.\s*(next|resolve|reject)\s*\(', body):
            results['net_concurrency'].append({
                'file': rel, 'line': ln, 'snippet': f'{hook}() 未调用 handler',
                'note': '拦截器每条路径都必须恰好调用一次 handler.next/resolve/reject，'
                        '否则请求永久挂起——表现为"点了没反应"，不报错也不超时'})
        elif re.search(r'\bif\s*\(', body) and \
                len(re.findall(r'handler\s*\.\s*(?:next|resolve|reject)\s*\(', body)) == 1:
            results['net_concurrency'].append({
                'file': rel, 'line': ln, 'snippet': f'{hook}() 有分支但只有 1 处 handler 调用',
                'note': '存在分支却只调用了一次 handler：确认每条路径都会走到，'
                        '漏掉的那条会让请求永久挂起'})

    # 10) 新请求发起前没有取消旧的
    if 'CancelToken' in clean:
        for m in re.finditer(r'(\w*[Tt]oken\w*)\s*=\s*CancelToken\s*\(', clean):
            field = m.group(1)
            head = clean[max(0, m.start() - 400):m.start()]
            if not re.search(re.escape(field) + r'\s*[?!]?\s*\.\s*cancel\s*\(', head):
                results['net_concurrency'].append({
                    'file': rel, 'line': line_of(clean, m.start()),
                    'snippet': f'{field} = CancelToken() 前未见 cancel()',
                    'note': f'创建新 CancelToken 前没有先 {field}?.cancel() 掉旧的，'
                            f'等于没用取消能力：旧请求继续占用连接和流量，'
                            f'其响应还可能后到并覆盖新数据'})
        if not re.search(r'CancelToken\s*\.\s*isCancel\s*\(', clean):
            m = re.search(r'CancelToken', clean)
            results['net_concurrency'].append({
                'file': rel, 'line': line_of(clean, m.start()),
                'snippet': '用了 CancelToken 但未见 CancelToken.isCancel 判断',
                'note': '主动取消会抛 DioException，若不用 isCancel 过滤，'
                        '会被当成网络错误提示给用户——用户什么都没做错却看到报错'})

    # 11) 大 JSON 解析后紧跟 fromJson 映射，两段都在主线程
    for m in re.finditer(r'(jsonDecode|json\.decode)\s*\(', clean):
        seg = clean[m.start():m.start() + 400]
        if re.search(r'\.\s*map\s*\(', seg) and 'fromJson' in seg and 'compute' not in seg:
            results['net_concurrency'].append({
                'file': rel, 'line': line_of(clean, m.start()),
                'snippet': 'jsonDecode + map(fromJson) 同在主线程',
                'note': '解析和对象构造两段都在 UI isolate。大列表接口足以造成可见卡顿。'
                        '修：Dio 配 BackgroundTransformer，或 ResponseType.plain + '
                        'compute 一次做完 decode+映射。**影响取决于返回条数，先确认接口分页上限**'})

    # 12) http 包不判 statusCode 直接解析（4xx/5xx 不抛异常，会解析到错误页）
    for m in re.finditer(r'(\w+)\s*=\s*await\s+[\w.]*\.\s*(?:get|post|put|patch|delete)\s*\(', clean):
        var = m.group(1)
        seg = clean[m.end():m.end() + 500]
        uses_body = re.search(r'(jsonDecode|json\.decode)\s*\(\s*' + re.escape(var) + r'\s*\.\s*body',
                              seg)
        if uses_body and 'statusCode' not in seg:
            results['net_concurrency'].append({
                'file': rel, 'line': line_of(clean, m.start()),
                'snippet': f'{var}.body 直接 jsonDecode，未判 statusCode',
                'note': 'package:http 对 4xx/5xx **不抛异常**，照常返回响应。'
                        '服务端报错时这里会去解析一个 HTML 错误页 → FormatException，'
                        '且错误信息完全误导。必须先判 statusCode'})

    # 13) 请求没有被 try 接住 —— 精度较低（异常可能由上层接住），按文件聚合成一条，避免刷屏
    untried = [line_of(clean, m.start())
               for m in re.finditer(r'await\s+(?:dio|_dio|client|_client|http)\s*\.\s*'
                                    r'(?:get|post|put|patch|delete)\s*[<(]', clean)
               if not re.search(r'\btry\s*\{', clean[max(0, m.start() - 600):m.start()])]
    if untried:
        results['net_concurrency'].append({
            'file': rel, 'line': untried[0],
            'snippet': f'{len(untried)} 处请求调用未见 try 包裹',
            'note': '行 ' + ', '.join(map(str, untried[:12]))
                    + ('…' if len(untried) > 12 else '')
                    + '。附近没有 try，请求失败的异常会逃逸。**这条精度低**：'
                      '异常可能由调用链上层接住，必须顺着调用方确认，别直接下结论'})

    # 14) HttpClient 未限制每主机连接数
    if re.search(r'\bHttpClient\s*\(', clean) and 'maxConnectionsPerHost' not in clean:
        m = re.search(r'\bHttpClient\s*\(', clean)
        results['net_concurrency'].append({
            'file': rel, 'line': line_of(clean, m.start()), 'snippet': 'HttpClient()',
            'note': 'dart:io 的 HttpClient 默认不限制单主机并发连接数。'
                    '高并发场景建议显式设 maxConnectionsPerHost（浏览器惯例为 6）'})


def rule_hits(pattern, clean, path, note, results, key):
    for m in pattern.finditer(clean):
        results[key].append({
            'file': path, 'line': line_of(clean, m.start()),
            'snippet': m.group(0).strip(), 'note': note,
        })


# ---------------------------------------------------------------- 单文件分析

SOURCE = {}          # rel -> 原始行列表，用于输出证据片段
DISPOSE_BODIES = {}  # (rel, 类名) -> (起始行, dispose 方法原文)


def evidence(rel, line, before=0, after=0):
    """取某一行前后的原文，带行号。让审计者不必为了看一眼而单独 Read 一次文件。"""
    src = SOURCE.get(rel)
    if not src or not line:
        return []
    lo, hi = max(1, line - before), min(len(src), line + after)
    return [f'      {i:>4}| {src[i - 1].rstrip()}' for i in range(lo, hi + 1)]


def analyse_file(path: str, rel: str, results: dict):
    try:
        raw = open(path, encoding='utf-8', errors='replace').read()
    except OSError as e:
        print(f'  [skip] {rel}: {e}', file=sys.stderr)
        return

    clean = blank_noise(raw)
    lines = raw.splitlines()
    SOURCE[rel] = lines
    nloc = len(lines)

    results['files'].append({'file': rel, 'lines': nloc})
    results['_norm'].append((rel, normalized_lines(clean)))
    if nloc > 500:
        results['long_files'].append({'file': rel, 'lines': nloc,
                                      'note': f'文件 {nloc} 行，疑似职责过多'})

    if rel.endswith(('.g.dart', '.freezed.dart', '.gr.dart', '.config.dart',
                     '.pb.dart', '.mocks.dart')):
        results['generated'].append({'file': rel, 'lines': nloc})
        return

    # ---- 类块切分（配对分析的基础）
    for cm in re.finditer(r'\bclass\s+(\w+)[^{;]*?\{', clean):
        cname = cm.group(1)
        header = clean[cm.start():cm.end()]
        body_start = cm.end() - 1
        body_end = match_block(clean, body_start)
        if body_end == -1:
            continue
        body = clean[body_start:body_end + 1]
        offset = body_start
        is_state = bool(re.search(r'extends\s+State\s*<', header))
        is_notifier = bool(re.search(r'(extends|with)\s+\w*(ChangeNotifier|StateNotifier|Bloc|Cubit)',
                                     header))

        # dispose 方法体（State / ChangeNotifier 都可能有）
        dm = re.search(r'\bvoid\s+dispose\s*\(\s*\)\s*(?:async\s*)?\{', body)
        dispose_body, has_dispose = '', False
        if dm:
            de = match_block(body, dm.end() - 1)
            if de != -1:
                dispose_body = body[dm.end() - 1:de + 1]
                has_dispose = True
                # 记下 dispose 原文：核实"资源有没有被释放"只需要看这一段，
                # 把它直接打出来，审计者就不用为每条线索单独 Read 一次文件
                dl = line_of(clean, offset + dm.start())
                chunk = evidence(rel, dl, 0, dispose_body.count('\n') + 1)
                # dispose 里如果调了私有方法，真正的释放很可能在那里面——
                # 一并打出来，省掉"跟进去看"那一次 Read
                for name in set(re.findall(r'(_\w+)\s*\(\s*\)', dispose_body)):
                    for mn, ms, me in method_ranges(body):
                        if mn != name:
                            continue
                        ml = line_of(clean, offset + ms)
                        chunk.append(f'      ── dispose 调用的 {name}()（{rel}:{ml}）──')
                        chunk += evidence(rel, ml, 0, body[ms:me].count('\n'))
                DISPOSE_BODIES[(rel, cname)] = (dl, '\n'.join(chunk))

        if is_state or is_notifier:
            # 资源创建点 -> 找承载它的字段名
            for typ, release in DISPOSABLES.items():
                for m in re.finditer(r'(\w+)\s*=\s*(?:await\s+)?' + typ + r'[.\w]*\s*\(', body):
                    field = m.group(1)
                    ln = line_of(clean, offset + m.start())
                    released = bool(re.search(
                        re.escape(field) + r'[\s?!.]*\.\s*' + release + r'\s*\(', dispose_body))
                    # 间接释放：dispose 里调了别的私有方法
                    indirect = bool(re.search(r'_\w+\s*\(\s*\)\s*;', dispose_body))
                    if not released:
                        results['unreleased'].append({
                            'file': rel, 'line': ln, 'class': cname,
                            'field': field, 'type': typ, 'expect': f'{field}.{release}()',
                            'has_dispose': has_dispose, 'indirect_calls': indirect,
                            'note': ('dispose() 中未直接出现释放调用'
                                     + ('；但 dispose 内调用了其他私有方法，可能间接释放，务必跟进去看'
                                        if indirect else
                                        ('；该类没有 dispose() 方法' if not has_dispose else ''))),
                        })

            # StreamSubscription
            for m in re.finditer(r'(\w+)\s*=\s*[\w.$\[\]()]*\.listen\s*\(', body):
                field = m.group(1)
                ln = line_of(clean, offset + m.start())
                if not re.search(re.escape(field) + r'[\s?!.]*\.\s*cancel\s*\(', dispose_body):
                    results['unreleased'].append({
                        'file': rel, 'line': ln, 'class': cname, 'field': field,
                        'type': 'StreamSubscription', 'expect': f'{field}.cancel()',
                        'has_dispose': has_dispose, 'indirect_calls': False,
                        'note': 'dispose() 中未出现 cancel()',
                    })

            # Timer 不在这里查，交给下面的 analyse_timers 专项处理

        analyse_timers(body, offset, clean, rel, cname, dispose_body, has_dispose, results)

        # addListener / removeListener 配对
        for m in re.finditer(r'([\w.$]+)\s*\.\s*addListener\s*\(\s*([^),]*)', body):
            target, cb = m.group(1), m.group(2).strip()
            ln = line_of(clean, offset + m.start())
            anon = cb.startswith('(') or cb.startswith('{') or cb == ''
            removed = bool(re.search(re.escape(target.split('.')[-1]) + r'\s*\.\s*removeListener',
                                     body))
            if anon:
                results['listener'].append({
                    'file': rel, 'line': ln, 'class': cname, 'target': target,
                    'note': '传入匿名闭包，removeListener 无法移除同一实例（闭包不等价）'})
            elif not removed:
                results['listener'].append({
                    'file': rel, 'line': ln, 'class': cname, 'target': target,
                    'note': f'{target}.addListener 无对应 removeListener'})

        for m in re.finditer(r'addObserver\s*\(', body):
            ln = line_of(clean, offset + m.start())
            if 'removeObserver' not in body:
                results['listener'].append({
                    'file': rel, 'line': ln, 'class': cname, 'target': 'WidgetsBinding',
                    'note': 'addObserver 无对应 removeObserver'})

        # build 方法体积与内容
        bm = re.search(r'Widget\s+build\s*\(\s*BuildContext[^)]*\)\s*\{', body)
        if bm:
            be = match_block(body, bm.end() - 1)
            if be != -1:
                bbody = body[bm.end() - 1:be + 1]
                blines = bbody.count('\n') + 1
                bstart_line = line_of(clean, offset + bm.start())
                if blines > 80:
                    results['long_build'].append({
                        'file': rel, 'line': bstart_line, 'class': cname, 'lines': blines,
                        'note': f'build 方法 {blines} 行，rebuild 边界过粗'})
                for m in re.finditer(
                        r'=\s*(?:new\s+)?(\w*Controller|Timer|StreamController)\s*\(', bbody):
                    results['build_alloc'].append({
                        'file': rel, 'line': line_of(clean, offset + bm.start() + m.start()),
                        'class': cname, 'snippet': m.group(0).strip(),
                        'note': '在 build 内创建有状态对象，每次 rebuild 都会重建'})
                for m in re.finditer(r'(future|stream)\s*:\s*(?!_|\w+\.\w*$)[\w.]+\s*\(', bbody):
                    results['build_alloc'].append({
                        'file': rel, 'line': line_of(clean, offset + bm.start() + m.start()),
                        'class': cname, 'snippet': m.group(0).strip(),
                        'note': 'FutureBuilder/StreamBuilder 的数据源在 build 内创建，每次 rebuild 都会重新发起'})

        # 静态字段持有短生命周期对象
        for m in re.finditer(r'\bstatic\s+[\w<>?, ]*\b(BuildContext|State|GlobalKey|Widget)\b',
                             body):
            results['static_hold'].append({
                'file': rel, 'line': line_of(clean, offset + m.start()), 'class': cname,
                'snippet': m.group(0).strip(),
                'note': 'static 字段持有 UI 生命周期对象，可能导致整棵子树无法 GC'})

        # 长方法（非 build）
        for m in re.finditer(r'\n[ \t]*(?:@override\s*\n\s*)?[\w<>?, \[\]]+\s+(\w+)\s*\([^;{]*\)'
                             r'\s*(?:async\s*\*?\s*)?\{', body):
            name = m.group(1)
            if name in ('build', 'if', 'for', 'while', 'switch', 'catch', 'return'):
                continue
            me = match_block(body, m.end() - 1)
            if me == -1:
                continue
            mlines = body[m.end() - 1:me + 1].count('\n') + 1
            if mlines > 80:
                results['long_method'].append({
                    'file': rel, 'line': line_of(clean, offset + m.start()), 'class': cname,
                    'method': name, 'lines': mlines, 'note': f'方法 {mlines} 行'})

    # ---- 文件级规则（不依赖类块）

    # 长列表构建方式：children 由动态集合展开
    for m in re.finditer(r'\b(ListView|GridView|Column|SingleChildScrollView)\s*\('
                         r'(?![^()]{0,60}\bbuilder\b)[^;]{0,400}?children\s*:\s*(.{0,80})',
                         clean, re.S):
        tail = m.group(2)
        if re.search(r'\.\s*map\s*\(|\bfor\s*\(\s*(final|var|int)\b|\.\.\.\w', tail):
            results['eager_list'].append({
                'file': rel, 'line': line_of(clean, m.start()), 'widget': m.group(1),
                'note': f'{m.group(1)}(children:) 由动态集合展开，全部子项立即构建且常驻；'
                        f'需确认数据量。量大时应改 ListView.builder / SliverList'})

    # 无上限的静态缓存
    for m in re.finditer(r'\bstatic\s+(?:final|late\s+final|const)?\s*'
                         r'(Map|List|Set|HashMap|LinkedHashMap)\s*<[^;={}]{0,120}>\s*(\w+)',
                         clean):
        coll, name = m.group(1), m.group(2)
        if re.search(r'\bconst\b', clean[max(0, m.start() - 40):m.start() + 40]):
            continue
        has_evict = bool(re.search(re.escape(name) + r'\s*\.\s*(clear|remove|removeWhere)\s*\(',
                                   clean))
        results['static_cache'].append({
            'file': rel, 'line': line_of(clean, m.start()), 'snippet': f'static {coll} {name}',
            'note': f'静态集合 {name} 生命周期与进程等长'
                    + ('；文件内未见 clear/remove，疑似无上限增长'
                       if not has_evict else '；文件内有清理调用，需确认是否覆盖所有增长路径')})

    # enum switch 带 default（新增枚举值时静默走 default）
    for m in re.finditer(r'switch\s*\([^)]*\)\s*\{', clean):
        se = match_block(clean, m.end() - 1)
        if se == -1:
            continue
        sbody = clean[m.end() - 1:se + 1]
        if re.search(r'\bcase\s+\w+\.\w+\s*:', sbody) and re.search(r'\bdefault\s*:', sbody):
            results['enum_switch'].append({
                'file': rel, 'line': line_of(clean, m.start()), 'snippet': 'switch(...) + default',
                'note': '对枚举 switch 带 default 兜底，新增枚举值时编译器不再报错，会静默走 default'})

    # 未被引用的私有成员（同文件内只出现一次 = 只有声明）
    for m in re.finditer(r'\n\s*(?:static\s+)?(?:final\s+|const\s+)?[\w<>?, \[\]]+\s+'
                         r'(_\w+)\s*[({=;]', clean):
        name = m.group(1)
        if len(re.findall(r'(?<![\w.])' + re.escape(name) + r'\b', clean)) == 1:
            results['dead_code'].append({
                'file': rel, 'line': line_of(clean, m.start()), 'snippet': name,
                'note': f'私有成员 {name} 在本文件内只出现声明处一次，疑似死代码'})

    # 图片解码
    for m in re.finditer(r'\bImage\s*\.\s*(network|file|asset|memory)\s*\([^;]{0,300}', clean):
        if 'cacheWidth' not in m.group(0) and 'cacheHeight' not in m.group(0):
            results['image'].append({
                'file': rel, 'line': line_of(clean, m.start()),
                'snippet': f'Image.{m.group(1)}(...)',
                'note': '未设 cacheWidth/cacheHeight，按原始像素解码；大图或列表场景内存开销大'})

    # await 之后使用 context
    for m in re.finditer(r'\bawait\b', clean):
        seg = clean[m.end():m.end() + 400]
        stop = seg.find('\n}')
        seg = seg if stop == -1 else seg[:stop]
        cm2 = re.search(r'\b\w+\s*\.\s*of\s*\(\s*context\b|\bNavigator\s*\.\s*\w+\s*\(\s*context',
                        seg)
        if cm2:
            head = clean[max(0, m.start() - 300):m.start()]
            if 'mounted' not in seg[:cm2.start()] and 'mounted' not in head[-120:]:
                results['async_context'].append({
                    'file': rel, 'line': line_of(clean, m.end() + cm2.start()),
                    'snippet': cm2.group(0).strip(),
                    'note': 'await 之后使用 context，未见 mounted 检查'})

    # initState 里用 InheritedWidget
    im = re.search(r'\bvoid\s+initState\s*\(\s*\)\s*\{', clean)
    if im:
        ie = match_block(clean, im.end() - 1)
        if ie != -1:
            ibody = clean[im.end() - 1:ie + 1]
            for m in re.finditer(r'\b(Theme|MediaQuery|Localizations|DefaultTabController|'
                                 r'Scaffold|Navigator)\s*\.\s*of\s*\(\s*context', ibody):
                results['initstate_context'].append({
                    'file': rel, 'line': line_of(clean, im.end() - 1 + m.start()),
                    'snippet': m.group(0).strip(),
                    'note': 'initState 中访问 InheritedWidget，依赖尚未建立，应移到 didChangeDependencies'})

    analyse_concurrency(clean, rel, results)

    rule_hits(SYNC_IO, clean, rel,
              '同步批量读写文件，直接阻塞 UI 线程；改用 await 的异步版本',
              results, 'main_thread')
    for m in SYNC_IO_META.finditer(clean):
        # 元数据同步调用本身不是问题，但出现在 build() 里仍值得看一眼
        head = clean[max(0, m.start() - 1500):m.start()]
        if re.search(r'Widget\s+build\s*\(', head) and '\n  }' not in head.split(
                'Widget build(')[-1]:
            results['main_thread'].append({
                'file': rel, 'line': line_of(clean, m.start()),
                'snippet': m.group(0).strip(),
                'note': '文件元数据同步调用出现在 build 路径上。注意：官方 lint 规则 '
                        'avoid_slow_async_io 推荐这类操作用同步版本，'
                        '所以**同步本身不是问题**；要看的是它是否每帧都执行'})
    rule_hits(HEAVY_MAIN_THREAD, clean, rel,
              '编解码/哈希调用，数据量大时应移入 compute/Isolate（小数据不必）',
              results, 'main_thread')
    rule_hits(RENDER_COST, clean, rel, '可能触发 saveLayer / 离屏渲染，大面积使用需评估',
              results, 'render')
    rule_hits(DIRECT_IO_DEP, clean, rel, '直接依赖具体网络/存储实现', results, 'coupling')
    rule_hits(re.compile(r'(?<![.\w])print\s*\('), clean, rel,
              'print 输出（release 仍执行），建议 debugPrint 或日志抽象', results, 'lint')
    rule_hits(re.compile(r'\bPlatform\s*\.\s*is(Android|IOS|MacOS|Windows|Linux|Fuchsia)\b'),
              clean, rel, 'dart:io Platform 判断，web 平台不可用；确认是否需 kIsWeb 兜底',
              results, 'lint')
    rule_hits(re.compile(r'\bMediaQuery\s*\.\s*of\s*\(\s*context\s*\)\s*\.\s*(size|padding|'
                         r'viewInsets|devicePixelRatio|textScale\w*)'),
              clean, rel, '订阅整个 MediaQuery；只取单项时可用 MediaQuery.sizeOf 等避免多余 rebuild',
              results, 'rebuild')
    rule_hits(re.compile(r'catch\s*\([^)]*\)\s*\{\s*\}'), clean, rel,
              '空 catch 块，异常被吞', results, 'lint')
    rule_hits(re.compile(r'\bsetState\s*\('), clean, rel, '', results, '_setstate')

    # 依赖方向：widget 文件里出现 dart:io / 具体实现 import
    for m in re.finditer(r"import\s+'(package:(?:http|dio|sqflite|shared_preferences|hive|"
                         r"firebase_\w+)[^']*|dart:io)'", clean):
        results['coupling'].append({
            'file': rel, 'line': line_of(clean, m.start()), 'snippet': m.group(1),
            'note': 'import 具体实现/平台库；若该文件同时包含 Widget，说明 UI 与实现耦合'})


# ---------------------------------------------------------------- 输出

SECTIONS = [
    ('timer', '【Timer 专项 · 高优先级】能否停止 / 是否重复启动 / 回调是否引发并发 setState 或请求'),
    ('unreleased', '【内存 · 高优先级】资源创建与 dispose 未配对（逐条打开原文确认，注意外部传入的 controller 不该由本类释放）'),
    ('listener', '【内存】监听器注册与注销未配对'),
    ('static_hold', '【内存】static 字段持有 UI 生命周期对象'),
    ('static_cache', '【内存】静态集合缓存（确认是否有上限/淘汰）'),
    ('image', '【内存】图片未限制解码尺寸'),
    ('main_thread', '【卡顿 · 高优先级】主线程上的同步 IO / 重计算'),
    ('build_alloc', '【卡顿】build 内创建有状态对象或数据源'),
    ('long_build', '【卡顿】超长 build 方法'),
    ('eager_list', '【卡顿+内存】动态集合用 children 全量构建'),
    ('rebuild', '【卡顿】rebuild 范围可能过大'),
    ('render', '【卡顿】高开销渲染组件'),
    ('net_concurrency', '【网络并发】请求扇出、节流、去重、取消（结合运行时数据量判断）'),
    ('coupling', '【解耦】直接依赖具体实现'),
    ('export_surface', '【解耦】package 导出面'),
    ('enum_switch', '【解耦】枚举 switch 带 default'),
    ('long_file', '【解耦】超长文件'),
    ('long_method', '【精简/解耦】超长方法'),
    ('duplicate', '【精简】逐字重复代码块（可直接提取复用）'),
    ('struct_dup', '【精简 · 重点】结构重复：复制后改名（同一 bug 要修 N 遍，最该封装）'),
    ('dead_code', '【精简】疑似死代码（本文件内未被引用的私有成员）'),
    ('initstate_context', '【规范】initState 中访问 InheritedWidget'),
    ('async_context', '【规范】await 后使用 context 且无 mounted 检查'),
    ('lint', '【规范 · P3】'),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('package')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--no-evidence', action='store_true',
                    help='不输出证据片段（默认输出，能省掉大量单独 Read）')
    ap.add_argument('--focus', required=True,
                    choices=['memory', 'jank', 'net', 'structure', 'all'],
                    help='分析方向（必填，没有默认值——必须先问过用户）：'
                         'memory=崩溃与内存 jank=UI卡顿 net=网络与并发 '
                         'structure=代码结构 all=全量')
    args = ap.parse_args()

    root = os.path.abspath(args.package)
    lib = os.path.join(root, 'lib')
    if not os.path.isdir(lib):
        print(f'错误: 找不到 {lib}。请传入包含 pubspec.yaml 的 package 根目录。', file=sys.stderr)
        sys.exit(1)

    results = defaultdict(list)
    results['files'] = []
    for dirpath, dirnames, filenames in os.walk(lib):
        dirnames[:] = [d for d in dirnames if d not in ('.dart_tool', 'build', '.git')]
        for fn in sorted(filenames):
            if fn.endswith('.dart'):
                p = os.path.join(dirpath, fn)
                analyse_file(p, os.path.relpath(p, root), results)

    results['long_file'] = results.pop('long_files', [])

    # 重复代码块：逐字重复 + 结构重复（复制后改名）
    literal, structural, dup_lines = find_duplicates(results.pop('_norm', []))
    for occ in literal:
        head = occ[0]
        results['duplicate'].append({
            'file': head[0], 'line': head[1],
            'snippet': f'{head[2] - head[1] + 1}+ 行逐字重复，共 {len(occ)} 处',
            'note': '位置: ' + ' | '.join(f'{f}:{s}-{e}' for f, s, e in occ[:8])
                    + (f' …另 {len(occ) - 8} 处' if len(occ) > 8 else '')})
    for occ in structural:
        head = occ[0]
        files = {f for f, _, _ in occ}
        results['struct_dup'].append({
            'file': head[0], 'line': head[1],
            'snippet': f'{head[2] - head[1] + 1}+ 行结构相同，共 {len(occ)} 处'
                       f'（跨 {len(files)} 个文件）',
            'note': '仅标识符/字面量不同，疑似复制后改名。位置: '
                    + ' | '.join(f'{f}:{s}-{e}' for f, s, e in occ[:8])
                    + (f' …另 {len(occ) - 8} 处' if len(occ) > 8 else '')})
    results['_dup_lines'] = dup_lines

    # 包导出面：lib/ 根目录除 barrel 外不应直接放实现文件
    pkg_name = ''
    try:
        pub = open(os.path.join(root, 'pubspec.yaml'), encoding='utf-8').read()
        nm = re.search(r'^name:\s*(\S+)', pub, re.M)
        pkg_name = nm.group(1) if nm else ''
    except OSError:
        pass
    root_files = [f['file'] for f in results['files']
                  if os.path.dirname(f['file']) == 'lib']
    strays = [f for f in root_files if os.path.basename(f) != f'{pkg_name}.dart']
    if pkg_name and strays:
        results['export_surface'].append({
            'file': 'lib/', 'line': 0, 'snippet': ', '.join(strays),
            'note': f'实现文件直接放在 lib/ 根目录，使用方可直接 import 内部实现；'
                    f'约定做法是移入 lib/src/，根目录只保留 {pkg_name}.dart 做 export'})
    setstate_by_file = defaultdict(int)
    for h in results.pop('_setstate', []):
        setstate_by_file[h['file']] += 1

    if args.json:
        print(json.dumps({k: v for k, v in results.items()}, ensure_ascii=False, indent=2))
        return

    files = results['files']
    total_lines = sum(f['lines'] for f in files)
    print('=' * 72)
    print(f'扫描范围: {os.path.relpath(lib, os.getcwd()) if lib.startswith(os.getcwd()) else lib}')
    print(f'dart 文件: {len(files)} 个，共 {total_lines} 行'
          + (f'（其中生成代码 {len(results["generated"])} 个，已跳过分析）'
             if results['generated'] else ''))
    print('=' * 72)
    print('\n## 文件体量 Top 15（按行数）')
    for f in sorted(files, key=lambda x: -x['lines'])[:15]:
        mark = '  <-- 建议精读' if f['lines'] > 300 else ''
        print(f'  {f["lines"]:>5}  {f["file"]}{mark}')

    dup_lines = results.pop('_dup_lines', 0)
    if dup_lines:
        pct = dup_lines * 100.0 / max(1, total_lines)
        verdict = ('重复率偏高，封装收益大' if pct >= 15 else
                   '重复率中等，挑高频的封装' if pct >= 7 else '重复率不高')
        print(f'\n## 重复度\n  参与重复的代码行: {dup_lines} / {total_lines} '
              f'({pct:.1f}%) —— {verdict}')

    if setstate_by_file:
        print('\n## setState 调用密度（高密度文件值得看 rebuild 范围）')
        for fn, c in sorted(setstate_by_file.items(), key=lambda x: -x[1])[:10]:
            if c >= 3:
                print(f'  {c:>3} 次  {fn}')

    # 分析方向 -> 只输出这些类别的线索。定向分析能显著减少读进上下文的量。
    FOCUS_KEYS = {
        # 「用得太晚」（对象已销毁后还在用）归到崩溃与内存
        'memory': {'timer', 'unreleased', 'listener', 'static_hold', 'static_cache',
                   'image', 'async_context'},
        # 「用得太早」（依赖未建立）和「错误的帧阶段」归到 UI 卡顿
        'jank': {'main_thread', 'build_alloc', 'long_build', 'eager_list', 'rebuild',
                 'render', 'initstate_context'},
        # 竞态、Future 丢弃本来就在 net_concurrency 里
        'net': {'net_concurrency', 'timer'},
        'structure': {'duplicate', 'struct_dup', 'dead_code', 'long_file', 'long_method',
                      'coupling', 'export_surface', 'enum_switch'},
    }
    FOCUS_LABEL = {
        'memory': '① 崩溃与内存（资源泄漏、内存暴涨、销毁后仍在用、运行期崩溃）',
        'jank': '② UI 卡顿（主线程阻塞、setState 时机、rebuild 范围、组件与渲染开销）',
        'net': '③ 网络与并发（扇出、拦截器耗时、旧请求取消、大 JSON 解析、失败异常、竞态）',
        'structure': '④ 代码结构（精简、封装、解耦）',
        'all': '⑤ 全量（以上全部 + 规范与 lint）',
    }
    allow = FOCUS_KEYS.get(args.focus)
    if allow is not None:
        print(f'\n>>> 分析方向: {FOCUS_LABEL[args.focus]}')
        print('>>> 其余方向的线索本次不输出。报告的「分析方向」一栏要如实写明，'
              '并列出未覆盖的方向。')

    total_hits = 0
    for key, title in SECTIONS:
        if allow is not None and key not in allow:
            continue
        hits = results.get(key) or []
        # 同一位置的同一条线索只报一次
        seen, deduped = set(), []
        for h in hits:
            sig = (h.get('file'), h.get('line'), h.get('snippet'), h.get('note'))
            if sig in seen:
                continue
            seen.add(sig)
            deduped.append(h)
        hits = deduped
        if not hits:
            continue
        total_hits += len(hits)
        print(f'\n## {title}  ({len(hits)})')
        shown_dispose = set()
        for h in hits[:60]:
            loc = f'{h["file"]}:{h.get("line", "?")}'
            extra = h.get('expect') or h.get('snippet') or h.get('target') or h.get('method') or ''
            cls = f'[{h["class"]}] ' if h.get('class') else ''
            print(f'  - {loc}  {cls}{extra}')
            if not args.no_evidence:
                for ln in evidence(h['file'], h.get('line'), 0, 1):
                    print(ln)
                # 释放类线索：把 dispose 原文一并打出，核实无需再开文件
                dkey = (h.get('file'), h.get('class'))
                if key in ('unreleased', 'timer', 'listener') and dkey in DISPOSE_BODIES \
                        and dkey not in shown_dispose:
                    shown_dispose.add(dkey)
                    dl, dtext = DISPOSE_BODIES[dkey]
                    print(f'      ── 该类的 dispose()（{h["file"]}:{dl}）──')
                    print(dtext)
                elif key in ('unreleased', 'timer') and dkey not in DISPOSE_BODIES \
                        and dkey not in shown_dispose:
                    shown_dispose.add(dkey)
                    print(f'      ── {h.get("class")} 没有 dispose() 方法 ──')
            if h.get('note'):
                print(f'      -> {h["note"]}')
        if len(hits) > 60:
            print(f'  ... 另有 {len(hits) - 60} 条同类线索')

    # 按命中的类别给出该读哪几节清单——只读用得上的，别整份读进上下文
    KEY_TOPIC = {
        'timer': 'timer', 'unreleased': 'memory', 'listener': 'memory',
        'static_hold': 'memory', 'static_cache': 'memory', 'image': 'memory',
        'main_thread': 'jank', 'build_alloc': 'jank', 'long_build': 'jank',
        'eager_list': 'jank', 'rebuild': 'jank', 'render': 'jank',
        'net_concurrency': 'net', 'coupling': 'decouple', 'export_surface': 'decouple',
        'enum_switch': 'decouple', 'long_file': 'decouple', 'long_method': 'dup',
        'duplicate': 'dup', 'struct_dup': 'dup', 'dead_code': 'dup',
        'initstate_context': 'early', 'async_context': 'norms', 'lint': 'norms',
    }
    # 各方向必读的主题（不管扫描有没有命中，方向选定了这些就得读）
    FOCUS_TOPICS = {
        'memory': ['core', 'memory', 'timer', 'data', 'lint'],
        'jank': ['core', 'jank', 'early', 'excluded'],
        'net': ['core', 'net', 'timer'],
        'structure': ['core', 'dup', 'decouple'],
        'all': ['core'],
    }
    topics = list(FOCUS_TOPICS.get(args.focus, ['core']))
    if args.focus == 'all':
        # 全量时按实际命中扩展；定向分析用固定主题集即可，多读一节就是多花一节的钱
        for key, _ in SECTIONS:
            t = KEY_TOPIC.get(key)
            if results.get(key) and t and t not in topics:
                topics.append(t)
        for t in ('data', 'lint'):   # 这两类扫描抓不全，全量时始终要人工看
            if t not in topics:
                topics.append(t)

    print('\n' + '=' * 72)
    print('## 该读哪几节清单（只读这些，不要整份读进上下文）')
    print(f'  python3 {os.path.join(HERE, "ref.py")} {" ".join(topics)}')
    print('  一次调用取回全部所需章节；写报告前再取 template。')
    print('=' * 72)
    print(f'共 {total_hits} 条线索。')
    print('提醒: 以上均为正则线索，误报是预期内的。写进报告前必须 Read 原文件确认，')
    print('      并排除 references/checklist.md「高频误报清单」中列出的情况。')
    print('=' * 72)


if __name__ == '__main__':
    main()
