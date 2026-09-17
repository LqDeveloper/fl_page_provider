import 'package:flutter/widgets.dart';

import '../controller/fl_base_controller.dart';
import 'fl_selector.dart';

/// 基于 [FlSelector] 的抽象视图基类
///
/// 把「传 ids + 写 builder」换成「override 两个成员」，适合需要独立成类的片段。
/// 子类只需实现：
/// - [observeIds] — 需要监听的 ID 列表
/// - [buildWidget] — 根据 controller 数据构建 UI
///
/// 内部自动用 [FlSelector] 包装，仅在 [observeIds] 对应的数据变化时触发
/// [buildWidget] 重建。
///
/// ## 把不变的部分摘出重建范围
///
/// override [staticChild] 返回那棵与 [observeIds] 无关的子树，它只构建一次，
/// 之后每次重建都作为 `child` 原样交还给 [buildWidget]——Flutter 见到同一个
/// Widget 实例会直接跳过那棵子树。不需要就不用管，默认 `null`。
///
/// ```dart
/// class CountSection extends FlSelectorView<PageId, PageController> {
///   const CountSection({super.key});
///
///   @override
///   List<PageId> get observeIds => const [PageId.count];
///
///   @override
///   Widget? get staticChild => const Icon(Icons.star);   // 只建一次
///
///   @override
///   Widget buildWidget(BuildContext context, PageController c, Widget? child) {
///     return Row(children: [if (child != null) child, Text('${c.count}')]);
///   }
/// }
/// ```
///
/// 上界是 [FlBaseController]（且带上 `<E>`），理由见 [FlSelector]。
abstract class FlSelectorView<E extends Enum, T extends FlBaseController<E>>
    extends StatelessWidget {
  const FlSelectorView({super.key});

  /// 关心的 ID 列表，只有它们被通知时本组件才重建。不能为空，见 [FlSelector]。
  List<E> get observeIds;

  /// 不参与重建的静态子树，原样透传给 [buildWidget] 的 `child`。
  ///
  /// 必须**每次取值都返回同一个实例**才有意义——写成 `const` 字面量，或缓存到
  /// 字段里；每次 new 一个新的等于没优化。默认 `null`。
  Widget? get staticChild => null;

  @override
  Widget build(BuildContext context) {
    return FlSelector<E, T>(
      ids: observeIds,
      builder: buildWidget,
      child: staticChild,
    );
  }

  /// 构建 UI。[child] 就是 [staticChild]，没 override 时为 `null`。
  Widget buildWidget(BuildContext context, T controller, Widget? child);
}
