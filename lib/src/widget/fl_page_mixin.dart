import 'package:flutter/widgets.dart';

import '../controller/fl_base_controller.dart';
import 'fl_provider_builder.dart';

/// 页面级 Controller 注入 Mixin
///
/// 提供 [getProviderWidget] 快捷方法，内部使用 [FlProviderBuilder] 组合
/// `FlPageProvider` + `FlPageLifecycleView`，
/// 将 controller 注入子树并通过 [buildWithController] 渲染页面。
///
/// 子类需实现：
/// - [createController] — 创建 controller 实例
/// - [buildWithController] — 使用 controller 构建页面 UI
mixin FlPageMixin<T extends FlBaseController> {
  /// 组装 provider + 生命周期转发 + [buildWithController]，由 [FlBasePage] /
  /// [FlBasePageState] 的 `build` 调用。
  ///
  /// 标 `@protected` 是因为它是**管道而非入口**：页面该实现的是
  /// [createController] 与 [buildWithController]，手动再调一次它会多铺一层
  /// provider。只有把本 mixin 混进自定义 Widget 时才需要自己调。
  @protected
  Widget getProviderWidget(BuildContext context) {
    return FlProviderBuilder(
      observeAppLifecycle: observeAppLifecycle,
      observePageIndex: observePageIndex,
      create: createController,
      builder: (cxt, controller) => buildWithController(cxt, controller),
    );
  }

  /// 是否让 controller 收到 App 前后台事件，见 [FlProviderBuilder.observeAppLifecycle]。
  bool get observeAppLifecycle => false;

  /// 本页是否是 `PageView` / `TabBarView` / `IndexedStack` 的一页，
  /// 见 [FlProviderBuilder.observePageIndex]。
  ///
  /// 开启后宿主侧**还必须**用 `FlPageIndexScope.wrapChildren` /
  /// `wrapItemBuilder` 包裹子页，只做一半不报错但完全无效。
  bool get observePageIndex => false;

  /// 创建本页控制器，只调用一次，实例由 provider 在页面销毁时 `dispose`。
  ///
  /// 跑在首帧 `build` 里，早于控制器的 `onPageInit`，约束见
  /// [FlProviderBuilder.create]：可以 `context.rc<X>()` 读祖先控制器，不要用
  /// `Theme.of` / `MediaQuery.of` 这类会建立依赖的查找，也不要在这里同步发通知。
  /// 这里只 new，初始化副作用放 `onPageInit`，拉数据放 `onPageStart`。
  T createController(BuildContext context);

  Widget buildWithController(BuildContext context, T controller);
}
