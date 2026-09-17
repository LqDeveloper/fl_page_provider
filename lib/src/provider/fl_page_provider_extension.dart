import 'package:flutter/widgets.dart';

import '../controller/fl_base_controller.dart';
import 'fl_page_provider.dart';

/// 从 [BuildContext] 取控制器的三种粒度。
///
/// | 方法 | 建立依赖 | 何时重建调用方 |
/// | --- | --- | --- |
/// | [rc] | 否 | 从不 |
/// | [selectIds] | 是 | 仅所列 ID 被通知时 |
/// | [wc] | 是 | 控制器每次通知 |
///
/// 三者都只按**精确泛型**向上查找最近的 `FlPageProvider<T>`，找不到抛
/// [FlPageProviderNotFoundError]。
///
/// ## 名字为什么是 rc / wc 而不是 read / watch
///
/// `read` 与 `watch` 是 pub 上 `provider` 包在 [BuildContext] 上占着的名字
/// （`ReadContext` / `WatchContext`）。两个包同时被导入时，同名的扩展成员会让每个
/// 调用点都报 `ambiguous_extension_member_access`——这是 Dart 的扩展解析规则，不
/// 是哪一方的 bug，而且**加导入前缀也不管用**：带前缀导入的扩展照样参与隐式解析，
/// 只能靠 `hide` 或者把扩展名写出来（`FooExtension(context).read()`）化解。
///
/// 本扩展索性不去挤那两个名字：`rc` / `wc` / [selectIds] 在 `provider` 侧都不存在，
/// 于是两个包可以原样各自导入，一个 `hide` 都不用写，短名也不必在调用点展开。
/// 混用示例见 example 的 `test/coexistence_test.dart`。
///
/// 本扩展是取控制器的**唯一**公开入口：底下那层 `FlPageProvider` 已经转为包内
/// 实现，外面拿不到，也就没有「绕开扩展直接查」的写法了。
extension FlControllerContextExtension on BuildContext {
  /// **r**ead **c**ontroller：取控制器但**不建立依赖**，控制器发通知不会重建
  /// 调用方。
  ///
  /// 事件回调里调方法用这个（`onPressed: () => context.rc<C>().increase()`）。
  T rc<T extends FlBaseController>() => FlPageProvider.of<T>(this);

  /// **w**atch **c**ontroller：取控制器并依赖它的**全部**通知，每次
  /// `notifyListeners` 都重建调用方。
  ///
  /// 粒度最粗，只在确实关心整个控制器时用；页面里按 ID 局部刷新请用 [selectIds]
  /// 或 `FlSelector`。
  T wc<T extends FlBaseController>() =>
      FlPageProvider.of<T>(this, listen: true);

  /// 取控制器并只依赖 [ids] 这几个 ID：只有它们被通知时才重建调用方。
  ///
  /// ```dart
  /// Widget build(BuildContext context) {
  ///   final c = context.selectIds<CounterId, CounterController>(
  ///     const [CounterId.count],
  ///   );
  ///   return Text('${c.count}');
  /// }
  /// ```
  ///
  /// 重建范围就是调用方这个 Widget 的整棵子树——想缩小到一小块，把那块拆成
  /// 独立 Widget，或改用 `FlSelector` 的 `child` 参数把不变的部分摘出去。
  ///
  /// 同一个 Widget 里多次调用会**累加**依赖的 ID（与 [wc] 混用则以 [wc] 为准，
  /// 见 [FlPageProvider]）。
  ///
  /// ## 不要放在条件分支里
  ///
  /// ```dart
  /// if (expanded) context.selectIds<Id, C>(const [Id.detail]);  // ✗
  /// ```
  ///
  /// Flutter 只在 `Element.deactivate()` 时解除依赖登记，**重建时从不清理**。
  /// 所以一旦某次 build 走了不调用的那条分支，上一轮登记的 ID 就永久留在表里：
  /// 这个 Widget 会在每次 `Id.detail` 被通知时白重建一次，直到它被卸载。
  /// （实测：关掉条件后连发两次通知，build 次数照样 +1 +1。）
  ///
  /// 这是 Flutter 依赖模型本身的行为，`provider` 的 `context.select` 同样如此。
  /// 两种躲开的写法：无条件调用（不需要时改用 [wc] 或干脆不读），或者把那一块
  /// 拆成独立 Widget——条件不成立时它整个卸载，依赖随之解除。
  T selectIds<E extends Enum, T extends FlBaseController<E>>(List<E> ids) {
    final T controller = FlPageProvider.of<T>(this, listen: true, aspect: ids);
    assert(
      ids.isNotEmpty,
      '$T: selectIds 收到空的 ids。空列表不是「不限定 ID」，而是「一个 ID 都不'
      '关心」——调用方永远不会重建。要跟着控制器全量刷新请改用 '
      'context.wc<$T>()。',
    );
    assert(() {
      final List<E> missing = ids
          .where((E id) => !controller.isRegistered(id))
          .toList(growable: false);
      assert(
        missing.isEmpty,
        '$T: selectIds 的 ids 里 $missing 未注册——请把它们放进 '
        'shouldNotifyIds。未注册的 ID 版本号恒为 0，比对永远得出「没变」，'
        '调用方一次都不会重建，且不会报错。',
      );
      return true;
    }());
    return controller;
  }
}
