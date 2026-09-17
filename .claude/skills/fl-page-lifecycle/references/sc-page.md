# 场景：页面级资源起停

[1 视频/音频](#1-视频--音频播放器) · [2 埋点](#2-曝光与停留时长埋点) · [3 轮询/WebSocket](#3-轮询--websocket) · [7 App 前后台](#7-app-前后台)

节号在四个 `sc-*.md` 里全局唯一。前提：路由观察者已注册（见 `sc-route.md` 第 9 节）。代码多抄自库自带 `example/`，签名一定对得上源码。

---

## 1. 视频 / 音频播放器

**`onPageResume` / `onPagePause`**：dialog 盖住时只发 `pause`，正是「弹窗弹出来视频就该停」的时机。用 start/stop 的话弹窗期间声音还在响。

```dart
class _VideoPageState extends State<VideoPage> with FlPageLifecycleMixin {
  late final VideoPlayerController _player;
  bool _wantsToPlay = true;   // 用户手动暂停过就置 false，回来不强行续播

  @override
  void initState() {
    super.initState();
    _player = VideoPlayerController.networkUrl(Uri.parse(widget.url))
      ..initialize().then((_) {
        if (!mounted) return;
        setState(() {});
        if (isPageResumed && _wantsToPlay) _player.play();  // 初始化可能晚于 resume
      });
  }

  @override
  void onPageResume() {
    if (_wantsToPlay) _player.play();
  }

  @override
  void onPagePause() {
    if (_player.value.isInitialized) _wantsToPlay = _player.value.isPlaying;
    _player.pause();
  }

  @override
  void dispose() {
    _player.dispose();     // 自己的资源；路由订阅由 mixin 处理
    super.dispose();
  }
}
```

`_wantsToPlay` 只在用户手动操作和 `onPagePause` 里改写，且要等 `isInitialized` 之后——否则「还在加载时用户就离开」会被误判成「用户不想播」。

不用开 `observeAppLifecycle`：切后台时 `onPagePause` 同样会走到。只有要区分「被别的页面覆盖」和「整个 App 进后台」（比如后台继续播音频）才需要它。

**信息流里多个视频卡片自动播**：本库负责「Feed 页是否 resumed」，`visibility_detector` 负责「哪张卡在屏上」。两个一起用；只用后者会在用户已跳走的页面上继续播。

---

## 2. 曝光与停留时长埋点

**`onPageStart` / `onPageStop`**：dialog 弹出不算离开页面，不该这时结算时长。

start 与 stop 严格配对且幂等，缺的那半在 `dispose` 补发，所以不存在「页面在 pause 状态被销毁，时长丢了」的漏埋。

```dart
class _ArticlePageState extends State<ArticlePage> with FlPageLifecycleMixin {
  DateTime? _enterAt;
  String _pageId = 'unknown';

  @override
  void onPageContextReady(String? routeName, Object? arguments) {
    _pageId = routeName ?? 'unknown';   // 路由参数这时才可用
  }

  @override
  void onPageStart() {
    _enterAt = DateTime.now();
    Analytics.pageView(_pageId, args: arguments);
  }

  @override
  void onPageStop() {
    final at = _enterAt;
    if (at == null) return;
    _enterAt = null;
    // routeName 在 onPageStop 里还能读，到 onPageDispose 就是 null 了
    Analytics.pageDuration(_pageId, DateTime.now().difference(at));
  }
}
```

要把切后台的时间刨掉：开 `observeAppLifecycle => true`，`onAppBackground` 结算一段、`onAppForeground` 重新计时，累加即真实停留。

`popUntil` 会让被跨过的中间层各闪一对 start/stop（见 `sc-route.md` 第 6 节），可能多记几条曝光——用停留时长阈值过滤极短记录即可。

全项目统一埋点（不逐页重写）见 `sc-arch.md` 第 13 节。

---

## 3. 轮询 / WebSocket

**`onPageStart` / `onPageStop`**，再开 `observeAppLifecycle` 挡住切后台。

为什么不是 resume/pause：用户开个筛选 bottomSheet、点个确认 dialog，页面并没有离开，这时轮询该继续，回来看到的才是新数据。resume/pause 会在弹窗弹出瞬间断掉刷新——很常见的线上问题。轮询的成本是后台默默花点流量，不是用户看得见听得见的东西。

两层都要：路由事件管「跳去了别的页面」，App 事件管「整个 App 进后台」。只做前者，后台时定时器还在烧电。

```dart
class _DashboardPageState extends State<DashboardPage> with FlPageLifecycleMixin {
  Timer? _timer;

  @override
  bool get observeAppLifecycle => true;   // 取值必须整个生命周期恒定

  void _start() {
    _timer?.cancel();                     // 幂等：先取消再建，避免重复定时器
    _timer = Timer.periodic(const Duration(seconds: 10), (_) => _fetch());
    _fetch();
  }

  void _stop() {
    _timer?.cancel();
    _timer = null;
  }

  @override
  void onPageStart() => _start();         // 弹窗盖上来不会走到这里

  @override
  void onPageStop() => _stop();

  @override
  void onAppBackground() => _stop();

  @override
  void onAppForeground() {
    if (isPageAppeared) _start();         // 用户可能是在别的页面切出去的
  }

  Future<void> _fetch() async {
    final data = await api.load();
    if (!mounted) return;                 // await 之后必查 mounted
    setState(() => _data = data);
  }
}
```

WebSocket 同理。重连代价高的话两对回调都用、分两级：`onPagePause` 只停 UI 侧消费，`onPageStop` 才真断连——`pause` 是「可能马上回来」，`stop` 才是「确实离开了」。

---

## 7. App 前后台

出处：`example/lib/src/app_lifecycle_page.dart`

**只要前后台、不关心页面可见性**时用 `FlAppLifecycleMixin`（没有开关，`initState` 就订阅两条流）：

```dart
class _PageState extends State<Page> with FlAppLifecycleMixin {
  @override
  void onAppForeground() {
    super.onAppForeground();
    _refreshIfStale();
  }

  @override
  void onAppBackground() {
    super.onAppBackground();
    _stopWork();
  }
}
```

**页面里顺带要前后台**时别用它（不能和 `FlPageLifecycleMixin` 叠加），改开 `observeAppLifecycle => true`，同样拿到五个 App 事件：

```dart
@override
bool get observeAppLifecycle => true;

@override
void onAppForeground() {
  if (!isPageAppeared) return;                     // 只刷新用户真看得见的页面
  if (DateTime.now().difference(_lastLoad) < const Duration(minutes: 5)) return;
  _load();
}
```

**为什么不用 Flutter 自带的 `didChangeAppLifecycleState`**：来电、下拉通知栏、控制中心这些**瞬时打断**只产生 `inactive`，库把它们过滤掉了。自己写的话用户每划一下通知栏就触发一次刷新，接口会被刷爆。

非页面场景（service 单例）直接订流，自己 cancel 自己的订阅：

```dart
final _sub = FlLifecycleManager.instance.stream.listen((fg) {
  if (fg) syncQueue.flush();
});
// 不要调 FlLifecycleManager.cancel()，那是全局的，会让所有页面都收不到 App 事件
```

冷启动只有**第一个**订阅者会收到那次补发的 `true`，别依赖它做初始化。
