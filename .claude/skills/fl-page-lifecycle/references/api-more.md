# API 速查（其余公开面）

主用面（枚举、`FlPageLifecycleMixin`、`FlPageIndexScope`、`FlPageLifecycleView`）在 `api.md`。

[ControllerMixin](#flpagecontrollermixin) · [RouteMixin](#flpageroutemixin) · [AppMixin](#flapplifecyclemixin) · [AnimationMixin](#flanimationlifecyclemixin) · [RouteObserver](#flrouteobserver) · [ObserverProxy](#flrouteobserverproxy) · [事件总线](#事件总线) · [LifecycleManager](#fllifecyclemanager) · [assert 原文](#assert-与-debug-提示原文)

---

## FlPageControllerMixin

```dart
mixin FlPageControllerMixin      // 无 on 约束、无类型参数，任何类都能混入
```

**不订阅任何东西，也没有 `dispose`。** 事件全靠页面转发。

```dart
FlLifecycleState get lifecycleState;   // 初值 onPageInit
bool get isPageResume;                 // 最后一个事件是否 onPageResume
bool get isPagePause;
bool get isForeground;
String? get routeName;
Object? get arguments;

void setupRouteInfo(String? name, Object? arguments);   // 注意首参名是 name

@mustCallSuper
void onLifecycleChanged(FlLifecycleState state, {BuildContext? context});   // 转发入口
```

模板回调（除最后一个外都 `@protected`，都不是 `mustCallSuper`）：与主 mixin 同名的那 18 个，**除了**：

```dart
void onPageContextReady(BuildContext? context)   // ⚠️ 和主 mixin 上同名回调签名不同
void onPageIndexChanged(int from, int to)         // 非 @protected，且 onLifecycleChanged 不分发它
```

主 mixin 有、这里没有的是 `onLifecycleStateChanged` 与 `appLifecycleChanged`；`onPageReassemble` 两边都有。用法见 `sc-arch.md` 第 12 节。

---

## FlPageRouteMixin

```dart
mixin FlPageRouteMixin<T extends StatefulWidget> on State<T>
    implements LifecycleRouteAware
```

getter：`ModalRoute? modalRoute`（无路由或 dispose 后 null）· `String? routeName` · `Object? arguments` · `bool isCurrent` · `bool hasRoute`

回调全部 `@protected`、无 `mustCallSuper`：

```dart
void onPageContextReady(String? routeName, Object? arguments)
void onPageEnterAnimationStart()   void onPageEnterAnimationEnd()
void onPageLeaveAnimationStart()   void onPageLeaveAnimationEnd()
void onRouteStart()    // ⚠️ 是 onRoute*，不是 onPage*
void onRouteResume()   void onRoutePause()   void onRouteStop()
```

另有四个 `routePageStart` / `routePageResume` / `routePagePause` / `routePageStop`，是 `@internal @override`，注释声明不许重写但**没加 `@nonVirtual`**（主 mixin 那四个加了），所以编译器拦不住——这也是它和主 mixin 叠加时最先撞上的成员。

实际幂等语义见 pitfalls.md 末尾。没有 `onLifecycleStateChanged` 那样的统一出口。

---

## FlAppLifecycleMixin

```dart
mixin FlAppLifecycleMixin<T extends StatefulWidget> on State<T>

bool get isForeground;
bool get hasInit;      // dispose 后 false

@protected void onAppForeground()                             // 无 mustCallSuper
@protected void onAppBackground()                             // 无 mustCallSuper
@protected void appLifecycleChanged(AppLifecycleState state)  // 这里是空实现，无 mustCallSuper
```

`initState` **无条件**订阅（2 条流），没有开关；`dispose` 退订。

---

## FlAnimationLifecycleMixin

```dart
mixin FlAnimationLifecycleMixin<T extends StatefulWidget> on State<T>
```

无 getter。四个 `@protected`、无 `mustCallSuper` 的回调：

```dart
void onPageEnterAnimationStart()   // AnimationStatus.forward
void onPageEnterAnimationEnd()     // completed —— 一个生命周期里可能触发两次
void onPageLeaveAnimationStart()   // reverse —— 可能反复触发
void onPageLeaveAnimationEnd()     // dismissed
```

`didChangeDependencies` 里重试直到有 `ModalRoute`；没有 `ModalRoute` 时什么都不发也不抛。

---

## FlRouteObserver

```dart
class FlRouteObserver extends NavigatorObserver {
  static final FlRouteObserver instance = FlRouteObserver._();
  factory FlRouteObserver() => instance;   // 和 .instance 是同一个对象
}
```

公开面：`instance`、该 factory、四个 `NavigatorObserver` 重写。`subscribe` / `unsubscribe` 是 `@internal`。

**只能挂一个 `Navigator`**（它是单例，Flutter 有 `assert(observer.navigator == null)`）。嵌套的用下面的 proxy。

行为：

- `didPush`：下层订阅者收 `pause`（新路由 `is PopupRoute`）或 `stop`（普通路由）。
- `didPop` / `didRemove`：离开的路由的订阅者被原子摘除并逐个 `stop`；然后**仅当 `previousRoute?.isCurrent == true`** 才唤醒下层（popup 走 resume，普通走 start）。这个判断就是抑制 `pushAndRemoveUntil` / `popUntil` 误发 start 的地方。
- `didReplace`：旧路由 stop，**不唤醒下层**。
- 每个订阅者的调用各自包 guard，一个抛异常不影响其他订阅者和下层页面。

---

## FlRouteObserverProxy

给**嵌套 `Navigator`** 用的转发观察者。

```dart
class FlRouteObserverProxy extends NavigatorObserver { }
// 隐式默认构造：无参、非 const、无状态；每个嵌套 Navigator 各 new 一个
```

没有静态成员、没有字段。四个重写（`didPush` / `didPop` / `didRemove` / `didReplace`）原样转发给 `FlRouteObserver.instance`，订阅表全局仍只有一份，页面侧无需改动。**`didStartUserGesture` / `didStopUserGesture` 不转发。**

用法与为什么需要它：见 `sc-route.md` 第 9 节、pitfalls.md 第 15 条。

---

## 事件总线

```dart
// mixin on State<S>
@protected void observeEvent<T>(void Function(T event) onData);
@protected void dispatchEvent<T>(T event);
// dispose 自动取消全部订阅（@mustCallSuper）

// FlGlobalEventBus，纯静态
static void configure(FlIEventBus bus);     // 与旧实例不同则销毁旧的
static Future<void> destroy() async;        // ⚠️ 全局
static Stream<T> observeEvent<T>();
static void dispatchEvent<T>(T event);

// FlIEventBus（抽象）
Stream<T> on<T>();          // T == dynamic 时不过滤
void fire(dynamic event);
Future<void> destroy();

// FlEventBus implements FlIEventBus
FlEventBus({bool sync = false});
FlEventBus.customController(StreamController<dynamic> controller);
StreamController<dynamic> get streamController;
// fire 在 controller 已关闭时是 no-op
```

`destroy()` 后下次使用会惰性重建，但**旧订阅不会迁移**。传窄化的 controller（如 `StreamController<String>`）能通过 `customController`（泛型协变），但第一次 fire 不匹配类型时抛 `TypeError`。

事件是**全局广播**，stop 状态的页面照样收到。

---

## FlLifecycleManager

```dart
class FlLifecycleManager extends WidgetsBindingObserver {
  static final FlLifecycleManager instance = FlLifecycleManager._();
  factory FlLifecycleManager() => instance;

  bool get isForeground;                    // lifecycleState == resumed
  Stream<bool> get stream;                  // 过滤后的前后台；读取即自动 listen()
  Stream<AppLifecycleState> get lifecycle;  // 原始、不过滤；读取即自动 listen()
  void listen();                            // 幂等
  void cancel();                            // 幂等；⚠️ 全局

  @override
  void didChangeAppLifecycleState(AppLifecycleState state);
}
```

两个广播 controller 是 `final` 且**永不关闭**。冷启动补发：首次 `listen()` 时若已 `resumed` 且从未发过前台事件，用微任务发一次 `true`——**每进程只有一次，只有第一个订阅者能看到**。`paused` → 发 `false`；`resumed` → 只在来自 `paused` 时（或冷启动补发）发 `true`。`inactive` / `hidden` / `detached` 在 `stream` 上不发（这就是过滤瞬时打断的机制），但都会流过 `lifecycle`。

---

## assert 与 debug 提示原文

1. `FlPageIndexScope` 构造：

```
controller 只支持 PageController、TabController，或 IndexedStack 这类非滚动容器用的 ValueListenable<int>，收到的是 ${controller.runtimeType}
```

2. 开关稳定性（`initState` 和每次 `didChangeDependencies` 都检查）：

```
observePageIndex 在运行时被改成了 $observePageIndex（初始为 $_debugObservePageIndex）。它必须在整个生命周期内保持不变，否则可见性状态机会停在对不齐的中间态。
observeAppLifecycle 在运行时被改成了 $observeAppLifecycle（初始为 $_debugObserveAppLifecycle）。它只在 initState 读取一次，改了也不会生效。
```

3. `observeEvent` 重复订阅（**本次订阅被跳过**）：

```
observeEvent<$T> 重复订阅了同一个回调。请把它移到 initState 中只调用一次——写在 build / onPageResume 里会让订阅数随重建次数线性增长。本次订阅已被忽略。
```

4. 未注册 observer（`debugPrint`，**每进程最多一次**）：

```
[page_lifecycle] 当前 Navigator 没有注册 FlRouteObserver，页面的 onPageStart / onPageResume / onPagePause / onPageStop 不会触发（转场动画回调不受影响，它直接监听 ModalRoute.animation）。请加上：
  MaterialApp(navigatorObservers: [FlRouteObserver()], ...)
嵌套 Navigator 各自也要加一个，但不能复用同一个实例——根用 FlRouteObserver()，嵌套的每个用一个新的 FlRouteObserverProxy()。（本提示每次运行只输出一遍）
```

5. 漏包内层容器的 `debugPrint` 原文见 `api.md` 的 FlPageIndexScope 一节。
