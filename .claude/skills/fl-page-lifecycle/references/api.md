# API 速查（主用面）

照源码抄写。**对不上就来查，别凭印象拼**——库里有同名不同参的回调。

本文：[枚举](#fllifecyclestate) · [FlPageLifecycleMixin](#flpagelifecyclemixin) · [FlPageIndexScope](#flpageindexscope) · [FlPageLifecycleView](#flpagelifecycleview)。
其余（Controller/Route/App/Animation mixin、RouteObserver 与 Proxy、事件总线、LifecycleManager、**assert 与 debug 提示原文**）在 `api-more.md`。

```dart
import 'package:fl_page_lifecycle/fl_page_lifecycle.dart';   // 一个导入拿到全部公开面
```

不要 import `package:fl_page_lifecycle/src/...` 下的任何文件。

---

## FlLifecycleState

`enum`，18 个值，**按声明顺序**：

```
1 onPageInit              7 onPageResume               13 onPageDispose
2 onPageContextReady      8 onPageEnterAnimationEnd    14 onAppResume
3 onPagePostFrame         9 onPagePause                15 onAppInactive
4 onPageReassemble       10 onPageStop                 16 onAppPause
5 onPageEnterAnimationStart  11 onPageLeaveAnimationStart  17 onAppForeground
6 onPageStart            12 onPageLeaveAnimationEnd    18 onAppBackground
```

枚举自身的成员（不是 extension）：`bool get isPageResume` · `bool get isPagePause` · `bool get isAppEvent`（∈ {onAppForeground, onAppBackground, onAppResume, onAppInactive, onAppPause}）。

没有 `isPageEvent`、没有 `label`、没有别的 extension。

---

## FlPageLifecycleMixin

```dart
mixin FlPageLifecycleMixin<T extends StatefulWidget> on State<T>
    implements LifecycleRouteAware
```

### 开关与 getter

| 名称 | 类型 | 默认 / 说明 |
|---|---|---|
| `observePageIndex` | `bool` | `false`；整个生命周期内必须恒定（debug 断言把关），写字面常量最保险 |
| `observeAppLifecycle` | `bool` | `false`；同上，且只在 `initState` 读一次 |
| `routeName` | `String?` | `ModalRoute.settings.name`；**`onPageContextReady` 之前、不在任何路由中、dispose 之后都是 null** |
| `arguments` | `Object?` | `RouteSettings.arguments`；为 null 的时机同 `routeName` |
| `isInPageScope` | `bool` | 首次 `didChangeDependencies` 前为 false |
| `pageIndex` | `int` | 不在页码作用域中为 -1 |
| `currentPageIndex` | `int` | 未知为 -1 |
| `pageScopeDepth` | `int` | 最外层 0，不在作用域中 -1 |
| `isForeground` | `bool` | 读 `WidgetsBinding.lifecycleState`，无需订阅 |
| `isPageAppeared` | `bool` | start 已发且 stop 未发 —— **判「可见」用这个** |
| `isPageResumed` | `bool` | resume 已发且 pause 未发 —— 判「可交互」 |
| `isCurrent` | `bool` | `ModalRoute.isCurrent`，实时；无 ModalRoute 时 false |

### 可重写回调

全部 `@protected`、`void`、空实现（除注明者）：

```dart
void onPageInit()
void onPageContextReady(String? routeName, Object? arguments)   // ← 两个参数
void onPagePostFrame()
void onPageReassemble()                        // 仅 debug（kDebugMode 门禁），热重载时触发
void onPageEnterAnimationStart()
void onPageStart()
void onPageResume()
void onPageEnterAnimationEnd()
void onPageLeaveAnimationStart()
void onPagePause()
void onPageStop()
void onPageLeaveAnimationEnd()
void onPageDispose()
void onAppResume()        // 以下五个需 observeAppLifecycle == true
void onAppInactive()
void onAppPause()
void onAppForeground()
void onAppBackground()
void onPageIndexChanged(int from, int to)       // 仅 isInPageScope 时；只报本层；三条约定见下

@protected @mustCallSuper
void onLifecycleStateChanged(FlLifecycleState state)    // 18 个事件的统一出口，空实现

@mustCallSuper @protected
void appLifecycleChanged(AppLifecycleState state)       // 非空：它分发上面三个原始 App 事件
```

**只有这两个是 `@mustCallSuper`**。`hidden` / `detached` 被显式列出且刻意不发事件。

`@internal @override @nonVirtual`（不可重写）：`routePageStart()` / `routePageResume()` / `routePagePause()` / `routePageStop()`。

### 机制要点

- `_emit` 先调模板回调、再调 `onLifecycleStateChanged`，两者各自包在独立的 `FlLifecycleGuard.run` 里。异常走 `FlutterError.reportError`，不传播。
- `initState`：`observeAppLifecycle` 为真 → 2 条全局流订阅；发 `onPageInit`；注册首帧回调。
- `didChangeDependencies`：`observePageIndex` 为真 → 订阅最近的 Scope；随后 `attachOnce(context)` 订阅 observer 并绑动画监听，首次成功时发 `onPageContextReady`。失败不锁定，后续每次都会重试。
- `dispose` 顺序与 `routeName` 的可读性：见 pitfalls.md 第 11 条。
- 首帧门禁：`observePageIndex && isInPageScope` 时首帧不 start；否则若路由已 attach 且 `!isCurrent` 则不 start。**无 `ModalRoute` 时不设门禁**（见 pitfalls.md 末尾）。

---

## FlPageIndexScope

```dart
class FlPageIndexScope extends StatefulWidget

FlPageIndexScope({                  // 非 const（带 assert）
  super.key,
  required int pageIndex,
  required Listenable controller,  // PageController / TabController / ValueListenable<int>
  required Widget child,
})
```

`build` 返回包着 `child` 的内部 InheritedWidget，不加布局节点。

消费者可用的静态方法：

```dart
static int  depthOf(BuildContext context);              // 不在作用域中 -1
static Listenable listenableOf(Listenable controller);   // TabController → animation ?? controller
static int? indexOf(Listenable controller);
static int  initialIndexOf(Listenable controller);
static NullableIndexedWidgetBuilder wrapItemBuilder({
  required Listenable controller, required NullableIndexedWidgetBuilder builder});
static List<Widget> wrapChildren({
  required Listenable controller, required List<Widget> children});
```

`maybeOf` 与 `debugResetWarnings` 是 `@internal`，`FlPageIndexScopeData` / `FlPageIndexVisibility` 在导出处被 `hide` —— **消费者拿不到，别写**。

`indexOf` 返回 `null`：`TabController.length == 0`；`PageController.positions.length != 1`（布局前，或一个 controller 被多个 `PageView` 共用）；`PageController.page == null`。传 `ValueListenable<int>` 时直接返回 `controller.value`（那个值本身就是结论，不用采样）。

### 提交时机

三类 `controller` 的差别只有这一处。**滚动容器**（`PageController` / `TabController`）只在停在某一页时提交，判据是最近一层 `Scrollable` 的 `ScrollPosition.isScrollingNotifier`（`Idle` / `Hold` 为静止，`Drag` / `Ballistic` / `Driven` 为运动中）；不在任何 `Scrollable` 里时恒为静止。**非滚动容器**（`ValueListenable<int>`，如 `IndexedStack`）当场提交，不设门禁也**不绑任何 `ScrollPosition`**。提交后都走帧末两阶段队列：同一帧内所有 hide 先于所有 show。行为后果见 `sc-index.md` 第 4 节。

### onPageIndexChanged 的三条约定

① **同一对参数**——本层每个已挂载的页收到的 `(from, to)` 完全一致，包括刚切过去的那一页（旧页码记在层上）。② **一次报到位**——`animateToPage(0 → 4)` 报 `(0, 4)`，不逐级报中间值。③ **不补发**——本层首次确定页码时不发；某次换页之后才挂上来的宿主也不补发那一次。要「本页成了当前页」这个信号用 `onPageStart`。

### 漏包内层容器的 debug 提示

`observePageIndex => true` 但离本页最近的容器没包 Scope 时，debug 下 `debugPrint` 一次（**不是抛异常的 assert**，因为允许误报）。每个「宿主类型+容器类型」组合只输出一遍。**只认 `PageView` / `TabBarView`，`IndexedStack` 漏包没有任何提示。** 开头是：

```
[page_lifecycle] $hostType 打开了 observePageIndex，但离它最近的 $containerType 没有用 FlPageIndexScope 包子页，$cause
```

`$cause` 两种（按日志检索时用这两句的开头）：

```
向上也找不到任何 FlPageIndexScope，本页会被当成普通页面：首帧就发出 onPageStart / onPageResume，之后再也不会随切页发出 onPageStop。
于是本页绑到了更外层的 Scope（depth=${data.depth}、pageIndex=${data.pageIndex}）：可见性只跟着那一层的页码走，切换 $containerType 的子页不会发出 onPageStart / onPageStop（子页 keepAlive 时旧页会永远停在 appeared），pageIndex / pageScopeDepth 读到的也是外层的值。
```

后面还会跟一段「请给这个 $containerType 也包一层」的示例代码。

嵌套细节见 `sc-index.md` 第 4、5、15、16 节。

---

## FlPageLifecycleView

```dart
typedef FlPageLifecycleCallback   = void Function(BuildContext context, FlLifecycleState state);
typedef FlPageRouteParamCallback  = void Function(BuildContext context, String? routeName, Object? arguments);
typedef FlPageIndexChangedCallback = void Function(BuildContext context, int from, int to);

const FlPageLifecycleView({
  super.key,
  bool observePageIndex = false,
  bool observeAppLifecycle = false,
  FlPageLifecycleCallback? onStateChanged,
  FlPageRouteParamCallback? onRouteParam,      // ← 叫 onRouteParam，没有 onContextReady
  FlPageIndexChangedCallback? onPageIndexChanged,
  required Widget child,
});
```

内部 State 混入完整的主 mixin，`build` 原样返回 `widget.child`。mixin 的 getter（`routeName` / `isPageAppeared` …）**不对外暴露**。
