#!/usr/bin/env python3
"""排查 fl_page_provider 里「编译得过、analyze 也不报、但 UI 静默不刷新」的接错方式。

  python3 scripts/verify.py lib/ --analyze   # 顺带跑 flutter analyze，一次调用出两份结果

不传路径默认扫 lib/。传整个目录，别只传单文件（跨文件的检查会失准）。
❌ = 本地可判定的确定错误；⚠️ = 取决于扫描范围或写法，再确认一眼。有 ❌ 时退出码为 1。
fl_page_lifecycle 那侧的名字检查交给 fl-page-lifecycle skill 的 scripts/verify_api_names.py。
"""

import re
import subprocess
import sys
from pathlib import Path

PUBLIC = {
    "FlBaseController", "FlBasePage", "FlBasePageState", "FlPageMixin",
    "FlProviderBuilder", "FlSelector", "FlSelectorBuilder", "FlSelectorView",
    "FlControllerContextExtension",
    # 随包入口再导出的 fl_page_lifecycle 公开面
    "FlPageLifecycleMixin", "FlPageLifecycleView", "FlPageControllerMixin",
    "FlPageRouteMixin", "FlAppLifecycleMixin", "FlAnimationLifecycleMixin",
    "FlStateEventBusMixin", "FlRouteObserver", "FlRouteObserverProxy",
    "FlPageIndexScope", "FlPageIndexScopeData", "FlPageIndexVisibility",
    "FlPageIndexDelegate", "FlPageIndexChangedCallback", "FlLifecycleState",
    "FlLifecycleManager", "FlLifecycleGuard", "FlGlobalEventBus", "FlEventBus",
    "FlIEventBus", "FlAppLifecycleDelegate", "FlPageLifecycleCallback",
    "FlPageLifecycleObserver", "FlPageRouteDelegate", "FlPageRouteParamCallback",
    "FlPageViewScope", "FlPageViewChangedCallback", "FlRouteAnimationBinding",
}
INTERNAL = {
    "FlPageProvider": "包内实现，页面请用 FlProviderBuilder / FlBasePage / FlBasePageState",
    "FlInheritedWidget": "包内实现，取实例用 context.rc，按 ID 订阅用 FlSelector",
    "FlNotifyMixin": "包内实现，控制器请继承 FlBaseController",
    "FlEventBusMixin": "包内实现，事件能力已在 FlBaseController 上",
    "FlIdVersions": "包内实现，外部拿不到",
    "FlPageProviderNotFoundError": "包内实现，不要 catch 它，按报错文案改接线",
}
FAKE_MEMBERS = {
    "notifyId": "notifySingleListener", "notifyIds": "notifyMultiListeners",
    "registerId": "registerIds（一般不用手调，写 shouldNotifyIds 就行）",
    "selectId": "FlSelector", "watchIds": "FlSelector", "readController": "rc",
    "watchController": "FlSelector", "notifyAll": "notifyMultiListeners",
}
FL_TOKEN = re.compile(r"\bFl[A-Z][A-Za-z0-9_]*")


def strip(src: str) -> str:
    """去掉注释和字符串字面量，避免文档里的示例被当成代码。行号保持不变。"""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            seg = src[i:(n if j < 0 else j + 2)]
            out.append("\n" * seg.count("\n"))
            i = n if j < 0 else j + 2
        elif c in "'\"":
            q, j = c, i + 1
            while j < n and src[j] != q:
                if src[j] == "\\":
                    j += 1
                elif src[j] == "\n":
                    break
                j += 1
            out.append('""')
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def line_of(code: str, off: int) -> int:
    return code.count("\n", 0, off) + 1


