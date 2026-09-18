import 'package:fl_page_provider/fl_page_provider.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

/// 依赖登记这一侧的契约：门禁断言拦不拦得住、多次登记怎么累加，
/// 以及 `FlSelector` / `FlSelectorView` 的 child。
void main() {
  int countOf(String key) => _builds[key] ?? 0;

  setUp(_builds.clear);

  Future<_SelController> pumpTree(WidgetTester tester, Widget child) async {
    late _SelController controller;
    await tester.pumpWidget(
      Directionality(
        textDirection: TextDirection.ltr,
        child: FlProviderBuilder<_SelController>(
          create: (_) => controller = _SelController(),
          builder: (_, _) => child,
        ),
      ),
    );
    return controller;
  }

  group('门禁断言', () {
    testWidgets('selectIds 传空列表会断言', (WidgetTester tester) async {
      await pumpTree(tester, const _EmptySelect());

      expect(tester.takeException(), isAssertionError);
    });

    testWidgets('selectIds 传未注册的 ID 会断言', (WidgetTester tester) async {
      await pumpTree(tester, const _GhostSelect());

      expect(tester.takeException(), isAssertionError);
    });

    testWidgets('FlSelector 传空 ids 会断言', (WidgetTester tester) async {
      await pumpTree(
        tester,
        FlSelector<_Id, _SelController>(
          ids: const <_Id>[],
          builder: (_, _, _) => const SizedBox.shrink(),
        ),
      );

      expect(tester.takeException(), isAssertionError);
    });

    testWidgets('FlSelector 传未注册的 ids 会断言', (WidgetTester tester) async {
      await pumpTree(
        tester,
        FlSelector<_Id, _SelController>(
          ids: const <_Id>[_Id.ghost],
          builder: (_, _, _) => const SizedBox.shrink(),
        ),
      );

      expect(tester.takeException(), isAssertionError);
    });

    testWidgets('FlSelectorView 的 observeIds 未注册同样会断言', (
      WidgetTester tester,
    ) async {
      await pumpTree(tester, const _GhostView());

      expect(tester.takeException(), isAssertionError);
    });
  });

  group('同一个 build 里多次登记', () {
    testWidgets('两次 selectIds：两个 ID 都算数', (WidgetTester tester) async {
      final _SelController controller = await pumpTree(
        tester,
        const _TwiceSelect(),
      );
      expect(countOf('twice'), 1);

      controller.bump(_Id.a);
      await tester.pump();
      expect(countOf('twice'), 2);

      controller.bump(_Id.b);
      await tester.pump();
      expect(countOf('twice'), 3, reason: '第二次登记没把第一次挤掉');

      controller.bump(_Id.c);
      await tester.pump();
      expect(countOf('twice'), 3, reason: '没登记的 ID 仍然不该惊动它');
    });
  });

  group('放在条件分支里的 selectIds', () {
    testWidgets('条件关掉之后，旧 ID 仍然会白白触发重建', (WidgetTester tester) async {
      final GlobalKey<_ConditionalSelectState> key =
          GlobalKey<_ConditionalSelectState>();
      final _SelController controller = await pumpTree(
        tester,
        _ConditionalSelect(key: key),
      );
      expect(countOf('conditional'), 1);

      controller.bump(_Id.b);
      await tester.pump();
      expect(countOf('conditional'), 2);

      // 关掉条件：这一帧压根不会调 selectIds，于是登记表没有机会被重置。
      key.currentState!.turnOff();
      await tester.pump();
      expect(countOf('conditional'), 3);

      controller.bump(_Id.b);
      await tester.pump();
      controller.bump(_Id.b);
      await tester.pump();

      expect(
        countOf('conditional'),
        5,
        reason:
            'Flutter 只在 Element.deactivate 时解依赖，这是文档里点名的坑，'
            '不是回归——要躲开请无条件调用，或把那一块拆成独立 Widget。',
      );
    });
  });

  group('child 不参与重建', () {
    testWidgets('FlSelectorView 的 staticChild 只构建一次', (
      WidgetTester tester,
    ) async {
      final _SelController controller = await pumpTree(
        tester,
        const _ViewWithStaticChild(),
      );
      expect(countOf('view'), 1);
      expect(countOf('static'), 1);

      controller.bump(_Id.a);
      await tester.pump();

      expect(countOf('view'), 2);
      expect(countOf('static'), 1, reason: '同一个实例，子树整棵跳过');
      expect(find.text('static-child'), findsOneWidget);
    });

    testWidgets('不传 child 时 builder 拿到 null', (WidgetTester tester) async {
      Widget? seen = const SizedBox.shrink();
      await pumpTree(
        tester,
        FlSelector<_Id, _SelController>(
          ids: const <_Id>[_Id.a],
          builder: (_, _, Widget? child) {
            seen = child;
            return const SizedBox.shrink();
          },
        ),
      );

      expect(seen, isNull);
    });

    testWidgets('FlSelectorView 默认的 staticChild 是 null', (
      WidgetTester tester,
    ) async {
      await pumpTree(tester, const _ViewWithoutChild());

      expect(_lastChild, isNull);
    });

    testWidgets('父级重建时：同一个实例才跳得过子树，每次现 new 的跟着重建', (WidgetTester tester) async {
      // 按 ID 的通知只重建 FlSelector 那一层，staticChild 压根不会被重新取值
      // ——上一条用例验的就是它。这条验的是另一半：父级把整个 view 重建掉时，
      // 「每次返回同一个实例」这个要求才真正起作用。
      final GlobalKey<_RebuildHostState> key = GlobalKey<_RebuildHostState>();
      await pumpTree(tester, _RebuildHost(key: key));
      expect(countOf('static'), 1);
      expect(countOf('fresh'), 1);

      key.currentState!.rebuild();
      await tester.pump();

      expect(
        countOf('static'),
        1,
        reason: 'const 实例，Flutter 见到同一个 Widget 直接跳过那棵子树',
      );
      expect(countOf('fresh'), 2, reason: '每次取值都新建一个，等于没优化——文档里点名的写法');
    });
  });

  group('ids 自身的形态', () {
    testWidgets('同一个 ID 写两遍：不出问题，也不会重建两次', (WidgetTester tester) async {
      final _SelController controller = await pumpTree(
        tester,
        const _DuplicatedIdsSelect(),
      );
      expect(countOf('dup'), 1);

      controller.bump(_Id.a);
      await tester.pump();

      expect(countOf('dup'), 2);
    });

    testWidgets('运行期拼出来的 ids 一样生效（不必是 const）', (WidgetTester tester) async {
      final _SelController controller = await pumpTree(
        tester,
        const _RuntimeIdsSelect(),
      );

      controller.bump(_Id.b);
      await tester.pump();
      expect(countOf('runtime'), 2);

      controller.bump(_Id.c);
      await tester.pump();
      expect(countOf('runtime'), 2, reason: 'c 不在拼出来的那批里');
    });
  });

  group('兄弟子树各自的 provider', () {
    testWidgets('通知只落在自己那棵子树上', (WidgetTester tester) async {
      late _SelController left;
      late _SelController right;

      await tester.pumpWidget(
        Directionality(
          textDirection: TextDirection.ltr,
          child: Column(
            children: <Widget>[
              FlProviderBuilder<_SelController>(
                create: (_) => left = _SelController(),
                builder: (_, _) => const _Probe('left'),
              ),
              FlProviderBuilder<_SelController>(
                create: (_) => right = _SelController(),
                builder: (_, _) => const _Probe('right'),
              ),
            ],
          ),
        ),
      );
      expect(countOf('left'), 1);
      expect(countOf('right'), 1);
      expect(identical(left, right), isFalse);

      left.bump(_Id.a);
      await tester.pump();

      expect(countOf('left'), 2);
      expect(countOf('right'), 1, reason: '同类型的兄弟 provider 互不相干');
    });
  });

  group('拿到的就是 provider 里那个实例', () {
    testWidgets('FlSelector 的 builder 与 FlSelectorView 的 buildWidget 都是', (
      WidgetTester tester,
    ) async {
      _SelController? fromSelector;
      final _SelController created = await pumpTree(
        tester,
        FlSelector<_Id, _SelController>(
          ids: const <_Id>[_Id.a],
          builder: (_, _SelController c, _) {
            fromSelector = c;
            return const SizedBox.shrink();
          },
        ),
      );

      expect(identical(fromSelector, created), isTrue);
    });
  });
}

