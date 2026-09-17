import 'package:flutter/widgets.dart';

import '../controller/fl_base_controller.dart';
import 'fl_page_mixin.dart';

/// 页面基类（有状态）：[FlBasePage] 的 `State` 版本。
///
/// 需要 `State` 才能做的事才用它——`TickerProviderStateMixin`、`GlobalKey`、
/// 本页在 `PageView` / `TabBarView` / `IndexedStack` 里需要保活，或者页面自己
/// 还有一份跟控制器无关的局部 UI 状态。其余情况用 [FlBasePage] 更省一个类。
///
/// ```dart
/// class CounterPage extends StatefulWidget {
///   const CounterPage({super.key});
///   @override
///   State<CounterPage> createState() => _CounterPageState();
/// }
///
/// class _CounterPageState
///     extends FlBasePageState<CounterPage, CounterController> {
///   @override
///   bool get wantKeepAlive => true;            // 需要保活时才写
///
///   @override
///   CounterController createController(BuildContext context) =>
///       CounterController();
///
///   @override
///   Widget buildWithController(BuildContext context, CounterController c) =>
///       Scaffold(body: Text('\${c.count}'));
/// }
/// ```
abstract class FlBasePageState<
  S extends StatefulWidget,
  T extends FlBaseController
>
    extends State<S>
    with FlPageMixin<T>, AutomaticKeepAliveClientMixin {
  /// 默认 `false`。在 `PageView` / `TabBarView` 里要保住滚动位置、表单输入时
  /// override 成 `true`。
  @override
  bool get wantKeepAlive => false;

  /// **override 本方法时必须调 `super.build(context)`** —— 那是
  /// [AutomaticKeepAliveClientMixin] 的要求，漏了保活不生效。
  /// 页面 UI 请写在 [FlPageMixin.buildWithController] 里，不要重写 `build`。
  @override
  Widget build(BuildContext context) {
    super.build(context);
    return getProviderWidget(context);
  }
}
