#!/usr/bin/env python3
"""生成 fl_page_provider 的页面模板：ID 枚举 + Controller + Page Widget。

模板里那些 super 调用、ID 登记、订阅位置都是「漏了不报错但静默失效」的地方，
交给脚本写比每次现拼可靠，也省掉把整份模板读进上下文。

  python3 scripts/new_page.py user_profile --dir lib/pages
  python3 scripts/new_page.py user_profile --ids avatar,name,list --keep-alive
  python3 scripts/new_page.py feed msg mine --host home      # 四件套 + PageView 宿主，一次生成
  python3 scripts/new_page.py order --bus --split            # 全局事件 + 三文件分开
  python3 scripts/new_page.py demo --stdout                  # 只打印不落盘
"""

import argparse
import os
import re
import sys

# ---------- 命名 ----------


def to_snake(name: str) -> str:
    s = re.sub(r"[\s\-]+", "_", name.strip())
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"_+", "_", s).strip("_").lower()
    s = re.sub(r"_(page|widget)$", "", s)
    return s


def to_pascal(snake: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in snake.split("_") if p)


def to_camel(token: str) -> str:
    p = to_pascal(to_snake(token))
    return p[:1].lower() + p[1:]


IDENT = re.compile(r"^[a-z][A-Za-z0-9]*$")


# ---------- 代码片段 ----------


def header(*imports: str) -> str:
    return "\n".join(imports) + "\n"


def enum_block(enum: str, ids: list) -> str:
    return (
        f"/// {enum} 是本页的刷新单位：一个 ID 对应一块会单独重建的 UI。\n"
        f"/// 加字段就加 ID——通知谁，就只有订阅了谁的那一块重建。\n"
        f"enum {enum} {{ {', '.join(ids)} }}\n"
    )


def bus_block(evt: str) -> str:
    return (
        f"/// 全局事件：任何一处 `dispatchEvent(const {evt}())` 发出，\n"
        f"/// 所有 `observeEvent<{evt}>()` 的 Controller 都会收到（含发送方自己）。\n"
        f"class {evt} {{\n"
        f"  const {evt}();\n"
        f"}}\n"
    )


def controller_block(cls: str, enum: str, ids: list, bus_evt, app_lifecycle: bool) -> str:
    first = ids[0]
    out = [
        f"class {cls} extends FlBaseController<{enum}> {{",
        "  /// 只有登记在这里的 ID 才会触发重建。",
        "  /// 漏登记的 ID 版本号恒为 0，比对永远得出「没变」——不报错，UI 停在旧数据上。",
        "  @override",
        f"  List<{enum}> get shouldNotifyIds => {enum}.values;",
        "",
        "  int _count = 0;",
        "",
        "  int get count => _count;",
        "",
        "  void increase() {",
        "    _count++;",
        f"    // 改完数据再通知，只通知真正变了的 ID；多个一起变用 notifyMultiListeners。",
        f"    // 不要调 notifyListeners()：它不推进 ID 版本号，FlSelector 一个都不会重建。",
        f"    notifySingleListener({enum}.{first});",
        "  }",
        "",
        "  @override",
        "  void onPageInit() {",
        "    super.onPageInit(); // 必须：shouldNotifyIds 在这里登记",
    ]
    if bus_evt:
        out += [
            "    // 订阅只在这里做一次，且传方法引用——写闭包字面量拦不住重复订阅，",
            "    // 订阅数会随重建线性增长。取消由基类在 dispose 里做，不用自己管。",
            f"    observeEvent<{bus_evt}>(_on{bus_evt});",
        ]
    else:
        out += [
            "    // 要收全局事件就在这里订阅一次，且传方法引用（闭包字面量拦不住重复订阅）：",
            "    // observeEvent<LoginEvent>(_onLogin);",
        ]
    out += [
        "  }",
        "",
    ]
    if bus_evt:
        out += [
            f"  void _on{bus_evt}({bus_evt} event) {{",
            f"    notifySingleListener({enum}.{first});",
            "  }",
            "",
        ]
    out += [
        "  @override",
        "  void onPageStart() {",
        "    super.onPageStart();",
        "    // 页面可见：轮询 / WebSocket / 曝光埋点 / 倒计时——dialog 盖上来时**不**停。",
        "  }",
        "",
        "  @override",
        "  void onPageStop() {",
        "    super.onPageStop();",
        "    // 与 onPageStart 成对；路由信息（routeName）要读就在这里读，onPageDispose 里已是 null。",
        "  }",
        "",
        "  @override",
        "  void onPageResume() {",
        "    super.onPageResume();",
        "    // 页面可交互：视频音频 / 动画 / 相机 / 定位——dialog 一盖就该停的放这对。",
        "  }",
        "",
        "  @override",
        "  void onPagePause() {",
        "    super.onPagePause();",
        "  }",
        "",
    ]
    if app_lifecycle:
        out += [
            "  @override",
            "  void onAppForeground() {",
            "    super.onAppForeground();",
            "    // 需要 observeAppLifecycle => true 才会来。",
            "  }",
            "",
            "  @override",
            "  void onAppBackground() {",
            "    super.onAppBackground();",
            "  }",
            "",
        ]
    out += [
        "  @override",
        "  void dispose() {",
        "    // 自己 new 的 Timer / StreamSubscription / TextEditingController 在这里释放；",
        "    // observeEvent 的订阅由基类自动取消，不用重复写。",
        "    super.dispose();",
        "  }",
        "}",
    ]
    return "\n".join(out) + "\n"