enum _Id { a, b, c, ghost }

/// `ghost` 故意不注册。
class _SelController extends FlBaseController<_Id> {
  _SelController() {
    registerIds(shouldNotifyIds);
  }

  @override
  List<_Id> get shouldNotifyIds => const <_Id>[_Id.a, _Id.b, _Id.c];

  int value = 0;

  void bump(_Id id) {
    value++;
    notifySingleListener(id);
  }
}

final Map<String, int> _builds = <String, int>{};

void _count(String key) => _builds[key] = (_builds[key] ?? 0) + 1;

Widget? _lastChild = const SizedBox.shrink();

class _EmptySelect extends StatelessWidget {
  const _EmptySelect();

  @override
  Widget build(BuildContext context) {
    context.selectIds<_Id, _SelController>(const <_Id>[]);
    return const SizedBox.shrink();
  }
}

class _GhostSelect extends StatelessWidget {
  const _GhostSelect();

  @override
  Widget build(BuildContext context) {
    context.selectIds<_Id, _SelController>(const <_Id>[_Id.ghost]);
    return const SizedBox.shrink();
  }
}

class _GhostView extends FlSelectorView<_Id, _SelController> {
  const _GhostView();

  @override
  List<_Id> get observeIds => const <_Id>[_Id.ghost];

