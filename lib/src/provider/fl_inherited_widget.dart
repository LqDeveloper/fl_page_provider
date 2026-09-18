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
/// 本 Widget 手上只有 [create] 这个工厂，**控制器实例归 [FlInheritedElement]**
/// ——造、持、销都在那一层。这正是 `provider` 的形状：`_InheritedProviderScope`
/// 只带一个 `owner`，值由 `_InheritedProviderScopeElement` 在自己的 `build` 里
/// 造出来、在 `unmount` 里释放（`inherited_provider.dart`）。
///
/// 好处是「谁拥有控制器」这件事只有一个答案。Widget 是不可变的配置，父级每次
/// 重建都换一个新实例；把控制器挂在配置上，就得额外回答「配置换了、实例要不要
/// 跟着换」——[FlInheritedElement] 才是跨重建活着的那个对象，控制器挂在它身上，
/// 那个问题从根上就不存在。
///
/// 查找按**精确泛型**匹配（`getElementForInheritedWidgetOfExactType`），所以
/// `FlInheritedWidget<A>` 找不出 `FlInheritedWidget<B>`，即使 B 是 A 的子类。
class FlInheritedWidget<T extends FlBaseController> extends InheritedWidget {
  /// 控制器工厂。调用时机与三条约束见 [FlPageProvider.create]，实例由
  /// [FlInheritedElement] 在首次 `build` 时造出、在 `unmount` 时 `dispose`。
  const FlInheritedWidget({
    required this.create,
    required super.child,
    super.key,
  });

  /// 见 [FlPageProvider.create]。
  final T Function(BuildContext context) create;

  /// 恒为 `false`。
  ///
  /// 控制器归 Element 且一造出来就终身不换，所以父级重建换掉的只是 [create]
  /// 那个闭包——而它在首次 `build` 之后再不会被调用，换与不换对子树没有任何
  /// 可观测差别。通知依赖方一律走 listener → [FlInheritedElement.notifyClients]
  /// 那条路，与 Widget 相等性无关。`provider` 的
  /// `_InheritedProviderScope.updateShouldNotify` 同样直接返回 `false`。
  @override
  bool updateShouldNotify(FlInheritedWidget<T> oldWidget) => false;

  @override
  FlInheritedElement<T> createElement() => FlInheritedElement<T>(this);
}

/// debug 期记录「哪些控制器已被某个 [FlInheritedElement] 认领」。
///
/// **只在 `assert` 内被访问**，所以 release 构建里这张表和所有读写它的代码一起
/// 被树摇掉，零开销。拦的是这件事：同一个实例交给两个 provider 时，先卸载的那个
/// 会把它 `dispose` 掉，另一棵子树于是静默冻结（`FlNotifyMixin.notifyListeners`
/// 开头就是 `if (_disposed) return;`），要等第二个也卸载才撞上 Flutter 的双
/// dispose 断言——报错点离病因隔了一整个页面生命周期。
///
/// 代价：条目在卸载时移除，所以某个 Element 的 `unmount` 若被跳过，debug 下会
/// 残留一个条目。这不是缓存，别把它当缓存读。
final Set<ChangeNotifier> _debugOwnedControllers = <ChangeNotifier>{};

/// 认领成功返回 `true`；已被别人认领则返回 `false`（调用方的 assert 会失败）。
bool _debugClaim(ChangeNotifier controller) =>
    _debugOwnedControllers.add(controller);

bool _debugRelease(ChangeNotifier controller) {
  _debugOwnedControllers.remove(controller);
  return true;
}

/// [controller] 当前是否被某个 [FlInheritedElement] 认领着。
///
/// 只给测试用：那张表是私有的，而「create 失败后没有残留认领」这条保证从外面
/// 观察不到，只能直接问。
@visibleForTesting
bool debugIsOwnedController(ChangeNotifier controller) =>
    _debugOwnedControllers.contains(controller);

/// 依赖方登记的「我关心哪些 ID，以及上次见到的版本号」。
///
/// 只有这一种形态。早先还有一个 `_FlIdDependency.all()`（`versions == null` 表示
/// 「任何通知都重建」），服务于 `context.wc`；`wc` 移除、`selectIds` 转为包内实现
/// 之后它就再没有调用方了，连同 `isAll` 一起删掉了。现在唯一的「无条件重建」路径
/// 是 [FlInheritedElement.notifyDependent] 里那条「压根没登记过」的保守兜底。
class _FlIdDependency {
  /// 已登记的 ID → 登记那一刻的版本号快照。
  final Map<Enum, int> versions = <Enum, int>{};

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
}

