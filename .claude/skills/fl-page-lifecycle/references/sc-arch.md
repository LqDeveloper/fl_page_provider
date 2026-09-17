# 场景：架构与机制

[10 事件总线](#10-跨页事件总线) · [11 局部子树观测](#11-局部子树观测) · [12 Controller/ViewModel](#12-controller--viewmodel) · [13 全项目统一埋点](#13-全项目统一埋点) · [14 回调里 setState 报错](#14-生命周期回调里-setstate-报错)

节号在四个 `sc-*.md` 里全局唯一。

---

## 10. 跨页事件总线

出处：`example/lib/src/event_bus_page.dart`

两个没有共同父级的页面通信。事件是普通类，靠类型区分，不用注册。订阅随 `dispose` 自动取消，不用存 `StreamSubscription`。

```dart
class CartChanged {
  const CartChanged(this.count);
  final int count;
}

class _CartBadgeState extends State<CartBadge>
    with FlPageLifecycleMixin, FlStateEventBusMixin {
  int _count = 0;

  @override
  void initState() {
    super.initState();
    observeEvent<CartChanged>(_onCartChanged);   // 必须在 initState 调一次
  }

  void _onCartChanged(CartChanged e) {
    if (!isPageAppeared) return;    // 事件是全局广播，stop 的页面照样收到
    if (!mounted) return;
    setState(() => _count = e.count);
  }

  void _add() => dispatchEvent(CartChanged(_count + 1));
}
```

两个坑：

- `observeEvent` 写进 `build` 或 `onPageResume` 会让订阅数随重建线性增长。重复的 `(类型, 回调)` 组合会被**静默忽略** + debug assert，但只有**方法引用**能去重，现场写的闭包字面量每次都是新对象。
- **绝不要在 `dispose` 或 pop 回调里调 `FlGlobalEventBus.destroy()`**——它关掉整条广播流，所有其他页面的订阅都收到 `done` 后静默失活。页面级清理 mixin 已经做了。`destroy()` 只用于测试 `tearDown` 或 App 退出。

`State` 之外用 `FlGlobalEventBus.observeEvent<T>()`（返回 `Stream<T>`，自己 cancel）和 `dispatchEvent<T>()`。换实现用 `FlGlobalEventBus.configure(...)`，在 `runApp` 前调。

---

## 11. 局部子树观测

出处：`example/lib/src/lifecycle_view_page.dart`

页面是 `StatelessWidget`、mixin 链太长不想再加、或只想给**一张卡片**做曝光统计。

```dart
FlPageLifecycleView(
  onStateChanged: (context, state) {
    if (state.isPageResume) _player.play();
    if (state.isPagePause) _player.pause();
  },
  onRouteParam: (context, routeName, arguments) =>   // 注意叫 onRouteParam
      Analytics.pageView(routeName, args: arguments),
  child: const Scaffold(body: Text('Product')),
)
```

`child` 原样返回，不加布局节点。mixin 的那些 getter 不对外暴露，需要就改用 mixin。

只观测一张卡片（mixin 做不到的用法）：

```dart
FlPageLifecycleView(
  onStateChanged: (context, state) {
    if (state.isPageResume) Analytics.impression('card_x');
  },
  child: const _CardBody(),
)
```

**成本要有数**：每个实例内部都是完整的 mixin（1 条路由订阅 + 1 个首帧回调，开 `observeAppLifecycle` 再加 2 条流）。一页放几个免费，长列表每个 item 一个要先算。

---

## 12. Controller / ViewModel

出处：`example/lib/src/controller_page.dart`

**前提**：`FlPageControllerMixin` **不订阅任何东西**，事件必须由页面转发。一个回调都不触发时先查转发。

页面侧转发两处：

```dart
class _DetailPageState extends State<DetailPage> with FlPageLifecycleMixin {
  late final _controller = DetailController();

  @override
  void onLifecycleStateChanged(FlLifecycleState state) {
    super.onLifecycleStateChanged(state);                     // 必须
    _controller.onLifecycleChanged(state, context: context);  // 转发之一
  }

  @override
  void onPageContextReady(String? routeName, Object? arguments) {
    _controller.setupRouteInfo(routeName, arguments);         // 转发之二
  }
}
```

Controller 是普通类，不依赖任何状态管理库：

```dart
class DetailController with FlPageControllerMixin {
  Timer? _poll;

  @override
  void onPageResume() => _poll = Timer.periodic(...);

  @override
  void onPagePause() { _poll?.cancel(); _poll = null; }

  @override
  void onPageDispose() => _poll?.cancel();   // 它没有 dispose，收尾放这里

  /// ⚠️ 签名和页面 mixin 上的同名回调不一样：这里是 BuildContext?
  @override
  void onPageContextReady(BuildContext? context) {
    debugPrint('route=$routeName args=$arguments');
  }
}
```

三个坑：`onPageContextReady` 在 Controller 上是 `(BuildContext? context)`，写成 `(routeName, arguments)` 会变成一个永远不被调用的新方法；它没有 `dispose`；`onPageIndexChanged(int, int)` **不会**被 `onLifecycleChanged` 分发，要页面显式调。

时序与幂等完全由转发方决定——绕过 `FlPageLifecycleMixin` 自己驱动的话，配对保证不再成立。

随时可读：`lifecycleState`、`isPageResume` / `isPagePause`、`isForeground`、`routeName` / `arguments`。

---

## 13. 全项目统一埋点

出处：`example/lib/src/widgets/lifecycle_log.dart` 的 `DemoLogMixin`

所有页面都要埋点时，别在每个页面重复写。`onLifecycleStateChanged` 是 18 个事件的**统一出口**：

```dart
mixin PageTrackMixin<T extends StatefulWidget> on State<T>, FlPageLifecycleMixin<T> {
  String get trackName => routeName ?? runtimeType.toString();

  DateTime? _enterAt;

  @override
  void onLifecycleStateChanged(FlLifecycleState state) {
    super.onLifecycleStateChanged(state);    // 必须
    switch (state) {
      case FlLifecycleState.onPageStart:
        _enterAt = DateTime.now();
        Analytics.pageView(trackName, args: arguments);
      case FlLifecycleState.onPageStop:
        final at = _enterAt;
        if (at != null) {
          Analytics.pageDuration(trackName, DateTime.now().difference(at));
          _enterAt = null;
        }
      default:
        break;
    }
  }
}

class _OrderPageState extends State<OrderPage>
    with FlPageLifecycleMixin, PageTrackMixin { }
```

`mixin X<T extends StatefulWidget> on State<T>, FlPageLifecycleMixin<T>` 这个声明形式是关键——它约束了只能叠在主 mixin 上，因此里面能直接用 `routeName`、`isPageAppeared`。**这是唯一正确的叠加形式**（叠自己的 mixin，不是叠库里的另一个入口）。

用统一出口而不是重写每个模板回调的好处：子类可以自由重写 `onPageStart` 写业务逻辑，不会覆盖掉埋点——两者是独立的两条分发路径，各自包在独立的异常守卫里。

**异常会被吞掉**：每次分发都有守卫兜着，异常走 `FlutterError.reportError`，`try/catch` 抓不到，只在控制台或 `FlutterError.onError` 里能看到。好处是你的回调抛异常不会阻断其他回调、后续事件或其他页面。所以埋点上报这类可能失败的操作，自己再包一层 `try/catch` 更稳妥。守卫分两层（本库的 `FlLifecycleGuard` 与 Flutter 自己对动画监听器的兜底），区别见 `pitfalls.md` 第 10 条。

---

## 14. 生命周期回调里 setState 报错

出处：`example/lib/src/widgets/lifecycle_log.dart` 的 `_notify()`

**症状**：在 `onPageContextReady` 或 `onPageStart` 里 `setState`，报 `setState() or markNeedsBuild() called during build`。

**原因**：`onPageInit` 从 `initState` 发出、`onPageContextReady` 从 `didChangeDependencies` 发出，这两个时机都在构建期内；`onPageStart` / `onPageResume` 走首帧回调，也可能落在 `persistentCallbacks` 阶段。在这些时机触发重建，Flutter 直接抛异常。

**怎么办**：这些早期回调里只做赋值和计算；要刷新 UI 就推到帧末。

```dart
void _safeNotify(VoidCallback fn) {
  if (SchedulerBinding.instance.schedulerPhase ==
      SchedulerPhase.persistentCallbacks) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) fn();          // 帧末执行时页面可能已销毁
    });
  } else {
    fn();
  }
}
```

`onPagePause` / `onPageStop` 这类由路由事件驱动的回调通常不在构建期，`setState` 是安全的——但不确定时推到帧末总没错。
