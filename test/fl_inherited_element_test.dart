import 'package:fl_page_provider/fl_page_provider.dart';
// 本文件要验的是 Element 这一层的契约，而 FlInheritedWidget 是包内实现、不出口，
// 只能从 src 直接引。同包内的 src 引用不受 implementation_imports 约束。
import 'package:fl_page_provider/src/provider/fl_inherited_widget.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

/// `FlInheritedElement` 这一层的契约：控制器上到底挂了几个 listener、什么时候
/// 摘掉，以及控制器实例被换掉那一下——版本号快照失效，本轮必须全员重建。
///
/// 换实例这条路径从公开 API 走不到（`FlPageProvider` 的 `create` 只跑一次，
/// 控制器不会中途更换），所以这里直接铺一个 `FlInheritedWidget` 来驱动它。
/// 它不是「用不上的分支」：没有它，任何将来允许换控制器的入口都会静默地把
/// 依赖方留在旧数据上。
void main() {
  int countOf(String key) => _builds[key] ?? 0;

  setUp(_builds.clear);

  Widget host(Widget child) =>
      Directionality(textDirection: TextDirection.ltr, child: child);

  group('控制器上只挂一个 listener', () {
    testWidgets('子树里有多少依赖方，控制器上都只有一个监听者', (WidgetTester tester) async {
      late _SwapController controller;
      await tester.pumpWidget(
        host(
          FlProviderBuilder<_SwapController>(
            create: (_) => controller = _SwapController(),
            builder: (_, _) => const Column(
              children: <Widget>[_SelA(), _SelB(), _WatchProbe(), _SelA()],
            ),
          ),
        ),
      );

      expect(
        controller.listenerCount,
        1,
        reason: '整棵子树共用 Element 挂的那一个 listener',
      );
    });

    testWidgets('子树卸载时 listener 被摘掉，且早于 controller.dispose', (
      WidgetTester tester,
    ) async {
      late _SwapController controller;
      await tester.pumpWidget(
        host(
          FlProviderBuilder<_SwapController>(
            create: (_) => controller = _SwapController(),
            builder: (_, _) => const _SelA(),
          ),
        ),
      );
      expect(controller.listenerCount, 1);

      await tester.pumpWidget(host(const SizedBox.shrink()));

      expect(controller.listenerCount, 0, reason: 'unmount 里 removeListener');
      expect(controller.listenerCountAtDispose, 0, reason: '摘干净了才轮到 dispose');
      expect(controller.disposed, isTrue);
    });
  });

  group('updateShouldNotify', () {
    test('只认控制器实例本身，child 换了不算', () {
      final _SwapController a = _SwapController();
      final _SwapController b = _SwapController();
      addTearDown(a.dispose);
      addTearDown(b.dispose);

      const Widget child = SizedBox.shrink();
      final FlInheritedWidget<_SwapController> first =
          FlInheritedWidget<_SwapController>(controller: a, child: child);

      expect(
        first.updateShouldNotify(
          FlInheritedWidget<_SwapController>(
            controller: a,
            child: const Text('别的 child', textDirection: TextDirection.ltr),
          ),
        ),
        isFalse,
      );
      expect(
        first.updateShouldNotify(
          FlInheritedWidget<_SwapController>(controller: b, child: child),
        ),
        isTrue,
      );
    });
  });

  group('换控制器实例', () {
    testWidgets('本轮所有依赖方无条件重建——版本号两边都是 0 也一样', (WidgetTester tester) async {
      final _SwapController first = _SwapController();
      final _SwapController second = _SwapController()..value = 99;
      addTearDown(first.dispose);
      addTearDown(second.dispose);
      final GlobalKey<_SwapHostState> key = GlobalKey<_SwapHostState>();

      await tester.pumpWidget(
        host(
          _SwapHost(
            key: key,
            initial: first,
            child: const Column(children: <Widget>[_SelA(), _SelB()]),
          ),
        ),
      );
      expect(countOf('sel-a'), 1);
      expect(countOf('sel-b'), 1);

      key.currentState!.swap(second);
      await tester.pump();

      expect(countOf('sel-a'), 2, reason: '快照是对着旧控制器记的，跟新控制器没有可比性');
      expect(
        countOf('sel-b'),
        2,
        reason: 'b 的版本号两边都是 0，逐 ID 比对会得出「没变」——必须由换实例这条路兜住',
      );
      expect(find.text('a=99'), findsOneWidget);
    });

    testWidgets('listener 跟着迁移：旧实例的通知不再作数，新实例的才算', (WidgetTester tester) async {
      final _SwapController first = _SwapController();
      final _SwapController second = _SwapController();
      addTearDown(first.dispose);
      addTearDown(second.dispose);
      final GlobalKey<_SwapHostState> key = GlobalKey<_SwapHostState>();

      await tester.pumpWidget(
        host(_SwapHost(key: key, initial: first, child: const _SelA())),
      );
      expect(first.listenerCount, 1);

      key.currentState!.swap(second);
      await tester.pump();
      expect(first.listenerCount, 0);
      expect(second.listenerCount, 1);
      final int afterSwap = countOf('sel-a');

      first.bumpA();
      await tester.pump();
      expect(countOf('sel-a'), afterSwap, reason: '旧控制器已经没人听了');

      second.bumpA();
      await tester.pump();
      expect(countOf('sel-a'), afterSwap + 1);
    });

    testWidgets('换实例只让本轮全员重建，下一轮回到 ID 粒度', (WidgetTester tester) async {
      final _SwapController first = _SwapController();
      final _SwapController second = _SwapController();
      addTearDown(first.dispose);
      addTearDown(second.dispose);
      final GlobalKey<_SwapHostState> key = GlobalKey<_SwapHostState>();

      await tester.pumpWidget(
        host(
          _SwapHost(
            key: key,
            initial: first,
            child: const Column(children: <Widget>[_SelA(), _SelB()]),
          ),
        ),
      );
      key.currentState!.swap(second);
      await tester.pump();
      final int aAfterSwap = countOf('sel-a');
      final int bAfterSwap = countOf('sel-b');

      second.bumpA();
      await tester.pump();

      expect(countOf('sel-a'), aAfterSwap + 1);
      expect(
        countOf('sel-b'),
        bAfterSwap,
        reason: '_controllerChanged 是一次性的，通知完就复位',
      );
    });
  });

  group('排期与卸载', () {
    testWidgets('通知已排期，依赖方在兑现之前被移除：不抛', (WidgetTester tester) async {
      late _SwapController controller;
      await tester.pumpWidget(
        host(
          FlProviderBuilder<_SwapController>(
            create: (_) => controller = _SwapController(),
            builder: (_, _) => const _SelA(),
          ),
        ),
      );

      // 通知发出去了（已 markNeedsBuild），但这一帧还没跑就把整棵树换掉。
      controller.bumpA();
      await tester.pumpWidget(host(const SizedBox.shrink()));

      expect(tester.takeException(), isNull);
      expect(controller.disposed, isTrue);
    });

    testWidgets('控制器 dispose 之后再通知：闸在控制器那一侧，Element 收不到', (
      WidgetTester tester,
    ) async {
      late _SwapController controller;
      await tester.pumpWidget(
        host(
          FlProviderBuilder<_SwapController>(
            create: (_) => controller = _SwapController(),
            builder: (_, _) => const _SelA(),
          ),
        ),
      );
      await tester.pumpWidget(host(const SizedBox.shrink()));

      controller.bumpA();
      await tester.pump();

      expect(tester.takeException(), isNull);
    });
  });
}