/// [FlInheritedWidget] 的 Element：控制器的**所有者**，也是 ID 粒度重建的实现。
///
/// ## 控制器的生死
///
/// 造在自己的首次 [build] 里，销在 [unmount] 里，中间终身不换实例。这是
/// `provider` 的分工：值由 `_InheritedProviderScopeElement` 持有，`lazy: false`
/// 时在它的 `build()` 里读一次 `value` 把创建逼出来，卸载时 `unmount()` 调
/// `_delegateState.dispose()`。本类照搬，只是把「值」收窄成控制器。
///
/// 为什么是 Element 而不是外面套一层 `StatefulWidget`：Element 本就是跨重建
/// 活着的那个对象，控制器挂在它身上，`build` 里一句 `??=` 就够了；`State` 那
/// 一层除了搬运之外不提供任何额外能力，还多一层 Element、多一处「谁真正拥有
/// 控制器」的分歧。
///
/// [FlPageProvider.create] 的两条硬约束也落在本类上：
/// - 不许在 create 里建立 InheritedWidget 依赖，见 [dependOnInheritedElement]；
/// - create 里的同类型查找跳过本层、直接往上找，见
///   [getElementForInheritedWidgetOfExactType]。
///
/// ## ID 粒度重建是怎么工作的
///
/// `InheritedWidget` 天生只在**自己被重建**时通知依赖方，而 [ChangeNotifier]
/// 发通知时 Widget 树纹丝不动，两者对不上。这个 Element 就是那座桥：
///
/// 1. 首次 [build] 造出控制器后给它挂**唯一一个** listener——无论子树里有多少个
///    依赖方，控制器上永远只有这一个监听者；
/// 2. 控制器发通知 → `markNeedsBuild()`，把「要通知依赖方」这件事排进正常的
///    构建流程，同一帧内多次通知只排一次；通知本身发自 build 阶段时，这一步
///    推迟到本帧收尾之后（见 `_handleNotify`）；
/// 3. [build] 时调用 `notifyClients`，框架逐个回调 [notifyDependent]，
///    **由我们决定每个依赖方到底重不重建**。
///
/// 第 3 步是 ID 粒度的落点。每个依赖方经 [updateDependencies] 登记自己关心的 ID
/// 列表，我们为它存一份「上次见到的版本号」快照；通知到来时逐个比对，只有版本号
/// 真的变了的依赖方才会收到 `didChangeDependencies()`。
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
class FlInheritedElement<T extends FlBaseController> extends InheritedElement {
  /// 以 [FlInheritedWidget] 为配置创建 Element。
  FlInheritedElement(FlInheritedWidget<T> super.widget);

  /// 控制器实例，首次 [build] 时由 [FlInheritedWidget.create] 造出。
  ///
  /// 非 `null` 之后就不再变：本类不提供换实例的入口，[FlInheritedWidget.create]
  /// 换了也不重造（与 `provider` 的 `create` 一致）。
  T? _controller;

  /// [FlInheritedWidget.create] 抛过异常就记在这里，之后不再重试。
  ///
  /// 兼作「已经失败过」的标志位——非 `null` 即失败过，不必再单开一个 bool。
  ///
  /// 为什么不重试：`build` 会被反复调用，而 `create` 失败是确定性的（少个
  /// 祖先、参数不对），重试只会把同一个异常每帧再抛一遍，把真正有用的首次
  /// 异常淹没在刷屏里；`create` 里若带副作用（起请求、注册监听、埋点），还会
  /// 跟着重复执行。`provider` 用 `_initError` 做的是同一件事。
  Object? _createError;

  /// 已排好一次「通知依赖方」，同一帧内的后续通知直接合并。
  bool _notifyScheduled = false;

  /// 正在跑 [FlInheritedWidget.create]。只在 `assert` 里置位与复位，release
  /// 构建中没有任何代码写它。
  bool _debugCreating = false;

  /// 当前配置。[Element.widget] 只声明到 `Widget`，这里收口成一次向下转型。
  FlInheritedWidget<T> get _config => widget as FlInheritedWidget<T>;

