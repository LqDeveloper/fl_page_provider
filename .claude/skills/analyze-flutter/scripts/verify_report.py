#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验《package分析报告.md》里的每一条定位和代码片段是否真的对得上源码。

这个脚本的存在意义：**让"瞎编"变成机械可检测的**。

审计报告里最危险的不是漏报，是编造——编一个不存在的行号、凭记忆改写一段代码、
或者干脆虚构一个问题。人工复核成本很高，但这些都能自动查：

  - 报告里写的文件存在吗？
  - 行号在文件范围内吗？
  - 「锚点」那行原文在文件里真的存在吗？出现几次？
  - 「现状」代码块里的每一行，是不是真的能在文件里逐字找到？

任何一条对不上，那条问题就不可信。写完报告必须跑一遍，有 FAIL 就回去改，
不要把没通过校验的报告交出去。

用法:
    python3 verify_report.py <报告路径> <package根目录>
    python3 verify_report.py <报告路径> <package根目录> --quiet   # 只报问题
"""

import argparse
import os
import re
import sys

ISSUE_RE = re.compile(r'^#{2,4}\s+(P[0-3]-\d+)\s+(.*)$')
STATUS_RE = re.compile(r'\*\*状态\*\*\s*(.+?)\s*$', re.M)
# 「验证」字段必须以一个反引号片段开头 —— 那是"修复后必须能在文件里搜到的代码事实"。
# 判断是否已修复要靠它，不能靠锚点：很多修复（比如往 dispose() 里补一行）
# 根本不会动到锚点所在的那一行，锚点永远还在。
VERIFY_RE = re.compile(r'\*\*验证\*\*\s*`([^`]+)`')
DONE_RE = re.compile(r'已修复|已解决|✅')
SKIP_RE = re.compile(r'不修|忽略|won.?t.?fix|⏭')
LOC_RE = re.compile(r'\*\*定位\*\*\s*`?([^`\s]+?):(\d+)(?:-(\d+))?`?')
ANCHOR_RE = re.compile(r'\*\*锚点\*\*\s*`(.+?)`\s*$', re.M)
FENCE_RE = re.compile(r'```(?:dart|)\n(.*?)```', re.S)
STATE_BLOCK_RE = re.compile(r'\*\*现状\*\*.*?```(?:dart|)\n(.*?)```', re.S)

SKIP_LINE = re.compile(r'^\s*(//.*)?$')          # 空行或纯注释行不参与比对
ELLIPSIS = re.compile(r'^\s*//\s*\.\.\.|^\s*\.\.\.\s*$')


def load(path):
    try:
        return open(path, encoding='utf-8', errors='replace').read().splitlines()
    except OSError:
        return None


def norm(s):
    return re.sub(r'\s+', ' ', s.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('report')
    ap.add_argument('package')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--recheck', action='store_true',
                    help='复查模式：对照当前源码判断每条问题是否还在，'
                         '用于修复后回来更新报告状态')
    a = ap.parse_args()

    try:
        text = open(a.report, encoding='utf-8').read()
    except OSError as e:
        print(f'读不到报告: {e}', file=sys.stderr)
        sys.exit(2)

    root = os.path.abspath(a.package)
    cache = {}

    def src(rel):
        if rel not in cache:
            cache[rel] = load(os.path.join(root, rel))
        return cache[rel]

    # 按 ### P0-1 切分成条目
    lines = text.splitlines()
    marks = [(i, m.group(1), m.group(2))
             for i, ln in enumerate(lines) for m in [ISSUE_RE.match(ln)] if m]
    if not marks:
        print('⚠ 报告里没找到形如 "### P0-1 标题" 的问题条目。'
              '格式不符合模板，无法校验——请按 report-template.md 的结构重写。')
        sys.exit(2)

    fails, warns, checked = [], [], 0
    still, gone, marked_done, marked_skip = [], [], [], []
    for idx, (start, iid, title) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        block = '\n'.join(lines[start:end])
        checked += 1
        problems = []

        st = STATUS_RE.search(block)
        status = st.group(1).strip() if st else ''
        is_done = bool(DONE_RE.search(status))
        is_skip = bool(SKIP_RE.search(status))
        if is_done:
            marked_done.append((iid, title.strip()))
        elif is_skip:
            marked_skip.append((iid, title.strip()))

        # 已标记「已修复」的条目：源码已经变了，锚点对不上是正常的，不当失败处理。
        # 但在复查模式下要反过来确认——若锚点还在，说明"修复"并没有真的落地。
        if is_done and not a.recheck:
            continue

        loc = LOC_RE.search(block)
        if not loc:
            problems.append('缺 **定位** 字段（应为 `path:start-end`）')
            rel = None
        else:
            rel, s1 = loc.group(1), int(loc.group(2))
            s2 = int(loc.group(3)) if loc.group(3) else s1
            code = src(rel)
            if code is None:
                problems.append(f'文件不存在: {rel}')
            else:
                if s1 < 1 or s2 > len(code):
                    problems.append(
                        f'行号越界: 写的是 {s1}-{s2}，但 {rel} 只有 {len(code)} 行')

        anchor = ANCHOR_RE.search(block)
        if not anchor:
            warns.append(f'{iid}: 缺 **锚点** 字段，AI 工具无法定位改哪一处')
        elif rel and src(rel) is not None:
            code = src(rel)
            needle = norm(anchor.group(1))
            hits = [i + 1 for i, ln in enumerate(code) if needle in norm(ln)]
            if not hits:
                problems.append(f'锚点在源文件里找不到 → 疑似编造或凭记忆改写: `{anchor.group(1)}`')
            elif len(hits) > 1:
                warns.append(f'{iid}: 锚点在 {rel} 中出现 {len(hits)} 次（行 '
                             f'{", ".join(map(str, hits[:5]))}），机械替换会改错地方，'
                             f'请换一个更长的唯一片段')
            elif loc and not (s1 - 5 <= hits[0] <= s2 + 5):
                problems.append(f'锚点实际在第 {hits[0]} 行，但 **定位** 写的是 {s1}-{s2}'
                                f' → 行号记串了')

        st = STATE_BLOCK_RE.search(block)
        if st and rel and src(rel) is not None:
            code_norm = [norm(x) for x in src(rel)]
            bad = []
            for ln in st.group(1).splitlines():
                if SKIP_LINE.match(ln) or ELLIPSIS.match(ln):
                    continue
                if norm(ln) not in code_norm:
                    bad.append(ln.strip())
            if bad:
                problems.append(
                    '「现状」代码块有 %d 行在源文件里找不到 → 不是逐字复制:\n        %s'
                    % (len(bad), '\n        '.join(bad[:4])))

        if a.recheck:
            ver = VERIFY_RE.search(block)
            code = src(rel) if rel else None
            if not ver:
                warns.append(f'{iid}: 「验证」字段没有以反引号代码片段开头，无法机器复查'
                             f'——请改成 **验证** `<修复后应能搜到的代码>` — <说明>')
                still.append((iid, title.strip(), status, '无法判定'))
            elif code is None:
                still.append((iid, title.strip(), status, '文件读不到'))
            else:
                fact = norm(ver.group(1))
                if any(fact in norm(ln) for ln in code):
                    gone.append((iid, title.strip(), status, fact))
                else:
                    still.append((iid, title.strip(), status, fact))
            continue

        if problems:
            fails.append((iid, title.strip(), problems))

    print('=' * 70)
    print(f'{"报告复查" if a.recheck else "报告校验"}: {os.path.basename(a.report)}')
    print(f'共 {checked} 条问题条目'
          + (f'（已标记修复 {len(marked_done)}，标记不修 {len(marked_skip)}）'
             if marked_done or marked_skip else ''))
    print('=' * 70)

    if a.recheck:
        # 复查判据是「验证」字段里那个代码事实是否已出现在源码中
        print(f'\n【验证条件未成立 → 问题仍未修复】{len(still)} 条\n')
        for iid, title, status, fact in still:
            print(f'  · [{iid}] {title}')
            print(f'      未搜到: {fact}')
            if DONE_RE.search(status):
                print('      ⚠ 已被标记为「已修复」，但验证条件不成立 —— 修复没有落地！')
        print(f'\n【验证条件已成立 → 修复已落地】{len(gone)} 条\n')
        for iid, title, status, fact in gone:
            if DONE_RE.search(status):
                print(f'  ✅ [{iid}] {title}  —— 状态与源码一致')
            elif SKIP_RE.search(status):
                print(f'  ⏭ [{iid}] {title}  —— 标记为不修但验证条件已成立，确认一下')
            else:
                print(f'  ? [{iid}] {title}')
                print(f'      已搜到: {fact}')
                print('      → 状态还是「待修复」，确认后改成「✅ 已修复 YYYY-MM-DD（依据）」')
        if warns and not a.quiet:
            print(f'\n⚠ {len(warns)} 条无法机器复查\n')
            for w in warns:
                print(f'      · {w}')
        print('\n注意：验证条件成立只说明**那个代码事实出现了**，不等于整体改对了。'
              '涉及行为变化的（内存不再上涨、列表不再卡顿）仍需实际跑一遍确认。\n')
        sys.exit(0)

    if fails:
        print(f'\n❌ {len(fails)} 条未通过（这些条目不可信，必须回去核对源码后改正）\n')
        for iid, title, ps in fails:
            print(f'  [{iid}] {title}')
            for p in ps:
                print(f'      ✗ {p}')
            print()
    if warns and not a.quiet:
        print(f'⚠ {len(warns)} 条提醒（不阻断，但会影响 AI 工具自动修复）\n')
        for w in warns:
            print(f'      · {w}')
        print()
    if not fails:
        print('\n✅ 全部条目的文件、行号、锚点、现状代码都能和源码对上。\n')

    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
