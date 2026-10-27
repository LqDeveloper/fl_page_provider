import 'package:flutter/widgets.dart';

import '../controller/fl_base_controller.dart';
import '../provider/fl_page_provider_extension.dart';

/// [FlSelector] 的构建回调。[child] 原样透传构造时传入的那个子树。
typedef FlSelectorBuilder<E extends Enum, T extends FlBaseController<E>> =
    Widget Function(BuildContext context, T controller, Widget? child);

/// 基于注册 ID 的选择性重建组件
///
/// 只依赖 [ids] 这几个 ID：控制器通知其它 ID 时本组件不重建。判定由
/// `FlPageProvider` 的 Element 逐 ID 比对版本号完成，不经过任何哈希合并。
///
/// 用法：
/// ```dart
/// FlSelector<PageId, PageController>(
///   ids: const [PageId.title, PageId.count],
///   builder: (context, controller, child) => Text('${controller.count}'),
/// )
/// ```
///
/// 重建范围是 [builder] 返回的整棵子树。其中不随 [ids] 变化的部分传给 [child]，
/// 它只构建一次，之后每次重建都把同一个实例交还给 [builder]——Flutter 见到同一个
/// Widget 实例会直接跳过那棵子树。
/// ## 上界是 [FlBaseController]
///
/// 与 `FlBasePage` / `FlBasePageState` / `FlProviderBuilder` 那条链一致：页面侧
/// 注入子树的本来就是 [FlBaseController]，选择器这边跟着收口，整套 API 只有一种
/// 控制器概念。写成 `FlBaseController<E>` 而不是裸的 `FlBaseController`，是为了
/// 把 [ids] 的枚举类型和控制器绑在一起——裸上界会退化成
/// `FlBaseController<Enum>`，`FlSelector<某个不相干的 Id, SomeController>` 也能
/// 编译过去。
///
/// 代价是：只混入 `FlNotifyMixin` 而不继承 [FlBaseController] 的控制器用不了本
/// 组件。而本组件（连同 [FlSelectorView]）是按 ID 订阅的**唯一**公开入口——
/// 底下那层 `context.selectIds` 已转为包内实现，没有绕开的写法。需要订阅就让
/// 控制器继承 [FlBaseController]。
class FlSelector<E extends Enum, T extends FlBaseController<E>>
    extends StatelessWidget {
  const FlSelector({
    required this.ids,
    required this.builder,
    super.key,
    this.child,
  });

  /// 关心的 ID 列表，只有它们被通知时本组件才重建。
  final List<E> ids;

  /// 构建回调。
  final FlSelectorBuilder<E, T> builder;

  /// 不参与重建的静态子树，原样透传给 [builder]。
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    // 空列表与未注册 ID 的两道断言都在 context.selectIds 里（后者会把缺的
    // ID 逐个列出来），这里不再重复：之前这两道排在它之后，永远轮不到。
    return builder(context, context.selectIds<E, T>(ids), child);
  }
}
