import 'package:flutter/widgets.dart';

import 'package:fl_page_lifecycle/fl_page_lifecycle.dart';

import '../controller/fl_base_controller.dart';
import '../provider/fl_page_provider.dart';
import '../provider/fl_page_provider_extension.dart';

/// 创建带生命周期感知的 Controller 并注入子树
///
/// 内部组合 [FlPageProvider] 与 [FlPageLifecycleView]：
/// - 通过 [create] 创建控制器实例并注入 widget 树，由 [FlPageProvider] 负责 `dispose`
/// - 通过 [FlPageLifecycleView] 把页面生命周期、路由参数与页码变化转发给 controller
/// - 通过 [builder] 渲染页面，可直接拿到 controller
///
/// 转发的三条链路分别落到 controller 的 `onLifecycleChanged`、
/// `setupRouteInfo` 与 `onPageIndexChanged` 上，均由 [FlPageControllerMixin] 提供。
class FlProviderBuilder<T extends FlBaseController> extends StatelessWidget {
  /// 是否由页码（而非路由）驱动可见性判定，见 [FlPageLifecycleView.observePageIndex]。
  ///
  /// 为 `true` 时宿主侧还必须用 `FlPageIndexScope.wrapChildren` /
  /// `wrapItemBuilder` 包裹子页，否则本页会被当成普通页面：首帧即可见，
  /// 收不到任何切页生命周期。
  final bool observePageIndex;

  /// 是否把 App 前后台事件也转发给 controller，
  /// 见 [FlPageLifecycleView.observeAppLifecycle]。默认 `false`。
  final bool observeAppLifecycle;

  /// 创建 controller 实例，只调用一次，实例由 [FlPageProvider] 托管。
  ///
  /// 跑在首帧 `build` 里，早于控制器的 `onPageInit`。三条约束与 `provider` 的
  /// `create` 一致（详见 [FlPageProvider.create]）：
  ///
  /// - 可以 `context.rc<X>()` 读祖先控制器——不建立依赖，拿的是活实例。
  /// - 不要用 `Theme.of` / `MediaQuery.of` 这类会建立依赖的查找：[create] 只跑
  ///   一次，控制器会静默停在创建那一刻的旧值上。debug 期有断言拦着。
  /// - 不要同步发通知：那时 `registerIds` 还没跑，会撞上 `FlNotifyMixin` 的断言。
  ///
  /// 这里只 new：初始化副作用放 `onPageInit`，拉数据这类重活放 `onPageStart`。
  final T Function(BuildContext context) create;

  /// 页面 UI，[controller] 即 [create] 创建出的实例。
  final Widget Function(BuildContext context, T controller) builder;

  const FlProviderBuilder({
    required this.create,
    required this.builder,
    super.key,
    this.observePageIndex = false,
    this.observeAppLifecycle = false,
  });

  @override
  Widget build(BuildContext context) {
    return FlPageProvider<T>(
      create: create,
      child: Builder(
        builder: (innerContext) {
          final controller = innerContext.rc<T>();
          return FlPageLifecycleView(
            observePageIndex: observePageIndex,
            observeAppLifecycle: observeAppLifecycle,
            onStateChanged: (cxt, state) {
              controller.onLifecycleChanged(state, context: cxt);
            },
            onRouteParam: (_, name, arguments) {
              controller.setupRouteInfo(name, arguments);
            },
            onPageIndexChanged: (_, from, to) {
              controller.onPageIndexChanged(from, to);
            },
            // 传 innerContext 而不是外层 context：后者在 FlPageProvider 之上，
            // 用它 read 本页控制器会抛 FlPageProviderNotFoundError，同类型嵌套时
            // 更会静默命中外层那一个。
            child: builder(innerContext, controller),
          );
        },
      ),
    );
  }
}
