/// 只为文档里的 [FlPageProvider] 链接而引：真正的依赖方向是单向的，
/// fl_page_provider.dart 引本文件，本文件不反向依赖它。
/// @docImport 'fl_id_versions.dart';
/// @docImport 'fl_page_provider.dart';
library;

import 'dart:async';

import 'package:flutter/scheduler.dart';
import 'package:flutter/widgets.dart';

import '../controller/fl_base_controller.dart';

/// 真正承载控制器的 `InheritedWidget`，由 [FlPageProvider] 铺在子树顶上。
///
/// 查找按**精确泛型**匹配（`getElementForInheritedWidgetOfExactType`），所以
/// `FlInheritedWidget<A>` 找不出 `FlInheritedWidget<B>`，即使 B 是 A 的子类。
class FlInheritedWidget<T extends FlBaseController> extends InheritedWidget {
  /// [controller] 的生命周期由 [FlPageProvider] 管，本 Widget 只负责往下传。
  const FlInheritedWidget({
    required this.controller,
    required super.child,
    super.key,
  });

  /// 被注入的控制器。
  final T controller;

  /// 只有控制器实例本身被换掉才算「Widget 变了」。控制器内部数据变化不走这条
  /// 路径——那是 listener → [FlInheritedElement.notifyClients] 的活。
  @override
  bool updateShouldNotify(FlInheritedWidget<T> oldWidget) =>
      !identical(controller, oldWidget.controller);

  @override
  FlInheritedElement<T> createElement() => FlInheritedElement<T>(this);
}

/// 依赖方登记的「我关心哪些 ID，以及上次见到的版本号」。
class _FlIdDependency {
  /// 全量依赖：任何通知都重建（`context.wc`）。
  _FlIdDependency.all() : versions = null;

  /// ID 粒度依赖。
  _FlIdDependency.ids() : versions = <Enum, int>{};

  /// `null` 表示全量依赖。
  final Map<Enum, int>? versions;

  /// 下一次登记时是否先清空已记录的 ID。
  ///
  /// 由 [resetScheduled] 排的微任务置位，也就是「上一轮登记已经结束了」。依赖方
  /// 一重建就会重新登记一遍自己当前关心的 ID，先清空才能让登记表跟着它当前真正
  /// 关心的那批 ID 走——`ids` 随条件变化时，旧 ID 不清就会永远留在表里。
  bool shouldReset = false;

  /// 已排好一个「本轮登记结束后置位 [shouldReset]」的微任务。
  ///
  /// 同一次 `build` 里可以多次 `selectIds`，那些登记必须**累加**；微任务不会插进
  /// 同步的构建流程，只会在整帧跑完后执行，正好把「一轮登记」框成一帧。
  bool resetScheduled = false;

  bool get isAll => versions == null;
}

/// [FlInheritedWidget] 的 Element，ID 粒度重建的实现所在。
///
/// ## 它是怎么工作的
///
/// `InheritedWidget` 天生只在**自己被重建**时通知依赖方，而 [ChangeNotifier]
/// 发通知时 Widget 树纹丝不动，两者对不上。这个 Element 就是那座桥：
///
/// 1. [mount] 时给控制器挂**唯一一个** listener——无论子树里有多少个依赖方，
///    控制器上永远只有这一个监听者；
/// 2. 控制器发通知 → `markNeedsBuild()`，把「要通知依赖方」这件事排进正常的
///    构建流程，同一帧内多次通知只排一次；通知本身发自 build 阶段时，这一步
///    推迟到本帧收尾之后（见 `_handleNotify`）；
/// 3. [build] 时调用 `notifyClients`，框架逐个回调 [notifyDependent]，
///    **由我们决定每个依赖方到底重不重建**。
///
/// 第 3 步是 ID 粒度的落点。每个依赖方经 [updateDependencies] 登记自己关心的 ID
/// 列表，我们为它存一份「上次见到的版本号」快照；通知到来时逐个比对，只有版本号
/// 真的变了的依赖方才会收到 `didChangeDependencies()`。没登记 ID 的依赖方
/// （`context.wc`）则每次都重建。
///
/// ## 为什么是逐 ID 比对，而不是把版本号哈希成一个 int
///
/// 本库早先的做法是 `Selector<T, int>` + 多项式哈希 `31 * h + v`：把一组 ID 的
/// 版本号压成一个整数，靠整数是否相等来判断要不要重建。那样能用，但多了一个
/// **有损**的中间表示——两次取值相等只是哈希相等，不等价于「这些 ID 都没变」。
/// 实践中触发一次别名要么靠哈希碰撞，要么靠计数器绕回原值，正常代码碰不到；
/// 但这道推理本不必存在。逐 ID 比对配上只增不减的版本号
/// （见 [FlIdVersions.idVersion]）是精确的，不依赖任何关于调用频率的假设，
/// 也省掉了每次通知重算哈希。
///
/// 与 `provider` 的 `Selector` / `context.select` 的完整对比，以及这套机制的代价，
/// 见 `doc/update_engine_design_zh.md`。
class FlInheritedElement<T extends FlBaseController> extends InheritedElement {
  /// 以 [FlInheritedWidget] 为配置创建 Element。
  FlInheritedElement(FlInheritedWidget<T> super.widget);

  /// 已排好一次「通知依赖方」，同一帧内的后续通知直接合并。
  bool _notifyScheduled = false;

  /// 控制器实例被换掉了，本轮所有依赖方无条件重建（版本号快照已失去意义）。
  bool _controllerChanged = false;

