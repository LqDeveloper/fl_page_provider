import 'package:flutter/widgets.dart';
import 'package:meta/meta.dart';

import '../controller/fl_base_controller.dart';
import 'fl_inherited_widget.dart';

/// 把一个 [FlBaseController] 注入子树，并按 **ID 粒度** 精确重建依赖方。
///
/// **包内实现细节。** 使用方请走 `FlProviderBuilder`（或它上面的 `FlBasePage` /
/// `FlBasePageState`）——那一层在本类之外还接好了生命周期转发，直接用本类等于
/// 只铺了一半。取控制器走 `context.rc` / `wc` / `selectIds`。
///
/// 本类只管控制器的**生死**：[create] 出来的实例由它在子树销毁时 `dispose`，
/// 没有第二种所有权。注入与重建的机制在 [FlInheritedWidget] / [FlInheritedElement]
/// 里——控制器上只挂一个 listener，通知经 `markNeedsBuild()` 折进正常构建流程，
/// 再由 [FlInheritedElement.notifyDependent] 逐个依赖方比对版本号决定重不重建。
@internal
class FlPageProvider<T extends FlBaseController> extends StatefulWidget {
  /// 创建并托管控制器：实例由本 Widget 在销毁时 `dispose`。
  ///
  /// 构造函数要单独再标一次 `@internal`：类上的标注拦得住类型位置的引用和
  /// `FlPageProvider.of` 这类静态调用，但拦不住 `FlPageProvider(...)`——分析器
  /// 把它解析成对无名构造函数的引用，而构造函数没被标注就不算越界。
  @internal
  const FlPageProvider({required this.create, required this.child, super.key});

  /// 控制器工厂，在首次 `build` 时调用**一次**，之后父级重建不会再造。
  ///
  /// 因为跑在 `build` 里而不是 `initState`，里面可以安全地查 `InheritedWidget`
  /// （`Theme.of` 等）。
  ///
  /// 所有权是单向的：返回的实例一律由本 Widget 释放。让 [create] 返回一个外部
  /// 持有的实例（全局单例之类）意味着它会在这棵子树销毁时被 `dispose` 掉——
  /// 本类不提供「借用不释放」的口子。
  final T Function(BuildContext context) create;

  /// 被注入的子树。
  final Widget child;

  /// 向上查找最近的 `FlPageProvider<T>` 并返回它持有的控制器。
  ///
  /// - [listen] 为 `false`（默认）时**不建立依赖**：拿到实例调方法用，控制器
  ///   发通知不会重建调用方。等价于 `context.rc<T>()`。
  /// - [listen] 为 `true` 时建立依赖，[aspect] 决定粒度：传 `List<Enum>` 则只在
  ///   这些 ID 变化时重建，传 `null` 则任何通知都重建。
  ///
  /// 找不到时抛 [FlPageProviderNotFoundError]。
  static T of<T extends FlBaseController>(
    BuildContext context, {
    bool listen = false,
    Object? aspect,
  }) {
    final InheritedElement? element = context
        .getElementForInheritedWidgetOfExactType<FlInheritedWidget<T>>();
    if (element == null) {
      throw FlPageProviderNotFoundError(T, context.widget.runtimeType);
    }
    if (listen) {
      context.dependOnInheritedElement(element, aspect: aspect);
    }
    return (element.widget as FlInheritedWidget<T>).controller;
  }

  @override
  State<FlPageProvider<T>> createState() => _FlPageProviderState<T>();
}

/// debug 期记录「哪些控制器已被某个 [FlPageProvider] 认领」。
///
/// **只在 `assert` 内被访问**，所以 release 构建里这张表和所有读写它的代码一起
/// 被树摇掉，零开销。拦的是这件事：同一个实例交给两个 provider 时，先卸载的那个
/// 会把它 `dispose` 掉，另一棵子树于是静默冻结（`FlNotifyMixin.notifyListeners`
/// 开头就是 `if (_disposed) return;`），要等第二个也卸载才撞上 Flutter 的双
/// dispose 断言——报错点离病因隔了一整个页面生命周期。
///
/// 代价：条目在 `dispose` 时移除，所以某个 provider 的 `dispose` 若被跳过，
/// debug 下会残留一个条目。这不是缓存，别把它当缓存读。
final Set<ChangeNotifier> _debugOwnedControllers = <ChangeNotifier>{};

/// 认领成功返回 `true`；已被别人认领则返回 `false`（调用方的 assert 会失败）。
bool _debugClaim(ChangeNotifier controller) =>
    _debugOwnedControllers.add(controller);

bool _debugRelease(ChangeNotifier controller) {
  _debugOwnedControllers.remove(controller);
  return true;
}

class _FlPageProviderState<T extends FlBaseController>
    extends State<FlPageProvider<T>> {
  T? _controller;

  @override
  void dispose() {
    final T? controller = _controller;
    if (controller != null) {
      assert(_debugRelease(controller));
      controller.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // ??= 而不是每次重建都调 create：控制器要跨父级重建活下来。
    final T controller = _controller ??= _create(context);
    return FlInheritedWidget<T>(controller: controller, child: widget.child);
  }

  T _create(BuildContext context) {
    final T created = widget.create(context);
    assert(
      _debugClaim(created),
      '$T 的这个实例已经被另一个 FlPageProvider 认领了。所有权是单向的：'
      'create 返回什么，这个 provider 就在子树销毁时 dispose 什么——两个 '
      'provider 拿同一个实例，先卸载的那个会把它 dispose 掉，另一棵子树的 UI '
      '会静默冻结。请让每个 provider 的 create 各自新建一个实例；确实要共享'
      '状态就把它提到共同的祖先上，只铺一个 provider。',
    );
    return created;
  }
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