METHOD = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\([^();{}]*\)\s*(?:async\s*)?\{")
CLASS = re.compile(r"\b(?:class|mixin)\s+([A-Za-z0-9_]+)([^{;]*)\{")


def _block(code: str, open_idx: int) -> int:
    """返回与 open_idx 处 '{' 配对的 '}' 的下标。"""
    depth, i, n = 0, open_idx, len(code)
    while i < n:
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


def classes(code: str):
    """(类名, 类声明头, 类体, 类体起始偏移) —— 够应付页面/控制器这种写法。"""
    for m in CLASS.finditer(code):
        start = m.end() - 1
        end = _block(code, start)
        yield m.group(1), m.group(2), code[start:end + 1], start


def methods(body: str, base: int):
    """(方法名, 方法体, 绝对偏移, 是否带 @override)"""
    for m in METHOD.finditer(body):
        if m.group(1) in ("if", "for", "while", "switch", "catch"):
            continue
        start = m.end() - 1
        end = _block(body, start)
        before = body[max(0, m.start() - 120):m.start()]
        yield m.group(1), body[start:end + 1], base + start, "@override" in before


def run_analyze() -> int:
    """在同一次调用里跑掉 flutter analyze，只回显真正的问题行。"""
    try:
        r = subprocess.run(["flutter", "analyze"], capture_output=True, text=True, timeout=600)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"\n⚠️  flutter analyze 没跑成（{type(e).__name__}），请自行确认")
        return 0
    bad = [ln for ln in r.stdout.splitlines()
           if re.search(r"^\s*(error|warning|info)\s*[•·]", ln)]
    print("\n--- flutter analyze ---")
    if not bad:
        print("✓ 0 error 0 warning")
        return 0
    for ln in bad[:40]:
        print(ln.strip())
    if len(bad) > 40:
        print(f"... 另有 {len(bad) - 40} 条")
    return 1 if any(ln.strip().startswith(("error", "warning")) for ln in bad) else 0


