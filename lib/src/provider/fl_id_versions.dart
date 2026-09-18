import 'package:meta/meta.dart';

/// 按 ID 暴露版本号的非泛型视图。
///
/// 包内实现细节：唯一的实现方是 `FlNotifyMixin`，唯一的消费方是
/// `FlInheritedElement`，两者都不出包。控制器侧要的能力请直接用
/// `FlBaseController`。
///
/// `FlNotifyMixin` 是泛型的（`FlNotifyMixin<T extends Enum>`），而
/// `FlInheritedElement` 站在 Widget 层，拿不到也不关心具体的枚举类型——它只需要
/// 「这个 ID 现在是第几版」。本接口就是两者之间那道不带泛型的窄口子。
///
/// 控制器不实现本接口时，`FlInheritedElement` 读到的版本号恒为 `0`。注意这不是
/// 「退化成全量刷新」——恒等的版本号意味着比对永远得出「没变」，那些
/// `FlSelector` 依赖方**一次都不会重建**，UI 静默停在旧数据上。`FlInheritedElement`
/// 在 debug 期对此有断言。
@internal
abstract interface class FlIdVersions {
  /// [id] 的当前版本号；每次该 ID 被通知就 +1。未注册的 ID 返回 `0`。
  ///
  /// 调用方只比较相邻两次取值是否相同，从不解释具体数值。但也正因为如此，实现
  /// 方**不该回绕**：绕回原值会让那次变更被静默吞掉。`FlNotifyMixin` 的实现是
  /// 只增不减的。
  int idVersion(Enum id);

  /// [id] 有没有被注册过。
  ///
  /// 存在的理由是 [idVersion] **区分不了**「没注册」和「注册了但还没被通知过」
  /// ——两种情况都返回 `0`。而这两件事的后果完全不同：后者是正常的初始状态，
  /// 前者意味着那个 ID 的版本号永远不会动，依赖它的 Widget 一次都不会重建。
  /// 门禁必须能分辨，所以单独开一个不带泛型的判定口子。
  bool isRegistered(Enum id);
}
