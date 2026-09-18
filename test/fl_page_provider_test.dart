import 'package:fl_page_provider/fl_page_provider.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

/// 本包的行为契约。
///
/// 这些断言原先只存在于 `example/test/` 里，要经由 example 的页面才跑得到；
/// 这里把它们重写成自包含版本——只依赖本包的公开 API，不需要 example、不需要
/// MaterialApp、不需要路由。包本体的回归护栏应该在这一层。
void main() {
  int countOf(String key) => _builds[key] ?? 0;

  setUp(_builds.clear);

  /// 把 [child] 挂到一个最小可用的树上：Directionality + 控制器。
  ///
  /// [onCreate] 拿得到本次创建的控制器实例。
  Future<void> pumpTree(
    WidgetTester tester,
    Widget child, {
    void Function(LabController controller)? onCreate,
    Key? providerKey,
  }) async {
    await tester.pumpWidget(
      Directionality(
        textDirection: TextDirection.ltr,
        child: FlProviderBuilder<LabController>(
          key: providerKey,
          create: (_) {
            final LabController controller = LabController();
            onCreate?.call(controller);
            return controller;
          },
          builder: (_, _) => child,
        ),
      ),
    );
  }

  group('ID 粒度重建', () {
    const Widget probes = Column(
      children: <Widget>[
        _ReadProbe(),
        _WatchProbe(),
        _SelA(),
        _SelB(),
        _SelAB(),
      ],
    );

    testWidgets('首帧：每个探针各构建一次', (WidgetTester tester) async {
      await pumpTree(tester, probes);

      for (final String id in <String>[
        'read',
        'watch',
        'sel-a',
        'sel-b',
        'sel-ab',
      ]) {
        expect(countOf(id), 1, reason: '$id 应当只构建一次');
      }
    });

    testWidgets('通知 a：只有认领了 a 的重建，read 纹丝不动', (WidgetTester tester) async {
      late LabController controller;
      await pumpTree(
        tester,
        probes,
        onCreate: (LabController c) => controller = c,
      );

      controller.bumpA();
      await tester.pump();

      expect(countOf('read'), 1, reason: 'rc 不建立依赖');
      expect(countOf('sel-b'), 1, reason: 'b 没被通知');
      expect(countOf('watch'), 2);
      expect(countOf('sel-a'), 2);
      expect(countOf('sel-ab'), 2);
      expect(find.text('a=1'), findsOneWidget);
    });

    testWidgets('通知无人认领的 c：只有订了全部 ID 的那个重建', (WidgetTester tester) async {
      late LabController controller;
      await pumpTree(
        tester,
        probes,
        onCreate: (LabController c) => controller = c,
      );

      controller.bumpC();
      await tester.pump();

      expect(countOf('watch'), 2, reason: 'c 也在它订的那批里');
      for (final String id in <String>['read', 'sel-a', 'sel-b', 'sel-ab']) {
        expect(countOf(id), 1, reason: '$id 不该被 c 惊动');
      }
    });

    testWidgets('一次通知推进 a 和 b：认领 [a, b] 的只跳一次', (WidgetTester tester) async {
      late LabController controller;
      await pumpTree(
        tester,
        probes,
        onCreate: (LabController c) => controller = c,
      );

      controller.bumpAB();
      await tester.pump();

      expect(countOf('sel-ab'), 2, reason: '推进两个 ID 仍然只是一次重建');
      expect(countOf('sel-a'), 2);
      expect(countOf('sel-b'), 2);
    });
  });

  group('通知的时机与合并', () {
    testWidgets('同帧连发 3 次，合并成一次重建', (WidgetTester tester) async {
      late LabController controller;
      await pumpTree(
        tester,
        const Column(children: <Widget>[_SelA(), _WatchProbe()]),
        onCreate: (LabController c) => controller = c,
      );

      controller
        ..bumpA()
        ..bumpA()
        ..bumpA();
      await tester.pump();

      expect(countOf('sel-a'), 2, reason: '三次通知被合并');
      expect(countOf('watch'), 2);
      expect(find.text('a=3'), findsOneWidget, reason: '三次推进都算数，只是重建合并了');
    });

    testWidgets('在 build 中通知：不抛 setState during build，推迟一帧兑现', (
      WidgetTester tester,
    ) async {
      final GlobalKey<_FireDuringBuildState> key =
          GlobalKey<_FireDuringBuildState>();
      await pumpTree(
        tester,
        Column(
          children: <Widget>[
            _FireDuringBuild(key: key),
            const _SelA(),
          ],
        ),
      );
      expect(countOf('sel-a'), 1);

      key.currentState!.arm();
      await tester.pump();

      expect(
        tester.takeException(),
        isNull,
        reason: '不该抛 setState during build',
      );
      expect(countOf('sel-a'), 1, reason: '本帧不兑现——此刻 markNeedsBuild 非法');

      await tester.pump();
      expect(countOf('sel-a'), 2, reason: '推迟一帧后照样兑现');
    });

    testWidgets('在帧外的 buildScope 里通知：同样推迟，不撞框架断言', (WidgetTester tester) async {
      // runApp 的初次挂载就是这种 build：Timer.run → attachRootWidget →
      // buildScope，schedulerPhase 还是 idle。只看相位会漏判，通知直接
      // markNeedsBuild 就撞 "called during build"。这里在 pump 之外手动跑一次
      // buildScope 复现同样的相位。
      final GlobalKey<_FireDuringBuildState> key =
          GlobalKey<_FireDuringBuildState>();
      await pumpTree(
        tester,
        Column(
          children: <Widget>[
            _FireDuringBuild(key: key),
            const _SelA(),
          ],
        ),
      );
      expect(countOf('sel-a'), 1);

      key.currentState!.armSilently();
      (key.currentContext! as Element).markNeedsBuild();
      expect(
        SchedulerBinding.instance.schedulerPhase,
        SchedulerPhase.idle,
        reason: '前提：此刻不在帧内',
      );
      tester.binding.buildOwner!.buildScope(tester.binding.rootElement!);

      expect(
        tester.takeException(),
        isNull,
        reason: 'owner.debugBuilding 已经为 true，得走推迟那条路',
      );
      expect(countOf('sel-a'), 1, reason: '这一轮 buildScope 里不兑现');

      // 第一次 pump 跑 post-frame 回调（markNeedsBuild），第二次才真正重建。
      await tester.pump();
      await tester.pump();
      expect(countOf('sel-a'), 2, reason: '推迟之后照样兑现');
    });
  });

  group('依赖登记', () {
    testWidgets('换了 ids 之后，旧 ID 立刻不再触发重建', (WidgetTester tester) async {
      late LabController controller;
      final GlobalKey<_DynamicProbeState> key = GlobalKey<_DynamicProbeState>();
      await pumpTree(
        tester,
        _DynamicProbe(key: key),
        onCreate: (LabController c) => controller = c,
      );

      // 起始认领 a。
      controller.bumpA();
      await tester.pump();
      expect(countOf('dynamic'), 2);

      // 切到认领 b：这一下是父级驱动的重建。
      key.currentState!.observe(LabId.b);
      await tester.pump();
      final int afterSwitch = countOf('dynamic');

      controller.bumpA();
      await tester.pump();
      expect(
        countOf('dynamic'),
        afterSwitch,
        reason: '换了 ids 之后 a 就不是依赖了，不必等下一轮',
      );

      controller.bumpB();
      await tester.pump();
      expect(countOf('dynamic'), afterSwitch + 1, reason: '新 ID 正常生效');
    });
  });

  group('FlSelector 与 FlSelectorView', () {
    testWidgets('FlSelector 的 child 不参与重建', (WidgetTester tester) async {
      late LabController controller;
      await pumpTree(
        tester,
        const _SelectorWithChild(),
        onCreate: (LabController c) => controller = c,
      );
      expect(countOf('selector-builder'), 1);
      expect(countOf('selector-child'), 1);

      controller.bumpA();
      await tester.pump();

      expect(countOf('selector-builder'), 2);
      expect(
        countOf('selector-child'),
        1,
        reason: 'child 是同一个 Widget 实例，子树整棵跳过',
      );
    });

    testWidgets('FlSelectorView 按 observeIds 重建', (WidgetTester tester) async {
      late LabController controller;
      await pumpTree(
        tester,
        const _CountView(),
        onCreate: (LabController c) => controller = c,
      );
      expect(countOf('view'), 1);

      controller.bumpB();
      await tester.pump();
      expect(countOf('view'), 1, reason: 'observeIds 只有 a');

      controller.bumpA();
      await tester.pump();
      expect(countOf('view'), 2);
      expect(find.text('view a=1'), findsOneWidget);
    });
  });

  group('控制器所有权', () {
    testWidgets('create 只跑一次，父级重建不重造', (WidgetTester tester) async {
      int created = 0;
      const Key providerKey = ValueKey<String>('provider');

      await pumpTree(
        tester,
        const _SelA(),
        providerKey: providerKey,
        onCreate: (_) => created++,
      );
      expect(created, 1);

      // 原地重建一次同样的树。
      await pumpTree(
        tester,
        const _SelA(),
        providerKey: providerKey,
        onCreate: (_) => created++,
      );
      expect(created, 1, reason: '控制器要跨父级重建活下来');
    });

    testWidgets('create 抛异常：只跑一次，后续 build 不再重试', (WidgetTester tester) async {
      int calls = 0;
      const Key providerKey = ValueKey<String>('failing');

      Future<void> pumpFailing() => tester.pumpWidget(
        Directionality(
          textDirection: TextDirection.ltr,
          child: FlProviderBuilder<LabController>(
            key: providerKey,
            create: (_) {
              calls++;
              throw StateError('boom');
            },
            builder: (_, _) => const SizedBox.shrink(),
          ),
        ),
      );

      await pumpFailing();
      expect(calls, 1);
      expect(
        '${tester.takeException()}',
        contains('boom'),
        reason: '首次原样抛 create 自己的异常，堆栈也是原始的',
      );

      // 原地重建一次同样的树。
      await pumpFailing();

      expect(calls, 1, reason: '失败是确定性的，重试只会刷屏并重复 create 里的副作用');
      expect(
        '${tester.takeException()}',
        contains('不再重试'),
        reason: '第二次抛的是说明性的 StateError，不是再跑一遍 create',
      );
    });

    testWidgets('热重载清掉失败记录：改好的 create 会重新跑', (WidgetTester tester) async {
      int calls = 0;
      bool shouldFail = true;
      const Key providerKey = ValueKey<String>('reassemble');

      Future<void> pumpIt() => tester.pumpWidget(
        Directionality(
          textDirection: TextDirection.ltr,
          child: FlProviderBuilder<LabController>(
            key: providerKey,
            create: (_) {
              calls++;
              if (shouldFail) throw StateError('boom');
              return LabController();
            },
            builder: (_, _) => const SizedBox.shrink(),
          ),
        ),
      );

      await pumpIt();
      expect(calls, 1);
      tester.takeException();

      // 「改好代码」，再热重载。
      shouldFail = false;
      // 走框架热重载的那条路，但不用 reassembleApplication()：它末尾是
      // `scheduleWarmUpFrame(); await endOfFrame;`，而测试里的帧要靠 pump 驱动，
      // 于是那个 future 永远不完成（拿一棵空树也一样卡死，与本库无关）。
      // buildOwner.reassemble 就是框架热重载时遍历 Element 树的那一步。
      tester.binding.buildOwner!.reassemble(tester.binding.rootElement!);
      await tester.pump();

      expect(calls, 2, reason: 'reassemble 清了失败记录，create 得以重跑');
      expect(tester.takeException(), isNull, reason: '这次 create 成功了');
    });

    testWidgets('子树销毁时控制器被 dispose', (WidgetTester tester) async {
      late LabController controller;
      await pumpTree(
        tester,
        const _SelA(),
        onCreate: (LabController c) => controller = c,
      );
      expect(controller.disposed, isFalse);

      await tester.pumpWidget(const SizedBox.shrink());

      expect(controller.disposed, isTrue);
    });
  });

  group('读取粒度', () {
    testWidgets('rc 取到的和按 ID 订阅拿到的是同一个实例', (WidgetTester tester) async {
      late LabController created;
      late LabController fromRc;
      late LabController fromSelect;

      await pumpTree(
        tester,
        Builder(
          builder: (BuildContext context) {
            fromRc = context.rc<LabController>();
            fromSelect = context.selectIds<LabId, LabController>(const <LabId>[
              LabId.a,
            ]);
            return const SizedBox.shrink();
          },
        ),
        onCreate: (LabController c) => created = c,
      );

      expect(identical(fromRc, created), isTrue);
      expect(identical(fromSelect, created), isTrue);
    });

    testWidgets('找不到 provider 时抛错', (WidgetTester tester) async {
      await tester.pumpWidget(
        Directionality(
          textDirection: TextDirection.ltr,
          child: Builder(
            builder: (BuildContext context) {
              context.rc<LabController>();
              return const SizedBox.shrink();
            },
          ),
        ),
      );

      expect(tester.takeException(), isNotNull);
    });
  });
}