def _fit(one_line: str, wrapped: str) -> str:
    """超过 80 列就换成 dart format 会排成的样子，省得生成完还要再 format 一遍。"""
    return one_line if len(one_line) <= 80 else wrapped


def _members(cls: str) -> list:
    """createController + buildWithController 的签名，长了自动折行。"""
    return [
        "  @override",
        _fit(f"  {cls} createController(BuildContext context) => {cls}();",
             f"  {cls} createController(BuildContext context) =>\n      {cls}();"),
        "",
        "  @override",
        _fit(f"  Widget buildWithController(BuildContext context, {cls} controller) {{",
             "  Widget buildWithController(\n    BuildContext context,\n"
             f"    {cls} controller,\n  ) {{"),
    ]


def page_block(
    page: str,
    cls: str,
    enum: str,
    ids: list,
    title: str,
    stateful: bool,
    keep_alive: bool,
    page_index: bool,
    app_lifecycle: bool,
) -> str:
    first = ids[0]
    body = [
        "    return Scaffold(",
        f"      appBar: AppBar(title: const Text('{title}')),",
        "      body: Center(",
        f"        // 只有 {enum}.{first} 被通知时，这一块才重建；页面其余部分不动。",
        f"        child: FlSelector<{enum}, {cls}>(",
        f"          ids: const [{enum}.{first}],",
        "          builder: (_, c, __) => Text('${c.count}'),",
        "        ),",
        "      ),",
        "      floatingActionButton: FloatingActionButton(",
        "        // 只是调方法：直接用 controller（或 context.rc），不建立依赖。",
        "        onPressed: controller.increase,",
        "        child: const Icon(Icons.add),",
        "      ),",
        "    );",
    ]
    switches = []
    if page_index:
        switches += [
            "  /// 本页是 PageView / TabBarView / IndexedStack 的一页。",
            "  /// 宿主侧**还必须**用 FlPageIndexScope.wrapChildren 包裹子页，只做一半静默无效。",
            "  @override",
            "  bool get observePageIndex => true;",
            "",
        ]
    if app_lifecycle:
        switches += [
            "  /// 打开后 Controller 才收得到 onAppForeground / onAppBackground。",
            "  @override",
            "  bool get observeAppLifecycle => true;",
            "",
        ]

    if not stateful:
        out = [
            f"class {page} extends FlBasePage<{cls}> {{",
            f"  const {page}({{super.key}});",
            "",
        ]
        out += switches
        out += _members(cls) + body + ["  }", "}"]
        return "\n".join(out) + "\n"

    state = f"_{page}State"
    out = [
        f"class {page} extends StatefulWidget {{",
        f"  const {page}({{super.key}});",
        "",
        "  @override",
        f"  State<{page}> createState() => {state}();",
        "}",
        "",
        _fit(f"class {state} extends FlBasePageState<{page}, {cls}> {{",
             f"class {state}\n    extends FlBasePageState<{page}, {cls}> {{"),
    ]
    if keep_alive:
        out += [
            "  /// 切走再切回要保住滚动位置 / 表单输入时才开；开了这一页就不会被销毁。",
            "  @override",
            "  bool get wantKeepAlive => true;",
            "",
        ]
    out += switches + _members(cls) + body + ["  }", "}"]
    return "\n".join(out) + "\n"


