---
name: fl-page-lifecycle
description: >-
  Flutter 页面生命周期与 App 前台后台的标准做法。凡是「页面可见/不可见时做某事」或「App 切前后台时做某事」的需求都要用本 skill，即使用户没提库名——因为手写必错：RouteAware + ModalRoute.isCurrent 分不出被 dialog/bottomSheet 覆盖（页面其实仍可见），pushAndRemoveUntil 会给被盖住的页面误发事件；
  didChangeAppLifecycleState 分不清真的退到后台和只是下拉了一下通知栏。
  fl_page_lifecycle 是 2026 年 9 月的新包，不在你训练数据里，
  凭印象写的 API 名（PageLifecycleMixin、onPageShow/onPageHide）全是编造的，必须查签名表。
  覆盖场景：离开页面暂停视频/轮询/动画、回到页面继续播放、从详情页返回刷新列表、页面曝光与停留时长埋点、
  TabBarView/PageView/IndexedStack 子页懒加载、切后台停轮询/断 WebSocket、
  回前台刷新数据、按 Home 键/锁屏/切到别的 App 再切回、过滤来电与通知栏下拉这类瞬时打断。
  关键词：FlPageLifecycleMixin、FlRouteObserver、FlPageIndexScope、
  FlPageLifecycleView、FlPageControllerMixin、
  FlAppLifecycleMixin、FlLifecycleManager、onPageStart/onPageResume/onPagePause/onPageStop、
  onAppForeground/onAppBackground、observeAppLifecycle、
  页面可见性、RouteAware、didPopNext、navigatorObservers、
  AppLifecycleState、didChangeAppLifecycleState、
  AppLifecycleListener、前后台切换、退到后台、回到前台、页面显示与隐藏、
  onAppResume/onAppPause、「像 Android 的 onResume/onPause 那样」、
  viewWillAppear。不适用于 widget 滚入视口（visibility_detector）与本库自身的审计/发版。
---

# fl_page_lifecycle 接入指导

**本 skill 对应 fl_page_lifecycle 0.0.3**，只写这一版的用法，不含任何历史版本的旧名与旧行为。

## 第 0 步：先确认项目装了这个包，以及版本

```bash
grep -n -A1 "fl_page_lifecycle" pubspec.yaml
```

**查到 0.0.3** → 往下走。**版本更低** → 停下来问用户要不要升上来，别按本 skill 写代码（`FlPageIndexScope`、`FlRouteObserverProxy`、`ValueListenable<int>` 在低版本里不存在）。**版本更高** → 以库自带的 `CHANGELOG.md` 和源码为准，并告诉用户本 skill 哪些结论可能过期。**完全没查到** → 停下来问用户，不要自作主张装依赖，也不要直接按本 skill 写代码（写出来的 import 根本解析不了）。问的时候说清这个需求用本库能少踩哪些坑，并给出 `flutter pub add fl_page_lifecycle`。

**用户说不装 → 本 skill 到此为止**，改用 Flutter 原生方案（`RouteAware` + `RouteObserver` / `didChangeAppLifecycleState`），并如实说明局限、别粉饰：前者分不出弹窗覆盖、`pushAndRemoveUntil` 会给被盖住的页面误发事件、start/stop 配对要自己保证；后者会把来电和下拉通知栏当成「回到前台」。逐条对照见 `references/pitfalls.md` 末尾「选型」。

本库回答的是**导航层面**的问题：「用户此刻在不在这个页面上」，不回答几何问题（widget 有没有滚进视口，那是 `visibility_detector`）。回调**配对且幂等**：每个 `start` 必有 `stop`，每个 `pause` 必有 `resume` 或 `stop`，缺的那半在 `dispose` 补发——成对写就是安全的，不用操心页面是怎么走的。

## 第 1 步：注册路由观察者

根 `Navigator` 用单例，**每个嵌套 `Navigator` 各用一个新的 `FlRouteObserverProxy()`**：

```dart
MaterialApp(navigatorObservers: [FlRouteObserver()], home: const HomePage())

ShellRoute(observers: [FlRouteObserverProxy()], builder: ...)          // go_router
Navigator(observers: [FlRouteObserverProxy()], onGenerateRoute: ...)   // 手写的 tab 内独立栈
```

**不能把同一个 observer 实例挂到两个 `Navigator` 上**——Flutter 的 `Navigator.initState` 里有 `assert(observer.navigator == null)`。`FlRouteObserver` 是单例，所以嵌套的必须各 new 一个 proxy；proxy 无状态，四个路由事件都转发进同一张订阅表，页面侧不用改代码。

不注册**不抛异常**，只是静默失效。先读项目的路由配置再决定加在哪，别默认只加在 `MaterialApp` 上。诊断：动画回调有、可见性回调没有 = 没注册。

## 选哪个入口

