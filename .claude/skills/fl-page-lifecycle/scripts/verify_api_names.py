#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 fl_page_lifecycle 的用法：① 名字是否真实存在 ② 高频误用原因排除。

为什么需要它：fl_page_lifecycle 是 2026 年 9 月才发布的新包，不在模型的训练数据里，
最常见的失败是编造出 `PageLifecycleMixin`、`onPageShow` / `onPageHide`、
`pauseOnOverlay:` 这类根本不存在的名字——代码一行都编译不过，但读起来很像真的。
第二类失败是名字都对、但接错了：漏注册观察者、Scope 只做了一半、开关不是常量……
这些**编译得过、也不报错**，只是回调静默不来，`flutter analyze` 同样发现不了。
这个脚本把两类一起查，只要 Python，适合在交代改动之前先自查一遍，
也适合「回调不触发」时第一时间跑一遍定位原因，比逐条读文档快。

用法：
    python3 verify_api_names.py <文件或目录> [更多路径...]
    python3 verify_api_names.py lib/pages/            # 查一个目录（名字 + 诊断）
    python3 verify_api_names.py --only-diagnose lib/  # 只做高频问题原因排除
    python3 verify_api_names.py --no-diagnose lib/    # 只查名字
    python3 verify_api_names.py --print-api           # 打印已知公开面
    python3 verify_api_names.py --lib <package>/lib <路径>   # 用真实源码重新推导公开面

退出码：0 = 没发现问题；1 = 发现可疑标识符或确定性误用；2 = 用法错误。
（只给出「提示」级结论时仍返回 0——那类结论依赖扫描范围，需要人再确认。）

维护提示：下面的 PUBLIC 是照 lib/fl_page_lifecycle.dart 的导出面逐个核对来的。
库的公开 API 变了就要同步改——这个脚本的价值完全建立在这份清单准确之上。
带 --lib 指向库的 lib/ 目录可以重新推导一份做对照。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 公开面

PUBLIC_TYPES = {
    "FlPageLifecycleMixin", "FlPageRouteMixin", "FlAppLifecycleMixin",
    "FlAnimationLifecycleMixin", "FlPageControllerMixin", "FlStateEventBusMixin",
    "FlPageLifecycleView", "FlPageIndexScope", "FlRouteObserver", "FlRouteObserverProxy",
    "FlLifecycleState",
    "FlLifecycleManager", "FlGlobalEventBus", "FlIEventBus", "FlEventBus",
    "FlPageLifecycleCallback", "FlPageRouteParamCallback", "FlPageIndexChangedCallback",
}

# 本版已经没有这些名字了，一律报错并给出新名。
#
# 之所以必须由脚本来抓：`FlPageLifecycleMixin` 上那四个成员是**直接删掉**的，没有垫片，
# 而 Dart 对「@override 了一个不存在的成员」只给 override_on_non_overriding_member
# **警告**、不是编译错误——代码照样能编译能跑，那个覆写就那么空挂着，
# 页面从此静默收不到页码驱动的事件。这正是 flutter analyze 不会让你停下来的那类问题。
RENAMED = {
    "observePageView": "observePageIndex",
    "onPageViewChanged": "onPageIndexChanged",
    "isInPageView": "isInPageScope",
    "pageViewDepth": "pageScopeDepth",
    "FlPageViewChangedCallback": "FlPageIndexChangedCallback",
    "FlPageViewScope": "FlPageIndexScope",
}

# 这几个是**删掉**的，写了也不会编译报错，只会静默失效——最危险的一类。
SILENTLY_DEAD = {
    "observePageView", "onPageViewChanged", "isInPageView", "pageViewDepth",
}

