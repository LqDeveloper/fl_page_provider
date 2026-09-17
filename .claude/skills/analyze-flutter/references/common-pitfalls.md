# Flutter 运行期故障自查清单：用错时机

## 收录标准（两条同时满足才收）

1. **调试期发现不了。** 红屏、溢出警戒条、布局错位这类一眼可见的问题**一律不收**——开发者自己跑一遍就解决了，写进审计报告是浪费篇幅。这里只收那些本地跑得好好的、上线才炸的。
2. **导致 app 不能正常工作。** 崩溃、功能静默失效、数据错乱、请求风暴。纯观感问题不收。

按这个标准筛下来，绝大多数是同一类根因：**API 用在了错误的时机**——用得太早（依赖还没建立）、用得太晚（对象已经销毁）、用在错误的帧阶段、或者被重复调用却没有防护。这类问题的共同特征是**只在特定时序下暴露**：慢网络、快速返回、后台切前台、低端机、恰好的操作顺序——所以本地测不出来。

文档因此按「时机错在哪里」组织，而不是按功能模块。

## 每条都必须有官方依据

依据只认四种，每条都在「依据」行注明：

| 依据类型 | 含义 |
|---|---|
| **框架断言** | Flutter 源码里有 `assert` 直接判定这是错的，运行时抛出带原文的错误，可拿原文反查 |
| **官方 lint 规则** | Dart linter 收录，有确切规则名，可配进 `analysis_options.yaml` |
| **官方 API 文档** | `api.flutter.dev` / `dart.dev` 明确写了"应该/不应该"，可引用原文 |
| **平台确定性事实** | 语言或运行时的确定行为，可验证但不是"规范" |

没有上述依据的一律标注**「工程共识，无官方规则」**，不伪装成规范。全文只有第 12 条属于这种情况。

## 为什么这类问题会反复发生

**官方有规则，但 `flutter_lints` 默认没开。**

`flutter_lints` 的 `flutter.yaml` 在 `package:lints/recommended.yaml` 之上只额外启用 10 条：

```
avoid_print                              avoid_unnecessary_containers
avoid_web_libraries_in_flutter           no_logic_in_create_state
prefer_const_constructors_in_immutables  sized_box_for_whitespace
sort_child_properties_last               use_build_context_synchronously
use_full_hex_values_for_flutter_colors   use_key_in_widget_constructors
```

而 `cancel_subscriptions`、`close_sinks`、`discarded_futures`、`unawaited_futures`、`avoid_void_async`——**恰好覆盖本文档里最贵的几类时序故障**——是 Dart linter 的正式规则，但默认不启用，所以永远不会在 CI 里报出来。

**先做这件事**，在项目 `analysis_options.yaml` 里加上：

```yaml
include: package:flutter_lints/flutter.yaml

linter:
  rules:
    - cancel_subscriptions   # 订阅活得比 State 久
    - close_sinks            # controller 活得比持有者久
    - discarded_futures      # Future 被丢弃，异常逃逸、顺序失控
    - unawaited_futures      # 异步上下文里漏写 await
    - avoid_void_async       # 调用方无法 await、无法 catch
```

存量代码会报出一批告警，按目录分批治理，不要一次性 `// ignore` 关掉。

**审计时**：项目没开这几条，本身就是一条该写进报告的改进建议（通常 P2），并且要说明它本可以拦住报告里的哪几条问题——这比单独列一条"建议加 lint"有说服力得多。

---

## 目录