| 页面形态 | 用 |
|---|---|
| 普通路由页 | `FlPageLifecycleMixin`（默认选择） |
| `PageView` / `TabBarView` / `IndexedStack` 子页 | `FlPageIndexScope` 包裹 + 子页 `observePageIndex => true`（缺一不可） |
| `StatelessWidget` / 不想加 mixin / 只观测某个子树 | `FlPageLifecycleView` |
| 逻辑在 Controller、ViewModel | `FlPageControllerMixin` + 页面转发（它自己不订阅任何东西） |
| 只要 App 前后台 | `FlAppLifecycleMixin` |
| 只要转场动画 | `FlAnimationLifecycleMixin` |
| 只要路由事件 | `FlPageRouteMixin`（回调是 `onRoute*` 不是 `onPage*`） |

**不能叠加**：后四个和 `FlPageLifecycleMixin` 订阅同一批源、成员名还会撞，叠了会让一个状态机完全不跑。要复用逻辑就叠自己的 mixin：

```dart
mixin MyTrackMixin<T extends StatefulWidget> on State<T>, FlPageLifecycleMixin<T> { }
```

（`FlStateEventBusMixin` 例外，和生命周期无关，可一起混入。）

## 最关键的判断：resume/pause 还是 start/stop

两对回调只差一处：**dialog / bottomSheet / popupMenu 盖上来时，只发 `pause`，不发 `stop`。** 判断标准一句话：**弹窗盖住页面时，这件事该不该继续？**

| 弹窗期间 | 用 | 场景 |
|---|---|---|
| 该停 | `onPageResume` / `onPagePause` | 视频音频、动画、相机、定位、传感器 |
| 该继续 | `onPageStart` / `onPageStop` | 轮询、WebSocket、曝光埋点与停留时长、倒计时 |

别无脑一律用 `resume/pause`——轮询用它的后果就是「一弹筛选面板刷新就断了」。需求描述里通常已写明期望，照描述选。两对可以同时用（埋点走 start/stop、播放器走 resume/pause），是独立的两层。滚动容器的子页还要注意：start/stop 要等翻页**停稳**才发（见下），需要「划走瞬间就静音」的别只靠它。

## 基本写法

```dart
class _DetailPageState extends State<DetailPage> with FlPageLifecycleMixin {
  @override
  void onPageResume() => _player.play();

  @override
  void onPagePause() => _player.pause();
}
```

两个开关重写成 getter，取值**必须整个生命周期恒定**（跟着 state 变会触发 debug assert，release 下状态机会卡在中间态；写字面常量最保险）：`observePageIndex`（默认 `false`，本页是按页码切换的容器的子页时开）、`observeAppLifecycle`（默认 `false`，需要五个 App 级事件时开，每实例多两条全局流订阅）。

状态随时可读，无需订阅：**判可见用 `isPageAppeared`**（不要用 `isCurrent`，dialog 一盖它就 false）、判可交互用 `isPageResumed`、判 App 在不在前台用 `isForeground`。

## 事件时序

```
push 进来        onPageInit → onPageContextReady → onPagePostFrame
                 → onPageStart → onPageResume → onPageEnterAnimationEnd
被路由覆盖        onPagePause → onPageStop  ...  onPageStart → onPageResume
被 dialog 覆盖    onPagePause               ...  onPageResume        （不 stop）
自己被 pop       onPageLeaveAnimationStart → onPagePause → onPageStop
                 → onPageLeaveAnimationEnd → onPageDispose
iOS 侧滑放弃     onPageLeaveAnimationStart → onPageEnterAnimationStart
                 → onPageEnterAnimationEnd            （不 pause，不 stop）
```

- 重写 `onLifecycleStateChanged` 必须调 `super`；重写 `appLifecycleChanged` **也必须**（它是三个原始 App 事件的分发器）。
- `onPageLeaveAnimationStart` 不代表页面会离开（侧滑放弃会反转）。不可逆的事放 `onPageLeaveAnimationEnd` 或 `onPageDispose`。
- `onPageDispose` 里 `routeName` 已是 `null`，要用路由信息在 `onPageStop` 读。
- 其余时序细节（首帧、入场动画不保证触发）见 `references/api.md`。

## 页码作用域：PageView / TabBarView / IndexedStack

```dart
PageView(
  controller: _controller,
  children: FlPageIndexScope.wrapChildren(   // 第 1 步：注入页码
    controller: _controller,
    children: const [FeedTab(), ProfileTab()],
  ),
)

class _FeedTabState extends State<FeedTab> with FlPageLifecycleMixin {
  @override
  bool get observePageIndex => true;         // 第 2 步：否则首帧就 start
}
```