  /// 当前注入的控制器。
  ///
  /// 首次 [build] 之后恒可读。之前谁都够不到本 Element——子树是在那次 build 里
  /// 才挂上的，而 `create` 自己的同类型查找已被
  /// [getElementForInheritedWidgetOfExactType] 挡到祖先那一层去了。
  T get controller {
    final T? created = _controller;
    if (created != null) return created;
    final Object? failed = _createError;
    if (failed != null) throw StateError(_createFailedMessage(failed));
    throw StateError(
      '$T 的控制器还没造出来就被读取了。create 不能读它自己正在创建的那个控制器；'
      '要读**祖先**的同类型控制器请用 context.rc<$T>()——它在 create 里会跳过'
      '本层，直接往上找。',
    );
  }

  /// [id] 的当前版本号。未注册的 ID 恒为 `0`，见 `FlIdVersions.idVersion`。
  ///
  /// 早先上界只到 `ChangeNotifier`，这里得先用 `Object` 接一手、再 `is FlIdVersions`
  /// 探一道，还配了条断言拦「控制器没混入 FlNotifyMixin」的静默失败。上界收到
  /// [FlBaseController] 之后那种控制器压根构造不出来，运行期探测和断言一并去掉。
  int _versionOf(Enum id) => controller.idVersion(id);

  /// 跳过本 Element 自己，从父级开始往上找。
  ///
  /// `Element._updateInheritance` 把 `InheritedElement` 自己也放进了它那份
  /// `_inheritedElements`，所以不覆写的话，`create(context)` 里一句
  /// `context.rc<T>()`（T 与本层同类型——同类型页面嵌套时很自然）会命中**本层**，
  /// 去读一个还没造出来的控制器。覆写之后同类型查找拿到的是祖先那一层，与
  /// create 之外的语义完全一致。`provider` 在 `_InheritedProviderScopeElement`
  /// 上覆写这个方法，为的是同一件事。
  ///
  /// 只影响「以本 Element 作为 context」的查找，也就是 `create` 那一次；子树里
  /// 的依赖方用的是它们自己那个 Element 的同名方法，照常能找到本层。
  @override
  InheritedElement?
  getElementForInheritedWidgetOfExactType<W extends InheritedWidget>() {
    InheritedElement? found;
    visitAncestorElements((Element parent) {
      if (parent.widget.runtimeType == W) {
        found = parent as InheritedElement;
      } else {
        found = parent.getElementForInheritedWidgetOfExactType<W>();
      }
      // 只看直接父级：往上找的活由它那份 _inheritedElements 一次做完。
      return false;
    });
    return found;
  }

  /// 在 [FlInheritedWidget.create] 期间上一道「不许建立 InheritedWidget 依赖」的锁。
  ///
  /// 为什么要拦：`create` 跑在本 Element 的 `build` 里，所以在它里面调
  /// `Theme.of(context)` 是一次**合法**的依赖登记，不报错。但 `create` 只跑这一
  /// 次，Theme 变了只会让本 Element 白重建一遍，控制器手上那份值永远停在创建那
  /// 一刻——没有异常，没有日志，只有一块静默过期的数据。`provider` 对同一件事的
  /// 处理是在 `create` 期间锁死 `dependOnInheritedElement`
  /// （`_debugInheritLocked`，见 `inherited_provider.dart`），本类照搬。
  ///
  /// 拦得住的是 `dependOnInheritedWidgetOfExactType` 那条路（它内部就是转调本
  /// 方法）；`context.rc` 走的 [getElementForInheritedWidgetOfExactType] 不经过
  /// 这里，也不该经过——它压根不建立依赖，在 `create` 里读祖先控制器正是本库
  /// 推荐的写法。
  @override
  InheritedWidget dependOnInheritedElement(
    InheritedElement ancestor, {
    Object? aspect,
  }) {
    assert(
      !_debugCreating,
      '$T 的 create 里建立了对 ${ancestor.widget.runtimeType} 的依赖'
      '（Theme.of / MediaQuery.of 这类查找）。\n'
      'create 只在首帧 build 时调用一次，依赖建得成，但它永远不会让 create 重跑'
      '——控制器会静默停在创建那一刻的旧值上，不报错，也没有日志。\n'
      '读祖先控制器请用 context.rc<X>()，它不建立依赖；确实要跟着 Theme / '
      'MediaQuery 变化的值，别在 create 里定格，改成在 build 里取好、按需传进'
      '控制器的方法。',
    );
    return super.dependOnInheritedElement(ancestor, aspect: aspect);
  }