/// 本测试用的 ID。`c` 故意不被任何探针认领。
enum LabId { a, b, c }

class LabController extends FlBaseController<LabId> {
  /// 不经页面直接用时，页面侧的 `onPageInit` 不一定来，这里把注册补上；
  /// 经页面用时 `onPageInit` 会再注册一次，幂等。
  LabController() {
    registerIds(shouldNotifyIds);
  }

  @override
  List<LabId> get shouldNotifyIds => LabId.values;

  int a = 0;
  int b = 0;
  int c = 0;
  bool disposed = false;

  void bumpA() {
    a++;
    notifySingleListener(LabId.a);
  }

  void bumpB() {
    b++;
    notifySingleListener(LabId.b);
  }

  void bumpC() {
    c++;
    notifySingleListener(LabId.c);
  }

  void bumpAB() {
    a++;
    b++;
    notifyMultiListeners(<LabId>[LabId.a, LabId.b]);
  }

  @override
  void dispose() {
    disposed = true;
    super.dispose();
  }
}

/// 各探针的 build 次数，每个用例开头清空。
final Map<String, int> _builds = <String, int>{};

/// 各探针共用的计数入口。
void _count(String key) => _builds[key] = (_builds[key] ?? 0) + 1;

class _ReadProbe extends StatelessWidget {
  const _ReadProbe();

