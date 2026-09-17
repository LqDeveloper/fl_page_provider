# 五维度检查清单

每条格式：**怎么识别** → **为什么是问题** → **改造方向**。
清单是索引不是判决书：命中某条只说明"值得去读那段代码"，是否成为报告条目取决于你读完原文后的判断。

---

## 目录

- [维度一：Flutter / Dart 开发规范](#维度一flutter--dart-开发规范)
- [维度二：内存泄漏与内存暴涨](#维度二内存泄漏与内存暴涨)
- [维度三：UI 线程阻塞与掉帧](#维度三ui-线程阻塞与掉帧)
- [维度四：代码精简](#维度四代码精简)
- [维度五：扩展性与解耦](#维度五扩展性与解耦)
- [维度六：网络请求并发与调度](#维度六网络请求并发与调度)
- [Timer 专项检查](#timer-专项检查跨内存--卡顿--网络)
- [高频误报清单](#高频误报清单必读)

---

## 维度一：Flutter / Dart 开发规范

多数属 P3（只给位置），但下面标了 ⬆ 的会实际引发线上问题，按实际危害提级。

| 检查项 | 识别 | 说明 |
|---|---|---|
| ⬆ async 后使用 BuildContext | `await` 之后出现 `context`（Navigator.of/ScaffoldMessenger.of/Theme.of） | Widget 可能已被移除，`context` 失效抛异常。修：`if (!mounted) return;`（State 内）或 `if (!context.mounted) return;` |
| ⬆ initState 中依赖 InheritedWidget | `initState()` 里出现 `Theme.of` / `MediaQuery.of` / `.dependOnInheritedWidgetOfExactType` | 此时依赖尚未建立，值不会更新且可能抛错。修：移到 `didChangeDependencies()` |
| ⬆ dart:io 平台判断未防 web | `Platform.isAndroid` / `Platform.isIOS` 且 package 未声明仅移动端 | web 上 `dart:io` 不可用会崩。修：先判 `kIsWeb`，或改用 `defaultTargetPlatform` |
| ⬆ 吞异常 | `catch (e) {}` 空块，或只 `print(e)` | 线上故障无法定位。修：至少上抛或经统一日志出口 |
| ⬆ 库导出面失控 | `lib/` 根目录直接放实现文件，而非 `lib/src/` + 单一导出文件 | 使用方会 import 内部实现，之后任何内部重构都是破坏性变更。修：实现移入 `lib/src/`，根目录只留 `<package>.dart` 做 `export` |
| print 调试输出 | `print(` | 生产日志污染，且 print 在 release 仍执行。修：`debugPrint` 或日志抽象 |
| 缺 const 构造函数 | Widget 类构造函数无 `const`，字段可 final | 阻断上层 const 优化，父级 rebuild 时无法复用 Element |
| 未用 super parameters | `Key? key`+`super(key: key)`（Dart 2.17+） | 冗余。修：`super.key` |
| 公共 API 无 dartdoc | `lib/` 下 public 类/方法无 `///` | package 的公共 API 是对外契约 |
| 命名不符 | 文件非 lower_snake_case；私有成员无 `_` 前缀 | Effective Dart |
| 缺 analysis_options.yaml | 根目录无该文件或未 include flutter_lints | 整个团队失去静态防线 |
| 可空处理粗暴 | 大量 `!`（bang）解包 | 空安全形同虚设，崩溃点。修：`?.` / `??` / 提前判空 |

---

## 维度二：内存泄漏与内存暴涨

**这是 P0 的主要来源，也是最容易误报的维度，务必逐个核对 `dispose()` 原文。**

### 2.1 必须成对释放的资源

在任意 `State` 类里创建了下列对象，就必须在同一个 `State` 的 `dispose()` 中释放。核查方法：找到字段名 → 打开 `dispose()` → 确认该字段被释放（直接释放，或调用的私有方法里释放）。

| 资源 | 创建 | 释放 |
|---|---|---|
| `AnimationController` | `AnimationController(vsync: this)` | `.dispose()` |
| `TextEditingController` | `TextEditingController()` | `.dispose()` |
| `ScrollController` / `PageController` / `TabController` | 同名构造 | `.dispose()` |
| `FocusNode` | `FocusNode()` | `.dispose()` |
| `ChangeNotifier` / `ValueNotifier` | 构造 | `.dispose()` |
| `StreamSubscription` | `.listen(...)` 的返回值 | `.cancel()` |
| `StreamController` | `StreamController()` | `.close()` |
| `Timer` / `Timer.periodic` | 构造 | `.cancel()` |
| `Ticker` | `createTicker(...)` | `.dispose()` |
| `OverlayEntry` | `OverlayEntry(...)` + `insert` | `.remove()` |
| `ReceivePort` / `Isolate` | `ReceivePort()` / `Isolate.spawn` | `.close()` / `.kill()` |
| 平台资源（VideoPlayerController、相机、播放器、WebViewController 等） | 构造/初始化 | 各自的 dispose/release |

**为什么是 P0**：这些对象大多持有 `this`（State）的引用或注册在全局调度器上。State 未被释放 → 它引用的整棵 Element 子树、图片、数据缓存都无法 GC。页面反复进出，内存单调上涨直到 OOM。`Timer.periodic` 更糟：它还会在页面销毁后继续触发 `setState`，抛 `setState() called after dispose()`。

### 2.2 监听器成对

| 注册 | 注销 |
|---|---|
| `xxx.addListener(_onChange)` | `xxx.removeListener(_onChange)` |
| `WidgetsBinding.instance.addObserver(this)` | `removeObserver(this)` |
| 事件总线 / 全局单例的 `on()`、`subscribe()`、`register()` | 对应的 off/unsubscribe |
| `SystemChannels` / `MethodChannel` handler | 置空或反注册 |

注意：`addListener(() {...})` 传匿名闭包**无法**被 `removeListener` 移除（闭包不是同一个实例）——这本身就是一个必报的缺陷。修：改成具名方法引用。

传入的 controller 若来自 widget 参数（`widget.controller`），**通常不应由本 State 释放**，释放了反而崩。看清来源再下结论。

### 2.3 长生命周期持有短生命周期

| 识别 | 说明 |
|---|---|
| `static` 字段持有 `BuildContext` / `State` / `Widget` / `GlobalKey` | 单例永生 → 被持有的页面永远不释放。P0 |
| 全局 `static Map/List` 做缓存，无容量上限、无过期、无清理 | 内存单调增长。修：LRU 上限，或改用 `WeakReference`（Dart 3.0+） |
| 闭包被注册到全局对象，闭包体内引用 `this` / `context` / `setState` | 隐式强引用，效果同上 |
| 单例里存整个响应对象 / 大 List 且从不清 | 数据类内存暴涨 |

### 2.4 图片与大对象

| 识别 | 说明 |
|---|---|
| `Image.network(...)` / `Image.file(...)` 无 `cacheWidth` / `cacheHeight` | 按原始像素解码。一张 4000×3000 的图解码后约 48MB（4 bytes/px），在列表里几张就 OOM。修：传 `cacheWidth: (displayWidth * devicePixelRatio).round()`，或用 `ResizeImage` |
| 一次性把大文件 / 大 JSON 读进内存并长期持有 | 修：流式处理，或用完置空 |
| 列表项持有完整原始数据对象 | 修：映射成轻量 view model |
| 未限制 `PaintingBinding.instance.imageCache` 大小而项目图片很大 | 默认 100MB / 1000 张，图多时可下调 |

### 2.5 列表构建方式

`ListView(children: [...])` / `Column` + `map().toList()` 渲染长列表：**所有 item 立即全部构建并常驻**。数据量大时既是内存问题也是卡顿问题。修：`ListView.builder` / `SliverList`（按需构建 + 回收）。数据量确定很小（如 ≤10 的固定菜单）时不是问题——先确认数据来源。

---

## 维度三：UI 线程阻塞与掉帧

Flutter UI 线程每帧预算 16.6ms（60Hz）/ 8.3ms（120Hz）。超过就掉帧。

### 3.1 主线程上的重活（P0）

| 识别 | 说明 |
|---|---|
| 同步**批量**读写：`readAsStringSync` / `readAsBytesSync` / `writeAsStringSync` | 磁盘 IO 直接阻塞 UI 线程，几十到几百 ms。修：换 `await` 异步版本。**注意区分**：`existsSync` / `statSync` / `lastModifiedSync` 这类元数据操作，官方 lint 规则 `avoid_slow_async_io` 反而推荐用同步版本（`dart:io` 的异步版更慢），不要把它们当成阻塞问题报——那是把规范讲反了 |
| 大 `jsonDecode` / `jsonEncode` 在主线程 | 修：`await compute(jsonDecode, str)` 移到 Isolate。小 JSON（几 KB）不必，标注"取决于数据量" |
| 加密 / 哈希 / 压缩 / 图片编解码在主线程 | 同上，用 `compute` 或 `Isolate.run`（Dart 2.19+） |
| 大数组 `sort` / 多层嵌套循环 / 复杂正则，在 `build()` 或帧回调里 | 修：移出 build，结果缓存；量大则进 Isolate |
| `sqflite` / `SharedPreferences` 同步或密集读写在滚动过程中 | 修：预加载 + 缓存 |

### 3.2 build 方法里的问题

`build()` 可能每帧被调用，里面的一切都要按"每秒 60 次"来衡量。

| 识别 | 说明 |
|---|---|
| 在 `build()` 里 `new` Controller / 创建 Future / `Stream` | `FutureBuilder(future: fetch())` 这种写法每次 rebuild 都重新发起请求。修：Future 存到 State 字段，在 `initState` 里赋值 |
| `build()` 里做数据转换、过滤、排序 | 修：在数据变更时算一次并缓存 |
| `build()` 方法超长（>80 行） | rebuild 边界过粗：任何一处小改动都重建整棵树。修：拆成独立 Widget 类（不是 `_buildXxx()` 方法——方法返回的子树和父级共享同一个 Element，无法独立 rebuild 也无法 const 复用） |
| 大量可 const 的 Widget 未加 `const` | const Widget 在 rebuild 时直接复用实例，跳过重建 |
| `MediaQuery.of(context)` 只为拿尺寸 | 会订阅全部 MediaQuery 变化（键盘弹出、字体缩放都触发 rebuild）。修：`MediaQuery.sizeOf(context)`（Flutter 3.10+） |

### 3.3 rebuild 范围

| 识别 | 说明 |
|---|---|
| `setState` 位于树很高的 State，而实际只有一个小部件要变 | 整棵子树 rebuild。修：下沉 setState，或用 `ValueListenableBuilder` / `AnimatedBuilder` 局部刷新 |
| 滚动监听里 `setState` | 每帧都触发全量 rebuild。修：`ValueNotifier` + `ValueListenableBuilder`，或加节流 |
| `AnimatedBuilder` / `AnimatedWidget` 未用 `child` 参数缓存不变子树 | 动画每帧重建静态内容。修：把不随动画变化的子树传给 `child` |
| 监听整个大对象而非需要的字段（Provider `watch` 全量 / 无 `Selector`） | 无关字段变化也 rebuild |

### 3.4 渲染开销

| 识别 | 说明 |
|---|---|
| `Opacity` 包裹复杂子树 | 触发 `saveLayer`，离屏渲染，开销大。修：用 `AnimatedOpacity` 之外考虑改用带透明度的颜色、`FadeTransition`，或对图片用 `Image(color: ...)` |
| `ClipRRect` / `ClipPath` 大面积使用 | 同样可能 `saveLayer`。修：能用 `BoxDecoration(borderRadius:)` 就不用 Clip |
| `BackdropFilter` / 大范围 `BoxShadow` / `ImageFiltered` | 高 GPU 开销，低端机明显掉帧 |
| `ListView` 未设 `itemExtent` / `prototypeItem`，item 高度一致 | 设了可跳过逐项测量，长列表滚动更稳 |
| 嵌套可滚动组件未加 `shrinkWrap: false` 且外层无约束 | `shrinkWrap: true` 会强制布局全部子项，长列表卡顿 |

---

## 维度四：代码精简与封装

判断标准是"删掉后行为不变"或"同样的事有更少的写法"。这一维度里**重复代码是重头戏**，单独展开在 4.1；其余零散项在 4.2。

### 4.1 重复代码与封装（必查）

先看扫描脚本的「重复度」一行拿到全局判断：参与重复的行数占比 ≥15% 说明封装收益很大，7–15% 挑高频的封装，<7% 只处理明显的几处。

**三种重复，危害递增：**

| 形态 | 怎么发现 | 危害 |
|---|---|---|
| **逐字复制** | 扫描脚本「逐字重复代码块」 | 改一处忘改另一处；行数虚胖 |
| **复制后改名**（结构相同，只有标识符/字面量不同） | 扫描脚本「结构重复」 | **最危险**——grep 搜不到，肉眼扫不出来，修 bug 时必漏。业务代码里这种比逐字复制更常见 |
| **已经分叉的复制** | 对比两处重复块，发现行为已不一致（一处加了判空/重试/埋点，另一处没有） | **这不是精简问题，是正确性问题**——说明历史上已经漏改过一次 |

**定级规则**（不要一律 P2）：

- 重复块**已经分叉**，行为不一致 → **P1**，并在报告里指出两处的具体差异，这本身就是一个待确认的 bug
- 重复涉及**关键逻辑**：网络请求与错误处理、鉴权、金额/库存计算、资源释放（dispose/cancel）→ **P1**，漏改一处就是线上事故。big 包里 6 个页面各自复制一份"忘了 cancel timer"的写法，就是同一个 P0 被复制了 6 份，报告里要合并成一条并列出全部位置
- 纯展示层、样板代码的重复 → **P2**

**封装手段选型**（给建议时必须落到具体手段，"提取一下"不算方案）：

| 重复形态 | 封装成什么 |
|---|---|
| 同一段 Widget 子树反复出现 | 独立的 `StatelessWidget` 类。**不要提取成 `_buildXxx()` 方法**——Widget 类才有独立的 rebuild 边界和 const 复用，方法只是把代码挪了个地方 |
| 逻辑相同、只有数据类型不同 | 泛型函数或泛型类：`class Repository<T> { Repository(this.fromJson); final T Function(Map<String, dynamic>) fromJson; }` |
| 每个 State 都有同一套生命周期样板（initState 建 controller、dispose 释放） | `mixin` 或基类：`mixin AutoDisposeTimer<T extends StatefulWidget> on State<T>`。这类封装还能顺手根治"某几个页面忘了 dispose" |
| 反复给同一类型写相同的转换/格式化 | `extension` on 该类型 |
| 每个页面重复的 Scaffold / AppBar / loading / error 壳 | 一个包装组件，如 `AppScaffold` 或 `AsyncView<T>(future:, builder:)` |
| 反复出现的常量（颜色、间距、时长、URL、超时） | 常量类、`ThemeExtension`、配置对象 |
| 每个 model 手写 `fromJson`/`toJson` | 代码生成（`json_serializable` / `freezed`）。**这是引入新依赖，必须在报告里标注**，并说明手写方案（一个泛型解析函数）也能解决大部分 |
| 只差一两个参数的 if/else 分支 | 参数化的私有 Widget，或传 builder 回调 |

**别过度封装**——这条同样要写进报告，避免对方矫枉过正：

- **三次法则**：出现第三次再封装。只出现 2 次且不足 5 行，抽象成本通常大于收益
- **像 ≠ 同**：两段代码长得像但业务语义不同（比如"订单金额校验"和"退款金额校验"），不要合并——它们会各自演化，强行合并最后会长成一个带 5 个 bool 参数的怪物
- **检验抽象是否切对**：如果调用点要传 4 个以上参数才能还原原来的行为，说明切错了位置，换一个切法

**改造方案要写清三件事**：抽到哪个文件、抽成什么（类名 / 函数签名）、有几处调用点要跟着改（这直接决定改造难度）。

### 4.2 其他精简项

一般 P2。

| 检查项 | 识别 |
|---|---|
| 死代码 | 未被引用的私有方法/字段/类；`if (false)`；不可达分支 |
| 未使用的 import | `dart analyze` 直报（P3） |
| 冗余 state | State 字段的值完全可由 `widget.xxx` 或其他字段推导。修：改成 getter |
| 多余的 setState | setState 里没有改任何字段；或连续多次 setState 可合并为一次 |
| 冗余嵌套 | `Container(child: Padding(child: Container(...)))`。修：单个 `Container` 的 `padding`/`decoration` 一次搞定；只做单一功能时用 `Padding`/`ColoredBox`/`SizedBox` 比 `Container` 更轻 |
| 手写 SDK 已有能力 | 自己实现 clamp / debounce / 深拷贝 / 列表分块，而 `num.clamp`、`Timer`、`collection` 包已有 |
| 无意义的 async/await | 方法体只有一句 `return xxx;` 却标 `async`；`await` 一个非 Future |
| 空 override | 只调用 `super.xxx()` 什么都不做的重写 |
| 过长的三元 / 嵌套条件 | 修：早返回（early return）、`switch` 表达式（Dart 3） |

---

## 维度五：扩展性与解耦

一般 P1（阻碍演进和测试）或 P2。

| 检查项 | 识别 | 说明 |
|---|---|---|
| UI 直接依赖具体实现 | Widget / State 里直接 `http.get`、`Dio()`、`sqflite.openDatabase`、`SharedPreferences.getInstance` | 无法 mock、无法换实现、无法单测。修：定义抽象接口（`abstract class XxxRepository`），实现类注入。这是最有价值的一类建议——具体到"抽哪个接口、谁注入" |
| 上帝类 / 超长文件 | 单文件 >500 行；单类承担 UI + 网络 + 缓存 + 业务规则 | 修：按职责拆分，说明拆成哪几个文件 |
| 超长方法 | 单方法 >80 行（build 见维度三） | 修：按语义分段抽方法 |
| 业务逻辑写在 Widget 里 | 网络请求、状态机、计算规则直接写在 State | 修：抽到 Controller / Notifier / Bloc（用 package 已有的状态管理方案，别强行推荐新框架） |
| 全局可变单例 | `static final instance` 且持有可变状态、被到处直接引用 | 隐式全局依赖，测试互相污染。修：依赖注入，或至少收窄到接口 |
| 硬编码散落 | URL、超时、颜色、文案字符串、magic number 直接写在逻辑里 | 修：集中到 `constants` / 主题 / 配置对象 |
| 包内循环依赖 | A import B，B 又 import A | 修：抽出共同依赖的第三方文件 |
| 枚举 switch 无穷举 | `switch (e)` 带 `default:` 兜底 | 新增枚举值时编译器不再报错，静默走 default。修：去掉 default 让编译器强制穷举 |
| 回调签名绑定具体类型 | 回调参数直接用具体实现类而非接口/值对象 | 扩展时被迫改签名（对 package 是破坏性变更） |
| 扩展点缺失 | 关键行为写死无法覆盖（如样式、文案、错误处理策略） | package 尤其重要。修：开放可选参数 / 策略对象 / builder 回调 |
| 违反接口隔离 | 抽象类塞了 10+ 方法，实现方被迫实现用不到的 | 修：拆小接口 |

---

## 维度六：网络请求并发与调度

这一维度的特点是**本地测不出来**：调试数据 3 条，`Future.wait` 看起来很快；线上 500 条就是同时打出 500 个请求，连接池排队、后端限流 429、超时后又同时重试。所以判断时必须回答一个问题——**这个集合运行时最大能有多少元素？**

答不上来就如实写"影响程度取决于运行时数据量，建议确认 <某集合> 的上界"，不要断言一定拥堵，也不要因为不确定就不报。

### 6.1 扇出无上限（P0/P1 的主要来源）

| 识别 | 说明 |
|---|---|
| `await Future.wait(list.map((e) => fetch(e)))` | **并发数 = list.length，没有任何上限**。这是一行代码打爆连接池的经典写法。list 是常数小集合（≤6）时没问题，来自接口/数据库就是隐患 |
| 循环里不 `await` 地发请求：`for (final x in xs) { post(x); }` | 全部同时发出，且是 fire-and-forget——异常没人接、失败没人知道 |
| `ListView.builder` 的 `itemBuilder` 里发请求（常见形态：`FutureBuilder(future: fetch(item.id))`） | 经典 N+1：快速滚动时瞬间并发几十个；滑出屏幕后请求不取消仍占连接；`build` 每次重建还会重新发起。修：上层一次性批量取数，或按可见范围分页 |
| 页面 `initState` 里并排发起 5 个以上互不依赖的请求 | 首屏请求风暴，互相抢带宽反而都变慢。修：区分首屏必需与可延后的，非关键的等首帧后再发 |

**改造方向**（按代价从小到大）：

```dart
// 1) 分批：最简单，无需新依赖
Future<List<R>> inBatches<T, R>(
  List<T> items, int size, Future<R> Function(T) task) async {
  final out = <R>[];
  for (var i = 0; i < items.length; i += size) {
    out.addAll(await Future.wait(items.skip(i).take(size).map(task)));
  }
  return out;
}

// 2) 并发闸门：吞吐更好，前一个完成就补下一个
class Gate {
  Gate(this.limit);
  final int limit;
  int _running = 0;
  final _queue = <Completer<void>>[];

  Future<T> run<T>(Future<T> Function() task) async {
    if (_running >= limit) {
      final c = Completer<void>();
      _queue.add(c);
      await c.future;
    }
    _running++;
    try {
      return await task();
    } finally {
      _running--;
      if (_queue.isNotEmpty) _queue.removeAt(0).complete();
    }
  }
}
```

并发上限取多少：移动端同域名一般 4–8 个之间，和浏览器惯例（6）对齐是安全起点。给建议时说清这是起点、需要按接口实际耗时压测调整，不要写死成"必须设为 6"。

### 6.2 重复与叠加

| 识别 | 说明 |
|---|---|
| `Timer.periodic` 周期内发请求 | 周期短于请求耗时时，上一个没回来下一个照发，弱网下持续堆积。修：改成"完成后再排下一次"（递归 `Future.delayed`），或加 in-flight 判断直接跳过本次 |
| 滚动触底加载没有 loading 守卫 | 滚动回调每帧触发，同一页被请求十几次。修：`if (_loading) return; _loading = true;`，`finally` 里复位 |
| 输入框 `onChanged` 直接发请求 | 每敲一个字符一个请求。修：debounce 300–500ms，且新请求发出前取消/丢弃上一个 |
| 同一份数据被多个 widget 同时请求 | 缺 in-flight 去重。修：`Map<String, Future<T>> _inFlight`，同 key 复用同一个 Future，完成后移除 |
| 重试没有退避和次数上限 | 批量请求同时失败会同时重试，形成雪崩。修：指数退避 + 抖动 + 最大次数；只对 5xx/超时重试，4xx 不重试 |

### 6.3 连接与取消

| 识别 | 说明 |
|---|---|
| 每次请求 `http.Client()` / `Dio()` 新建 | 连接池和 keep-alive 失效，每个请求重新 TCP + TLS 握手；旧 client 还常常没 `close()`。修：复用一个长生命周期实例，由持有方负责 close |
| `HttpClient` 未设 `maxConnectionsPerHost` | `dart:io` 默认**不限制**单主机连接数。高并发场景显式设一个上限 |
| 页面退出 / 参数变化后旧请求不取消 | 旧响应回来还可能覆盖新数据（竞态）。修：Dio 用 `CancelToken`；`http` 包没有取消能力，退而求其次记一个 requestId，回调时对不上就丢弃 |
| 请求没有超时 | 弱网下连接被长期占用。修：`client.get(...).timeout(const Duration(seconds: 10))` 或 Dio 的 `connectTimeout`/`receiveTimeout` |

### 6.4 拦截器里的耗时操作

**拦截器是全局放大器**：写在 `onRequest` / `onResponse` / `onError` 里的任何开销，都会乘以请求总数，而且**跑在 UI isolate 上**——既拖慢每一个请求，又直接吃掉帧预算。这里最容易被忽视，因为拦截器代码通常只有十几行，看起来"没干什么"。

| 识别 | 说明 |
|---|---|
| 日志拦截器打印完整响应体：`print(jsonEncode(response.data))` / `debugPrint(response.toString())` | **最高频的一条**。每个响应都在主线程做一次完整 JSON 序列化，大响应直接掉帧；release 包里 `print` 仍执行。修：只打 URL + 状态码 + 耗时；打 body 要限长并用 `kDebugMode` 守卫 |
| `onRequest` 里加签 / 加密 / 计算 HMAC | 每个请求都在主线程跑一遍加密。修：轻量算法可留，重的移入 isolate 或预先算好 |
| `onRequest` 里每次 `await SharedPreferences.getInstance()` 取 token | 每个请求一次异步 IO。修：启动时取一次缓存在内存里，变更时刷新 |
| 拦截器里做同步文件 IO、数据库查询、大循环 | 同上，全都乘以请求数 |
| token 刷新没有互斥 | 并发请求同时收到 401 → 同时发起 N 个刷新请求，还可能互相覆盖新 token。修：用 `QueuedInterceptor`（Dio 会串行化），或自己维护一个"正在刷新"的 Future 让后续请求复用 |
| 用 `QueuedInterceptor` 但里面有慢操作 | `QueuedInterceptor` 是串行的，一个慢拦截器会把**所有**请求排队堵住。修：确认里面没有长 await |
| `handler.next()` / `handler.resolve()` 有分支没调用 | 请求永远挂起，表现为"点了没反应"，不报错也不超时。**必查**：每条路径都要恰好调用一次 handler |

**怎么查**：搜 `InterceptorsWrapper`、`extends Interceptor`、`extends QueuedInterceptor`，把 `onRequest`/`onResponse`/`onError` 三个方法体完整读一遍，逐行问"这行乘以一万次请求还能接受吗"。

### 6.5 新请求发起前，旧请求取消了吗

同一个入口被反复触发（搜索输入、下拉刷新、切 tab、切筛选条件、分页快速滑动）时，**旧请求还在飞，新请求又发出去了**。后果是双份的：连接和流量被浪费、请求堆积；以及旧响应可能后到并覆盖新数据（竞态）。

| 识别 | 说明 |
|---|---|
| 反复触发的方法里直接发请求，看不到任何取消/去重痕迹 | 最常见形态。先确认这个方法的触发频率——只在 `initState` 调一次的不算 |
| 有 `CancelToken` 字段，但新请求前没有 `cancel()` 旧的 | 等于没用。**创建新 token 前必须先取消旧的** |
| 用 `http` 包（没有取消能力）且无序号守卫 | `package:http` 无法取消已发出的请求，只能丢弃结果 |
| `CancelToken` 全局共用一个 | 取消一个会把所有请求都取消掉 |

**Dio（能真正取消，优先用）**：

```dart
CancelToken? _token;

Future<void> search(String q) async {
  _token?.cancel('superseded');          // ← 先掐掉上一个
  final token = _token = CancelToken();
  try {
    final r = await dio.get('/search', queryParameters: {'q': q}, cancelToken: token);
    if (token.isCancelled) return;
    // 用 r
  } on DioException catch (e) {
    if (CancelToken.isCancel(e)) return; // 主动取消不是错误，别弹提示
    rethrow;
  }
}
```

**`package:http`（取消不了，只能丢弃）**：用递增序号，回调时对不上就 return（见 6.2 的竞态写法）。要注意这只解决了"结果覆盖"，**流量和连接仍然被浪费**——所以对高频入口（搜索框）仍然需要 debounce 把请求数压下来。

**特别注意**：`CancelToken.isCancel(e)` 判断要有。很多项目取消后走进统一错误处理，给用户弹一个"网络错误"——用户明明什么都没做错。

### 6.6 大 JSON 解析在哪个 isolate

网络响应的解析是**主线程上最容易被忽略的一块大开销**：Dio 默认在主 isolate 上把 body 解成 `Map`，接着业务代码再循环 `fromJson` 构造对象，两段加起来在大列表接口上足以造成肉眼可见的卡顿。

| 识别 | 说明 |
|---|---|
| `jsonDecode(resp.body)` 后紧跟 `(list).map((e) => X.fromJson(e)).toList()` | 解析 + 构造两段都在主线程。影响取决于响应大小和条数，**要标注"取决于运行时数据量"** |
| Dio 未配置后台解析 | Dio 自带 `BackgroundTransformer`，把 JSON 解析放到后台 isolate。配置一行：`dio.transformer = BackgroundTransformer();` |
| 需要连 `fromJson` 一起搬到后台 | 用 `ResponseType.plain` 拿字符串，再 `await compute(_parseX, body)`，在 isolate 里一次做完 decode + 映射 |
| 小响应也硬上 `compute` | 反向问题。几 KB 的数据序列化到 isolate 的开销比解析本身还大。先估量级再建议 |

```dart
// 一次搬完 decode + fromJson，适合大列表接口
List<Item> _parseItems(String body) =>
    (jsonDecode(body)['items'] as List)
        .map((e) => Item.fromJson(e as Map<String, dynamic>))
        .toList();

final resp = await dio.get('/items',
    options: Options(responseType: ResponseType.plain));
final items = await compute(_parseItems, resp.data as String);
```

**判断"大量"要有依据**：看接口语义（列表页 / 全量同步 / 分页大小）、看有没有分页参数。查不到就写"影响程度取决于返回条数，建议确认接口分页上限"，不要直接断言卡顿。

### 6.7 请求失败的异常有没有被接住

| 识别 | 说明 |
|---|---|
| `await dio.get(...)` 不在 `try` 里，调用链上也没人 catch | `DioException` 逃逸。在 `void`/fire-and-forget 路径上是静默失败，在 build 相关路径上是崩溃 |
| **用 `package:http` 却不判 `statusCode`** | **经典坑**：`http.get` 对 4xx/5xx **不抛异常**，照常返回响应。直接 `jsonDecode(resp.body)` 去解析一个 500 的 HTML 错误页 → `FormatException`，且错误信息完全误导 |
| catch 了但不分类型 | 超时、无网络、401、500、解析失败对用户是完全不同的事，一律弹"网络错误"等于没做错误处理。Dio 用 `e.type`（`DioExceptionType.connectionTimeout` 等）分支 |
| `catch (e) {}` 空块吞掉 | 见规范维度，官方 lint `empty_catches` 默认已启用 |
| 只在每个调用点各写各的 catch，没有统一出口 | 错误提示不一致、上报缺失。修：拦截器 `onError` 做统一分类和上报，业务层只处理需要特殊对待的 |
| `onError` 里没有调用 `handler.next(e)` / `handler.reject(e)` | 错误被吃掉，调用方永远等不到结果 |

```dart
// http 包：必须自己判状态码
final resp = await client.get(uri).timeout(const Duration(seconds: 10));
if (resp.statusCode != 200) {
  throw HttpException('${resp.statusCode}: ${resp.reasonPhrase}');
}
final data = jsonDecode(resp.body);
```

### 6.8 定级参考

- **P0**：扇出规模由外部数据决定且无上限（`Future.wait` 打整个列表、itemBuilder 内发请求）；轮询叠加导致请求无限堆积；`handler.next` 漏调导致请求永久挂起；`http` 不判 statusCode 直接解析（必然在服务端报错时崩）
- **P1**：无防抖搜索、分页无守卫、重试无退避、每次新建 client、请求无超时；**拦截器里打印完整响应体或做加解密**；反复触发的入口不取消旧请求；请求失败无人接住
- **P2**：缺 in-flight 去重、未设 `maxConnectionsPerHost`、大 JSON 未走后台 isolate（量级不明时）、错误未分类、首屏请求可再分优先级

---

## Timer 专项检查（跨内存 / 卡顿 / 网络）

Timer 单独拎出来查，因为它同时踩三条线：停不掉是内存泄漏，回调重是 UI 卡顿，回调发请求是网络拥堵。而且 Timer 的 bug 有个共同特征——**单看每一处都对，凑在一起才错**，靠通读很难发现，必须按下面四问逐个过。

**每发现一个 Timer，依次回答这四个问题：**

### 问题一：它停得掉吗？

| 情况 | 结论 |
|---|---|
| `Timer.periodic(d, cb);` 返回值没被任何变量接住 | **必报 P0**。没有句柄就调不到 `cancel()`，这个 Timer 活到进程结束 |
| 存进了字段，但 `dispose()` 里没有 `cancel()` | **P0**。页面销毁后继续触发，典型现象是 `setState() called after dispose` 崩溃 + 请求继续发 |
| 存进了局部变量，方法返回后就没人持有 | **P0**，同第一种 |
| `cancel()` 写在某个条件分支里（比如只有成功才 cancel） | **P1**。异常路径漏掉，需要挪到 `finally` 或 `dispose` |

注意：一次性 `Timer(d, cb)` 触发过就自然结束，危害远小于 `periodic`；但如果它在等待期内页面就销毁了，回调里的 `setState`/`context` 一样会炸，仍需 cancel。

### 问题二：会不会没停旧的又开新的？

**这是最隐蔽也最值得查的一条。** 只要创建 Timer 的语句写在一个「可能被调用多次」的方法里，而这条语句之前没有先 `cancel()` 旧的，就会出现 N 个 Timer 并行——**setState 频率变 N 倍，网络请求也变 N 倍**，而且 N 随着用户操作单调增长。

会被重复调用的典型入口：

- `didUpdateWidget`（父级每次 rebuild 且参数变化就调）
- `didChangeAppLifecycleState` 的 `resumed` 分支（每次切回前台）
- `didChangeDependencies`（可能被调多次）
- 下拉刷新 / 重试 / 重连 / 登录成功回调
- 任何名字叫 `start` / `restart` / `_beginXxx` 的公开或半公开方法

判断方法：找到创建语句所在的方法名，**再全文搜这个方法被谁调用、调用了几处**。只在 `initState` 里创建一次的不算问题。

正确写法就一行：

```dart
void _startPolling() {
  _poll?.cancel();          // ← 关键：先停旧的
  _poll = Timer.periodic(interval, (_) => _refresh());
}
```

### 问题三：回调会不会引发大量并发 UI 更新？

| 识别 | 说明 |
|---|---|
| 回调里 `setState` | 按周期触发**整个 State 的 rebuild**。周期 1 秒还好，100ms 就是每秒 10 次全树重建 |
| 周期 < 200ms | 高频任务。单帧预算 16.6ms，回调只要涉及 setState / IO / 计算就很容易吃掉 |
| 回调里没有 `mounted` 判断 | 销毁后触发必崩 |
| 同一个类持有多个 Timer | 回调可能互相叠加，各自的停止路径都要单独确认 |

改造方向：倒计时、进度、计时这类**只有一个小部件要变**的场景，用 `ValueNotifier` + `ValueListenableBuilder` 把 rebuild 收窄到那个部件，整棵树不动。真需要每帧更新的动画走 `AnimationController`/`Ticker`，不要用 `Timer` 手搓帧循环。

### 问题四：回调会不会引发大量并发网络请求？

| 识别 | 说明 |
|---|---|
| 周期性发请求，且没有 in-flight 判断 | 上一次没返回下一次照发。弱网下请求耗时 > 周期，请求就会持续堆积，直到连接池打满 |
| 轮询周期 + 问题二的重复启动同时存在 | N 个 Timer × 每个都发请求，**这是最容易打爆接口的组合**，报告里要把两者关联起来写 |
| 回调里的请求失败后重试，重试又没退避 | 与轮询叠加成雪崩 |

改造方向——**周期性请求不要用 `Timer.periodic`，用「完成后再排下一次」**：

```dart
Future<void> _loop() async {
  while (mounted && !_stopped) {
    await _refresh();                                   // 等这次真正结束
    await Future.delayed(const Duration(seconds: 5));   // 再等间隔
  }
}
```

这样天然不会叠加。代价是需要一个 `_stopped` 标志位来停止（没有 Timer 句柄了），`dispose()` 里要把它置 true。

### 递归 `Future.delayed` 自调用

`someMethod()` 里 `await Future.delayed(d, () => someMethod())` 是手搓的轮询，行为等价于 `Timer.periodic`，但**没有句柄可以 cancel**，只能靠标志位停。看到这种写法要确认：有没有停止条件？页面销毁后会不会继续跑？异常路径会不会让循环断掉或者变成死循环？

---

## 高频误报清单（必读）

写进报告前，逐条排除下列情况——这些是"看起来像 bug 其实不是"的高发区：

1. **controller 来自外部**：`widget.controller` / 构造参数传入的 controller，由创建方释放。本 State 里 dispose 它反而是 bug。
2. **间接释放**：`dispose()` 里调用了 `_cleanUp()`，真正的释放在那个方法里。要跟进去看。
3. **`late final` + `AutomaticKeepAliveClientMixin`**：keepAlive 场景下对象存活是设计意图，不是泄漏。
4. **顶层/静态常量集合**：`static const` 或 `final` 不可变常量表不是"无上限缓存"。
5. **小数据量的 `ListView(children:)`**：固定 3-5 项的菜单用 children 完全正确。确认数据来源是固定的还是动态的。
6. **`_buildXxx()` 方法**：不是无条件的错误。只有当这段子树的 rebuild 频率和成本值得独立边界时才建议拆 Widget 类，报告里要说明这个理由，否则就是教条。
7. **`compute` 不是免费的**：小数据（几 KB 以内）用 `compute` 反而更慢（要序列化 + 启 Isolate）。建议前先估量级。
8. **`const` 用不了的场景**：字段依赖运行时值时构造函数无法 const，不要一律要求加 const。
9. **示例/生成代码**：`*.g.dart`、`*.freezed.dart` 是代码生成产物，不作为问题条目（可在报告里说明已跳过）。
10. **`print` 在 `assert` 或 `kDebugMode` 守卫内**：已经被保护，降级或不报。
11. **类型提升（type promotion）不适用于 public 字段**：`maxSelection` 是 public final 字段时，Dart **不会**把 `if (maxSelection != null)` 提升为非空，`maxSelection!` 是必需的，不是冗余。只有局部变量和私有 final 字段才享受提升。没跑 `dart analyze` 就不要断言某个 `!`、某个 `const` 是多余的。
12. **`late final` 未初始化不等于泄漏**：`late` 只是延迟初始化，与生命周期无关。
13. **`Future.wait` 本身不是问题**：对固定的 2–5 个互不依赖的请求并行，正是它该干的事。只有当集合大小由外部数据决定时才是隐患——先确认来源。
14. **`fetch` / `load` / `search` 命名的方法不一定发网络请求**：可能只是读本地缓存或过滤内存列表。扫描脚本按命名猜，必须打开看实现。
15. **单例 / 应用级对象的 client 不需要 close**：生命周期与进程等长是设计意图。只有方法内新建的才需要。
16. **创建 Timer 前已经 `cancel()` 的不是重复启动**：`_t?.cancel(); _t = Timer.periodic(...)` 是标准写法，不要报。同理，回调内 `timer.cancel()` 自停的一次性倒计时也是对的。
17. **只在 `initState` 里创建的 Timer 不存在重复启动问题**：`initState` 每个 State 只跑一次。先确认创建语句所在的方法到底会不会被调多次，再下结论。
