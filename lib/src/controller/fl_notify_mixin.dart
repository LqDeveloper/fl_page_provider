import 'package:flutter/foundation.dart';

import '../provider/fl_id_versions.dart';
import '../provider/fl_page_provider.dart';

/// 基于注册 ID 的选择性通知 Mixin
///
/// 通过 [registerIds] 注册需要追踪的 ID，后续调用 [notifyMultiListeners] 或
/// [notifySingleListener] 时只递增对应 ID 的版本号。`FlInheritedElement` 读这些
/// 版本号（经 [idVersion]）决定哪些依赖方需要重建，见 [FlPageProvider]。
///
/// 注意 [notifyListeners] 本身**没有 ID 概念**：它照常通知所有监听者，ID 粒度
/// 是在 Widget 侧按版本号过滤出来的。正因为如此，子类直接调它会让所有
/// `selectIds` 依赖方静默不刷新，debug 期有门禁拦着，见 [notifyListeners]。
///
/// 本 mixin 只管「喊」，不管「什么时候兑现成重建」——包括 build 阶段发出的通知
/// 该如何推迟。那道约束来自 Widget 层，也就由 Widget 层的 `FlInheritedElement`
/// 自己处理，见 [notifyListeners]。
@internal
mixin FlNotifyMixin<T extends Enum> on ChangeNotifier implements FlIdVersions {
  /// 已注册的 ID → 它的版本号。注册过的 ID 才在表里。
  ///
  /// 存 `int` 而不是一个计数器对象：一个 ID 要记的就只有一个数，包一层对象等于
  /// 每注册一个 ID 多一次堆分配。
  final Map<T, int> _versions = <T, int>{};

  bool _disposed = false;
  bool _registered = false;

  /// debug 期的「这次 [notifyListeners] 是不是从 [_bumpAndNotify] 进来的」。
  ///
  /// 只在 `assert` 内置位与复位，release 构建里门禁连同这几行一起被树摇掉，
  /// 热路径上不剩任何判断。见 [notifyListeners] 的门禁说明。
  bool _debugInBump = false;

  @protected
  @mustCallSuper
  @override
  void dispose() {
    logMessage(() => '[dispose]');
    _disposed = true;
    _registered = false;
    _versions.clear();
    super.dispose();
  }

  @protected
  @mustCallSuper
  void registerIds(List<T> ids) {
    clearRegisteredIds();
    logMessage(() => '[register] ids: $ids');
    for (final T id in ids) {
      _versions[id] = 0;
    }
    _registered = true;
  }

  @protected
  @mustCallSuper
  void clearRegisteredIds() {
    _versions.clear();
    _registered = false;
  }

  /// **子类不要直接调用**，请走 [notifySingleListener] / [notifyMultiListeners]。
  ///
  /// 直接调它会通知所有监听者，却**不推进任何 ID 的版本号**：`context.wc` 那批
  /// 依赖方照常重建，而 `selectIds` / `FlSelector` 那批逐 ID 比对下来一律得出
  /// 「没变」，一次都不会重建。症状是「明明发了通知，那一块就是不刷新」，
  /// 且不报错——页面静默停在旧数据上。
  ///
  /// Dart 没有「把继承来的公开成员藏起来」的写法（[protected] 拦的是类层级
  /// **之外**的调用方，恰恰不拦子类），所以这里改用一道 debug 期门禁：不是经
  /// 上面两个入口进来的调用直接断言。release 构建里这道门禁会被树摇掉。
  ///
  /// 确实只想惊动 `wc` 那半边时，仍然请走一个专门的 ID——ID 粒度是本库唯一的
  /// 通知语义，没有第二套约定。
  ///
  /// 通知**什么时候兑现成重建**不归这一层管：那是 Widget 侧的约束（build 阶段
  /// 不能 `markNeedsBuild`），由 `FlInheritedElement` 自己推迟到本帧结束。控制器
  /// 只负责如实地喊一声，喊完立即返回。
  @protected
  @mustCallSuper
  @override
  void notifyListeners() {
    if (_disposed) return;
    assert(
      _debugInBump,
      '$runtimeType 直接调用了 notifyListeners()。它不推进任何 ID 的版本号，'
      'selectIds / FlSelector 那批依赖方比对下来一律是「没变」，一次都不会重建'
      '——不报错，只是那一块静默停在旧数据上。请改用 '
      'notifySingleListener(id) 或 notifyMultiListeners(const [...])；'
      '想全量刷新就专门留一个 ID，调用方那边用 context.wc 订。',
    );
    super.notifyListeners();
  }

  /// 推进 [ids] 各自的版本号，然后通知。空列表直接返回。
  @protected
  @mustCallSuper
  void notifyMultiListeners(List<T> ids) {
    if (_disposed || ids.isEmpty) return;
    logMessage(() => '[notify] ids: $ids');
    _bumpAndNotify(ids);
  }

  /// [notifyMultiListeners] 的单 ID 版本。
  @protected
  @mustCallSuper
  void notifySingleListener(T id) {
    if (_disposed) return;
    logMessage(() => '[notify] id: $id');
    _bumpAndNotify(<T>[id]);
  }

  /// 推进版本号 → [onNotified] → [notifyListeners]，两个通知入口共用这一段。
  ///
  /// 走的是私有方法而不是让 [notifySingleListener] 转调 [notifyMultiListeners]：
  /// 那样一来重写 [notifyMultiListeners] 会连带改掉单 ID 那条路的行为。
  void _bumpAndNotify(List<T> ids) {
    assert(
      _registered,
      '$runtimeType 还没调用过 registerIds——表里一个 ID 都没有，'
      '这次通知不会触发任何重建。',
    );
    for (final T id in ids) {
      // 一次查表同时兼作「已注册吗」的判定，省掉一次 containsKey。
      final int? version = _versions[id];
      assert(
        version != null,
        '$runtimeType: $id 未注册——请把它放进 shouldNotifyIds。'
        '未注册的 ID 版本号恒为 0，永远不会触发重建。',
      );
      if (version != null) _versions[id] = version + 1;
    }
    onNotified(ids);
    _notifyFromBump();
  }

  /// 把门禁打开再调一次 [notifyListeners]——这是唯一被认可的入口。
  ///
  /// try/finally 是给 [onNotified] 之后那批监听者兜底的：哪怕有谁抛出来，
  /// 标志位也要复位，否则后续一次真正越界的直调反而被放过去。
  void _notifyFromBump() {
    assert(() {
      _debugInBump = true;
      return true;
    }());
    try {
      notifyListeners();
    } finally {
      assert(() {
        _debugInBump = false;
        return true;
      }());
    }
  }

  /// 见 [FlIdVersions.isRegistered]。
  ///
  /// 取代了早先的 `containsId` / `containsMultiId`：那两个是泛型的（`T`），
  /// Widget 层拿不到具体枚举类型，只能靠 `@internal` 勉强跨文件用；而本方法在
  /// 不带泛型的 [FlIdVersions] 上，`context.selectIds` 与 `FlSelector` 都能直接
  /// 调，同一个判定不必再留两套写法。
  @override
  bool isRegistered(Enum id) => _versions.containsKey(id);

  /// 供 `FlInheritedElement` 逐 ID 比对新旧版本号，见 [FlIdVersions]。
  ///
  /// **只增不减，不回绕。** 调用方只看相邻两次取值是否相同，那么「推进过、又刚好
  /// 绕回原值」就会把那次变更静默吞掉。回绕模数取得越小，这个窗口越近：早先取
  /// 1000，意味着某个 ID 在相邻两次求值之间推进整 1000 次就会漏掉一次重建。
  /// 不回绕的话，要到 int 溢出（web 上 2^53）才有同样的问题，实际到不了。
  ///
  /// 同理这里也**不做**多 ID 的哈希合并：合并后两个 ID 一增一减可以互相抵消出
  /// 同一个哈希值，那次变更一样被吞掉。逐个比对、逐个递增，没有这些问题。
  @override
  int idVersion(Enum id) => _versions[id] ?? 0;

  /// 调试钩子，默认什么也不做。
  ///
  /// 收的是「构造消息的闭包」而不是消息本身：默认实现是空的，而通知在热路径上，
  /// 不该为一条没人读的日志去拼字符串（`'$ids'` 还要把整个列表串一遍）。
  @internal
  @protected
  void logMessage(String Function() message) {}

  /// 通知发出前的钩子，[events] 是本次推进过版本号的 ID。
  @protected
  void onNotified(List<T> events) {}
}