  @override
  Widget buildWidget(
    BuildContext context,
    _SelController controller,
    Widget? child,
  ) => const SizedBox.shrink();
}

class _TwiceSelect extends StatelessWidget {
  const _TwiceSelect();

  @override
  Widget build(BuildContext context) {
    _count('twice');
    context.selectIds<_Id, _SelController>(const <_Id>[_Id.a]);
    context.selectIds<_Id, _SelController>(const <_Id>[_Id.b]);
    return const SizedBox.shrink();
  }
}

/// 把 `selectIds` 放在 if 里——文档里明说不要这么写的那种写法。
class _ConditionalSelect extends StatefulWidget {
  const _ConditionalSelect({super.key});

  @override
  State<_ConditionalSelect> createState() => _ConditionalSelectState();
}

class _ConditionalSelectState extends State<_ConditionalSelect> {
  bool _on = true;

  void turnOff() => setState(() => _on = false);

  @override
  Widget build(BuildContext context) {
    _count('conditional');
    if (_on) {
      context.selectIds<_Id, _SelController>(const <_Id>[_Id.b]);
    }
    return const SizedBox.shrink();
  }
}

class _ViewWithStaticChild extends FlSelectorView<_Id, _SelController> {
  const _ViewWithStaticChild();

  @override
  List<_Id> get observeIds => const <_Id>[_Id.a];

  @override
  Widget? get staticChild => const _StaticChild();

  @override
  Widget buildWidget(
    BuildContext context,
    _SelController controller,
    Widget? child,
  ) {
    _count('view');
    return Column(children: <Widget>[?child, Text('v=${controller.value}')]);
  }
}

class _StaticChild extends StatelessWidget {
  const _StaticChild();

  @override
  Widget build(BuildContext context) {
    _count('static');
    return const Text('static-child');
  }
}

/// 每次取值都新建一个 child——文档里说的「等于没优化」那种写法。
class _ViewWithFreshChild extends FlSelectorView<_Id, _SelController> {
  const _ViewWithFreshChild();

  @override
  List<_Id> get observeIds => const <_Id>[_Id.a];

  // 故意不写 const：每次取值都是一个新实例，这正是本用例要验的写法。
  @override
  // ignore: prefer_const_constructors
  Widget? get staticChild => _FreshChild();

  @override
  Widget buildWidget(
    BuildContext context,
    _SelController controller,
    Widget? child,
  ) => Column(children: <Widget>[?child]);
}

class _FreshChild extends StatelessWidget {
  const _FreshChild();

  @override
  Widget build(BuildContext context) {
    _count('fresh');
    return const Text('fresh-child');
  }
}

/// 能被外部驱动重建的宿主，两个 view 都**不写 const**，才会跟着一起重建。
class _RebuildHost extends StatefulWidget {
  const _RebuildHost({super.key});

  @override
  State<_RebuildHost> createState() => _RebuildHostState();
}

class _RebuildHostState extends State<_RebuildHost> {
  int _tick = 0;

  void rebuild() => setState(() => _tick++);

  @override
  Widget build(BuildContext context) {
    return Column(
      children: <Widget>[
        Text('tick $_tick'),
        // ignore: prefer_const_constructors
        _ViewWithStaticChild(),
        // ignore: prefer_const_constructors
        _ViewWithFreshChild(),
      ],
    );
  }
}

class _DuplicatedIdsSelect extends StatelessWidget {
  const _DuplicatedIdsSelect();

  @override
  Widget build(BuildContext context) {
    _count('dup');
    context.selectIds<_Id, _SelController>(const <_Id>[_Id.a, _Id.a]);
    return const SizedBox.shrink();
  }
}

class _RuntimeIdsSelect extends StatelessWidget {
  const _RuntimeIdsSelect();

  @override
  Widget build(BuildContext context) {
    _count('runtime');
    context.selectIds<_Id, _SelController>(<_Id>[_Id.values.first, _Id.b]);
    return const SizedBox.shrink();
  }
}

class _Probe extends StatelessWidget {
  const _Probe(this.tag);

  final String tag;

  @override
  Widget build(BuildContext context) {
    _count(tag);
    context.selectIds<_Id, _SelController>(const <_Id>[_Id.a]);
    return const SizedBox.shrink();
  }
}

class _ViewWithoutChild extends FlSelectorView<_Id, _SelController> {
  const _ViewWithoutChild();

  @override
  List<_Id> get observeIds => const <_Id>[_Id.a];

  @override
  Widget buildWidget(
    BuildContext context,
    _SelController controller,
    Widget? child,
  ) {
    _lastChild = child;
    return const SizedBox.shrink();
  }
}
