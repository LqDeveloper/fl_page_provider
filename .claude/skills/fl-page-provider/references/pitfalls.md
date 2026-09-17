# 症状速查

这些都**编译得过、`flutter analyze` 也不报**，所以只能按症状倒查。先跑
`python3 scripts/verify.py lib/`，它能直接定位到行的就不必看这里。

## UI 不刷新

| 症状 | 原因 | 改法 |
|---|---|---|
| 某一块怎么都不重建，数据明明变了 | 通知的 ID 没写进 `shouldNotifyIds`。未登记的 ID 版本号恒为 `0`，比对永远得出「没变」 | 加进 `shouldNotifyIds`，或直接 `XxxEvent.values` |
| 整页都不刷新，`onPageInit` 里还打了日志 | 覆写 `onPageInit` 漏了 `super.onPageInit()`——ID 登记就在 super 里 | 第一行补 super |
| 热重载之后就不刷新了，重启又好 | 覆写 `onPageReassemble` 漏了 super（重新登记在那里） | 补 super |
| `FlSelector` 从来不重建 | `ids: const []`。空列表是「一个 ID 都不关心」，不是「不限定 ID」 | 写上真正关心的 ID；要全量刷新用 `context.wc<T>()` |
| 改了数据没反应，但换个页面回来就对了 | 只改了字段没发通知 | 补 `notifySingleListener` / `notifyMultiListeners` |
| 同一次变更，有的块刷了有的块没刷 | 控制器里调了 `notifyListeners()`。它不推进任何 ID 的版本号，`wc` 的依赖方会重建、`selectIds` / `FlSelector` 的一个都不会 | 子类里一处都别调它；要整页刷新就把相关 ID 一起列进 `notifyMultiListeners` |
| 某个页面整个静默冻结，其它页面正常 | `create` 返回了共享实例：所有权是单向的，第一个关闭的子树把它 `dispose` 了，之后 `notifyListeners` 开头的 `if (_disposed) return;` 直接吞掉所有通知 | 每个 `create` 各 new 一个；确实要共享就把 provider 提到共同祖先上，只铺一个 |

## 重建太多

| 症状 | 原因 | 改法 |
|---|---|---|
| 点个按钮整页闪 | 用 `context.wc<T>()` 取控制器。它是全量依赖 | 只调方法用 `rc`；要显示数据用 `selectIds` / `FlSelector` |
| 收起某块之后，它相关的通知还在让整页重建 | `selectIds` 写在条件分支里。Flutter 只在 `Element.deactivate()` 时解除依赖登记，**重建时从不清理**，上一轮登记的 ID 会一直留到卸载 | 无条件调用，或把那块拆成独立 Widget（条件不成立时整个卸载，依赖随之解除）。`provider` 的 `context.select` 同样如此 |
| `FlSelector` 里一大片静态 UI 跟着重建 | 静态部分写在 `builder` 里了 | 传给 `child` 参数（或 `FlSelectorView.staticChild`），并保证每次是同一个实例 |
| 埋点重复上报 / 接口重复请求，次数随进出页面增长 | `observeEvent` 写在 `build`、`onPageResume` 这类会重复执行的地方；它不解除已有订阅 | 移到 `onPageInit`，只订阅一次 |
| 已经移到 `onPageInit` 了还是重复 | 传的是闭包字面量。重复订阅的拦截靠回调相等来识别，闭包每次都是新对象 | 传方法引用：`observeEvent<Foo>(_onFoo)` |

## 生命周期回调不来

| 症状 | 原因 | 改法 |
|---|---|---|
| 一个生命周期回调都不来，页面渲染正常 | 没注册 `FlRouteObserver`。不注册不抛异常，只是静默失效 | `MaterialApp(navigatorObservers: [FlRouteObserver()])` |
| 根 `Navigator` 正常，tab 内独立栈的页面收不到 | 嵌套 `Navigator` 没挂 observer，或复用了 `FlRouteObserver()` 单例（Flutter 的 `assert(observer.navigator == null)` 会炸） | 每个嵌套 `Navigator` 各 new 一个 `FlRouteObserverProxy()` |
| `PageView` 子页首帧就全部 `onPageStart` | 宿主侧没用 `FlPageIndexScope.wrapChildren` 包 | 包上；两半缺一不可 |
| 包了 Scope，切页还是收不到 start/stop | 子页没 `observePageIndex => true` | 打开这个开关 |
| 嵌套容器：切外层有事件，切内层没有 | 只包了外层。本页会静默绑到外层 Scope 上（`IndexedStack` 漏包连 debug 提示都没有） | **每一层**容器都要包 |
| 弹个 dialog，轮询就断了 | 用了 `onPageResume` / `onPagePause`。dialog 盖上来只发 `pause`，不发 `stop` | 判断标准：弹窗期间这件事该不该继续。该继续用 `onPageStart` / `onPageStop`（轮询、WebSocket、曝光埋点、倒计时），该停用 `resume` / `pause`（视频音频、动画、相机、定位） |
| `onPageDispose` 里读 `routeName` 拿到 `null` | 那时路由信息已清 | 在 `onPageStop` 读 |

更细的生命周期问题（时序、`popUntil` / `pushAndRemoveUntil`、go_router / auto_route 的注册
位置、转场动画）属于 fl_page_lifecycle 那一层，读那个 skill 的 `references/pitfalls.md` 与
`sc-route.md`，本文不重复。

## 取控制器报错

`FlPageProviderNotFoundError` 的三种成因（报错文案里也写了）：

1. 页面没用 `FlBasePage` / `FlBasePageState` / `FlProviderBuilder` 承载。
2. 用的 `context` 在承载它的那一层**之上**——最常见的是在创建 provider 的同一个 `build`
   里直接用那个 `context`。改用 `Builder` 或子 Widget 的 context。`buildWithController`
   拿到的 context 已经在 provider 之下，可以直接用。
3. 泛型写的是父类型。查找按**精确类型**匹配，父类型找不出子类，反过来也一样。

## 保活

`wantKeepAlive => true` 只在 `FlBasePageState` 上有；开了这一页就不会被销毁，控制器也跟着
活着。`IndexedStack` 本身就保活，用 `ValueNotifier<int>` 驱动 Scope 时子页不需要再开。
覆写 `build` 必须调 `super.build(context)`，否则保活静默失效——正常写法是只实现
`buildWithController`，不碰 `build`。