enum _Id { a, b }

class _SwapController extends FlBaseController<_Id> {
  /// 不经页面直接用，所以注册放在构造函数里。
  _SwapController() {
    registerIds(shouldNotifyIds);
  }

  @override
  List<_Id> get shouldNotifyIds => const <_Id>[_Id.a, _Id.b];

  int value = 0;
  bool disposed = false;

  /// 当前挂着的监听者数量——本库的承诺是「与依赖方数量无关，恒为 1」。
  int listenerCount = 0;

  /// [dispose] 那一刻的 [listenerCount]，用来钉住摘 listener 与释放的先后。
  int listenerCountAtDispose = -1;

  void bumpA() {
    value++;
    notifySingleListener(_Id.a);
  }

  @override
  void addListener(VoidCallback listener) {
    listenerCount++;
    super.addListener(listener);
  }

  @override
  void removeListener(VoidCallback listener) {
    listenerCount--;
    super.removeListener(listener);
  }

  @override
  void dispose() {
    disposed = true;
    listenerCountAtDispose = listenerCount;
    super.dispose();
  }
}

/// 直接铺一个 [FlInheritedWidget]，把「换控制器实例」这条路径开出来。
///
/// 控制器的释放不归它管（[FlPageProvider] 才管生死），由用例自己 tearDown。
class _SwapHost extends StatefulWidget {
  const _SwapHost({required this.initial, required this.child, super.key});

  final _SwapController initial;
  final Widget child;

  @override
  State<_SwapHost> createState() => _SwapHostState();
}

class _SwapHostState extends State<_SwapHost> {
  late _SwapController _controller = widget.initial;

  void swap(_SwapController next) => setState(() => _controller = next);

  @override
  Widget build(BuildContext context) {
    return FlInheritedWidget<_SwapController>(
      controller: _controller,
      child: widget.child,
    );
  }
}

final Map<String, int> _builds = <String, int>{};

void _count(String key) => _builds[key] = (_builds[key] ?? 0) + 1;

class _SelA extends StatelessWidget {
  const _SelA();

  @override
  Widget build(BuildContext context) {
    _count('sel-a');
    final _SwapController c = context.selectIds<_Id, _SwapController>(
      const <_Id>[_Id.a],
    );
    return Text('a=${c.value}');
  }
}

class _SelB extends StatelessWidget {
  const _SelB();

  @override
  Widget build(BuildContext context) {
    _count('sel-b');
    context.selectIds<_Id, _SwapController>(const <_Id>[_Id.b]);
    return const SizedBox.shrink();
  }
}

class _WatchProbe extends StatelessWidget {
  const _WatchProbe();

  @override
  Widget build(BuildContext context) {
    _count('watch');
    return Text('watch=${context.wc<_SwapController>().value}');
  }
}