只包不开 → 首帧全部 start，等于没懒加载；只开不包 → 可见性永远不变。**嵌套时每一层容器都要包**——只包外层不报错，本页会静默绑到外层 Scope 上，切内层子页收不到 start/stop（`PageView` / `TabBarView` 漏包时 debug 会提示一次，**`IndexedStack` 漏包没有任何提示**）。

`controller` 收三种：`PageController`、`TabController`、`ValueListenable<int>`（`IndexedStack` 这类非滚动容器用一个 `ValueNotifier<int>` 同时驱动 `IndexedStack.index` 和 Scope，子页不需要 `AutomaticKeepAliveClientMixin`）。构造函数**不是 const**。

**提交时机**：滚动容器（`PageView` / `TabBarView`）**停稳才提交**——`animateToPage(0→4)` 掠过的中间页、拖过半页又拖回来的放弃动作一个事件都不发（消除假曝光），`jumpToPage` 当场提交，代价是 start/stop 比「滑过半页」晚约一次回弹动画；`ValueListenable<int>` 驱动的容器**当场提交**，不设门禁也不绑 `ScrollPosition`。完整规则见 `references/sc-index.md`。

## 按需去读哪个文件

正文到此够应付大部分改动。下面按需读，**一次只读一个**（每个 4–9KB，别整批读）：

| 要做的事 | 读 `references/` 下的 |
|---|---|
| 视频音频、曝光与停留时长埋点、轮询/WebSocket、App 前后台 | `sc-page.md` |
| 页码容器：懒加载、嵌套容器、`onPageIndexChanged`、`IndexedStack` | `sc-index.md` |
| 注册位置（go_router / auto_route / 嵌套 `Navigator`）、`popUntil` / `pushAndRemoveUntil`、转场动画、tab 内独立路由栈 | `sc-route.md` |
| 事件总线、只观测子树、Controller/ViewModel、全项目统一埋点、回调里 `setState` 报错 | `sc-arch.md` |
| 查签名：枚举、主 mixin、`FlPageIndexScope`、`FlPageLifecycleView` | `api.md` |
| 查其余类型的签名，或 assert / debug 提示原文 | `api-more.md` |
| 脚本没定位出来的行为异常（有症状速查表） | `pitfalls.md` |

这是个新包，不在你的训练数据里——`PageLifecycleMixin`、`onPageShow`/`onPageHide`、`onPageVisible`、`pauseOnOverlay:` 这类全是编造的，真名一律以 `Fl` 开头。拿不准就查 `api.md`，别凭印象拼。

## 排错与交付前自检

**回调不触发、行为不对，先跑脚本，不要先翻文档。** 它一遍查两类问题：编造的 API 名，以及十几种「编译得过、`analyze` 也不报、但回调静默不来」的接错方式（漏注册、observer 实例复用、Scope 只做一半、开关非常量、漏 `super`、`observeEvent` 位置、全局销毁、叠加入口 mixin、Controller 没转发或签名错、旧名残留…），每条直接给出原因、改法和对应文档位置。

```bash
python3 scripts/verify_api_names.py <改动涉及的目录>       # 名字 + 高频误用，只需 Python
python3 scripts/verify_api_names.py --only-diagnose lib/   # 只排错
flutter analyze                                            # 期望 0 error 0 warning
```

`❌` 是本地可判定的确定错误，`⚠️` 取决于扫描范围（比如注册写在别的目录），要再确认一眼。一次传整个目录（只传单文件会误报项目自己的类）。跑不了 Flutter 环境时至少跑脚本，并说明 `analyze` 没跑。脚本查不到的（参数顺序、类型）靠 `analyze`；它也定位不了的，再按上表读 `pitfalls.md`。

交代改动时说清：改了哪些文件、每个回调里放了什么、观察者注册在哪（嵌套栈是否覆盖到）、resume/pause 与 start/stop 按什么选的。

对照清单：

- [ ] 确认过 `pubspec.yaml` 里有 `fl_page_lifecycle` 0.0.3（没有或版本不符则已问过用户）
- [ ] 根挂 `FlRouteObserver()`，**每个嵌套 `Navigator` 各挂一个新的 `FlRouteObserverProxy()`**（不能复用实例）
- [ ] 判可见性用 `isPageAppeared` 而非 `isCurrent`；起停成对，且按「弹窗期间该不该继续」选的那对
- [ ] 没叠加库里的多个入口 mixin；两个开关取值恒定；重写 `onLifecycleStateChanged` / `appLifecycleChanged` 都调了 `super`
- [ ] `observeEvent<T>` 只在 `initState` 调一次；没在页面级清理里调 `FlGlobalEventBus.destroy()` / `FlLifecycleManager.cancel()`（全局，会连坐所有页面）
- [ ] `await` 后碰 `context` / `setState` 前查了 `mounted`
- [ ] 页码容器场景：每层容器都包了 Scope；知道滚动容器的事件要等停稳才发
- [ ] 脚本跑过，无编造标识符
