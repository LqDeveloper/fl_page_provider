# 场景：页码容器（PageView / TabBarView / IndexedStack）

[4 懒加载](#4-pageview--tabbarview-懒加载) · [5 嵌套容器](#5-嵌套-pageview--tabbarview) · [15 onPageIndexChanged 三条约定](#15-onpageindexchanged-的三条约定) · [16 IndexedStack](#16-indexedstack)

节号在四个 `sc-*.md` 里全局唯一。前提：路由观察者已注册（见 `sc-route.md` 第 9 节）。

**通用两步，缺一不可**：容器侧 `FlPageIndexScope.wrapChildren` 注入页码，子页侧 `observePageIndex => true`。只包不开 → 首帧全部 start（等于没懒加载）；只开不包 → 可见性永远不变。

---

## 4. PageView / TabBarView 懒加载

出处：`example/lib/src/page_view_page.dart`

子页全都被 build 且保活，路由事件说明不了哪个在屏上，所以换成按页码驱动。

```dart
// 宿主
PageView(
  controller: _controller,
  onPageChanged: (index) => setState(() => _index = index),
  children: FlPageIndexScope.wrapChildren(        // 第 1 步
    controller: _controller,
    children: const [PageOne(), PageTwo(), PageThree()],
  ),
)
```

```dart
// 子页
class _FeedTabState extends State<FeedTab>
    with FlPageLifecycleMixin, AutomaticKeepAliveClientMixin {
  @override
  bool get observePageIndex => true;   // 第 2 步：不开的话首帧就 start
  @override
  bool get wantKeepAlive => true;      // 不保活的话划回来 State 是新的，_loaded 丢失

  bool _loaded = false;

  @override
  void onPageStart() {
    if (_loaded) return;
    _loaded = true;
    _fetch();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);              // AutomaticKeepAliveClientMixin 要求
    return const SizedBox();
  }
}
```

### 提交时机：停稳才算翻过去

可见性**只在容器停在某一页上时提交**，判据是最近一层 `Scrollable` 的 `ScrollPosition.isScrollingNotifier`；`TabBarView` 内部也是 `PageView`，两种控制器同一条路径。

| 操作 | 结果 |
|---|---|
| `animateToPage(0 → 4)` / `TabController.animateTo` | 只有 `S0:stop` + `S4:start`，被掠过的 1/2/3 **一个事件都不发** |
| 拖过半页又拖回来松手 | **什么都不发** |
| `jumpToPage` | 不产生滚动活动，**当场提交** |
| 正常翻一页（含 fling） | 停稳时发出，成对 |

这条规则解决**假曝光**：按「滑过半页就提交」的话，`animateToPage` 掠过的中间页各自会收到一对只隔几帧的 start/stop，埋点凭空多出几次浏览，视频/轮询也被启停一轮。攒到停下来再看，它们从可见变回不可见全发生在冻结期内，一个事件都不发。

**代价**：start/stop 比「滑过半页」晚到约一次回弹动画的时间。要「划走瞬间就静音」就配合路由事件或自行监听控制器。Scope 不在任何 `Scrollable` 里时恒为静止，行为与加这层门禁前一致。

### 其他要点

- **首页无需滑动即 start**：attach 当场就能确定页码是 0，立刻发 start。
- **子页同时受页码和路由驱动**：翻页发 start/stop，在子页上弹 dialog 照样 pause/resume，从子页 push 新路由照样 pause/stop。两套机制叠加生效。
- 同一帧内**所有 hide 先于所有 show**（帧末两阶段队列），不会出现两个子页同时认为自己可见；一次翻页的 stop 与 start 落在同一批里。
- `TabBarView` 把 `controller` 换成 `TabController`；`PageView.builder` 用 `wrapItemBuilder`；一个 `PageController` 别给多个 `PageView` 共用（`indexOf` 会返回 `null`）；构造函数带 assert 所以**不是 const**；要量尺寸用 `onPagePostFrame`。

---

## 5. 嵌套 PageView + TabBarView

出处：`example/lib/src/page_view_page.dart` 的 `PageThree`

外层 `PageView`、内层 `TabBarView` 各包一层 Scope，内层传 `TabController`，每个子页都开 `observePageIndex`。

```dart
TabBarView(
  controller: _tabController,
  children: FlPageIndexScope.wrapChildren(
    controller: _tabController,
    children: [_TabChild(tag: 'A'), _TabChild(tag: 'B')],
  ),
)
```

**每一层容器都必须包。** 只包外层、漏掉内层**不会报错**：本页静默绑到外层 Scope，于是切内层子页收不到 start/stop（子页 keepAlive 时旧页会永远停在 appeared），`pageIndex` / `pageScopeDepth` 读到的也是外层的值。

debug 下会 `debugPrint` 提示一次，形如「`_InnerHost` 打开了 observePageIndex，但离它最近的 `TabBarView` 没有用 FlPageIndexScope 包子页」，并告诉你它绑到了哪一层。每个「宿主类型+容器类型」组合只输出一遍。**允许误报**：页面内部的轮播 `PageView` 本来就该跟着外层页码走，这时忽略提示即可；本页完全不需要按页码驱动就把 `observePageIndex` 改回 `false`。

**可见性按整条链判定**：子页可见要求每一层祖先都在自己宿主的当前页。用户从底部导航切到别的 tab 时，内层正在显示的子 tab 也会一起收到 `stop`，里面的视频/轮询被正确停掉——不用自己再判断一层。外层滑动期间内层同样不提交，外层停稳才一起发出。

调试嵌套层级时子页里可直接读：`pageIndex`、`pageScopeDepth`（最外层 0，每嵌一层 +1，不在 Scope 里是 -1）。

两类容器（滚动的 / `IndexedStack`）可以互相嵌套，规则不变。

---

## 15. onPageIndexChanged 的三条约定

`void onPageIndexChanged(int from, int to)`，仅在 `isInPageScope` 为 true 时触发，**只反映本页所在那一层**——嵌套时外层换页不从这里报出来，要听外层就把宿主挂在外层的 Scope 下。

**① 同一对参数。** 本层每个已挂载的页收到的 `(from, to)` 完全一致，包括刚切过去的那一页（旧页码记在层上，不是各自页上）。已被移出视口销毁的页自然收不到，要每页都收就配合 `keepAlive`。

**② 一次报到位。** `animateToPage(0 → 4)` 报的是 `(0, 4)`，不会把途中的 1/2/3 逐级报出来。

**③ 不补发。** 本层第一次确定页码时不发（没有「旧页码」）；在某次换页**之后**才挂上来的宿主也不会补发那一次——`jumpToPage` 落地后才建出来的新当前页、页面里条件渲染进来的 `FlPageLifecycleView` 都属于这种。

要的是「本页成了当前页」这个信号就用 `onPageStart`，它在这些情形下照常触发。`FlPageLifecycleView` 最容易踩到第 ③ 条。

---

## 16. IndexedStack

出处：`example/lib/src/indexed_stack_page.dart`

子页全部保活、切走也不销毁，所以和 `PageView` 一样需要 Scope 告诉它们「你下去了」。驱动源是一个 `ValueNotifier<int>`，同时喂给 `IndexedStack.index` 和 Scope：

```dart
class _HomeState extends State<Home> {
  final _index = ValueNotifier<int>(0);

  // 包装结果与当前页码无关，建一次即可，别放进 builder
  late final List<Widget> _pages = FlPageIndexScope.wrapChildren(
    controller: _index,
    children: const [FeedTab(), MessageTab(), MineTab()],
  );

  @override
  void dispose() {
    _index.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    bottomNavigationBar: ValueListenableBuilder<int>(
      valueListenable: _index,
      builder: (context, index, _) => NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (i) => _index.value = i,   // 切页就是赋值
        destinations: const [...],
      ),
    ),
    body: ValueListenableBuilder<int>(
      valueListenable: _index,
      builder: (context, index, _) => IndexedStack(index: index, children: _pages),
    ),
  );
}

class _FeedTabState extends State<FeedTab> with FlPageLifecycleMixin {
  @override
  bool get observePageIndex => true;   // 不开的话三个 tab 首帧全 start
}
```

与 `PageView` 的三点不同：

- **不需要 `AutomaticKeepAliveClientMixin`**：`IndexedStack` 本来就保活所有子页，这恰恰是它们需要 Scope 的原因。
- **当场提交**：非滚动容器没有中间态，不设「停稳」门禁，也**不绑任何 `ScrollPosition`**——所以放在 `ListView` 里的 `IndexedStack` 不会被那个列表的滚动状态卡住。
- **漏包没有任何提示**：那条 debug 诊断只认 `PageView` / `TabBarView`（`IndexedStack` 常被当成纯布局用，逐个警告太吵）。忘了包就是静默失效，自己留意。

两个细节：切页时子页**不会重建**，所以在 `build` 里读 `currentPageIndex` 拿到的是旧值——`build` 里只读不变的 `pageIndex` / `pageScopeDepth`，可见性本身不依赖重建（Scope 直接听 notifier）。`IndexedStack(index: null)`（notifier 给 -1）会让所有页都不可见：当前页收 pause + stop，没有页 start。
