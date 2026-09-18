import 'package:flutter/widgets.dart';
import 'package:meta/meta.dart';

import '../controller/fl_base_controller.dart';
import 'fl_page_provider.dart';

/// 从 [BuildContext] 取控制器。
///
/// | 入口 | 建立依赖 | 何时重建 | 公开 |
/// | --- | --- | --- | --- |
/// | [rc] | 否 | 从不 | 是 |
/// | `FlSelector` / `FlSelectorView` | 是 | 仅所列 ID 被通知时 | 是 |
/// | [selectIds] | 是 | 仅所列 ID 被通知时 | 否，包内实现 |
///
/// 都只按**精确泛型**向上查找最近的 `FlPageProvider<T>`，找不到抛
/// [FlPageProviderNotFoundError]。
///
/// ## 只有两个公开入口：[rc] 与 `FlSelector`
///
/// 「取实例调方法」用 [rc]，「跟着某几个 ID 重建一块 UI」用 `FlSelector` /
/// `FlSelectorView`。带依赖的那条路只经由 Widget 提供，不开放 [BuildContext]
/// 上的写法——因为依赖登记在**调用方那个 Element** 上，写在页面 `build` 里就是
/// 整页跟着一个 ID 抖，而且放进条件分支还会留下永久白重建的尾巴（详见
/// [selectIds] 的文档）。包一层 Widget 两个问题一起没有：重建边界就是那层
/// Widget，条件不成立时它整个卸载、依赖随之解除。
///
/// ## 没有「全量依赖」这一档
///
/// 早先还有一个 `wc`（watch controller）：建立依赖但不限定 ID，控制器每发一次
/// 通知就重建调用方一次。它已被移除，原因有两条。
///
/// 一是 ID 粒度本该是本库**唯一**的通知语义。留着第二套约定，「同一次变更有的
/// 块刷了有的块没刷」这类问题就永远要先问一句「这块订的是哪一档」。
///
/// 二是它建立的全量依赖**跨帧不可逆**。Flutter 只在 `Element.deactivate()` 时解
/// 依赖登记，重建时从不清理；而全量依赖一旦登记，后续的 ID 登记不能再把它收窄
/// （否则 `wc` 那半边会漏通知）。两条合起来的后果是：一个 Widget 只要有过**一次**
/// `wc`，哪怕之后每帧都改按 ID 订阅，它也回不到 ID 粒度，会一直跟着控制器的
/// 每一次通知重建，直到被卸载——不报错，也没有日志。
///
/// 确实需要「任何变更都刷新这一块」时，专门留一个 ID：
///
/// ```dart
/// enum ProfileId { all, name, avatar }
///
/// // 控制器侧：每次变更都把 all 一起列进去
/// notifyMultiListeners(const [ProfileId.all, ProfileId.name]);
///
/// // 调用方侧：和别的订阅写法完全一致
/// FlSelector<ProfileId, ProfileController>(
///   ids: const [ProfileId.all],
///   builder: (context, c, _) => Text(c.name),
/// )
/// ```
///
/// 这样「谁会因为什么而重建」始终写在调用点上，不必回控制器里翻，也不会出现
/// 「订阅悄悄退化成全量」这种没有症状的性能塌陷。
///
/// ## 名字为什么是 rc 而不是 read
///
/// `read` 与 `watch` 是 pub 上 `provider` 包在 [BuildContext] 上占着的名字
/// （`ReadContext` / `WatchContext`）。两个包同时被导入时，同名的扩展成员会让每个
/// 调用点都报 `ambiguous_extension_member_access`——这是 Dart 的扩展解析规则，不
/// 是哪一方的 bug，而且**加导入前缀也不管用**：带前缀导入的扩展照样参与隐式解析，
/// 只能靠 `hide` 或者把扩展名写出来（`FooExtension(context).read()`）化解。
///
/// 本扩展索性不去挤那两个名字：`rc` 在 `provider` 侧不存在，于是两个包可以原样
/// 各自导入，一个 `hide` 都不用写，短名也不必在调用点展开。
/// 混用示例见 example 的 `test/coexistence_test.dart`。
///
/// 本扩展是从 [BuildContext] 取控制器的**唯一**入口：底下那层 `FlPageProvider`
/// 已经转为包内实现，外面拿不到，也就没有「绕开扩展直接查」的写法了。
extension FlControllerContextExtension on BuildContext {
  /// **r**ead **c**ontroller：取控制器但**不建立依赖**，控制器发通知不会重建
  /// 调用方。
  ///
  /// 事件回调里调方法用这个（`onPressed: () => context.rc<C>().increase()`）。
  T rc<T extends FlBaseController>() => FlPageProvider.of<T>(this);