PUBLIC_MEMBERS = {
    # 生命周期回调
    "onPageInit", "onPageContextReady", "onPagePostFrame", "onPageReassemble",
    "onPageEnterAnimationStart", "onPageStart", "onPageResume",
    "onPageEnterAnimationEnd", "onPagePause", "onPageStop",
    "onPageLeaveAnimationStart", "onPageLeaveAnimationEnd", "onPageDispose",
    "onAppResume", "onAppInactive", "onAppPause", "onAppForeground",
    "onAppBackground", "onPageIndexChanged", "onLifecycleStateChanged",
    "appLifecycleChanged",
    # FlPageRouteMixin 的回调是 onRoute*，不是 onPage*
    "onRouteStart", "onRouteResume", "onRoutePause", "onRouteStop",
    # FlPageControllerMixin 的公开入口
    "onLifecycleChanged", "setupRouteInfo",
    # 开关与状态 getter
    "observePageIndex", "observeAppLifecycle", "isPageAppeared", "isPageResumed",
    "isInPageScope", "pageIndex", "currentPageIndex", "pageScopeDepth",
    "isForeground", "isCurrent", "routeName", "arguments", "hasInit", "hasRoute",
    "modalRoute", "lifecycleState", "isPageResume", "isPagePause", "isAppEvent",
    # FlPageIndexScope 静态方法
    "wrapChildren", "wrapItemBuilder", "indexOf", "initialIndexOf",
    "listenableOf", "depthOf",
    # FlPageLifecycleView 参数
    "onStateChanged", "onRouteParam", "debugResetWarnings",
    # 事件总线与 manager
    "observeEvent", "dispatchEvent", "configure", "destroy", "instance",
    "streamController", "customController", "fire",
}

PUBLIC = PUBLIC_TYPES | PUBLIC_MEMBERS

# 本库类型名里的标志性词根。带这些词根、却不是公开名字、又不是项目自己声明的类型，
# 基本就是把真名记错了（FlPageLifecycleObserver、PageLifecycleScope 这一类）。
#
# 不用「Fl 开头」当判据：Flutter 自己有 Flexible / Flow / FloatingActionButton，
# 项目里也可能有别的 Fl 前缀类，那样误报会多到没人愿意跑这个脚本。
LIB_TOKENS = (
    "PageLifecycle", "PageIndexScope", "PageViewScope", "RouteObserver", "LifecycleState",
    "LifecycleManager", "StateEventBus", "GlobalEventBus", "IEventBus",
    "PageControllerMixin", "AppLifecycleMixin", "AnimationLifecycleMixin",
    "PageRouteMixin", "LifecycleScope", "LifecycleView", "LifecycleMixin",
)

TYPE_SHAPES = re.compile(
    r"\b([A-Za-z0-9_]*(?:" + "|".join(LIB_TOKENS) + r")[A-Za-z0-9_]*)\b"
)

# 成员名形状。这几类的真名是**封闭集合**（回调就那 26 个、开关就 2 个、状态 getter 就那几个），
# 所以这里的判据比类型名可靠得多。
MEMBER_SHAPES = re.compile(
    r"\b("
    r"on(?:Page|App|Route|Lifecycle)[A-Za-z0-9_]*"
    r"|observe[A-Z][A-Za-z0-9_]*"
    r"|isPage[A-Z][A-Za-z0-9_]*"
    r"|pauseOn[A-Za-z0-9_]*"          # 常见编造：pauseOnOverlay / pauseOnAppBackground
    r")\b"
)

# 本地声明：项目自己的类 / mixin / 方法 / getter / 字段，不该被算成编造的库 API。
LOCAL_DECL = re.compile(
    r"\b(?:mixin|class|typedef|enum|extension)\s+([A-Za-z0-9_]+)"
    r"|(?:void|Future<[^>]*>|[A-Za-z0-9_<>?,\s]+?)\s+([A-Za-z0-9_]+)\s*\([^)]*\)\s*(?:async\s*)?\{"
    r"|\bget\s+([A-Za-z0-9_]+)"
    r"|\bfinal\s+[A-Za-z0-9_<>?,\s]+?\s+([A-Za-z0-9_]+)\s*[;=]"
    r"|\b(?:this|super)\.([A-Za-z0-9_]+)"
)

# 带 @override 的声明不是本地声明，而是在**声称**覆写库里的某个成员。
# 覆写一个不存在的回调（`@override void onPageShow()`）正是最典型的编造，
# 所以这些名字必须照常参与校验，不能被上面的 LOCAL_DECL 豁免掉。
OVERRIDE_DECL = re.compile(
    r"@override\s*"
    r"(?:[A-Za-z0-9_<>?,\[\]\s]*?\s)?"
    r"(?:get\s+)?([A-Za-z0-9_]+)\s*[({=>;]"
)

