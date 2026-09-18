import 'package:flutter/widgets.dart';
import 'package:meta/meta.dart';

import '../controller/fl_base_controller.dart';
import 'fl_inherited_widget.dart';

/// 把一个 [FlBaseController] 注入子树，并按 **ID 粒度** 精确重建依赖方。
///
/// **包内实现细节。** 使用方请走 `FlProviderBuilder`（或它上面的 `FlBasePage` /
/// `FlBasePageState`）——那一层在本类之外还接好了生命周期转发，直接用本类等于
/// 只铺了一半。取实例调方法走 `context.rc`，按 ID 订阅走 `FlSelector` /
/// `FlSelectorView`。
///
/// 本类只是入口与配置：它把 [create] 交给 [FlInheritedWidget]，控制器的**生死**
/// 由 [FlInheritedElement] 管——造在它自己的首次 `build` 里，销在它的 `unmount`
/// 里，没有第二种所有权。这套分工与 `provider` 一致：`InheritedProvider` 只是
/// 一层 `SingleChildStatelessWidget`，值由 `_InheritedProviderScopeElement`
/// 持有（`inherited_provider.dart`）。
///
/// 注入与重建的机制也在那一层：控制器上只挂一个 listener，通知经
/// `markNeedsBuild()` 折进正常构建流程，再由 [FlInheritedElement.notifyDependent]
/// 逐个依赖方比对版本号决定重不重建。
@internal
class FlPageProvider<T extends FlBaseController> extends StatelessWidget {
  /// 铺一层 provider：控制器由 [FlInheritedElement] 创建并在销毁时 `dispose`。
  ///
  /// 构造函数要单独再标一次 `@internal`：类上的标注拦得住类型位置的引用和
  /// `FlPageProvider.of` 这类静态调用，但拦不住 `FlPageProvider(...)`——分析器
  /// 把它解析成对无名构造函数的引用，而构造函数没被标注就不算越界。
  @internal
  const FlPageProvider({required this.create, required this.child, super.key});

  /// 控制器工厂，在首次 `build` 时调用**一次**，之后父级重建不会再造。
  ///
  /// 具体是在 [FlInheritedElement] 的首次 `build` 里被调用，拿到的 `context`
  /// 就是那个 Element。时机上等价于 `provider` 的 `lazy: false`：控制器在首帧
  /// 就造出来，不等任何人来读。本库不提供 `lazy` 那档开关——控制器背着页面
  /// 生命周期（`onPageInit` 里的 `registerIds`、路由参数、事件总线订阅），懒加载
  /// 意味着「首帧没人读控制器」的页面永远不会初始化。
  ///
  /// ## 里面能做什么
  ///
  /// 与 `provider` 的 `create` 同一套规矩：
  ///
  /// - **可以** `context.rc<X>()` 读**祖先**控制器。它走
  ///   `getElementForInheritedWidgetOfExactType`，不建立依赖，拿到的是活实例。
  ///   X 与本层同类型也没问题：那个查找被
  ///   [FlInheritedElement.getElementForInheritedWidgetOfExactType] 挡到祖先那
  ///   一层去了，不会命中正在创建中的自己。
  /// - **不要**用 `Theme.of(context)` / `MediaQuery.of(context)` 这类**会建立
  ///   依赖**的查找。依赖建得成，但 [create] 只跑这一次，依赖再怎么响也不会让它
  ///   重跑——控制器会静默停在创建那一刻的旧值上。debug 期由
  ///   [FlInheritedElement.dependOnInheritedElement] 的锁拦下，`provider` 用
  ///   `_debugInheritLocked` 做的是同一件事。
  /// - **不要**同步发通知。[create] 早于页面生命周期的 `onPageInit`，那时
  ///   `registerIds` 还没跑，`FlNotifyMixin` 会断言「还没调用过 registerIds」。
  ///   `create: (_) => C()..load()` 这种写法，只要 `load()` 同步走到
  ///   `notifySingleListener` 就会撞上；异步的（第一个 `await` 之后再通知）没事，
  ///   微任务排在整帧之后。顺带一提，那一刻控制器上还没挂 listener（它是
  ///   `create` 返回之后才挂的），所以这种通知即便不断言也一定丢。
  ///
  /// 所以 [create] 里只 new：初始化副作用放控制器的 `onPageInit`，拉数据这类重活
  /// 放 `onPageStart`——`PageView` / `IndexedStack` 里每个被构建出来的子页都会在
  /// 建 widget 那一刻走一遍 [create]，可见与否不影响。
  ///
  /// 所有权是单向的：返回的实例一律由本层释放。让 [create] 返回一个外部持有的
  /// 实例（全局单例之类）意味着它会在这棵子树销毁时被 `dispose` 掉——本库不提供
  /// 「借用不释放」的口子。
  ///
  /// **抛异常只会被调用一次。** 首次异常照常上报（含完整堆栈），之后每次
  /// `build` 直接抛一个说明性的 `StateError`，不会重新执行 [create]——重试对
  /// 确定性的失败没有意义，只会刷屏并重复执行里面的副作用。debug 期热重载会
  /// 清掉这个记录，让改好的 [create] 重新跑一次。
  ///
  /// 抛出来的那一刻本层手上还没有实例，所以**已经 new 出来但没能返回的控制器
  /// 不会被 `dispose`**（`provider` 同样如此）。要么让 [create] 只做 `new`，
  /// 要么自己在里面 try/catch 兜住。
  final T Function(BuildContext context) create;

