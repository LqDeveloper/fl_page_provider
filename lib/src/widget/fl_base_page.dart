import 'package:flutter/widgets.dart';

import '../controller/fl_base_controller.dart';
import 'fl_page_mixin.dart';

/// 页面基类（无状态）：实现两个方法就得到一个**自带控制器与生命周期**的页面。
///
/// ```dart
/// class CounterPage extends FlBasePage<CounterController> {
///   const CounterPage({super.key});
///
///   @override
///   CounterController createController(BuildContext context) =>
///       CounterController();
///
///   @override
///   Widget buildWithController(BuildContext context, CounterController c) =>
///       Scaffold(body: Text('${c.count}'));
/// }
/// ```
///
/// 它替你接好了三件事（都在 [FlProviderBuilder] 里）：控制器的创建与释放、
/// 生命周期事件的转发、以及把控制器注入子树供 `FlSelector` / `context.rc`
/// 取用。[buildWithController] 直接拿到控制器，常规写法不需要再 `context.rc`。
///
/// 需要 `State`（`TickerProvider`、`AutomaticKeepAlive`、或本页在 `PageView` /
/// `TabBarView` 里）时改用 [FlBasePageState]。可 override 的开关见
/// [FlPageMixin.observePageIndex] 与 [FlPageMixin.observeAppLifecycle]。
abstract class FlBasePage<T extends FlBaseController> extends StatelessWidget
    with FlPageMixin<T> {
  const FlBasePage({super.key});

  @override
  Widget build(BuildContext context) {
    return getProviderWidget(context);
  }
}