  /// 取控制器并只依赖 [ids] 这几个 ID：只有它们被通知时才重建调用方。
  ///
  /// **包内实现细节，使用方请走 `FlSelector` 或 `FlSelectorView`。** 它们就是
  /// 本方法加一层 Widget 边界，而那层边界正是安全用它的前提，见下。
  ///
  /// ## 为什么不作为公开 API
  ///
  /// 两条，都跟「重建边界」有关。
  ///
  /// 一是**重建范围**：依赖登记在调用方那个 Element 上，所以本方法一响，调用方
  /// 的**整棵子树**都要重建。写在页面的 `build` 里，就等于整页跟着一个 ID 抖。
  /// `FlSelector` 把边界缩到它自己那一层，并且还能用 `child` 参数把不随该 ID
  /// 变化的子树摘出去。
  ///
  /// 二是**条件分支**：
  ///
  /// ```dart
  /// if (expanded) context.selectIds<Id, C>(const [Id.detail]);  // ✗
  /// ```
  ///
  /// Flutter 只在 `Element.deactivate()` 时解除依赖登记，**重建时从不清理**。
  /// 所以一旦某次 build 走了不调用的那条分支，上一轮登记的 ID 就永久留在表里：
  /// 这个 Widget 会在每次 `Id.detail` 被通知时白重建一次，直到它被卸载。
  /// （实测：关掉条件后连发两次通知，build 次数照样 +1 +1。）这是 Flutter 依赖
  /// 模型本身的行为，`provider` 的 `context.select` 同样如此。
  ///
  /// 换成 `FlSelector` 这个坑就不存在了——把它放进条件分支，条件不成立时它整个
  /// 卸载，依赖随 `deactivate()` 一起解除，不会留下白重建的尾巴。
  ///
  /// 同一个 Widget 里多次调用会**累加**依赖的 ID。
  @internal
  T selectIds<E extends Enum, T extends FlBaseController<E>>(List<E> ids) {
    final T controller = FlPageProvider.of<T>(this, ids: ids);
    assert(
      ids.isNotEmpty,
      '$T: FlSelector 收到空的 ids。空列表不是「不限定 ID」，而是「一个 ID 都不'
      '关心」——它永远不会重建。要跟着控制器全量刷新，请在 shouldNotifyIds '
      '里专门留一个「全量」ID，每次通知都把它一起列进 notifyMultiListeners，'
      '这里订它。',
    );
    assert(() {
      // 先判一次再 materialize：这段每个 selector 每次 build 都跑，而 missing
      // 正常情况下恒为空，没必要为拼报错信息白建一个列表。
      if (ids.every(controller.isRegistered)) return true;
      final List<E> missing = ids
          .where((E id) => !controller.isRegistered(id))
          .toList(growable: false);
      assert(
        missing.isEmpty,
        '$T: FlSelector 的 ids 里 $missing 未注册——请把它们放进 '
        'shouldNotifyIds。未注册的 ID 版本号恒为 0，比对永远得出「没变」，'
        '它一次都不会重建，且不会报错。',
      );
      return true;
    }());
    return controller;
  }
}