  @override
  Widget build() {
    _ensureController();
    if (_notifyScheduled) {
      notifyClients(_config);
    }
    return super.build();
  }

  /// 首次 [build] 造控制器，之后每次 build 直接返回。
  ///
  /// 时机上等价于 `provider` 的 `lazy: false`——它在
  /// `_InheritedProviderScopeElement.build` 里读一次 `value` 把创建逼出来，本库
  /// 是这一句 `??=`。本库不提供 `lazy` 那档开关，理由见 [FlPageProvider.create]。
  void _ensureController() {
    if (_controller != null) return;
    final Object? failed = _createError;
    if (failed != null) throw StateError(_createFailedMessage(failed));
    // 锁只在 debug 期存在：置位与复位都写在 assert 里，release 构建中这两行连同
    // 锁本身一起被树摇掉，create 的调用路径上不剩任何判断。
    assert(_debugSetCreating(true));
    try {
      // 传 this：create 拿到的 context 就是本 Element，与 provider 传
      // `element!` 一致。同类型的自查找已被 getElementForInheritedWidgetOfExactType
      // 挡开，建立依赖则被上面那道锁拦下。
      final T created = _config.create(this);
      // listener 挂在这里而不是 mount 里：mount 早于首次 build，那时控制器还不
      // 存在。provider 挂 ChangeNotifier 的 listener（`startListening`）同样在
      // `_CreateInheritedProviderState.build` 里，也晚于 mount。
      //
      // 先挂 listener、后认领：addListener 是这段里唯一还可能抛的调用（create
      // 返回了一个已经 dispose 过的实例时，debug 期它会断言）。认领若排在它
      // 前面，抛出来的那一刻实例已进了 _debugOwnedControllers、_controller 却
      // 还是 null，unmount 那条 `if (created != null)` 不会替它释放——一个被
      // 全局 Set 强引用到进程结束的控制器。
      created.addListener(_handleNotify);
      assert(
        () {
          if (_debugClaim(created)) return true;
          // 认领失败：这个实例归别的 provider，刚挂上的 listener 得先摘掉，
          // 否则它每发一次通知都会把本 Element（此时是 ErrorWidget）拉起来重建，
          // 再把那条「不再重试」的 StateError 重抛一遍。
          created.removeListener(_handleNotify);
          return false;
        }(),
        '$T 的这个实例已经被另一个 FlPageProvider 认领了。所有权是单向的：'
        'create 返回什么，这一层就在子树销毁时 dispose 什么——两个 provider 拿'
        '同一个实例，先卸载的那个会把它 dispose 掉，另一棵子树的 UI 会静默冻结。'
        '请让每个 provider 的 create 各自新建一个实例；确实要共享状态就把它提到'
        '共同的祖先上，只铺一个 provider。',
      );
      _controller = created;
    } catch (error) {
      // rethrow 保留原始堆栈，首次失败的上报内容与「没有这层记录」时完全一致。
      _createError = error;
      rethrow;
    } finally {
      // create 抛出来时也要复位：锁留着不放，本 Element 之后每一次正常的
      // Theme.of 都会被误拦。
      assert(_debugSetCreating(false));
    }
  }

  String _createFailedMessage(Object failed) =>
      '$T 的 create 在更早的一次 build 里抛了异常，本 provider 不再重试。\n'
      '首次那个异常已经被完整上报过（含堆栈），请从那里查起——在这里重复抛'
      '只会把它淹掉，create 里的副作用也会跟着重复执行。\n'
      '原始异常：$failed\n'
      '改好之后热重载即可重试，或者重新进入这个页面。';

  /// 把 [_debugCreating] 置成 [value]，恒返回 `true`，好让调用点写成
  /// `assert(_debugSetCreating(...))`——整句在 release 构建里一起消失。
  bool _debugSetCreating(bool value) {
    _debugCreating = value;
    return true;
  }

