import 'package:flutter/scheduler.dart';
import 'package:flutter/widgets.dart';
import 'package:provider/provider.dart';

/// 用 pub 上的 `provider` 包注入 [ChangeNotifier]，但**补上 build 阶段的相位判断**。
///
/// ## 补的是哪个缺口
///
/// `ChangeNotifierProvider` 走 `ListenableProvider._startListening`，那里直接把
/// 元素的 `markNeedsNotifyDependents` 挂成 listener：
///
/// ```dart
/// value?.addListener(e.markNeedsNotifyDependents);   // listenable_provider.dart:61
/// ```
///
/// 而 `markNeedsNotifyDependents` 是裸的 `markNeedsBuild()`，没有任何相位判断
/// （provider 6.1.5+1，`inherited_provider.dart:585-592`）：
///
/// ```dart
/// void markNeedsNotifyDependents() {
///   if (!_isNotifyDependentsEnabled) return;
///   markNeedsBuild();
///   _shouldNotifyDependents = true;
/// }
/// ```
///
/// 于是控制器只要在**某个 widget 的 build 方法里**发一次通知，就会撞上
/// 「setState() or markNeedsBuild() called during build」。原因在
/// `Element.markNeedsBuild` 的断言：它只放行「本次构建目标在自己之上」的情况
/// （`_debugIsInScope` 是从 `this` 往上找 target），而 provider 元素是发通知那个
/// widget 的**祖先**，方向正好相反，断言不放行。
///
/// 这不是纸上谈兵的场景：页面首帧按数据决定要不要拉刷新、`buildWithController`
/// 里顺手改了个字段、`ListView.builder` 的 itemBuilder 里回填一次缓存——都是在
/// build 阶段发通知。
///
/// 本库自带的引擎在 `FlInheritedElement._handleNotify` 里有这道判断，把兑现推迟
/// 到本帧收尾之后。本类用 [InheritedProvider] 的 `startListening` 钩子把同一道
/// 判断补回 provider 侧——`startListening` 是 provider 导出的公开 API，不需要改它
/// 的源码，也不需要在本库里加任何抽象层。
///
/// ## 用法
///
/// 与 `ChangeNotifierProvider` 同形，直接替换即可：
///
/// ```dart
/// DeferredChangeNotifierProvider<CounterController>(
///   create: (_) => CounterController(),
///   child: const CounterPage(),
/// )
/// ```
///
/// 行为验证见 `test/deferred_notify_test.dart`，那里把「裸
/// `ChangeNotifierProvider` 会抛」和「本类不抛、推迟一帧兑现」两条都钉住了。
class DeferredChangeNotifierProvider<T extends ChangeNotifier>
    extends StatelessWidget {
  const DeferredChangeNotifierProvider({
    required this.create,
    required this.child,
    super.key,
  });

  /// 控制器工厂，只调用一次；返回的实例由本 Widget 在子树销毁时 `dispose`。
  final T Function(BuildContext context) create;

  /// 被注入的子树。
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return InheritedProvider<T>(
      create: create,
      // provider 默认懒创建：没人 read 就不走 create，也就不会 startListening。
      // 而「页面一出现控制器就得在」是本库的前提（生命周期要往它身上转发），
      // 所以关掉懒加载，让 create 在首次 build 就跑。
      lazy: false,
      dispose: (_, T controller) => controller.dispose(),
      // 显式实例化成 <T>：交给推断会按上界给出 <ChangeNotifier>，和
      // StartListening<T> 对不上（InheritedContext<T> 在参数位，不协变）。
      startListening: _startListening<T>,
      child: child,
    );
  }

  /// 把通知折进正常构建流程；build 阶段发来的推迟到本帧收尾之后。
  ///
  /// 返回值是取消订阅的回调，由 provider 在元素卸载时调用。
  static VoidCallback _startListening<T extends ChangeNotifier>(
    // 是 InheritedContext<T?> 而不是 <T>——见 StartListening 的 typedef。
    InheritedContext<T?> element,
    T controller,
  ) {
    // 本帧已经排过一次「收尾后兑现」。同一帧内的后续通知直接合并掉，
    // 与 FlInheritedElement._notifyScheduled 同义。
    bool deferred = false;

    void handleNotify() {
      if (!element.mounted) return;

      if (SchedulerBinding.instance.schedulerPhase ==
          SchedulerPhase.persistentCallbacks) {
        if (deferred) return;
        deferred = true;
        SchedulerBinding.instance.addPostFrameCallback((_) {
          deferred = false;
          // 这期间子树可能已经被卸载了。
          if (element.mounted) element.markNeedsNotifyDependents();
        });
        return;
      }

      // 不在 build 阶段：照常排进构建流程，帧内合并由 markNeedsBuild 自己做。
      element.markNeedsNotifyDependents();
    }

    controller.addListener(handleNotify);
    return () => controller.removeListener(handleNotify);
  }
}