  /// 当前配置。[Element.widget] 只声明到 `Widget`，这里收口成一次向下转型。
  FlInheritedWidget<T> get _config => widget as FlInheritedWidget<T>;

  /// 当前注入的控制器。
  T get controller => _config.controller;

  /// [id] 的当前版本号。未注册的 ID 恒为 `0`，见 `FlIdVersions.idVersion`。
  ///
  /// 早先上界只到 `ChangeNotifier`，这里得先用 `Object` 接一手、再 `is FlIdVersions`
  /// 探一道，还配了条断言拦「控制器没混入 FlNotifyMixin」的静默失败。上界收到
  /// [FlBaseController] 之后那种控制器压根构造不出来，运行期探测和断言一并去掉。
  int _versionOf(Enum id) => controller.idVersion(id);

  @override
  void mount(Element? parent, Object? newSlot) {
    // 整棵子树共用这一个 listener，与依赖方数量无关。
    controller.addListener(_handleNotify);
    super.mount(parent, newSlot);
  }

  @override
  void update(FlInheritedWidget<T> newWidget) {
    final T old = controller;
    if (!identical(old, newWidget.controller)) {
      old.removeListener(_handleNotify);
      newWidget.controller.addListener(_handleNotify);
      // 换了控制器，依赖方手上那份版本号快照跟新控制器没有可比性，本轮全部重建。
      _controllerChanged = true;
    }
    super.update(newWidget);
  }

  @override
  void unmount() {
    controller.removeListener(_handleNotify);
    super.unmount();
  }

  void _handleNotify() {
    if (!mounted || _notifyScheduled) return;
    _notifyScheduled = true;

    // 通知发自 build 阶段（controller 在某个 build 方法里改了数据）：此刻
    // markNeedsBuild 会撞上 "setState during build"。推迟到本帧收尾之后再排，
    // 本帧后续的通知已经被 _notifyScheduled 合并掉了。
    //
    // 这道推迟属于 Widget 层：能不能 markNeedsBuild 是 Flutter 的构建约束，
    // 控制器不该为此知道 SchedulerPhase 的存在。
    if (SchedulerBinding.instance.schedulerPhase ==
        SchedulerPhase.persistentCallbacks) {
      SchedulerBinding.instance.addPostFrameCallback((_) {
        // 期间可能已经卸载，或被一次父级重建顺手兑现掉了。
        if (mounted && _notifyScheduled) markNeedsBuild();
      });
      return;
    }

    // 不在这里直接通知依赖方：markNeedsBuild 把它排进正常构建流程，既拿到了
    // 帧内合并，也避免在 ChangeNotifier 的调用栈里重入 Widget 构建。
    markNeedsBuild();
  }

  @override
  Widget build() {
    if (_notifyScheduled) {
      notifyClients(_config);
    }
    return super.build();
  }

  @override
  void notifyClients(FlInheritedWidget<T> oldWidget) {
    super.notifyClients(oldWidget);
    _notifyScheduled = false;
    _controllerChanged = false;
  }

  /// 依赖方登记它关心的 ID。[aspect] 为 `List<Enum>` 时是 ID 粒度，
  /// 其余（含 `null`）一律按全量依赖处理。
  @override
  void updateDependencies(Element dependent, Object? aspect) {
    final Object? current = getDependencies(dependent);
    if (current is _FlIdDependency && current.isAll) {
      // 已经全量依赖，不能再被一次 ID 登记收窄——否则同一个 Widget 里
      // watch 之后再 select，watch 那半边就漏了通知。
      return;
    }
    if (aspect is! List<Enum>) {
      setDependencies(dependent, _FlIdDependency.all());
      return;
    }
    final _FlIdDependency dependency = current is _FlIdDependency
        ? current
        : _FlIdDependency.ids();
    if (dependency.shouldReset) {
      dependency.shouldReset = false;
      dependency.versions!.clear();
    }
    if (!dependency.resetScheduled) {
      dependency.resetScheduled = true;
      // 微任务不打断同步的构建，所以本帧内的多次登记照常累加，下一帧重新登记时
      // 才清空。关键在于它**不问这次重建是谁触发的**：父级带起来的重建同样会让
      // 登记表重来一遍，旧 ID 不会多活一轮。
      // scheduleMicrotask 而不是 Future.microtask：我们只要「排一个微任务」，
      // 不需要那个没人 await 的 Future（discarded_futures 说的就是它）。
      scheduleMicrotask(() {
        dependency
          ..resetScheduled = false
          ..shouldReset = true;
      });
    }
    for (final Enum id in aspect) {
      dependency.versions![id] = _versionOf(id);
    }
    setDependencies(dependent, dependency);
  }

  /// 逐个依赖方决定重不重建——ID 粒度真正生效的地方。
  @override
  void notifyDependent(FlInheritedWidget<T> oldWidget, Element dependent) {
    final Object? dependency = getDependencies(dependent);
    if (dependency is! _FlIdDependency) {
      // 没走我们这套登记（理论上不会发生），保守地重建。
      dependent.didChangeDependencies();
      return;
    }
    if (dependency.isAll || _controllerChanged) {
      dependent.didChangeDependencies();
      return;
    }

    final Map<Enum, int> versions = dependency.versions!;
    var changed = false;
    for (final MapEntry<Enum, int> entry in versions.entries) {
      if (_versionOf(entry.key) != entry.value) {
        changed = true;
        break;
      }
    }
    if (!changed) return;

    for (final Enum id in versions.keys.toList(growable: false)) {
      versions[id] = _versionOf(id);
    }
    dependent.didChangeDependencies();
  }
}