  @override
  void reassemble() {
    // 热重载时清掉失败记录，给刚改过的 create 一次重试机会——否则改对了也要整
    // 重启才看得到。`reassemble` 只在 debug 期被框架调用；provider 没有这一手，
    // 它的 `_initError` 要等整重启才清。
    _createError = null;
    super.reassemble();
  }

  @override
  void unmount() {
    final T? created = _controller;
    if (created != null) {
      // 先摘 listener 再 dispose：反了的话 dispose 之后还去动 ChangeNotifier，
      // debug 期会撞断言。
      created.removeListener(_handleNotify);
      assert(_debugRelease(created));
      created.dispose();
    }
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
    //
    // 「正在 build」不只发生在帧里。runApp 的初次挂载走 Timer.run →
    // attachRootWidget → buildScope，那时 schedulerPhase 还是 idle；测试里手动
    // buildScope 也一样。这些场合只看相位会漏判，通知直接 markNeedsBuild 就撞
    // 框架那道断言。所以再问一句 owner.debugBuilding——它是 debug-only 的，而
    // markNeedsBuild 那道断言本身也是 debug-only 的，两者正好对齐：release 下
    // 没有断言可撞，scheduleBuildFor 会把本 Element 塞进同一个 buildScope 补建。
    bool building =
        SchedulerBinding.instance.schedulerPhase ==
        SchedulerPhase.persistentCallbacks;
    assert(() {
      building = building || (owner?.debugBuilding ?? false);
      return true;
    }());
    if (building) {
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
  void notifyClients(FlInheritedWidget<T> oldWidget) {
    super.notifyClients(oldWidget);
    _notifyScheduled = false;
  }

  /// 依赖方登记它关心的 ID。[aspect] 必须是 `List<Enum>`。
  ///
  /// 包内唯一的调用方是 `context.selectIds`（经 [FlPageProvider.of]），它一定传
  /// ID 列表。其余 aspect 只可能来自「绕开公开 API 直接对本 Element 调
  /// `dependOnInheritedElement`」，debug 期断言拦下，release 期按「没登记过」处理
  /// ——那条路在 [notifyDependent] 里是无条件重建，宁可多重建，不可漏重建。
  @override
  void updateDependencies(Element dependent, Object? aspect) {
    final Object? current = getDependencies(dependent);
    if (aspect is! List<Enum>) {
      assert(
        false,
        'FlInheritedElement 收到了不是 List<Enum> 的 aspect（${aspect.runtimeType}）。'
        '按 ID 订阅请用 FlSelector / FlSelectorView，不要直接对本 Element 调 '
        'dependOnInheritedElement。本次登记按「无条件重建」兜底。',
      );
      // 登记成框架默认的 null：notifyDependent 那边的 `is! _FlIdDependency`
      // 分支会让它每次通知都重建。
      setDependencies(dependent, null);
      return;
    }
    final _FlIdDependency dependency = current is _FlIdDependency
        ? current
        : _FlIdDependency();
    if (dependency.shouldReset) {
      dependency.shouldReset = false;
      dependency.versions.clear();
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
      dependency.versions[id] = _versionOf(id);
    }
    setDependencies(dependent, dependency);
  }

  /// 逐个依赖方决定重不重建——ID 粒度真正生效的地方。
  @override
  void notifyDependent(FlInheritedWidget<T> oldWidget, Element dependent) {
    final Object? dependency = getDependencies(dependent);
    if (dependency is! _FlIdDependency) {
      // 没走我们这套登记：要么是绕开公开 API 传了非法 aspect（updateDependencies
      // 已经断言过），要么是将来新增了别的登记形态。保守地重建。
      dependent.didChangeDependencies();
      return;
    }

    final Map<Enum, int> versions = dependency.versions;
    var changed = false;
    for (final MapEntry<Enum, int> entry in versions.entries) {
      if (_versionOf(entry.key) != entry.value) {
        changed = true;
        break;
      }
    }
    if (!changed) return;

    // 不必先 toList：Dart 的 Map 迭代器只在**结构性**修改（增删 key）时抛
    // ConcurrentModificationError，而这里所有 key 都来自 versions 自己，
    // 只改值不动键。往里写新 key 的话就得把 toList 加回来。
    for (final Enum id in versions.keys) {
      versions[id] = _versionOf(id);
    }
    dependent.didChangeDependencies();
  }
}