- [一、用得太早：依赖还没建立](#一用得太早依赖还没建立)
- [二、用得太晚：对象已经销毁](#二用得太晚对象已经销毁)
- [三、用在错误的帧阶段](#三用在错误的帧阶段)
- [四、被重复调用，却没有防护](#四被重复调用却没有防护)
- [五、时序不确定：并发与竞态](#五时序不确定并发与竞态)
- [六、非时序，但同样是调试期查不出的运行期故障](#六非时序但同样是调试期查不出的运行期故障)
- [不收录的问题](#不收录的问题及原因)
- [Review 抓手速查](#review-抓手速查)

---

## 一、用得太早：依赖还没建立

### 1. `initState` 里访问 `InheritedWidget`

**依据**：官方 API 文档。`State.initState` 原文：

> "You should not use `BuildContext.dependOnInheritedWidgetOfExactType` from this method."
> "`didChangeDependencies` will be called immediately following this method, and `BuildContext.dependOnInheritedWidgetOfExactType` can be used there."

`Theme.of(context)`、`MediaQuery.of(context)`、`Localizations.of(context)` 内部都走 `dependOnInheritedWidgetOfExactType`。

**为什么调试期发现不了**：首次进页面时往往能拿到值，看起来一切正常。真正的故障是**后续依赖变化时不会更新**——用户切换深色模式、切换语言、旋转屏幕之后，这个值还停在旧的，界面就花了。而这些操作在开发时很少做。

```dart
// ✗ 依赖尚未建立；且之后主题变化不会通知到这里
@override
void initState() {
  super.initState();
  _color = Theme.of(context).primaryColor;
}

// ✓ 文档指定的位置
@override
void didChangeDependencies() {
  super.didChangeDependencies();
  _color = Theme.of(context).primaryColor;
}
```

**review 抓手**：`initState` 方法体内出现 `.of(context)`。

### 2. 布局完成前读取尺寸 / 位置

**依据**：框架断言。在 layout 阶段之前访问 `RenderBox.size` 会触发断言，报错原文包含：

```
RenderBox was not laid out
```

**为什么调试期发现不了**：拿到的尺寸可能恰好是上一帧的旧值，或者在开发机上时序刚好对，换台设备或换个进入路径就崩。

```dart
// ✗ initState / build 里 widget 还没布局
final box = _key.currentContext!.findRenderObject() as RenderBox;
final h = box.size.height;

// ✓ 等这一帧画完；或者直接用 LayoutBuilder / MediaQuery 拿约束
WidgetsBinding.instance.addPostFrameCallback((_) {
  if (!mounted) return;
  final box = _key.currentContext?.findRenderObject() as RenderBox?;
  if (box == null || !box.hasSize) return;
  setState(() => _height = box.size.height);
});
```

**review 抓手**：`grep -n "findRenderObject\|\.size\b" lib/`，看调用位置是不是在 `initState`/`build` 里。

---

## 二、用得太晚：对象已经销毁

这一节是**线上崩溃的最大来源**。共同模式：某个异步回调在 State 销毁之后才到达，回调里还在用已经失效的东西。

### 3. `await` 之后使用 `BuildContext`

**依据**：官方 lint 规则 `use_build_context_synchronously`（在 `flutter_lints` 中**默认启用**）。规则原文：

> "Do not use `BuildContext` across asynchronous gaps."
> "Storing `BuildContext` for later usage can easily lead to difficult-to-diagnose crashes."

官方 `BuildContext.mounted` 文档：

> "If a `BuildContext` is used across an asynchronous gap (i.e. after performing an asynchronous operation), consider checking `mounted` to determine whether the context is still valid before interacting with it."

**为什么调试期发现不了**：本地网络快，`await` 几乎瞬间返回，页面还在。线上弱网下请求要几秒，用户早就返回上一页了——这时 `Navigator.of(context)` 会抛"looking up a deactivated widget's ancestor"。

```dart
// ✗
await api.submit();
Navigator.of(context).pop();

// ✓ State 内用 mounted，其他地方用 context.mounted
await api.submit();
if (!mounted) return;
Navigator.of(context).pop();
```

**注意**：这条规则默认是开的。代码里还大量存在，说明团队在忽略 analyzer 告警——那本身是个更值得写进报告的流程问题。

### 4. `State` 销毁后调用 `setState`

**依据**：框架断言，报错原文：

```
setState() called after dispose(): This error happens if you call setState() on a
State object for a widget that no longer appears in the widget tree.
```

这是第 5、6、7 条（资源没释放）的下游症状——真正要修的是让那些资源在 `dispose` 里停掉，而不是到处加 `mounted` 判断打补丁。

### 5. `StreamSubscription` 未取消

**依据**：官方 lint 规则 `cancel_subscriptions`（stable，**默认不启用**）。

**双重后果**：订阅持有 State → 整棵子树无法 GC（内存单调上涨）；回调在销毁后继续触发 → 第 4 条的崩溃。

```dart
// ✓
StreamSubscription<T>? _sub;
@override
void dispose() {
  _sub?.cancel();
  super.dispose();
}
```

**review 抓手**：每个 `.listen(` 的返回值，去 `dispose()` 里找对应的 `.cancel()`。

### 6. `StreamController` / `IOSink` 未关闭

**依据**：官方 lint 规则 `close_sinks`（stable，**默认不启用**）。

**不算问题**：应用级单例持有的 controller，生命周期与进程等长是设计意图。

### 7. `AnimationController` / `Ticker` 未释放

**依据**：框架断言。`SingleTickerProviderStateMixin.dispose` 断言 ticker 已停止，报错原文包含：

```
<State> was disposed with an active Ticker.
```

`vsync: this` 把 controller 注册到了帧回调上。State 销毁后它仍持有 `this`，整棵子树无法回收，且每帧仍在被驱动。

**不算问题**：controller 由外部传入（`widget.controller`），应由创建方释放——在这里 dispose 反而是 bug。

---

## 三、用在错误的帧阶段

### 8. 在 `build` 期间触发 rebuild

**依据**：框架断言，报错原文：

```
setState() or markNeedsBuild() called during build.
```

**成因**：`build()` 里直接 `setState`，或同步调用了一个内部会 `notifyListeners()` 的方法（比如在 build 里调 controller 的 setter）。

**为什么调试期不一定发现**：如果那个分支要特定数据才走到（比如"首次加载完成时同步一次状态"），本地跑不到那条路径就不会崩。

```dart
// ✓ 推到当前帧绘制完之后
WidgetsBinding.instance.addPostFrameCallback((_) {
  if (mounted) setState(() => _ready = true);
});
```

**review 抓手**：`build` 方法体内出现 `setState(` 或 `notifyListeners(`。

### 9. 在 `build` 里创建有状态对象或数据源

**依据**：官方 API 文档。`FutureBuilder` 文档说明 `future` 必须是提前创建好的对象，如果在 `build` 里现场创建，每次 rebuild 都会得到一个新的 Future 并重新触发整个异步流程。

**为什么调试期发现不了**：功能"能用"——数据也显示出来了。故障是**请求量翻几倍**，只在监控后端 QPS 或者用户抱怨流量时才发现。

```dart
// ✗ 每次 rebuild 都重新发起请求
FutureBuilder(future: api.load(), builder: ...)

// ✓ 在 initState 里创建一次，存进字段
late final Future<Data> _future = api.load();
FutureBuilder(future: _future, builder: ...)
```

同理，`build` 里 `new` 任何 Controller、Timer、StreamController 都是错的——它们会在每次 rebuild 时被重建，旧的还没释放。

**review 抓手**：`build` 方法体内出现 `future:`/`stream:` 后面跟方法调用，或 `= XxxController(`。

---

## 四、被重复调用，却没有防护

这一类的特征是：**方法本身没写错，错在它被调用的次数超出作者预期**。

### 10. `didChangeDependencies` 里发请求

**依据**：官方 API 文档。`State.didChangeDependencies` 说明它在 `initState` 之后调用一次，**并在依赖的 InheritedWidget 变化时再次调用**。主题切换、语言切换、屏幕旋转、键盘弹起改变 MediaQuery 都会触发。

**为什么调试期发现不了**：开发时很少切主题、转屏幕。线上用户一弹键盘，接口就多打一次。

```dart
// ✓ 一次性初始化放 initState；必须依赖 context 的加标志位
bool _loaded = false;
@override
void didChangeDependencies() {
  super.didChangeDependencies();
  if (_loaded) return;
  _loaded = true;
  _load();
}
```

**review 抓手**：`didChangeDependencies` 方法体里出现网络/IO 调用。

### 11. 没停旧的 Timer 就启动新的

**依据**：无单条 lint 规则，但**后果由框架断言暴露**（销毁后触发 → 第 4 条的 `setState() called after dispose()`）。属于 `Timer.cancel` 的正常用法要求。

**这是本文档里最隐蔽的一条**：每一处单独看都对，凑在一起才错。只要创建 Timer 的语句写在一个可能被调多次的方法里，而这条语句之前没有先 `cancel()` 旧的，就会出现 N 个 Timer 并行——**setState 频率和网络请求量都变成 N 倍，且 N 随用户操作单调增长**。

会被重复调用的典型入口：`didUpdateWidget`、`didChangeAppLifecycleState` 的 `resumed` 分支、`didChangeDependencies`、下拉刷新、重试、重连，以及任何叫 `start`/`restart` 的方法。

**为什么调试期发现不了**：开发时不会反复切后台、反复下拉刷新。用户切十次后台，就有十个 Timer 在跑。

```dart
// ✓ 就一行
void _startPolling() {
  _poll?.cancel();      // ← 关键
  _poll = Timer.periodic(interval, (_) => _refresh());
}
```

**判断方法**：找到创建语句所在的方法名，**全文搜这个方法被谁调用、调了几处**。只在 `initState` 里创建一次的不算问题。

---

## 五、时序不确定：并发与竞态

### 12. 异步竞态：慢的响应覆盖了快的

**依据**：**工程共识，无官方 lint 规则、无框架断言。** 写进报告时应如实说明这一点。

**症状**：搜索时先输入 "ab" 再输入 "abc"，最终显示的是 "ab" 的结果——"ab" 的请求慢、后返回，覆盖了 "abc"。切 tab 快速来回、分页快速滑动同理。

**为什么调试期发现不了**：本地每个请求都是几十毫秒，先发的必先回，顺序从不错乱。线上网络抖动才会出现后发先至。

```dart
// ✓ 记序号，对不上就丢弃
int _seq = 0;
Future<void> _search(String q) async {
  final mine = ++_seq;
  final r = await api.search(q);
  if (!mounted || mine != _seq) return;   // 已经有更新的请求了
  setState(() => _results = r);
}
```

**review 抓手**：`await` 之后直接 `setState` 赋值，且该方法可能被并发触发（搜索框 `onChanged`、切 tab、下拉刷新、分页）。

### 13. Future 被丢弃：异常逃逸，顺序失控

**依据**：官方 lint 规则 `discarded_futures`、`unawaited_futures`（均 stable，**默认不启用**）。

**三重后果**：异常逃逸到 Zone，日志里只有一句没有堆栈的报错；后续代码不等它完成就往下走，顺序不可控；如果在循环里，直接变成无上限并发。

**为什么调试期发现不了**：本地异步操作瞬间完成，看起来顺序是对的；异常也很少触发。

```dart
// ✗ 保存失败了，用户不知道，日志也查不到
saveDraft();

// ✓ 要么等，要么显式声明"我知道我不等"并接住异常
await saveDraft();
unawaited(saveDraft().catchError((e, s) => logger.error(e, s)));
```

`unawaited` 来自 `dart:async`。它的价值在于是一个**显式的、可搜索的**标记，区分"想好了不等"和"忘了写 await"。

### 14. `async` 用在 `void` 上

**依据**：官方 lint 规则 `avoid_void_async`（stable，**默认不启用**）。

返回 `void` 意味着调用方拿不到 Future——await 不了、catch 不了，异常只能逃逸。

```dart
// ✗
void submit() async { await api.post(...); }
// ✓
Future<void> submit() async { await api.post(...); }
```

**例外**：事件回调（`onPressed: () async { ... }`）签名由框架规定为 `void Function()`，这是框架契约不是错误——但回调体内部要自己 try/catch。

### 15. 对无界集合并发扇出

**依据**：**工程共识**（`Future.wait` 本身是正确 API，没有规则禁止它）。但后果确定：并发数等于集合长度，没有任何上限。

**为什么调试期发现不了**：调试数据 3 条，`Future.wait` 飞快。线上 500 条就是同时打出 500 个请求——连接池排队、后端限流 429、超时后又同时重试。

```dart
// ✗ 并发数 = ids.length
await Future.wait(ids.map((id) => fetch(id)));

// ✓ 分批
for (var i = 0; i < ids.length; i += 6) {
  await Future.wait(ids.skip(i).take(6).map(fetch));
}
```

**判断前必须回答**：这个集合运行时最大有多少元素？追到来源——写死的常量小集合不是问题，来自接口/数据库/用户选择就是隐患。**追不到就如实写"取决于运行时数据量，建议确认上界"**，不要断言一定拥堵。

---

## 六、非时序，但同样是调试期查不出的运行期故障

只收两条，都符合"本地测不出、线上必炸"的标准。

### 16. `jsonDecode` 按字面量决定 int 还是 double

**依据**：`dart:convert` 的确定行为——JSON 里 `1` 解出 `int`，`1.0` 解出 `double`，两者在 Dart 里是不同类型，`as int` 对 `double` 抛 `TypeError`。

**为什么调试期发现不了**：测试环境那条数据恰好是整数。生产环境某个用户的数据是小数，或者服务端换了序列化框架，就崩。**同一个接口，有的用户崩有的不崩。**

```dart
// ✗ type 'double' is not a subtype of type 'int'
final amount = json['amount'] as int;

// ✓ 先当 num 收
final amount = (json['amount'] as num?)?.toInt() ?? 0;
final ratio  = (json['ratio']  as num?)?.toDouble() ?? 0;
```

**review 抓手**：`grep -n "as int\|as double" lib/`，重点看 `fromJson`。
**不算问题**：数据来自本地常量、枚举 index、或自己 `toJson` 的往返。

### 17. `double` 不能精确表示十进制小数

**依据**：IEEE-754 二进制浮点数的确定行为。`0.1 + 0.2 == 0.3` 为 `false`，`19.99 * 3 == 59.97000000000001`。

**为什么调试期发现不了**：单个商品的价格显示正确。故障出在累加之后——十几件商品的总价差一分钱，对账才发现。

```dart
// ✓ 整数最小单位（分）运算，只在展示时换算
int totalCents = priceCents * count;
final display = (totalCents / 100).toStringAsFixed(2);
```

**不算问题**：纯展示、不参与累加对账的比例值（评分、百分比）。

---

## 不收录的问题及原因

以下问题确实高频，但**调试期跑一遍就能发现并解决**，不占审计报告篇幅。审计时看到最多在 P3 列一行位置，不展开：

| 问题 | 为什么不收 |
|---|---|
| `Expanded`/`Flexible` 用在非 Flex 父级下 | debug 立即红屏（`Incorrect use of ParentDataWidget`），跑一次就暴露 |
| 无界约束下放 `ListView` | debug 立即红屏（`Vertical viewport was given unbounded height`） |
| RenderFlex 溢出、键盘遮挡输入框 | 黄黑警戒条，肉眼可见 |
| 文本溢出未设 `maxLines`/`overflow` | 观感问题，不影响功能与数据 |
| 缺 `SafeArea` | 布局适配，视觉可见即可修 |
| 颜色/文案硬编码 | 不引发运行故障；且相关 lint `use_full_hex_values_for_flutter_colors` 只管十六进制写法，不管是否硬编码 |
| `GlobalKey` 重复使用 | debug 立即断言（`Multiple widgets used the same GlobalKey`） |
| 命名、`const`、未用 import 等 | `flutter analyze` 直接报，属于 P3 |
| `WillPopScope` 已弃用 | analyzer 报 deprecated，属 P3。**注意 `PopScope` 回调签名在版本间变更过，给替换方案前必须确认项目实际 SDK 版本** |

**这张表本身也有用**——审计时如果发现代码里大量存在这类"跑一次就会暴露"的问题，说明**项目可能根本没被完整运行或测试过**，那是一条比单个问题严重得多的结论，值得单独写一句。

---

## Review 抓手速查

```bash
cd <package>

echo '=== 0. 关键 lint 开了没（默认都不开，是本文档多数问题的根因）==='
grep -nE "cancel_subscriptions|close_sinks|discarded_futures|unawaited_futures|avoid_void_async" \
  analysis_options.yaml || echo '  ⚠ 一条都没开：资源泄漏与异步失控全靠人肉 review'

echo '=== 一、用得太早 ==='
echo '[1] initState 里访问依赖:'; grep -rn -A8 "void initState" lib/ | grep "\.of(context)"
echo '[2] 布局前读尺寸:';        grep -rn "findRenderObject" lib/

echo '=== 二、用得太晚（崩溃主来源）==='
echo '[3] await 后用 context:';  grep -rn -B2 -A2 "await " lib/ | grep -n "of(context)" | head -20
echo '[5] listen 未 cancel:';    grep -rn "\.listen(" lib/
echo '[6] controller 未 close:'; grep -rn "StreamController" lib/
echo '[7] Ticker 未 dispose:';   grep -rn "AnimationController(" lib/

echo '=== 三、错误的帧阶段 ==='
echo '[8] build 里 setState:';   grep -rn -A40 "Widget build" lib/ | grep "setState(\|notifyListeners("
echo '[9] build 里建数据源:';     grep -rn -A40 "Widget build" lib/ | grep -E "future:\s*\w+\(|= \w*Controller\("

echo '=== 四、被重复调用 ==='
echo '[10] 依赖变化里发请求:';    grep -rn -A6 "didChangeDependencies" lib/
echo '[11] Timer 创建点:';        grep -rn "Timer.periodic\|Timer(" lib/
echo '     ↑ 对每一处，找出所在方法名，再全文搜该方法被调用几次'

echo '=== 五、并发与竞态 ==='
echo '[12] await 后直接 setState:'; grep -rn -A3 "await " lib/ | grep "setState" | head -20
echo '[13] 丢弃的 Future:';         grep -rnE "^\s+_?[a-z]\w*\([^)]*\);\s*$" lib/ | head -20
echo '[14] async void:';            grep -rnE "void \w+\([^)]*\) async" lib/
echo '[15] 无界扇出:';              grep -rn "Future.wait" lib/

echo '=== 六、数据相关 ==='
echo '[16] JSON 强转:';   grep -rn "as int\b\|as double\b" lib/
echo '[17] 金额 double:'; grep -rniE "double +\w*(price|amount|total|fee|money|balance)" lib/
```

**抓手命中 ≠ 问题。** 每条上面都写了"不算问题"的情形，逐条排除后再写进报告，并按 `SKILL.md` 的判据（线上出事概率 × 严重程度）定级——第二节（用得太晚）多为 P0，第四、五节多为 P0/P1，第一、三、六节视影响面在 P1/P2。
