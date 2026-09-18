# fl_page_provider

页面级控制器：随页面创建、随页面释放，直接收页面与 App 生命周期回调，通知哪个 ID 就只重建认领了那个 ID 的 Widget。

[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[English](README.md) | 中文

---

## 目录

- [为什么需要它](#为什么需要它)
- [核心能力](#核心能力)
- [适用场景](#适用场景)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速开始](#快速开始)
- [用法](#用法)
  - [1. 定义控制器](#1-定义控制器)
  - [2. 把它挂到页面上](#2-把它挂到页面上)
  - [3. 只重建变了的那一块](#3-只重建变了的那一块)
  - [4. 两个读取入口](#4-两个读取入口)
  - [5. 页面与 App 生命周期](#5-页面与-app-生命周期)
  - [6. PageView / TabBarView 里的子页](#6-pageview--tabbarview-里的子页)
- [API 速查](#api-速查)
- [第三方依赖](#第三方依赖)
- [注意事项](#注意事项)
- [示例工程](#示例工程)
- [版本、贡献与许可](#版本贡献与许可)

---

## 为什么需要它

一个有自己状态的页面，通常要手接四件事：创建控制器、页面销毁时释放它、知道页面什么时候可见与不可见、
某个字段变了只刷新一小块 UI。自己写就是一对 `initState` / `dispose`、一份 `RouteAware` 订阅，
再加上 `setState`（整页重建）或者给每个字段手搓一个 `ValueNotifier`。

这个包把四件事收进一个类：

```dart
class ProfilePage extends FlBasePage<ProfileController> {
  const ProfilePage({super.key});

  @override
  ProfileController createController(BuildContext context) => ProfileController();

  @override
  Widget buildWithController(BuildContext context, ProfileController controller) => Scaffold(...);
}
```

控制器在首次 build 时创建，子树移除时释放，用户导航时会收到
`onPageStart` / `onPageResume` / `onPagePause` / `onPageStop`。它调用
`notifySingleListener(ProfileId.avatar)` 时，只有认领了 `ProfileId.avatar` 的 Widget 会重建，
页面上其余部分纹丝不动。

重建引擎是**逐 ID** 比对版本号而不是合并成哈希，所以两个 ID 一增一减不可能抵消成「什么都没变」
而吞掉一次重建。在 `build` 期间发出的通知会被推迟到本帧收尾之后兑现，而不是抛
`setState() or markNeedsBuild() called during build`。

## 核心能力

- 控制器的生命周期绑定页面子树——只创建一次，自动释放。
- 页面生命周期（`onPageStart`、`onPageResume`、`onPagePause`、`onPageStop`、进出场动画钩子、
  `onPageDispose`）直接回调到控制器上；App 前后台回调按页面单独开启。
- ID 粒度重建：`notifySingleListener(id)` 只重建认领了该 ID 的 Widget。
- 取控制器只有两个入口，不用挑：调方法用 `context.rc`（不建立依赖），显示数据用
  `FlSelector` / `FlSelectorView`（只在所列 ID 被通知时重建）。后者的 `child` 参数
  可以把子树里不变的部分摘出重建范围。
- `PageView` / `TabBarView` / `IndexedStack` 里的子页有正确行为——可见性由页码驱动，而非路由。
- 控制器自带进程内事件总线（`observeEvent` / `dispatchEvent`），订阅在 dispose 时自动取消。
- 对那些本来会静默失败的误用配了 debug 断言：未注册的 ID、空 `ids`、同一个控制器实例交给两个 provider。

## 适用场景

| 处境 | 这个包怎么帮上忙 |
|---|---|
| 页面被别的路由盖住时暂停视频或轮询 | 控制器上的 `onPagePause` / `onPageResume` |
| 从详情页返回后刷新列表 | `onPageResume`，或者由详情页派发一个事件 |
| AppBar 上的计数器不该带着整页重建 | `FlSelector` 只认领计数器关心的那个 ID |
| App 退到后台时断开 WebSocket | `observeAppLifecycle = true` 配 `onAppBackground` |
| 还没显示的 Tab 先不初始化 | `observePageIndex = true` 配 `FlPageIndexScope` |
| 登录 / 退出登录广播给所有已打开的页面 | 一个控制器 `dispatchEvent`，其余控制器 `observeEvent` |

## 环境要求

| 项 | 要求 |
|---|---|
| Dart SDK | `^3.11.5` |
| Flutter | `>=3.41.9` |
| 平台 | Flutter 支持的全部平台——未使用任何平台特定实现 |

没有 `flutter.plugin` 段，`lib/` 下也没有任何 `dart:io` / `dart:ffi` / `dart:html` /
`MethodChannel` / `Platform.is`。

## 安装

```yaml
dependencies:
  fl_page_provider: ^0.0.1
```

或者直接依赖本地检出：

```yaml
dependencies:
  fl_page_provider:
    path: ../fl_page_provider
```

```bash
flutter pub get
```

## 快速开始

`FlRouteObserver` 必须注册到 navigator 上。漏了它，页面生命周期回调一个都不会来——
控制器照样创建、UI 照样渲染，所以症状是「我的 `onPageResume` 不执行」而不是报错。

```dart
import 'package:fl_page_provider/fl_page_provider.dart';
import 'package:flutter/material.dart';

enum CounterId { count }

class CounterController extends FlBaseController<CounterId> {
  @override
  List<CounterId> get shouldNotifyIds => CounterId.values;

  int _count = 0;
  int get count => _count;

  void increase() {
    _count++;
    notifySingleListener(CounterId.count);
  }
}

class CounterPage extends FlBasePage<CounterController> {
  const CounterPage({super.key});

  @override
  CounterController createController(BuildContext context) => CounterController();

  @override
  Widget buildWithController(BuildContext context, CounterController controller) {
    return Scaffold(
      appBar: AppBar(title: const Text('Counter')),
      body: Center(
        child: FlSelector<CounterId, CounterController>(
          ids: const [CounterId.count],
          builder: (context, c, child) => Text('${c.count}'),
        ),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: controller.increase,
        child: const Icon(Icons.add),
      ),
    );
  }
}

void main() {
  runApp(MaterialApp(
    home: const CounterPage(),
    navigatorObservers: [FlRouteObserver()], // 必须
  ));
}
```

## 用法

### 1. 定义控制器

**什么时候用**：任何有自己状态、要发请求、或者需要知道自己可不可见的页面。

继承 `FlBaseController<E>`，`E` 是一个枚举，列出这个页面会通知哪些东西。把这些 ID 写进
`shouldNotifyIds`，页面初始化时会自动注册。

```dart
import 'package:fl_page_provider/fl_page_provider.dart';

enum ProfileId { avatar, nickname, followers }

class ProfileController extends FlBaseController<ProfileId> {
  @override
  List<ProfileId> get shouldNotifyIds => ProfileId.values;

  String _nickname = '';
  int _followers = 0;

  String get nickname => _nickname;
  int get followers => _followers;

  void rename(String value) {
    _nickname = value;
    notifySingleListener(ProfileId.nickname); // 单个 ID
  }

  void applyRemote(String name, int count) {
    _nickname = name;
    _followers = count;
    notifyMultiListeners([ProfileId.nickname, ProfileId.followers]); // 一次推进多个
  }
}
```

`notifySingleListener`、`notifyMultiListeners`、`registerIds` 都是 `@protected` 的：
在控制器内部调用，不要从 Widget 里调。

**跨页面事件。** 所有控制器共用一条进程内总线。在 `onPageInit` 里订阅，控制器 dispose 时订阅自动取消。

```dart
class FeedController extends FlBaseController<FeedId> {
  @override
  List<FeedId> get shouldNotifyIds => FeedId.values;

  @override
  void onPageInit() {
    super.onPageInit(); // 必须调
    observeEvent<LoginEvent>(_onLogin);
  }

  void _onLogin(LoginEvent event) => notifySingleListener(FeedId.list);

  void logout() => dispatchEvent(const LogoutEvent());
}
```

传方法引用，不要现写闭包：重复订阅的拦截是按回调身份比对的，而闭包字面量每次都是新对象。

### 2. 把它挂到页面上

**什么时候用**：按页面实际需要挑，不按个人偏好挑。

| 承载方式 | 什么时候用它 |
|---|---|
| `FlBasePage<T>` | 普通页面，不需要 `State` |
| `FlBasePageState<S, T>` | 需要 `TickerProvider`、`GlobalKey`、保活，或者页面自己还有局部 UI 状态 |
| `FlProviderBuilder<T>` | 控制器只作用于子树的一部分，而不是整个页面 |

无状态那种[快速开始](#快速开始)里已经写过了。有状态的照例拆成两个类：

```dart
class EditorPage extends StatefulWidget {
  const EditorPage({super.key});

  @override
  State<EditorPage> createState() => _EditorPageState();
}

class _EditorPageState extends FlBasePageState<EditorPage, ProfileController> {
  @override
  bool get wantKeepAlive => true;

  @override
  ProfileController createController(BuildContext context) => ProfileController();

  @override
  Widget buildWithController(BuildContext context, ProfileController controller) {
    return Scaffold(body: Text(controller.nickname));
  }
}
```

`FlProviderBuilder` 是同一套机制，只是不带页面基类：

```dart
FlProviderBuilder<ProfileController>(
  create: (context) => ProfileController(),
  builder: (context, controller) => Text(controller.nickname),
)
```

**参数 —— `FlProviderBuilder`**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `create` | `T Function(BuildContext)` | required | 只调用一次，返回的实例随子树销毁而 dispose |
| `builder` | `Widget Function(BuildContext, T)` | required | 页面 UI，直接拿到控制器 |
| `observePageIndex` | `bool` | `false` | 由页码而非路由驱动可见性判定 |
| `observeAppLifecycle` | `bool` | `false` | 是否也转发 App 前后台事件 |
| `key` | `Key?` | `null` | 标准 widget key |

**`FlBasePage` / `FlBasePageState` / `FlPageMixin` 上可覆写的成员**

| 成员 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `createController` | `T Function(BuildContext)` | required | 创建控制器 |
| `buildWithController` | `Widget Function(BuildContext, T)` | required | 页面 UI |
| `observePageIndex` | `bool` | `false` | 见[第 6 节](#6-pageview--tabbarview-里的子页) |
| `observeAppLifecycle` | `bool` | `false` | 见[第 5 节](#5-页面与-app-生命周期) |
| `wantKeepAlive` | `bool` | `false` | 仅 `FlBasePageState`——在 pager 里保活 |

### 3. 只重建变了的那一块

**什么时候用**：页面上某一小块变得很频繁，整页重建太浪费——角标计数、点赞按钮、进度条。

`FlSelector` 只依赖你列出的 ID，别的一概不管：

```dart
FlSelector<ProfileId, ProfileController>(
  ids: const [ProfileId.followers],
  builder: (context, controller, child) => Row(
    children: [if (child != null) child, Text('${controller.followers}')],
  ),
  child: const Icon(Icons.people), // 只构建一次，之后原样交还
)
```

**参数 —— `FlSelector`**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `ids` | `List<E>` | required | 依赖的 ID，不能为空 |
| `builder` | `FlSelectorBuilder<E, T>` | required | `(context, controller, child) => Widget` |
| `child` | `Widget?` | `null` | 不参与重建的静态子树 |
| `key` | `Key?` | `null` | 标准 widget key |

这一块值得独立成类时，改成继承 `FlSelectorView`：

```dart
class FollowerCount extends FlSelectorView<ProfileId, ProfileController> {
  const FollowerCount({super.key});

  @override
  List<ProfileId> get observeIds => const [ProfileId.followers];

  @override
  Widget? get staticChild => const Icon(Icons.people); // 必须每次都返回同一个实例

  @override
  Widget buildWidget(BuildContext context, ProfileController controller, Widget? child) {
    return Row(children: [if (child != null) child, Text('${controller.followers}')]);
  }
}
```

### 4. 两个读取入口

**什么时候用**：每次要从 Widget 里拿控制器的时候。只有两个入口，按「要不要跟着数据重建」分：

| 入口 | 建立依赖 | 何时重建 |
|---|---|---|
| `context.rc<T>()` | 否 | 从不 |
| `FlSelector` / `FlSelectorView` | 是 | 仅所列 ID 被通知时 |

```dart
// 回调里——只是想调个方法，不需要重建。
onPressed: () => context.rc<ProfileController>().rename('new name'),

// 要显示数据——包一层 FlSelector，只认这两个 ID。
FlSelector<ProfileId, ProfileController>(
  ids: const [ProfileId.nickname, ProfileId.avatar],
  builder: (context, c, _) => Text(c.nickname),
)
```

`rc` 是 *read controller* 的缩写。它刻意避开了 `read` 这个名字——`provider` 包已经在
`BuildContext` 上占用了 `read` / `watch`，避开之后两个包可以同时导入，既不用 `hide`
也不用加导入前缀。

**没有「每次通知都重建」那一档。** ID 粒度是本库唯一的通知语义。确实需要「任何变更都刷新
这一块」时，专门留一个 ID，每次通知都把它一起列进 `notifyMultiListeners`：

```dart
enum ProfileId { all, nickname, avatar }

// 控制器侧
notifyMultiListeners(const [ProfileId.all, ProfileId.nickname]);

// 调用方侧
FlSelector<ProfileId, ProfileController>(
  ids: const [ProfileId.all],
  builder: (context, c, _) => Text(c.nickname),
)
```

这样「谁会因为什么而重建」始终写在调用点上，不必回控制器里翻。

**按 ID 订阅只经 Widget 提供，没有 `BuildContext` 上的写法。** 依赖登记在**发起订阅的那个
Element** 上：写在页面 `build` 里就是整页跟着一个 ID 抖；而 Flutter 只在
`Element.deactivate()` 时解除依赖登记、重建时从不清理，放进条件分支还会留下永久白重建的
尾巴。`FlSelector` 自己就是一层 Widget，两个问题一起没有——重建边界就是它，条件不成立时
它整个卸载、依赖随之解除。所以**把 `FlSelector` 放进 `if` 分支是安全写法**，不是坑。

### 5. 页面与 App 生命周期

**什么时候用**：页面可见时开始干活、不可见时停下来——轮询、视频播放、动画、埋点停留时长。

在控制器上覆写钩子，第一行先调 `super`。

```dart
enum VideoId { playing }

class VideoController extends FlBaseController<VideoId> {
  @override
  List<VideoId> get shouldNotifyIds => VideoId.values;

  bool _playing = false;
  bool get isPlaying => _playing;

  @override
  void onPageResume() {
    super.onPageResume();
    _playing = true; // 页面可见且可交互
  }

  @override
  void onPagePause() {
    super.onPagePause();
    _playing = false; // 被别的路由盖住，或者 App 退到后台
  }

  @override
  void onAppBackground() {
    super.onAppBackground(); // 需要页面上 observeAppLifecycle = true
  }
}
```

控制器上可用的钩子：`onPageInit`、`onPageContextReady`、`onPagePostFrame`、`onPageReassemble`、
`onPageStart`、`onPageResume`、`onPageEnterAnimationStart`、`onPageEnterAnimationEnd`、
`onPagePause`、`onPageStop`、`onPageLeaveAnimationStart`、`onPageLeaveAnimationEnd`、
`onPageDispose`、`onAppResume`、`onAppInactive`、`onAppPause`、`onAppForeground`、
`onAppBackground`、`onPageIndexChanged`。

App 级别的钩子要页面主动开启才会来：

```dart
class VideoPage extends FlBasePage<VideoController> {
  const VideoPage({super.key});

  @override
  bool get observeAppLifecycle => true;

  @override
  VideoController createController(BuildContext context) => VideoController();

  @override
  Widget buildWithController(BuildContext context, VideoController controller) =>
      const Scaffold();
}
```

控制器上还有几个只读状态可以取：`lifecycleState`、`isPageResume`、`isPagePause`、`isForeground`、
`routeName`、`arguments`。

### 6. PageView / TabBarView 里的子页

**什么时候用**：页面是 `PageView`、`TabBarView` 或 `IndexedStack` 的一个子项。这些子项不是独立路由，
按路由判可见性分不出哪一个在屏幕上，可见性必须改由页码来定。

两半都要做。子页这边打开 `observePageIndex`：

```dart
class _TabOneState extends FlBasePageState<TabOne, TabOneController> {
  @override
  bool get observePageIndex => true;

  @override
  bool get wantKeepAlive => true;

  @override
  TabOneController createController(BuildContext context) => TabOneController();

  @override
  Widget buildWithController(BuildContext context, TabOneController controller) =>
      const Scaffold();
}
```

宿主这边用 `FlPageIndexScope` 包住子页：

```dart
TabBarView(
  children: FlPageIndexScope.wrapChildren(
    controller: DefaultTabController.of(context),
    children: const [TabOne(), TabTwo()],
  ),
)
```

懒构建的 pager 改用 `wrapItemBuilder`：

```dart
PageView.builder(
  controller: pageController,
  itemCount: 4,
  itemBuilder: FlPageIndexScope.wrapItemBuilder(
    controller: pageController,
    builder: (context, index) => TabOne(),
  ),
)
```

两个辅助方法收的都是 `Listenable`，所以 `TabController` 和 `PageController` 都能传。
只开了 `observePageIndex` 却没包宿主不会报错——那个页面会被当成普通页面：首帧即可见，
而且收不到任何切页回调。

## API 速查

`package:fl_page_provider/fl_page_provider.dart` 导出的全部内容。

| 名称 | 类型 | 作用 | 详见 |
|---|---|---|---|
| `FlBaseController<T extends Enum>` | abstract class | 控制器基类：生命周期 + ID 通知 + 事件总线 | [1](#1-定义控制器) |
| `FlBasePage<T>` | abstract class | 无状态页面基类 | [2](#2-把它挂到页面上) |
| `FlBasePageState<S, T>` | abstract class | 有状态页面基类，支持保活 | [2](#2-把它挂到页面上) |
| `FlPageMixin<T>` | mixin | `createController` / `buildWithController` 契约，供自定义承载方 | [2](#2-把它挂到页面上) |
| `FlProviderBuilder<T>` | class | 创建、托管控制器并注入子树 | [2](#2-把它挂到页面上) |
| `FlSelector<E, T>` | class | 只在所列 ID 变化时重建 | [3](#3-只重建变了的那一块) |
| `FlSelectorBuilder<E, T>` | typedef | `FlSelector.builder` 的签名 | [3](#3-只重建变了的那一块) |
| `FlSelectorView<E, T>` | abstract class | `FlSelector` 的类形式，供继承 | [3](#3-只重建变了的那一块) |
| `FlControllerContextExtension` | extension | `context.rc` | [4](#4-两个读取入口) |

导入本包的同时也会拿到 `fl_page_lifecycle` 的全部内容——`FlRouteObserver`、`FlPageIndexScope`、
`FlLifecycleState`、`FlPageLifecycleView`、`FlGlobalEventBus` 等等——不需要在自己的
`dependencies` 里再加那个包。

## 第三方依赖

| 依赖 | 版本约束 | 做什么用 | 本包用在哪 |
|---|---|---|---|
| `fl_page_lifecycle` | `^0.0.3` | 页面与 App 生命周期检测、路由观察者、页码可见性、全局事件总线 | `lib/src/controller/fl_base_controller.dart`、`lib/src/widget/fl_provider_builder.dart`、`lib/src/controller/fl_event_bus_mixin.dart` |
| `meta` | `^1.17.0` | 提供 `@internal` 注解，用来把实现类型挡在公开 API 之外 | `lib/src/provider/fl_page_provider.dart`、`lib/src/provider/fl_id_versions.dart` |

`fl_page_lifecycle` 在包入口处被整体再导出，所以它的 API 也构成本包公开面的一部分。

## 注意事项

**记得注册 `FlRouteObserver`。** 挂到 `MaterialApp.navigatorObservers`（或你自己的 `Navigator`
的 `observers`）。漏了它页面照常渲染、也不报错，但页面生命周期回调一个都不会来。

**通知的每个 ID 都必须在 `shouldNotifyIds` 里。** 未注册的 ID 版本号恒为 `0`，比对永远得出
「没变」，依赖方一次都不会重建。debug 下有断言拦，release 下静默失败。

**`ids` 不能是空列表。** `const []` 看着像「不限定 ID」，实际是「一个 ID 都不关心」，
于是这个 Widget 永远不会重建。想跟着控制器全量刷新，请专门留一个 ID 并在每次通知时把它
一起列进来。debug 下有断言。

**`create` 交出的是所有权。** 它返回的实例会在子树销毁时被 dispose。返回一个共享单例意味着
第一个关闭的页面就把它 dispose 了，其余子树静默冻结且不报错。一个 `create` 对应一个新实例。
debug 下有断言。

**覆写时一律记得调 `super`。** 控制器钩子这边，`onPageInit` 负责注册你的 ID，`onPageReassemble`
负责在热重载后重新注册。`FlBasePageState` 这边，只要覆写了 `build` 就必须调
`super.build(context)`——那是 `AutomaticKeepAliveClientMixin` 的要求，漏了保活就失效。
页面 UI 写在 `buildWithController` 里即可，通常没必要覆写 `build`。

**事件只在 `onPageInit` 里订阅一次。** `observeEvent` 不会解除已有订阅。写在 `build` 或
`onPageResume` 这类会重复执行的地方，订阅数会随重建次数线性增长，症状通常是埋点重复上报或
接口重复请求。传方法引用，重复订阅的拦截才认得出来。

**`observePageIndex` 两半都要做。** 只在页面上打开、不在宿主侧用 `FlPageIndexScope` 包裹，
是静默无效的——见[第 6 节](#6-pageview--tabbarview-里的子页)。

