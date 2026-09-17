# 场景：路由、注册位置与转场动画

[6 路由栈批量操作](#6-路由栈批量操作) · [8 转场动画](#8-转场动画) · [9 注册位置](#9-go_router--嵌套-navigator-注册位置) · [17 嵌套 Navigator](#17-嵌套-navigatortab-内独立路由栈)

节号在四个 `sc-*.md` 里全局唯一。

---

## 9. go_router / 嵌套 Navigator 注册位置

根 `Navigator` 挂单例 `FlRouteObserver()`，**其余每一个 `Navigator` 各挂一个新的 `FlRouteObserverProxy()`**：

```dart
// 根
MaterialApp(navigatorObservers: [FlRouteObserver()], home: const HomePage());

// go_router 的 ShellRoute
ShellRoute(observers: [FlRouteObserverProxy()], builder: (c, s, child) => Shell(child: child));

// StatefulShellRoute：每个分支各一个
StatefulShellBranch(observers: [FlRouteObserverProxy()], routes: [...]);

// auto_route：navigatorObservers 是 builder，每次都要返回新实例
appRouter.config(navigatorObservers: () => [FlRouteObserverProxy()]);

// 手写的 tab 内独立栈
Navigator(key: tabKey, observers: [FlRouteObserverProxy()], onGenerateRoute: ...);
```

**为什么不能复用同一个实例**：`FlRouteObserver` 是单例，而 Flutter 的 `Navigator.initState` 里有 `assert(observer.navigator == null)`——一个 `NavigatorObserver` 实例同时只能绑定一个 `NavigatorState`。把单例同时挂到根和嵌套 `Navigator` 上，第二个挂载时 debug 直接断言失败。两个嵌套 `Navigator` 复用同一个 proxy 也一样会断言，**该 new 就 new**。

proxy 是无状态的，只有一次对象分配的成本，写在 `build` 里也无妨；它把四个路由事件转发给 `FlRouteObserver.instance`，订阅表全局仍然只有一份，所以页面侧不用改任何代码。

不注册**不抛异常**，只是静默失效（debug 下 `debugPrint` 一条提示，但每进程只打一遍）。

**症状对照**：

| 症状 | 原因 |
|---|---|
| 四个可见性回调全不来，动画回调正常 | 漏注册 |
| debug 下 `assert(observer.navigator == null)` 失败 | 同一个 observer 实例挂了两个 `Navigator`——嵌套的改用新的 proxy |
| 只有嵌套栈里的页面不来 | 那个嵌套 `Navigator` 没挂 proxy |
| 子页首帧就全 start | 忘了 `observePageIndex => true` |
| 子页可见性永不变 | 忘了 `wrapChildren` |
| `onAppForeground` 不来 | 忘了 `observeAppLifecycle`，或重写 `appLifecycleChanged` 漏了 `super` |

---

## 6. 路由栈批量操作

出处：`example/lib/src/page_lifecycle_page.dart`

下单成功后回首页这类操作，栈里各层到底收到什么——这是最容易写出线上 bug 的地方。

**`pushAndRemoveUntil`**：新路由**先**被 push 到栈顶，然后才逐个 remove 下面的旧路由。每次 `didRemove` 时 `previousRoute` 都还被新页盖着，一层都没真的露出来，所以**底层页全程不会收到 `onPageStart`**。

业务含义：回首页时首页不会被误唤醒去多发一次曝光埋点或起一次轮询。手写 `RouteAware` 在这里必错——它会给没人看得见的页面发 start。

**`popUntil`**：是一个 `while` 循环，每次 `pop()` 都独立走一遍历史整理与观察者派发。所以被跨过的中间层**确实会短暂成为栈顶**，各自收到一对 `start → resume → pause → stop`。

这不是 bug，是配对的、会自我纠正的瞬态。但如果 `onPageStart` 里是曝光埋点，会多记几条——用停留时长阈值过滤掉极短记录即可。

---

## 8. 转场动画

出处：`example/lib/src/animation_page.dart`

把重活（大图解码、复杂首屏、埋点上报）推迟到入场动画播完，避免转场掉帧：

```dart
class _DetailPageState extends State<DetailPage> with FlAnimationLifecycleMixin {
  @override
  void onPageEnterAnimationEnd() => _loadHeavyStuff();
}
```

三条容易搞错的语义：

- **`onPageEnterAnimationStart` 首次进入通常不发**（监听器在 `onPageContextReady` 时才绑上，那时动画已经开始）。想表达「页面正在出现」用 `onPageContextReady`。
- **`onPageEnterAnimationEnd` 一个生命周期里可能触发两次**（正常入场一次，iOS 侧滑放弃回弹一次），计数逻辑要幂等。
- **`onPageLeaveAnimationStart` 不代表页面会离开**：侧滑放弃时后面跟的是 `onPageEnterAnimationStart` → `onPageEnterAnimationEnd`，永远不会有 `onPageLeaveAnimationEnd`，也没有 pause/stop。不可逆的事放 `onPageLeaveAnimationEnd` 或 `onPageDispose`。

首页（`home`）没有转场，两个入场动画事件都不发。

---

## 17. 嵌套 Navigator（tab 内独立路由栈）

出处：`example/lib/src/nested_navigator_page.dart`

结构是「外层按页码切 tab，每个 tab 内部有自己的路由栈」：

```
PageView
  └ FlPageIndexScope（wrapChildren 自动包）
      └ AutomaticKeepAliveClientMixin
          └ FlPageLifecycleView(observePageIndex: true)   ← 整栈粒度地听翻页
              └ Navigator(observers: [FlRouteObserverProxy()])   ← 听本栈路由
                  └ 栈内各页（FlPageLifecycleMixin）
```

```dart
PageView(
  controller: _controller,
  children: FlPageIndexScope.wrapChildren(
    controller: _controller,
    children: const [TabStack(name: '栈 A'), TabStack(name: '栈 B')],
  ),
)

// 一个 tab
FlPageLifecycleView(
  observePageIndex: true,
  child: Navigator(
    observers: [FlRouteObserverProxy()],        // 每个嵌套 Navigator 一个新实例
    onGenerateRoute: (settings) => MaterialPageRoute<void>(
      settings: settings,
      builder: (_) => const StackPage(depth: 0),
    ),
  ),
)

// 栈内页面
class _StackPageState extends State<StackPage> with FlPageLifecycleMixin {
  @override
  bool get observePageIndex => true;   // 不开就完全无视外层翻页
}
```

**可见性 =（本栈是当前页）且（本页是本栈栈顶）**。两个条件缺一不可：页码驱动的页面在**自己不是本 `Navigator` 栈顶**时不发 `onPageStart`。

实际表现：

- 在栈 A 压到第 1 层 → 划到栈 B：A#1 收 pause + stop
- 划回栈 A：**只有 A#1 复活**，被盖住的 A#0 保持 stopped
- 栈 A 隐藏时 pop 掉 A#1：不发 start，等划回来才发
- `jumpToPage` 时宿主路由正被别的路由盖着：切过去的那页也不会 start

不是丢了——盖住的路由 pop 之后会正常补上。

**一个容易忘的细节**：栈内页面弹 dialog 要用 `showDialog(context: context, useRootNavigator: false, ...)`，默认 `true` 会把弹窗压到根 `Navigator` 上，内层页面收不到 `pause`。