# 库内部实现细节：出现在说明文字里不算错，但出现在代码里说明用了非公开 API。
INTERNAL = {
    "FlLifecycleGuard", "FlPageRouteDelegate", "FlPageIndexDelegate",
    "FlAppLifecycleDelegate", "FlRouteAnimationBinding", "FlPageIndexScopeData",
    "FlPageIndexVisibility",
}

# Flutter / 常见三方包里恰好命中形状的真实名字。漏了会误报，所以宁可写全。
FRAMEWORK_OK = {
    # PageView / TabBar
    "onPageChanged",
    # webview_flutter —— 和 onPageStart 只差一个字母，最容易被误判
    "onPageStarted", "onPageFinished", "onPageProgress",
    # AppLifecycleListener（Flutter 3.13+）
    "onAppLifecycleStateChange",
    # WidgetsBindingObserver / AppLifecycleListener 的真实成员。名字里带 LifecycleState，
    # 正好命中类型形状——而「从 didChangeAppLifecycleState 迁过来」恰恰是本库最常见的场景，
    # 漏了这几个会在几乎每个迁移项目上误报。
    "didChangeAppLifecycleState", "handleAppLifecycleStateChanged",
    # Flutter 自带的生命周期与路由类型：它们是真实存在的，只是本库不用它们。
    # 报成「不存在」是错的——真要劝人迁移，那是 pitfalls.md 的事，不是这个脚本的事。
    "AppLifecycleState", "AppLifecycleListener", "RouteObserver", "RouteAware",
    "NavigatorObserver", "RouteSettings", "RouteInformation",
    # 观察者模式的通用命名
    "observer", "observers",
    # Flutter 里 Fl 开头的东西（这里只是保险，判据已不靠 Fl 前缀）
    "Flutter", "FlutterError", "FlutterErrorDetails", "FlutterLogo",
    "FlutterView", "FlexFit", "Flexible", "Flex", "FloatingActionButton",
    "Flow", "FlowDelegate",
}

DART_EXT = {".dart"}


def strip_comments_and_strings(src: str) -> str:
    """去掉注释与字符串字面量，避免把说明文字里的名字当成代码里的调用。

    多行的注释/字符串用等量换行替换，保持行号不变——诊断要报出准确的行。
    """
    def blank(m: re.Match) -> str:
        return "\n" * m.group(0).count("\n") or " "

    src = re.sub(r"/\*.*?\*/", blank, src, flags=re.S)
    src = re.sub(r"//[^\n]*", " ", src)
    src = re.sub(r"'''.*?'''|\"\"\"'*.*?\"\"\"", blank, src, flags=re.S)
    # 字符串字面量整体抹掉，但**保留插值**——`'$isInPageScope'` 里的标识符是代码，
    # 抹掉就漏检了。用等长空格替换非插值部分，保证行号与偏移不变。
    interp = re.compile(r"\$\{[^{}]*\}|\$[A-Za-z_][A-Za-z0-9_]*")

    def keep_interp(m: re.Match) -> str:
        body = m.group(0)
        out = [" "] * len(body)
        for i in interp.finditer(body):
            out[i.start():i.end()] = list(i.group(0))
        return "".join(out)

    src = re.sub(r"'(?:\\.|[^'\\\n])*'", keep_interp, src)
    src = re.sub(r"\"(?:\\.|[^\"\\\n])*\"", keep_interp, src)
    return src