# ---------- 落盘 ----------


def write(path: str, content: str, force: bool, stdout: bool) -> None:
    if stdout:
        print(f"// ===== {path} =====")
        print(content)
        return
    if os.path.exists(path) and not force:
        sys.exit(f"✗ {path} 已存在（要覆盖加 --force）")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✓ {path}")


def host_block(host_snake: str, children: list) -> str:
    """PageView 宿主：FlPageIndexScope 的包裹与 controller 类型最容易写错，交给脚本。"""
    pascal = to_pascal(host_snake)
    page, state = f"{pascal}Page", f"_{pascal}PageState"
    items = "\n".join(
        "          BottomNavigationBarItem(\n"
        "            icon: Icon(Icons.circle_outlined),\n"
        f"            label: '{to_pascal(c)}',\n"
        "          ),"
        for c in children)
    kids = "\n".join(f"      const {to_pascal(c)}Page()," for c in children)
    imports = "\n".join(f"import '{c}_page.dart';" for c in children)
    return f"""import 'package:flutter/material.dart';
import 'package:fl_page_provider/fl_page_provider.dart';

{imports}

class {page} extends StatefulWidget {{
  const {page}({{super.key}});

  @override
  State<{page}> createState() => {state}();
}}

class {state} extends State<{page}> {{
  final PageController _controller = PageController();
  int _index = 0;

  static const List<Widget> _pages = [
{kids}
  ];

  @override
  void dispose() {{
    _controller.dispose();
    super.dispose();
  }}

  @override
  Widget build(BuildContext context) {{
    return Scaffold(
      body: PageView(
        controller: _controller,
        // 这一半不能省：子页只开 observePageIndex 而宿主没包，是静默无效
        // （首帧全部 start，切页一个事件都不来）。嵌套容器每层都要包。
        children: FlPageIndexScope.wrapChildren(
          controller: _controller,
          children: _pages,
        ),
      ),
      bottomNavigationBar: BottomNavigationBar(
        type: BottomNavigationBarType.fixed,
        currentIndex: _index,
        // jumpToPage 当场提交页码；animateToPage 掠过的中间页不会发事件。
        onTap: (i) {{
          setState(() => _index = i);
          _controller.jumpToPage(i);
        }},
        items: const [
{items}
        ],
      ),
    );
  }}
}}
"""


def check_pubspec() -> None:
    """顺手替使用方做掉「确认依赖」那一步，省一次工具调用。"""
    for d in (".", ".."):
        p = os.path.join(d, "pubspec.yaml")
        if os.path.exists(p):
            text = open(p, encoding="utf-8", errors="replace").read()
            if "fl_page_provider" not in text:
                print("⚠️  当前 pubspec.yaml 里没有 fl_page_provider——先问用户要不要装"
                      "（flutter pub add fl_page_provider），别直接按生成的代码走。\n")
            return