  @override
  Widget build(BuildContext context) {
    _count('read');
    return Text('read a=${context.rc<LabController>().a}');
  }
}

class _WatchProbe extends StatelessWidget {
  const _WatchProbe();

  @override
  Widget build(BuildContext context) {
    _count('watch');
    // 订了全部 ID——任何一次通知都会惊动它。
    final LabController c = context.selectIds<LabId, LabController>(
      LabId.values,
    );
    return Text('watch a=${c.a}');
  }
}

class _SelA extends StatelessWidget {
  const _SelA();

  @override
  Widget build(BuildContext context) {
    _count('sel-a');
    final LabController c = context.selectIds<LabId, LabController>(
      const <LabId>[LabId.a],
    );
    return Text('a=${c.a}');
  }
}

class _SelB extends StatelessWidget {
  const _SelB();

  @override
  Widget build(BuildContext context) {
    _count('sel-b');
    final LabController c = context.selectIds<LabId, LabController>(
      const <LabId>[LabId.b],
    );
    return Text('b=${c.b}');
  }
}

class _SelAB extends StatelessWidget {
  const _SelAB();

  @override
  Widget build(BuildContext context) {
    _count('sel-ab');
    final LabController c = context.selectIds<LabId, LabController>(
      const <LabId>[LabId.a, LabId.b],
    );
    return Text('ab=${c.a}${c.b}');
  }
}

