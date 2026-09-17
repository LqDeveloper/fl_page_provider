# 避坑与排错

行为和预期不符时查这里：先看症状速查表定位，再看对应条目。

## 症状速查

| 症状 | 条目 |
|---|---|
| 四个可见性回调全不来，动画回调正常 | [1](#1-漏注册路由观察者) |
| 只有某些页面的回调不来 | [1](#1-漏注册路由观察者) |
| debug 下 `assert(observer.navigator == null)` 失败 | [15](#15-同一个-observer-实例挂了两个-navigator) |
| 弹 dialog / bottomSheet 时资源被误释放 | [2](#2-用-iscurrent-判断可见性) |
| 事件收到两遍，或某个状态机完全不跑 | [3](#3-叠加库里的多个入口-mixin) |
| 子页首帧全部 start，懒加载没生效 | [4](#4-页码容器只做了一半) |
| 子页可见性永远不变 | [4](#4-页码容器只做了一半) |
| `IndexedStack` 子页可见性不对，且没有任何提示 | [16](#16-indexedstack-漏包没有提示) |
| 切内层 tab 收不到 start/stop（外层切换正常） | [12](#12-嵌套时漏包内层容器) |
| 划回 tab 后只有栈顶页复活，下层没醒 | [17](#17-页码驱动的页面不是本栈栈顶时不发-start) |
| debug assert 挂掉，提示开关被改 | [5](#5-开关中途变了值) |
| `onAppForeground` / `onAppResume` 等不来 | [6](#6-重写时漏了-super) |
| 自己叠的埋点 mixin 不生效 | [6](#6-重写时漏了-super) |
| 订阅数随重建线性增长，或第二次订阅无效 | [7](#7-observeevent-调在了错误的地方) |
| 某页 pop 后，所有其他页面的事件/订阅全失活 | [8](#8-调了全局的销毁方法) |
| `FlPageControllerMixin` 一个回调都不触发 | [9](#9-controller-收不到事件) |
| `try/catch` 抓不到回调里的异常 | [10](#10-异常被守卫吞掉) |
| `onPageDispose` 里 `routeName` 是 null | [11](#11-dispose-的顺序) |
| `animateToPage` 掠过的中间页没有埋点 | [13](#13-翻页事件比预期少或比预期晚) |
| 翻页后 start/stop 比预期晚了一拍 | [13](#13-翻页事件比预期少或比预期晚) |
| `onPageIndexChanged` 没收到，或收到的不是相邻页码 | [14](#14-onpageindexchanged-没收到) |
| `setState() called during build` | `sc-arch.md` 第 14 节 |
| `popUntil` 后中间层闪了一对 start/stop | `sc-route.md` 第 6 节 |

---

## 1. 漏注册路由观察者

四个可见性事件由 `FlRouteObserver` 翻译路由变化而来，不注册就没有源，且**不抛异常**。转场动画回调直接监听 `ModalRoute.animation`、不受影响——所以「动画有、可见性没有」是确诊症状。

根 `Navigator` 挂 `FlRouteObserver()`，**每个嵌套 `Navigator` 各挂一个新的 `FlRouteObserverProxy()`**（不能复用实例，见 [15](#15-同一个-observer-实例挂了两个-navigator)）。go_router 的 `ShellRoute`、auto_route 的嵌套 router、手写的 tab 内独立栈都是常漏处。写法见 `sc-route.md` 第 9 节。

debug 下会 `debugPrint` 一条提示，但**每进程只打一遍**——多处漏注册只会看到一次，别以为只有一处。

## 2. 用 isCurrent 判断可见性

`ModalRoute.isCurrent` 在任何路由压上来时都变 `false`，包括 `PopupRoute`。而 `PopupRoute` 压上来时页面是**完全可见**的，库只发 `pause` 不发 `stop`。

判「可见」用 `isPageAppeared`，判「可交互」用 `isPageResumed`；`isCurrent` 唯一正当用途是真的想知道是不是栈顶。

## 3. 叠加库里的多个入口 mixin

它们订阅同一批源、成员名还会撞，但**撞的是哪些成员取决于组合**：

| 组合 | 撞的成员 | 后果 |
|---|---|---|
| 主 mixin + `FlPageRouteMixin` | `routePageStart` / `routePageResume` / `routePagePause` / `routePageStop`、`isCurrent` / `routeName` / `arguments` / `onPageContextReady`、四个动画回调 | 两个路由委托各自订阅了一遍 observer，事件双发；主 mixin 那四个 `routePage*` 是 `@nonVirtual`，分析器会报 `invalid_override_of_non_virtual_member` |
| 主 mixin（或 `FlPageRouteMixin`）+ `FlAnimationLifecycleMixin` | 只撞 `onPageEnterAnimationStart` / `End`、`onPageLeaveAnimationStart` / `End` | 两份动画绑定监听同一个 `ModalRoute.animation`，动画回调双发 |
| 主 mixin + `FlAppLifecycleMixin` | `isForeground`、`appLifecycleChanged`、`onAppForeground`、`onAppBackground` | `FlAppLifecycleMixin` 的 `appLifecycleChanged` 是空实现且**不是** `@mustCallSuper`，混在主 mixin 之后会把三个原始 App 事件的分发整条吃掉 |
| `FlPageRouteMixin` + `FlAppLifecycleMixin` | 不撞 | —— |

`FlAnimationLifecycleMixin` 全部成员只有那四个动画回调，`FlAppLifecycleMixin` 也没有任何 `routePage*` / `isCurrent` / `routeName`——排查时别去这两个里面找它们。

**选一个**。需要的能力主 mixin 全有（App 事件开 `observeAppLifecycle`，转场动画四个回调本来就在）。唯一正确的叠加是叠自己的 mixin，见 `sc-arch.md` 第 13 节。`FlStateEventBusMixin` 例外，可一起混入。

## 4. 页码容器只做了一半

包了 `FlPageIndexScope` 但子页没写 `observePageIndex => true` → 可见性还按路由算，首帧全部 start。
开了开关但外面没包 → 拿不到页码，可见性永远不变。

其他会踩的：`controller` 只接受 `PageController` / `TabController` / `ValueListenable<int>`（别的类型 debug assert）；构造函数带 assert 所以**不是 const**；一个 `PageController` 给多个 `PageView` 共用会让 `indexOf` 返回 `null`；要量尺寸用 `onPagePostFrame`；嵌套时子页可见要求**每层祖先都在自己宿主的当前页**，且**每层容器都要包**（见 [12](#12-嵌套时漏包内层容器)）；提交时机见 [13](#13-翻页事件比预期少或比预期晚)。

## 5. 开关中途变了值

`observePageIndex` 在 `initState` / `didChangeDependencies` 读，`observeAppLifecycle` 只在 `initState` 读一次。约束是**整个生命周期内取值恒定**（debug 下有断言比对首次取值），中途变了状态机就对不齐，release 下可能永远收不到 stop。

```dart
bool get observeAppLifecycle => widget.needApp;   // ✗ widget 更新后会变
bool get observePageIndex => _isInTab;             // ✗ 跟着 state 变
bool get observeAppLifecycle => true;             // ✓ 字面常量
```

转发一个自己不会变的值是允许的（库自己的 `FlPageLifecycleView` 就是 `=> widget.observePageIndex`），但只要那个来源可能变就是错的——需要条件行为请在回调内部判断，而不是改开关。

## 6. 重写时漏了 super

`onLifecycleStateChanged` 和 `appLifecycleChanged` 是 `@mustCallSuper` 的分发器。后者特别容易忽略——它的方法体就是发 `onAppResume` / `onAppInactive` / `onAppPause` 的地方，漏 `super` 这三个静默失效。

大多数情况**根本不需要重写这两个**，重写具体模板回调（`onPageResume` 等）就够，它们不需要 `super`。

## 7. observeEvent 调在了错误的地方

`FlStateEventBusMixin` 用 `(类型, 回调)` 组合去重，重复的**本次订阅被忽略** + debug assert。但去重键是 `(类型, 回调)`，只有**方法引用**稳定相等；现场写的闭包字面量不保证相等，挡不住。

```dart
// ✗ 每次 build 都新增一条
Widget build(c) { observeEvent<E>((e) => setState(...)); ... }

// ✓ 一次，方法引用
void initState() { super.initState(); observeEvent<E>(_onEvent); }
```

## 8. 调了全局的销毁方法

两个方法是**进程级**的：

- `FlGlobalEventBus.destroy()` 关掉整条广播流，所有活着的订阅收到 `done` 后死掉。之后会惰性重建总线，但**旧订阅不会迁移**。
- `FlLifecycleManager.cancel()` 移除 `WidgetsBinding` 观察者，所有页面都收不到 App 事件。

页面级清理什么都不用做——`FlStateEventBusMixin.dispose` 已取消自己的订阅。这两个只用于测试 `tearDown` 或 App 真的要退出时。自己订 `FlLifecycleManager.instance.stream` 就自己 cancel 那个 `StreamSubscription`。

## 9. Controller 收不到事件

`FlPageControllerMixin` **不订阅任何东西**，事件必须由页面转发两处（`onLifecycleChanged` + `setupRouteInfo`），见 `sc-arch.md` 第 12 节。

**签名陷阱**：Controller 上的 `onPageContextReady` 参数是 `BuildContext? context`，页面 mixin 上是 `(String? routeName, Object? arguments)`。写成后者会变成一个永远不被调用的新方法。`onPageIndexChanged` 也不会被 `onLifecycleChanged` 分发。

## 10. 异常被守卫吞掉

**本库的每一个回调抛异常都不会传播给调用方**，一律走 `FlutterError.reportError`。好处是一个回调抛异常不会阻断另一个回调、后续事件或其他页面；`dispose` 时即使 `onPageStop` 抛异常，路由订阅**仍会被解绑**，不泄漏。

代价：只能在控制台或 `FlutterError.onError` 里看到。埋点上报、网络请求这类可能失败的操作，回调里自己再包一层 `try/catch`。

兜住它的是两层，写 `FlutterError.onError` 过滤时可能需要区分：

- 绝大多数回调由库自己的 `FlLifecycleGuard.run` 兜，带 `library: 'fl_page_lifecycle'` 和「分发页面生命周期回调时」的 context。App 前后台三个回调（`onAppForeground` / `onAppBackground` / `appLifecycleChanged`）与 `observeEvent` 的订阅回调由 `StreamSubscription` 直接驱动，同样包了 guard——包它不是为了隔离（广播流本来就一个订阅者抛不影响下一个），而是为了不让异常变成交给 zone 的未捕获异步错误。
- 四个转场动画回调（`onPageEnterAnimationStart` / `End`、`onPageLeaveAnimationStart` / `End`）由 **Flutter 自己的** `AnimationLocalStatusListenersMixin.notifyStatusListeners` 兜——它对每个状态监听器逐个 try/catch 并上报。行为完全一致，只是 `FlutterErrorDetails` 上的 library 是 Flutter 的而不是本库的。

## 11. dispose 的顺序

顺序是：App 委托 detach → 补发 `onPagePause` / `onPageStop` → 路由委托 detach（退订 observer + 解绑动画）→ 页码作用域委托 detach → `onPageDispose`。

补发早于注销是有意的，所以 `routeName` / `arguments` 在 `onPageStop` 里仍可读，到 `onPageDispose` 就是 `null`。要用路由信息就在 `onPageStop` 读，或在 `onPageContextReady` 时存到字段里。

## 12. 嵌套时漏包内层容器

外层 `PageView` 包了 Scope、内层 `TabBarView` 忘了包时**不会报错**：本页静默绑到外层 Scope，于是切内层子页收不到 start/stop（子页 keepAlive 时旧页永远停在 appeared），`pageIndex` / `pageScopeDepth` 读到的也是外层的值。debug 下 `debugPrint` 提示一次，指出哪个宿主、最近的哪个容器没包、绑到了哪一层；每个「宿主类型+容器类型」组合只输出一遍，所以多个同类页面只看到一条。

**允许误报**：页面内部的轮播 `PageView` 本来就该跟着外层页码走，这时忽略提示即可。本页完全不需要按页码驱动生命周期时，把 `observePageIndex` 改回 `false`。

## 13. 翻页事件比预期少或比预期晚

**都是设计如此**，不是 bug。滚动容器的可见性只在**停稳**时提交：`animateToPage` 掠过的中间页和半途放弃的拖动都不发事件（消除假曝光），`jumpToPage` 当场提交；正常翻页的 start/stop 比「滑过半页」晚约一次回弹动画。

需要在划走瞬间就暂停视频/静音的，**别只靠它**——配合路由事件或自行监听控制器。规则全文与判据见 `sc-index.md` 第 4 节。（`ValueListenable<int>` 驱动的 `IndexedStack` 没有这层门禁，当场提交。）

## 14. onPageIndexChanged 没收到

三条约定决定了它什么时候不发：

- **本层第一次确定页码时不发**（没有「旧页码」可言）。
- **某次换页之后才挂上来的宿主不补发那一次**——`jumpToPage` 落地后才建出来的新当前页、条件渲染进来的 `FlPageLifecycleView` 都属于这种。
- **只报本页所在那一层**，嵌套时外层换页不从这里报出来。

另外它**一次报到位**：`animateToPage(0 → 4)` 报的是 `(0, 4)` 而不是逐级的 `(0,1) (1,2) (2,3) (3,4)`。同一层每个已挂载的页拿到的 `(from, to)` 完全一致，包括刚切过去的那一页。

要的是「本页成了当前页」这个信号，用 `onPageStart`——上面这些情形它都照常触发。

## 15. 同一个 observer 实例挂了两个 Navigator

Flutter 的 `Navigator.initState` 里有 `assert(observer.navigator == null)`——一个 `NavigatorObserver` 实例同时只能绑一个 `NavigatorState`。`FlRouteObserver` 是**单例**，所以把它同时挂到根和嵌套 `Navigator` 上，第二个挂载时 debug 直接断言失败。

根用 `FlRouteObserver()`，嵌套的每个各 new 一个 `FlRouteObserverProxy()`——两个嵌套 `Navigator` 复用同一个 proxy 一样会断言。proxy 无状态，写在 `build` 里也无妨。

## 16. IndexedStack 漏包没有提示

`PageView` / `TabBarView` 漏包 Scope 时 debug 会 `debugPrint` 提示一次，但**`IndexedStack` 漏包什么都不会说**——它常被当成纯布局用，逐个警告太吵。

所以 `IndexedStack` 的子页可见性不对时，先检查是不是忘了 `FlPageIndexScope.wrapChildren`。写法见 `sc-index.md` 第 16 节。

## 17. 页码驱动的页面不是本栈栈顶时不发 start

页码驱动的页面在**自己所属 `Navigator` 里不是栈顶**时，即使容器切回到它，也不发 `onPageStart`——被盖住的那层不该被唤醒，宿主路由被盖住时 `jumpToPage` 也不该启动一个没人看得见的页面。

**不是丢了**：盖住的路由 pop 之后会正常补上。可见性的完整条件是「本栈是当前页」**且**「本页是本栈栈顶」。见 `sc-route.md` 第 17 节。

---

## 两个容易想反的语义

**没有 `ModalRoute` 时，并非四个可见性事件全废。** 失效的只有**路由驱动的转场**（被覆盖/被揭开时的 pause/stop/start/resume）、两个转场动画事件和 `onPageContextReady` 本身。首帧的 `onPageStart` + `onPageResume` **照常触发**（首帧门禁只在已拿到 `ModalRoute` 时才生效），`onPagePause` + `onPageStop` 在 `dispose` 补发。测试 `'a page with no ModalRoute still starts on its first frame'` 钉的就是这个。所以给不在路由里的 widget 混入 mixin 是有意义的——能拿到「这个 widget 活着的这段时间」的成对启停。

**`FlPageRouteMixin` 是有幂等和补发的。** `_hasAppear` 让 `onRouteStart` / `onRouteStop` 一次性；resume 时若从未出现过会补发 start；`routePageStop()` 先发 pause 再发 stop；`dispose` 补发 pause/stop 对。真正没有守卫的只有 `routePagePause()`（无条件触发）。它与主 mixin 的真实差别是：不区分弹窗（`PopupRoute` 覆盖也按 pause 转发）、不管页码、没有 `onLifecycleStateChanged` 那样的统一出口。

## 选型：什么时候不该用这个库

它回答**导航层面**的问题。**不检测**：widget 滚出 `ListView` 视口（用 `visibility_detector`）、同一路由内被不透明 widget 盖住（两个库都不检测）、卡片露出百分比（`visibility_detector`）。

信息流自动播视频这类场景**两个一起用**：这个库确认 Feed 页本身 resumed（否则会在用户已跳走的页面上继续播），`visibility_detector` 确认哪张卡在屏上。

纯 App 前后台且不需要过滤瞬时打断的话，Flutter 自带的 `WidgetsBindingObserver` 就够。需要过滤来电/通知栏才值得用本库。

**用户不装本库时的原生替代与局限**（照实说，别粉饰）：

| 需求 | 原生替代 | 局限 |
|---|---|---|
| 页面可见性 | `RouteAware` + `RouteObserver` | 分不出弹窗覆盖（页面其实仍可见）；`pushAndRemoveUntil` 会给被盖住的页面误发 start；start/stop 配对要自己保证 |
| App 前后台 | `didChangeAppLifecycleState` / `AppLifecycleListener` | 来电、下拉通知栏这类瞬时打断会被当成「回到前台」，要自己过滤 |
| 页码容器子页 | 自己听 `PageController` / `TabController` | 嵌套判定、停稳时机、事件配对都要自己写 |