def main() -> None:
    p = argparse.ArgumentParser(description="生成 fl_page_provider 页面模板")
    p.add_argument("name", nargs="+",
                   help="页面名，可一次多个；snake_case 或 PascalCase 都行（user_profile / UserProfile）")
    p.add_argument("--host", metavar="NAME",
                   help="再生成一个 PageView 宿主页，把这些页面作为子页包进 FlPageIndexScope"
                        "（隐含子页 --page-index）")
    p.add_argument("--dir", default="lib/pages", help="输出目录，默认 lib/pages")
    p.add_argument("--ids", default="content", help="ID 枚举值，逗号分隔，默认 content")
    p.add_argument("--stateful", action="store_true", help="用 FlBasePageState（需要 State 时）")
    p.add_argument("--keep-alive", action="store_true", help="wantKeepAlive => true，隐含 --stateful")
    p.add_argument("--page-index", action="store_true",
                   help="observePageIndex => true，容器子页用，隐含 --stateful")
    p.add_argument("--app-lifecycle", action="store_true", help="observeAppLifecycle => true")
    p.add_argument("--bus", action="store_true", help="额外生成一个全局总线事件类并接好订阅")
    p.add_argument("--split", action="store_true", help="拆成 event / controller / page 三个文件")
    p.add_argument("--force", action="store_true", help="覆盖已存在的文件")
    p.add_argument("--stdout", action="store_true", help="只打印，不落盘")
    a = p.parse_args()
    if not a.stdout:
        check_pubspec()

    ids = [to_camel(x) for x in a.ids.split(",") if x.strip()]
    if not ids:
        sys.exit("✗ --ids 为空")
    bad = [i for i in ids if not IDENT.match(i)]
    if bad:
        sys.exit(f"✗ 这些 ID 不是合法的 Dart 标识符：{bad}")
    if len(set(ids)) != len(ids):
        sys.exit("✗ --ids 里有重复项")

    page_index = a.page_index or bool(a.host)
    stateful = a.stateful or a.keep_alive or page_index
    pkg = "import 'package:fl_page_provider/fl_page_provider.dart';"
    mat = "import 'package:flutter/material.dart';"
    d = a.dir.rstrip("/")

    snakes = []
    for raw in a.name:
        snake = to_snake(raw)
        if not snake:
            sys.exit("✗ 页面名为空")
        snakes.append(snake)
        pascal = to_pascal(snake)
        page, cls, enum = f"{pascal}Page", f"{pascal}Controller", f"{pascal}Event"
        bus_evt = f"{pascal}Changed" if a.bus else None

        enum_src = enum_block(enum, ids)
        if bus_evt:
            enum_src += "\n" + bus_block(bus_evt)
        ctrl_src = controller_block(cls, enum, ids, bus_evt, a.app_lifecycle)
        page_src = page_block(page, cls, enum, ids, pascal, stateful,
                              a.keep_alive, page_index, a.app_lifecycle)

        if a.split:
            write(f"{d}/{snake}_event.dart", enum_src, a.force, a.stdout)
            write(f"{d}/{snake}_controller.dart",
                  header(pkg, f"import '{snake}_event.dart';") + "\n" + ctrl_src,
                  a.force, a.stdout)
            write(f"{d}/{snake}_page.dart",
                  header(mat, pkg, f"import '{snake}_controller.dart';",
                         f"import '{snake}_event.dart';") + "\n" + page_src,
                  a.force, a.stdout)
        else:
            write(f"{d}/{snake}_page.dart",
                  header(mat, pkg) + "\n" + enum_src + "\n" + page_src + "\n" + ctrl_src,
                  a.force, a.stdout)

    if a.host:
        write(f"{d}/{to_snake(a.host)}_page.dart", host_block(to_snake(a.host), snakes),
              a.force, a.stdout)

    if not a.stdout:
        print("\n接下来：根 Navigator 挂 FlRouteObserver()（漏了生命周期回调一个都不来，且不报错）；"
              "改完跑 python3 scripts/verify.py lib/ 再 flutter analyze")
        if page_index and not a.host:
            print("子页开了 observePageIndex，宿主侧必须用 FlPageIndexScope.wrapChildren 包裹"
                  "（只做一半静默无效）；宿主也可以用 --host 一起生成")


if __name__ == "__main__":
    main()
