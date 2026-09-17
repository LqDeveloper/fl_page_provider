import 'dart:async';

import 'package:flutter/foundation.dart';

import 'package:fl_page_lifecycle/fl_page_lifecycle.dart';

/// 在 Controller 中收发全局事件的 mixin，订阅由本 mixin 在 [dispose] 中自动取消。
///
/// 与 `fl_page_lifecycle` 的 `FlStateEventBusMixin` 是同一套机制的两种宿主：
/// 那个 mixin 挂在 `State` 上，本 mixin 挂在 [ChangeNotifier] 上，共用
/// [FlGlobalEventBus] 这一条全局总线，互相收得到对方发的事件。
///
/// ```dart
/// class FeedController extends FlBaseController<FeedId> {
///   @override
///   void onPageInit() {
///     super.onPageInit();
///     observeEvent<LoginSuccess>(_handleLogin);   // 传方法引用，不要写闭包
///   }
///
///   void _handleLogin(LoginSuccess event) => notifySingleListener(FeedId.list);
/// }
/// ```
@internal
mixin FlEventBusMixin on ChangeNotifier {
  final List<StreamSubscription<dynamic>> _subscriptions =
      <StreamSubscription<dynamic>>[];

  /// 已登记的 (事件类型, 回调) 组合，用于挡掉重复订阅，见 [observeEvent]。
  final Set<(Type, Function)> _observed = <(Type, Function)>{};

  bool _disposed = false;

  /// [T] 类型事件的原始流，**订阅不受本 mixin 管理**，需自行 cancel。
  /// 只想拿事件、不想管释放，请用 [observeEvent]。
  @protected
  Stream<T> onEvent<T>() {
    return FlGlobalEventBus.observeEvent<T>();
  }

  /// 订阅 [T] 类型的事件，订阅会在 [dispose] 中自动取消。
  ///
  /// **只应在 `onPageInit` 中调用一次。** 本方法不会解除任何已有订阅，写进
  /// `onPageResume` 这类会重复执行的地方，订阅数就会随每次回到前台线性增长：
  /// 同一个事件回调多次，闭包持有的对象也跟着堆积，症状通常表现为埋点重复
  /// 上报或接口重复请求。
  ///
  /// 为此这里挡了一道：同一个 (T, [onData]) 组合重复登记时直接忽略，
  /// 并在 debug 模式下 `assert` 报错。注意**只有传方法引用**
  /// （`observeEvent<Foo>(_handleFoo)`）才拦得住——每次现写的闭包字面量
  /// 彼此不相等，识别不出来，仍然会重复订阅。
  ///
  /// 同一个事件类型配不同的回调是合法的，不受影响。
  @protected
  void observeEvent<T>(void Function(T event) onData) {
    if (_disposed) return;
    if (!_observed.add((T, onData))) {
      assert(
        false,
        'observeEvent<$T> 重复订阅了同一个回调。'
        '请把它移到 onPageInit 中只调用一次——写在 build / onPageResume 里会让'
        '订阅数随重建次数线性增长。本次订阅已被忽略。',
      );
      return;
    }
    _subscriptions.add(onEvent<T>().listen(onData));
  }

  /// 向全局总线发布一个 [T] 类型的事件。
  ///
  /// 所有 `observeEvent<T>()` 的订阅者都会收到，包括本控制器自己。
  @protected
  void dispatchEvent<T>(T event) {
    FlGlobalEventBus.dispatchEvent<T>(event);
  }

  @override
  @mustCallSuper
  void dispose() {
    _disposed = true;
    for (final sub in _subscriptions) {
      unawaited(sub.cancel());
    }
    _subscriptions.clear();
    _observed.clear();
    super.dispose();
  }
}