/// 运行时可以切换认领哪个 ID 的探针。
class _DynamicProbe extends StatefulWidget {
  const _DynamicProbe({super.key});

  @override
  State<_DynamicProbe> createState() => _DynamicProbeState();
}

class _DynamicProbeState extends State<_DynamicProbe> {
  LabId _id = LabId.a;

  void observe(LabId id) => setState(() => _id = id);

  @override
  Widget build(BuildContext context) {
    _count('dynamic');
    context.selectIds<LabId, LabController>(<LabId>[_id]);
    return Text('dynamic $_id');
  }
}

/// 在**自己的 build 期间**发通知——正是 markNeedsBuild 非法的那个时刻。
class _FireDuringBuild extends StatefulWidget {
  const _FireDuringBuild({super.key});

  @override
  State<_FireDuringBuild> createState() => _FireDuringBuildState();
}

class _FireDuringBuildState extends State<_FireDuringBuild> {
  bool _armed = false;

  void arm() => setState(() => _armed = true);

  /// 只置位不 setState，让用例自己决定这次 build 由谁、在什么相位触发。
  void armSilently() => _armed = true;

  @override
  Widget build(BuildContext context) {
    if (_armed) {
      _armed = false;
      context.rc<LabController>().bumpA();
    }
    return const SizedBox.shrink();
  }
}

class _SelectorWithChild extends StatelessWidget {
  const _SelectorWithChild();

  @override
  Widget build(BuildContext context) {
    return FlSelector<LabId, LabController>(
      ids: const <LabId>[LabId.a],
      builder: (BuildContext context, LabController c, Widget? child) {
        _count('selector-builder');
        return Column(children: <Widget>[?child, Text('sel a=${c.a}')]);
      },
      child: const _StaticChild(),
    );
  }
}

class _StaticChild extends StatelessWidget {
  const _StaticChild();

  @override
  Widget build(BuildContext context) {
    _count('selector-child');
    return const Text('static');
  }
}

class _CountView extends FlSelectorView<LabId, LabController> {
  const _CountView();

  @override
  List<LabId> get observeIds => const <LabId>[LabId.a];

  @override
  Widget buildWidget(
    BuildContext context,
    LabController controller,
    Widget? child,
  ) {
    _count('view');
    return Text('view a=${controller.a}');
  }
}