  /// 被注入的子树。
  final Widget child;

  /// 向上查找最近的 `FlPageProvider<T>` 并返回它持有的控制器。
  ///
  /// - [ids] 为 `null`（默认）时**不建立依赖**：拿到实例调方法用，控制器发通知
  ///   不会重建调用方。等价于 `context.rc<T>()`。
  /// - [ids] 非 `null` 时建立 ID 粒度依赖：只有这几个 ID 被通知时才重建调用方。
  ///
  /// 早先这里是 `bool listen` + `Object? aspect` 两个参数，于是「建立依赖但不
  /// 限定 ID」是写得出来的——那正是已经删掉的全量依赖。收成一个参数之后，那个
  /// 状态从签名上就不存在了。
  ///
  /// 控制器读自 Element 而不是 Widget：所有权在那一层，见 [FlInheritedElement]。
  ///
  /// 找不到时抛 [FlPageProviderNotFoundError]。
  static T of<T extends FlBaseController>(
    BuildContext context, {
    List<Enum>? ids,
  }) {
    final InheritedElement? element = context
        .getElementForInheritedWidgetOfExactType<FlInheritedWidget<T>>();
    if (element == null) {
      throw FlPageProviderNotFoundError(T, context.widget.runtimeType);
    }
    if (ids != null) {
      context.dependOnInheritedElement(element, aspect: ids);
    }
    // 只有 FlInheritedWidget<T> 造得出这个 Element，转型不会失败。
    return (element as FlInheritedElement<T>).controller;
  }

  @override
  Widget build(BuildContext context) =>
      FlInheritedWidget<T>(create: create, child: child);
}

/// 子树里找不到 `FlPageProvider<T>` 时抛出。
@internal
class FlPageProviderNotFoundError extends Error {
  /// 同样要单独标，理由见 [FlPageProvider] 的构造函数。
  @internal
  FlPageProviderNotFoundError(this.controllerType, this.widgetType);

  /// 被查找的控制器类型。
  final Type controllerType;

  /// 发起查找的 Widget 类型。
  final Type widgetType;

  @override
  String toString() {
    return '''
在 $widgetType 之上找不到 FlPageProvider<$controllerType>。

常见原因：
- 页面没有用 FlBasePage / FlBasePageState / FlProviderBuilder 承载。
- 查找用的 context 取自承载它的那层 widget 之上（例如直接用了 build 方法的
  context，而 provider 是在同一个 build 里创建的）。改用 Builder 或子 Widget 的 context。
- 泛型写的是父类型：查找按**精确类型**匹配，$controllerType 的父类型找不出它，
  反过来也一样。
''';
  }
}