def collect_files(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            out.extend(sorted(f for f in p.rglob("*") if f.suffix in DART_EXT))
        elif p.suffix in DART_EXT:
            out.append(p)
        elif p.exists():
            print(f"跳过（不是 dart 文件）：{p}", file=sys.stderr)
        else:
            print(f"路径不存在：{p}", file=sys.stderr)
    return out


def derive_public_from_lib(lib_dir: Path) -> set[str]:
    """从库源码重新推导一份公开面，用于核对上面那份清单是否过时。

    只看 lib/ 顶层导出的文件，并跳过标了 @internal 的声明。
    """
    entry = lib_dir / "fl_page_lifecycle.dart"
    if not entry.exists():
        print(f"找不到 {entry}", file=sys.stderr)
        return set()
    exported = []
    for m in re.finditer(r"export\s+'([^']+)'", entry.read_text(encoding="utf-8")):
        f = lib_dir / m.group(1)
        if f.exists():
            exported.append(f)
    names: set[str] = set()
    for f in exported:
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(
            r"@internal[\s\S]{0,80}?\b(?:mixin|class|typedef|enum)\s+([A-Za-z0-9_]+)", src
        ):
            names.discard(m.group(1))
        for m in re.finditer(r"\b(?:mixin|class|typedef|enum)\s+([A-Za-z0-9_]+)", src):
            if not m.group(1).startswith("_"):
                names.add(m.group(1))
        for m in re.finditer(r"\bvoid\s+([A-Za-z0-9_]+)\s*\(", src):
            if not m.group(1).startswith("_"):
                names.add(m.group(1))
        for m in re.finditer(r"\bget\s+([A-Za-z0-9_]+)", src):
            if not m.group(1).startswith("_"):
                names.add(m.group(1))
    return names


def parse_files(files: list[Path]) -> list[tuple[Path, str]]:
    """读入并去掉注释/字符串，两遍检查共用同一份解析结果。"""
    return [
        (f, strip_comments_and_strings(f.read_text(encoding="utf-8", errors="replace")))
        for f in files
    ]


def scan(parsed: list[tuple[Path, str]], public: set[str]) -> tuple[dict, dict, set[str]]:
    """返回 (可疑名字 -> [出现位置], 内部 API -> [出现位置], 本地声明集合)。

    本地声明是**跨全部被扫文件汇总**的：项目里 `PageLifecyclePage` 在 A 文件声明、
    B 文件使用是常态，逐文件判断会把 B 里的用法误报成编造。所以这个脚本要一次扫
    整个目录（或一次把全部改动文件都传进来），只扫单个文件会多报。
    """
    local: set[str] = set()
    for _f, code in parsed:
        local |= {g for m in LOCAL_DECL.finditer(code) for g in m.groups() if g}
        # 覆写声明要回到被校验的集合里：它声称的是库的成员，不是本地新增的。
        local -= set(OVERRIDE_DECL.findall(code))

    suspects: dict[str, list[str]] = {}
    internals: dict[str, list[str]] = {}
    for f, code in parsed:
        for i, line in enumerate(code.splitlines(), 1):
            names = set(TYPE_SHAPES.findall(line)) | set(MEMBER_SHAPES.findall(line))
            for name in names:
                if name in FRAMEWORK_OK or name in local:
                    continue
                where = f"{f}:{i}"
                if name in INTERNAL:
                    internals.setdefault(name, []).append(where)
                elif name not in public:
                    suspects.setdefault(name, []).append(where)
    return suspects, internals, local


# ------------------------------------------------------ 高频问题原因排除
#
# 这一遍查的是**编译得过、analyze 也不报、但回调静默不来**的接错方式。
# 每条都对应一个真实高频症状，结论分两级：
#   ❌ 本地就能判定的确定错误（退出码 1）
#   ⚠️ 取决于扫描范围的很可能问题（不影响退出码，需要人再确认一眼）

ENTRY_MIXINS = (
    "FlPageLifecycleMixin", "FlPageRouteMixin",
    "FlAppLifecycleMixin", "FlAnimationLifecycleMixin",
)


def _line_of(code: str, off: int) -> int:
    return code.count("\n", 0, off) + 1


def _brace_body(code: str, open_idx: int) -> tuple[int, int]:
    """给定 '{' 的下标，返回 (body 起, body 止)。括号不配对时返回到文件末尾。"""
    depth = 0
    for i in range(open_idx, len(code)):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return open_idx + 1, i
    return open_idx + 1, len(code)


def _member_body(code: str, decl_end: int) -> str:
    """从成员声明的 ')' 之后取方法体，兼容 `{...}` 与 `=> ...;` 两种写法。"""
    m = re.compile(r"\s*(=>|\{)").match(code, decl_end)
    if not m:
        return ""
    if m.group(1) == "{":
        s, e = _brace_body(code, m.end() - 1)
        return code[s:e]
    end = code.find(";", m.end())
    return code[m.end(): end if end != -1 else len(code)]


CLASS_RE = re.compile(r"\b(?:class|mixin)\s+([A-Za-z0-9_]+)([^{;]*)\{")
METHOD_RE = re.compile(r"\b([A-Za-z0-9_]+)\s*\([^();]*\)\s*(?:async\s*)?\{")


def _enclosing_method(code: str, off: int) -> str:
    last = ""
    for m in METHOD_RE.finditer(code, 0, off):
        last = m.group(1)
    return last


def diagnose(parsed: list[tuple[Path, str]]) -> list[dict]:
    found: list[dict] = []

    def add(level, title, why, fix, ref, spots):
        found.append(dict(level=level, title=title, why=why, fix=fix,
                          ref=ref, spots=spots))

    all_code = "\n".join(c for _, c in parsed)
    spot = lambda f, c, off: f"{f}:{_line_of(c, off)}"  # noqa: E731

    # ── 1. 旧名残留（本版已改名）
    olds: dict[str, list[str]] = {}
    for f, c in parsed:
        for old in RENAMED:
            for m in re.finditer(r"\b%s\b" % re.escape(old), c):
                olds.setdefault(old, []).append(spot(f, c, m.start()))
    for old, spots in sorted(olds.items()):
        new = RENAMED[old]
        if old in SILENTLY_DEAD:
            why = ("这个成员已删除，且没有兼容垫片。危险的是它**不会编译报错**——"
                   "`@override` 一个不存在的成员只是 override_on_non_overriding_member "
                   "警告，代码照样跑，那个覆写空挂着，页面从此静默收不到页码驱动的事件")
        else:
            why = "这个名字已经没有了（写了会编译报错）"
        add("❌", f"用了旧名 {old}", why, f"改成 {new}",
            "api.md（本版全部真名）", spots)

    # ── 2. 观察者注册
    root_reg, nested_wrong = [], []
    for f, c in parsed:
        for m in re.finditer(r"^.*\bnavigatorObservers\s*:.*$", c, re.M):
            if "FlRouteObserver" in m.group(0) and "Proxy" not in m.group(0):
                root_reg.append(spot(f, c, m.start()))
        for m in re.finditer(r"^(?!.*navigatorObservers).*\bobservers\s*:.*$", c, re.M):
            if "FlRouteObserver" in m.group(0) and "Proxy" not in m.group(0):
                nested_wrong.append(spot(f, c, m.start()))
    if nested_wrong:
        add("❌", "嵌套 Navigator 挂了 FlRouteObserver 本体",
            "它是单例，Flutter 的 Navigator.initState 里有 assert(observer.navigator == null)，"
            "第二个挂载点 debug 直接断言失败",
            "嵌套的每个 Navigator 各 new 一个 FlRouteObserverProxy()",
            "pitfalls.md 第 15 条", nested_wrong)
    if len(root_reg) > 1:
        add("❌", "FlRouteObserver 被挂到了多个 Navigator",
            "同一个单例实例同时只能绑一个 NavigatorState",
            "只有根 Navigator 用它，其余各用一个新的 FlRouteObserverProxy()",
            "pitfalls.md 第 15 条", root_reg)

    for f, c in parsed:
        for m in re.finditer(
            r"\b(?:final|const|var|late\s+final)\s+([A-Za-z0-9_]+)\s*=\s*"
            r"FlRouteObserverProxy\(\)", c
        ):
            name = m.group(1)
            uses = len(re.findall(r"\b%s\b" % re.escape(name), all_code)) - 1
            if uses > 1:
                add("❌", f"同一个 proxy 实例 {name} 被复用",
                    "两个 Navigator 复用一个 observer 实例一样会触发那条 assert",
                    "每个嵌套 Navigator 各 new 一个；proxy 无状态，写在 build 里也无妨",
                    "pitfalls.md 第 15 条", [spot(f, c, m.start())])

    uses_lifecycle = any(
        re.search(r"\bFlPage(?:LifecycleMixin|LifecycleView|RouteMixin)\b", c)
        for _, c in parsed
    )
    if uses_lifecycle and "FlRouteObserver" not in all_code:
        add("⚠️", "扫描范围内没看到任何 FlRouteObserver 注册",
            "四个可见性回调全部静默失效，且不抛异常（转场动画回调不受影响，"
            "所以「动画有、可见性没有」就是这个原因）",
            "根 Navigator 挂 FlRouteObserver()；注册写在别的目录时忽略本条",
            "pitfalls.md 第 1 条", [])

    # ── 3. 页码作用域只做了一半
    wraps = "wrapChildren" in all_code or "wrapItemBuilder" in all_code \
        or "FlPageIndexScope" in all_code
    opens = []
    for f, c in parsed:
        for m in re.finditer(r"\bobservePageIndex\s*(?:=>|:)\s*true\b", c):
            opens.append(spot(f, c, m.start()))
    if opens and not wraps:
        add("⚠️", "开了 observePageIndex，但扫描范围内没有 FlPageIndexScope",
            "拿不到页码，可见性永远不变",
            "容器侧用 FlPageIndexScope.wrapChildren 注入页码；"
            "容器写在别的目录时忽略本条",
            "pitfalls.md 第 4 条", opens)
    if wraps and not opens:
        add("⚠️", "包了 FlPageIndexScope，但扫描范围内没有子页开 observePageIndex",
            "子页可见性仍按路由算，首帧全部 start，等于没懒加载",
            "子页写 `bool get observePageIndex => true;`；"
            "子页在别的目录时忽略本条",
            "pitfalls.md 第 4 条", [])

    # ── 4. 逐个类的检查
    for f, c in parsed:
        for cm in CLASS_RE.finditer(c):
            cname, header = cm.group(1), cm.group(2)
            s, e = _brace_body(c, cm.end() - 1)
            body = c[s:e]
            at = lambda off=cm.start(): spot(f, c, off)  # noqa: E731

            entries = [x for x in ENTRY_MIXINS if re.search(r"\b%s\b" % x, header)]
            if len(entries) > 1:
                add("❌", f"{cname} 叠加了多个入口 mixin：{' + '.join(entries)}",
                    "它们订阅同一批源、成员名还会撞，结果是一个状态机根本不跑",
                    "只选一个（主 mixin 能力最全）；要复用逻辑就叠自己的 mixin",
                    "pitfalls.md 第 3 条", [at()])

            # 开关必须是字面常量
            for m in re.finditer(
                r"\bbool\s+get\s+(observePageIndex|observeAppLifecycle)\s*=>\s*([^;]+);",
                body
            ):
                expr = m.group(2).strip()
                if expr in ("true", "false"):
                    continue
                # 约束是「整个生命周期恒定」，不是「必须字面量」——库自己的
                # FlPageLifecycleView 就写 `=> widget.observePageIndex`。所以只能提醒，
                # 不能断言为错：转发一个不会变的值是合法的。
                add("⚠️", f"{cname}.{m.group(1)} 不是字面常量（值为 `{expr}`）",
                    "它在 initState / didChangeDependencies 读取，要求整个生命周期内取值恒定；"
                    "只要这个来源会变，状态机就对不齐（debug assert，release 下可能永远收不到 "
                    "stop）。转发一个自己不会变的值是允许的",
                    "确认这个表达式全程不变；会变就改成字面常量，条件行为放到回调内部判断",
                    "pitfalls.md 第 5 条", [spot(f, c, s + m.start())])

            # @mustCallSuper 的两个分发器
            for name in ("onLifecycleStateChanged", "appLifecycleChanged"):
                for m in re.finditer(r"\b%s\s*\([^)]*\)" % name, body):
                    mb = _member_body(body, m.end())
                    if mb and f"super.{name}" not in mb:
                        add("❌", f"{cname}.{name} 重写了但没调 super",
                            "它是 @mustCallSuper 的分发器，漏了 super 下游回调静默失效"
                            "（appLifecycleChanged 漏掉时 onAppResume / onAppInactive / "
                            "onAppPause 三个全不来）",
                            f"方法体第一行加 super.{name}(...)",
                            "pitfalls.md 第 6 条", [spot(f, c, s + m.start())])

            if re.search(r"\bFlPageControllerMixin\b", header):
                for m in re.finditer(r"\bonPageContextReady\s*\(\s*String", body):
                    add("❌", f"{cname}.onPageContextReady 签名写错",
                        "Controller 上它是 (BuildContext? context)，写成 "
                        "(String? routeName, Object? arguments) 会变成一个永远不被调用的新方法",
                        "改成 void onPageContextReady(BuildContext? context)；"
                        "路由信息读 routeName / arguments",
                        "pitfalls.md 第 9 条", [spot(f, c, s + m.start())])

    # ── 5. observeEvent 的位置
    for f, c in parsed:
        for m in re.finditer(r"\bobserveEvent\s*<", c):
            line = c[c.rfind("\n", 0, m.start()) + 1: c.find("\n", m.start())]
            if "FlGlobalEventBus" in line:
                continue
            host = _enclosing_method(c, m.start())
            if host and host != "initState":
                add("❌", f"observeEvent 写在了 {host} 里",
                    "订阅数会随重建线性增长；重复的 (类型, 回调) 组合本次订阅被静默忽略，"
                    "而现场写的闭包字面量每次都是新对象，去不了重",
                    "移到 initState，且传方法引用而不是闭包字面量",
                    "pitfalls.md 第 7 条", [spot(f, c, m.start())])

    # ── 6. 页面级代码里调了全局销毁
    for f, c in parsed:
        if "/test/" in str(f).replace("\\", "/") or str(f).endswith("_test.dart"):
            continue
        for pat, what in (
            (r"FlGlobalEventBus\s*\.\s*destroy\s*\(", "FlGlobalEventBus.destroy()"),
            (r"FlLifecycleManager[^;\n]*\.\s*cancel\s*\(", "FlLifecycleManager.cancel()"),
        ):
            spots = [spot(f, c, m.start()) for m in re.finditer(pat, c)]
            if spots:
                add("❌", f"业务代码里调了 {what}",
                    "这是进程级的：前者关掉整条广播流让所有页面的订阅静默失活，"
                    "后者让所有页面都收不到 App 事件",
                    "页面级清理什么都不用做，mixin 的 dispose 已处理；"
                    "这两个只用于测试 tearDown 或 App 退出",
                    "pitfalls.md 第 8 条", spots)

    # ── 7. 用 isCurrent 判可见性
    for f, c in parsed:
        for m in re.finditer(r"\bif\s*\(\s*(?:[^)]*[^A-Za-z0-9_.])?isCurrent\b", c):
            add("⚠️", "拿 isCurrent 当可见性判据",
                "任何路由压上来它都变 false，包括 PopupRoute——而弹窗盖上来时页面"
                "其实完全可见，库只发 pause 不发 stop",
                "判可见用 isPageAppeared，判可交互用 isPageResumed",
                "pitfalls.md 第 2 条", [spot(f, c, m.start())])

    # ── 8. 嵌套栈里弹 dialog
    # 只在**同一个文件**里既有嵌套 Navigator 又有 showDialog 时才提——
    # 全局触发会把「各页共用的弹窗工具类」也报出来，那是误报。
    for f, c in parsed:
        if "FlRouteObserverProxy" in c:
            for m in re.finditer(r"\bshowDialog\s*(?:<[^>]*>)?\s*\(", c):
                tail = c[m.end(): m.end() + 400]
                if "useRootNavigator" not in tail:
                    add("⚠️", "嵌套路由栈里的 showDialog 没写 useRootNavigator: false",
                        "默认 true 会把弹窗压到根 Navigator 上，内层页面收不到 pause",
                        "加 useRootNavigator: false",
                        "sc-route.md 第 17 节", [spot(f, c, m.start())])

    # ── 9. Controller 用了但没人转发
    if "FlPageControllerMixin" in all_code and "onLifecycleChanged" not in all_code:
        add("⚠️", "用了 FlPageControllerMixin，但扫描范围内没有页面转发",
            "它不订阅任何东西，没有转发就一个回调都不会触发",
            "页面侧在 onLifecycleStateChanged 里调 controller.onLifecycleChanged(...)，"
            "并在 onPageContextReady 里调 setupRouteInfo(...)",
            "pitfalls.md 第 9 条", [])

    return found


def print_diagnosis(found: list[dict]) -> bool:
    """打印诊断结论，返回是否存在确定性错误。"""
    if not found:
        print("\n✅ 高频误用排查：没发现问题。")
        return False
    hard = [x for x in found if x["level"] == "❌"]
    soft = [x for x in found if x["level"] == "⚠️"]
    print(f"\n高频误用排查：{len(hard)} 个确定问题，{len(soft)} 个待确认。")
    for item in hard + soft:
        print(f"\n{item['level']} {item['title']}")
        print(f"     原因：{item['why']}")
        print(f"     改法：{item['fix']}")
        print(f"     详见：{item['ref']}")
        for s in item["spots"][:5]:
            print(f"       {s}")
        if len(item["spots"]) > 5:
            print(f"       …… 共 {len(item['spots'])} 处")
    return bool(hard)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="校验 dart 代码里的 fl_page_lifecycle 标识符是否真实存在"
    )
    ap.add_argument("paths", nargs="*", help="要检查的 dart 文件或目录")
    ap.add_argument("--print-api", action="store_true", help="打印已知公开面后退出")
    ap.add_argument("--lib", metavar="DIR", help="库的 lib/ 目录，用它重新推导公开面做对照")
    ap.add_argument("--no-diagnose", action="store_true", help="只查名字，跳过高频误用排查")
    ap.add_argument("--only-diagnose", action="store_true", help="只做高频误用排查")
    args = ap.parse_args()

    if args.print_api:
        for n in sorted(PUBLIC):
            print(n)
        return 0

    if not args.paths:
        ap.print_usage()
        return 2

    public = set(PUBLIC)
    if args.lib:
        derived = derive_public_from_lib(Path(args.lib))
        if derived:
            only_derived = sorted(derived - public - INTERNAL)
            only_baked = sorted(public - derived)
            if only_derived:
                print("提示：源码里有、清单里没有的名字（清单可能过时）：")
                print("  " + ", ".join(only_derived))
            if only_baked:
                print("提示：清单里有、这次没从源码扫到的名字（多为枚举值或参数名，通常正常）：")
                print("  " + ", ".join(only_baked[:20])
                      + (" …" if len(only_baked) > 20 else ""))
            public |= derived
            print()

    files = collect_files(args.paths)
    if not files:
        print("没有找到 dart 文件")
        return 2

    parsed = parse_files(files)
    print(f"检查了 {len(files)} 个 dart 文件")
    if len(files) == 1:
        print("   （只扫了一个文件：项目自己的类如果声明在别处，可能被误报。"
              "建议一次传入整个目录或全部改动文件。）")

    # 库自身的 lib/ 里全是内部实现，两遍检查都不适用
    diagnose_on = not args.no_diagnose and not args.lib
    bad_usage = False
    if diagnose_on:
        bad_usage = print_diagnosis(diagnose(parsed))
    if args.only_diagnose:
        return 1 if bad_usage else 0

    suspects, internals, _local = scan(parsed, public | set(RENAMED))

    if internals:
        print("\n⚠️  用到了库的内部实现（标了 @internal 或未导出，不该在业务代码里出现）：")
        for name, spots in sorted(internals.items()):
            print(f"  {name}")
            for s in spots[:5]:
                print(f"      {s}")

    if not suspects:
        print("\n✅ 没有发现编造的标识符。")
        print("   注意这个脚本只查名字是否存在与上面那批高频接错方式，"
              "参数顺序、类型这些仍要靠 flutter analyze。")
        return 1 if (internals or bad_usage) else 0

    print("\n❌ 下面这些标识符在 fl_page_lifecycle 的公开 API 里不存在：")
    for name, spots in sorted(suspects.items()):
        print(f"\n  {name}")
        for s in spots[:5]:
            print(f"      {s}")
        if len(spots) > 5:
            print(f"      …… 共 {len(spots)} 处")
    print("\n真实的名字请查 references/api.md。常见对应关系：")
    print("  PageLifecycleMixin / FlPageLifecycleObserver → FlPageLifecycleMixin + FlRouteObserver.instance")
    print("  onPageShow / onPageHide                      → onPageStart / onPageStop（或 onPageResume / onPagePause）")
    print("  pauseOnOverlay: / pauseOnAppBackground:      → 没有这种构造参数，用回调 + observeAppLifecycle")
    return 1


if __name__ == "__main__":
    sys.exit(main())