def main() -> int:
    argv = [a for a in sys.argv[1:] if a != "--analyze"]
    analyze = "--analyze" in sys.argv[1:]
    paths = [Path(p) for p in argv] or [Path("lib")]
    files = []
    for p in paths:
        files += sorted(p.rglob("*.dart")) if p.is_dir() else [p]
    files = [f for f in files if ".dart_tool" not in f.parts and f.suffix == ".dart"]
    if not files:
        print("✗ 没找到 .dart 文件")
        return 1

    for d in (".", ".."):
        ps = Path(d) / "pubspec.yaml"
        if ps.exists():
            if "fl_page_provider" not in ps.read_text(encoding="utf-8", errors="replace"):
                print("⚠️  pubspec.yaml 里没有 fl_page_provider，确认一下依赖装了没\n")
            break

    parsed = [(f, strip(f.read_text(encoding="utf-8", errors="replace"))) for f in files]
    whole = "\n".join(c for _, c in parsed)
    hits = []

    def hit(bad, f, ln, what, why, fix):
        hits.append((bad, f"{f}:{ln}", what, why, fix))

    has_scope = "FlPageIndexScope.wrap" in whole
    has_index = re.search(r"observePageIndex\s*=>\s*true", whole) is not None
    has_observer = "FlRouteObserver(" in whole or "FlRouteObserverProxy(" in whole
    has_provider_pkg = "package:provider/" in whole

    # 控制器基类的传递闭包：BasePageController extends FlBaseController 之后，
    # 再继承 BasePageController 的也算控制器。
    ctrl_bases = {"FlBaseController"}
    for _ in range(3):
        for _, c in parsed:
            for cn, hd, _, _ in classes(c):
                if any(b in hd for b in ctrl_bases):
                    ctrl_bases.add(cn)

    for f, code in parsed:
        # ---- 名字 ----
        for m in FL_TOKEN.finditer(code):
            name = m.group(0)
            if name in INTERNAL:
                hit(True, f, line_of(code, m.start()), f"用了包内实现 {name}",
                    INTERNAL[name], "改用公开 API")
            elif name not in PUBLIC and not re.search(
                    rf"\b(class|mixin|enum|typedef|extension)\s+{name}\b", whole):
                hit(False, f, line_of(code, m.start()), f"未知标识符 {name}",
                    "本包和 fl_page_lifecycle 都没有这个名字，八成是凭印象拼的",
                    "查 references/api.md")
        for fake, real in FAKE_MEMBERS.items():
            for m in re.finditer(rf"\.{fake}\s*[(<]", code):
                hit(True, f, line_of(code, m.start()), f"{fake} 不存在", "编造的成员名", f"改用 {real}")
        if not has_provider_pkg:
            for m in re.finditer(r"context\.(read|watch|select)\s*<", code):
                hit(True, f, line_of(code, m.start()), f"context.{m.group(1)} 不是本库的名字",
                    "那是 provider 包的扩展；本库为了能和它共存，故意用了另一套名字",
                    "取实例调方法用 context.rc<T>()，按 ID 订阅用 FlSelector / FlSelectorView")

        # ---- 已移除 / 不再公开的入口 ----
        for m in re.finditer(r"context\.wc\s*<", code):
            hit(True, f, line_of(code, m.start()), "context.wc 已经从本库移除",
                "它建立的全量依赖跨帧不可逆：一旦登记，后续的 ID 登记不能再把它收窄，"
                "这个 Widget 会一直跟着每一次通知重建直到卸载，不报错也没日志",
                "要「任何变更都刷新这一块」就留一个全量 ID，每次通知都一起列进 "
                "notifyMultiListeners，调用方用 FlSelector 订它")
        for m in re.finditer(r"context\.selectIds\s*<", code):
            hit(True, f, line_of(code, m.start()), "context.selectIds 已转为包内实现（@internal）",
                "依赖登记在调用方那个 Element 上：写在页面 build 里就是整页跟着一个 ID 抖，"
                "放进条件分支还会留下永久白重建的尾巴",
                "改用 FlSelector<E, C>(ids: ...) 或 FlSelectorView<E, C>——"
                "那层 Widget 边界正是安全用它的前提")

        # ---- 空 ids ----
        for m in re.finditer(r"\bids\s*:\s*(?:const\s*)?\[\s*\]", code):
            hit(True, f, line_of(code, m.start()), "ids 是空列表",
                "空列表不是「不限定 ID」，是「一个 ID 都不关心」——这块永远不会重建",
                "写上真正关心的 ID；要全量刷新就留一个全量 ID，每次通知都带上它")

        # ---- 通知了没登记的 ID ----
        reg = re.search(r"shouldNotifyIds\s*=>\s*([^;]+);", code)
        notified = set()
        for m in re.finditer(r"notifySingleListener\s*\(\s*([A-Za-z0-9_.]+)", code):
            notified.add(m.group(1))
        for m in re.finditer(r"notifyMultiListeners\s*\(\s*\[([^\]]*)\]", code):
            notified |= {x.strip() for x in m.group(1).split(",") if x.strip()}
        if reg and notified:
            body = reg.group(1).strip()
            if re.fullmatch(r"(const\s*)?\[\s*\]", body):
                hit(True, f, line_of(code, reg.start()), "shouldNotifyIds 是空列表，却有通知调用",
                    "没登记的 ID 版本号恒为 0，比对永远得出「没变」，依赖方一次都不会重建",
                    "把用到的 ID 写进 shouldNotifyIds")
            elif not body.endswith(".values"):
                listed = {x.strip() for x in re.sub(r"^const\s*\[|\]$", "", body).split(",")}
                missing = sorted(n for n in notified if n not in listed and "." in n)
                if missing:
                    hit(True, f, line_of(code, reg.start()), f"{missing} 通知了但没登记",
                        "未登记的 ID 不会触发任何重建，debug 下才有断言，release 静默失败",
                        "加进 shouldNotifyIds（或直接写 XxxEvent.values）")

        # ---- 漏 super / 订阅位置 / 直接 notifyListeners（按类作用域判断） ----
        for cname, header, cbody, cstart in classes(code):
            is_state = "FlBasePageState" in header
            is_ctrl = any(b in header for b in ctrl_bases) or cname.endswith("Controller")
            for name, body, off, overridden in methods(cbody, cstart):
                ln = line_of(code, off)
                if overridden and name in ("onPageInit", "onPageReassemble") \
                        and f"super.{name}()" not in body:
                    hit(True, f, ln, f"{cname}.{name} 没调 super.{name}()",
                        "ID 登记就发生在 super 里；漏了它这一页的所有选择性刷新都不会生效",
                        f"第一行补 super.{name}();")
                if overridden and name == "dispose" and "super.dispose()" not in body:
                    hit(True, f, ln, f"{cname}.dispose 没调 super.dispose()",
                        "事件订阅、监听器都在 super 里释放，漏了就是泄漏",
                        "末尾补 super.dispose();")
                if is_state and name == "build" and "super.build(context)" not in body:
                    hit(True, f, ln, f"{cname} 覆写了 build 却没调 super.build(context)",
                        "AutomaticKeepAliveClientMixin 的硬性要求，漏了保活静默失效",
                        "页面 UI 写在 buildWithController 里，通常不必覆写 build")
                if name in ("build", "onPageResume", "onPageStart", "didChangeDependencies") \
                        and "observeEvent<" in body:
                    hit(True, f, ln, f"observeEvent 写在 {name} 里",
                        "它不解除已有订阅，放在会重复执行的地方，订阅数随重建线性增长"
                        "（症状：埋点重复上报、接口重复请求）", "移到 onPageInit，只订阅一次")
                if is_ctrl and re.search(r"(?<!super\.)\bnotifyListeners\s*\(\s*\)", body):
                    hit(True, f, ln, f"{cname}.{name} 里调了 notifyListeners()",
                        "它不推进任何 ID 的版本号，而依赖方全是按 ID 订阅的，"
                        "这次通知一个都惊动不了，页面静默停在旧数据上（debug 期有门禁会断言）",
                        "改用 notifySingleListener(id) / notifyMultiListeners([...])；"
                        "要「任何变更都刷新某一块」就留一个全量 ID，每次通知都一起列进来")

        # ---- 订阅传闭包字面量 ----
        for m in re.finditer(r"observeEvent<[^>]+>\s*\(\s*\(", code):
            hit(False, f, line_of(code, m.start()), "observeEvent 传的是闭包字面量",
                "重复订阅的拦截靠回调相等来识别，闭包每次都是新对象，拦不住",
                "传方法引用：observeEvent<Foo>(_onFoo)")

        # ---- create 交出的是所有权 ----
        for m in re.finditer(r"(?:create\s*:\s*\(\s*[^)]*\)|createController\s*\([^)]*\))\s*"
                             r"(?:=>|\{\s*return)\s*([A-Za-z_][A-Za-z0-9_.]*)\s*;", code):
            hit(False, f, line_of(code, m.start()), f"create 返回了已有实例 {m.group(1)}",
                "create 交出的是所有权：这个实例会在子树销毁时被 dispose，"
                "共享单例会让第一个关闭的页面把它 dispose 掉，其余子树静默冻结",
                "每个 create 各 new 一个；确实要共享就把 provider 提到共同祖先上")

        # ---- 嵌套 Navigator 复用 observer ----
        for m in re.finditer(r"Navigator\s*\((?:[^()]|\([^()]*\))*observers\s*:\s*\[[^\]]*"
                             r"FlRouteObserver\s*\(", code):
            hit(True, f, line_of(code, m.start()), "嵌套 Navigator 上挂了 FlRouteObserver()",
                "它是单例，同一实例挂到两个 Navigator 会撞 Flutter 的 "
                "assert(observer.navigator == null)",
                "嵌套栈各 new 一个 FlRouteObserverProxy()")

    # ---- 跨文件 ----
    has_container = re.search(r"\b(PageView|TabBarView|IndexedStack)\s*[(.]", whole) is not None
    if has_index and not has_scope:
        hit(has_container, files[0], 0,
            "有 observePageIndex => true，却没找到 FlPageIndexScope.wrap*"
            + ("" if has_container else "（扫描范围里也没有容器，确认宿主是不是在别的目录）"),
            "两半缺一不可：只在页面上打开而宿主没包，这些子页会被当成普通页面——"
            "首帧全部 start，切页一个事件都不来，且不报错",
            "宿主侧用 FlPageIndexScope.wrapChildren / wrapItemBuilder 包裹子页")
    if has_scope and not has_index:
        hit(False, files[0], 0, "包了 FlPageIndexScope，却没有任何 observePageIndex => true",
            "子页不开这个开关，Scope 注入的页码没人读，可见性永远不变",
            "容器子页上 override observePageIndex => true")
    if not has_observer:
        hit(False, files[0], 0, "扫描范围内没看到 FlRouteObserver()",
            "不注册不抛异常，只是页面生命周期回调一个都不来",
            "MaterialApp.navigatorObservers: [FlRouteObserver()]；"
            "确认一下是不是写在别的目录")

    err = sum(1 for h in hits if h[0])
    if not hits:
        print(f"✓ 扫了 {len(files)} 个文件，没发现已知的接错方式")
    else:
        warns = 0
        for bad, where, what, why, fix in sorted(hits, key=lambda h: (not h[0], h[1])):
            if bad:
                # 确定错误给全原因和改法：照着改一次就对，省一轮返工。
                print(f"❌ {where}  {what}\n     原因：{why}\n     改法：{fix}")
            else:
                warns += 1
                if warns <= 6:
                    print(f"⚠️  {where}  {what} → {fix}")
        if warns > 6:
            print(f"⚠️  另有 {warns - 6} 条待确认（同类，略）")
        print(f"\n{err} 个确定错误，{len(hits) - err} 个待确认。详见 references/pitfalls.md")

    rc = 1 if err else 0
    if analyze:
        rc = run_analyze() or rc
    elif not hits:
        print("  参数顺序、类型这类问题脚本看不出来，再跑一次 flutter analyze（或加 --analyze）")
    return rc


if __name__ == "__main__":
    sys.exit(main())
