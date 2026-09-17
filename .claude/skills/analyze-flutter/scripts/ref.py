#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按主题取参考文档的片段，避免整份读进上下文。

整份 checklist.md + common-pitfalls.md 约 23k tokens，而且一旦读进来就会在
之后每一轮里被重复处理。实际上一次审计只用得到其中几节——扫描脚本已经告诉你
命中了哪些类别，按需取就行。

用法:
    python3 ref.py memory timer net        # 一次取多个主题
    python3 ref.py --list                  # 看有哪些主题
    python3 ref.py core                    # 必读的那一小撮（误报清单等）
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(os.path.dirname(HERE), 'references')

CHECKLIST = 'checklist.md'
PITFALLS = 'common-pitfalls.md'
TEMPLATE = 'report-template.md'

# 主题 -> [(文件, 章节标题前缀), ...]；标题前缀按 "## " 级别匹配
TOPICS = {
    'core':    [(CHECKLIST, '高频误报清单')],
    'norms':   [(CHECKLIST, '维度一')],
    'memory':  [(CHECKLIST, '维度二'), (PITFALLS, '二、用得太晚')],
    'jank':    [(CHECKLIST, '维度三'), (PITFALLS, '三、用在错误的帧阶段')],
    'dup':     [(CHECKLIST, '维度四')],
    'decouple':[(CHECKLIST, '维度五')],
    'net':     [(CHECKLIST, '维度六'), (PITFALLS, '五、时序不确定')],
    'timer':   [(CHECKLIST, 'Timer 专项检查'), (PITFALLS, '四、被重复调用')],
    'early':   [(PITFALLS, '一、用得太早')],
    'data':    [(PITFALLS, '六、非时序')],
    'lint':    [(PITFALLS, '为什么这类问题会反复发生')],
    'excluded':[(PITFALLS, '不收录的问题及原因')],
    'template':[(TEMPLATE, None)],
}

DESC = {
    'core': '高频误报清单——写报告前必读，逐条排除',
    'norms': '维度一 开发规范',
    'memory': '维度二 内存泄漏 + 用得太晚（对象已销毁）',
    'jank': '维度三 UI 卡顿 + 错误的帧阶段',
    'dup': '维度四 重复代码与封装',
    'decouple': '维度五 扩展性与解耦',
    'net': '维度六 网络并发 + 竞态',
    'timer': 'Timer 专项四问 + 被重复调用',
    'early': '用得太早（依赖未建立）',
    'data': 'JSON 强转 / 金额 double',
    'lint': '默认没开的关键 lint 规则 + analysis_options 配置',
    'excluded': '不收录的问题清单（判断什么不该写进报告）',
    'template': '报告结构模板',
}


def slice_section(text: str, title_prefix):
    """取出以 '## <title_prefix>' 开头、到下一个同级 '## ' 之前的整段。"""
    if title_prefix is None:
        return text
    lines = text.splitlines()
    out, capturing = [], False
    for ln in lines:
        if ln.startswith('## '):
            if capturing:
                break
            capturing = ln[3:].strip().startswith(title_prefix)
        if capturing:
            out.append(ln)
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('topics', nargs='*')
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()

    if a.list or not a.topics:
        print('可用主题（可一次传多个）:\n')
        for k in TOPICS:
            print(f'  {k:<10} {DESC.get(k, "")}')
        print('\n例: python3 ref.py core memory timer')
        return

    unknown = [t for t in a.topics if t not in TOPICS]
    if unknown:
        print(f'未知主题: {", ".join(unknown)}。用 --list 看可用主题。', file=sys.stderr)
        sys.exit(1)

    seen = set()
    for topic in a.topics:
        for fname, title in TOPICS[topic]:
            if (fname, title) in seen:
                continue
            seen.add((fname, title))
            path = os.path.join(REF, fname)
            try:
                text = open(path, encoding='utf-8').read()
            except OSError as e:
                print(f'[读取失败] {path}: {e}', file=sys.stderr)
                continue
            body = slice_section(text, title)
            if not body.strip():
                print(f'[未找到章节] {fname} :: {title}', file=sys.stderr)
                continue
            print(f'\n{"=" * 70}\n# 来自 {fname}（主题 {topic}）\n{"=" * 70}\n')
            print(body)


if __name__ == '__main__':
    main()
