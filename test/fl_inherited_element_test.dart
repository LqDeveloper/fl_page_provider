import 'package:fl_page_provider/fl_page_provider.dart';
// 本文件要验的是 Element 这一层的契约，而 FlInheritedWidget 是包内实现、不出口，
// 只能从 src 直接引。同包内的 src 引用不受 implementation_imports 约束。
import 'package:fl_page_provider/src/provider/fl_inherited_widget.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

/// `FlInheritedElement` 这一层的契约：控制器由它创建与释放、控制器上到底挂了
/// 几个 listener、什么时候摘掉。
///
/// 「换控制器实例」这条路径已经不存在了：控制器归 Element，一造出来就终身不换
/// ——`FlInheritedWidget` 手上只有 `create`，`updateShouldNotify` 恒为 `false`，
/// 谁都没有换实例的入口。原先为它准备的那组用例连同 `_controllerChanged` 一起
/// 删掉了。
void main() {
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
    test('恒为 false：控制器归 Element，widget 侧没有可比的东西', () {
      const Widget child = SizedBox.shrink();
      _SwapController create(BuildContext context) => _SwapController();
      final FlInheritedWidget<_SwapController> first =
          FlInheritedWidget<_SwapController>(create: create, child: child);

      expect(
        first.updateShouldNotify(
          FlInheritedWidget<_SwapController>(create: create, child: child),
        ),
        isFalse,
      );
      expect(
        // 连 create 都换了也一样：它在首次 build 之后再不会被调用，换与不换
        // 对子树没有任何可观测差别。
        first.updateShouldNotify(
          FlInheritedWidget<_SwapController>(
            create: (BuildContext context) => _SwapController(),
            child: const Text('别的 child', textDirection: TextDirection.ltr),
          ),
        ),
        isFalse,
      );
    });
  });

  group('控制器的生死归 Element', () {
    testWidgets('create 跑在 Element 的首次 build 里，拿到的 context 就是它', (
      WidgetTester tester,
    ) async {
      BuildContext? seen;
      await tester.pumpWidget(
        host(
          FlProviderBuilder<_SwapController>(
            create: (BuildContext context) {
              seen = context;
              return _SwapController();
            },
            builder: (_, _) => const _SelA(),
          ),
        ),
      );

      expect(
        seen,
        isA<FlInheritedElement<_SwapController>>(),
        reason: 'provider 传给 create 的同样是它自己那个 Element',
      );
    });

    testWidgets('create 里读自己会被挡开：同类型查找跳过本层', (WidgetTester tester) async {
      Object? error;
      await tester.pumpWidget(
        host(
          FlProviderBuilder<_SwapController>(
            create: (BuildContext context) {
              // 本层还在创建中。查找被 getElementForInheritedWidgetOfExactType
              // 的覆写挡到祖先那一层，而祖先没有——所以是「找不到」，不是读到
              // 一个半成品。
              try {
                context.rc<_SwapController>();
              } catch (e) {
                error = e;
              }
              return _SwapController();
            },
            builder: (_, _) => const _SelA(),
          ),
        ),
      );

      expect(error, isA<Error>());
      expect('$error', contains('找不到 FlPageProvider'));
      expect(tester.takeException(), isNull);
    });
  });

  group('所有权认领', () {
    testWidgets('create 返回已 dispose 的实例：报错，且不留下认领残留', (
      WidgetTester tester,
    ) async {
      final _SwapController dead = _SwapController()..dispose();

      await tester.pumpWidget(
        host(
          FlProviderBuilder<_SwapController>(
            create: (_) => dead,
            builder: (_, _) => const SizedBox.shrink(),
          ),
        ),
      );

      final Object? error = tester.takeException();
      expect(
        error,
        isFlutterError,
        reason: 'addListener 撞 debugAssertNotDisposed',
      );
      expect(
        debugIsOwnedController(dead),
        isFalse,
        reason: '认领排在 addListener 之后：抛出来的实例不能进那张全局强引用表',
      );
    });

    testWidgets('同一个实例交给两个 provider：断言，且 listener 只剩第一个的', (
      WidgetTester tester,
    ) async {
      final _SwapController shared = _SwapController();
      addTearDown(() {
        if (!shared.disposed) shared.dispose();
      });

      await tester.pumpWidget(
        host(
          FlProviderBuilder<_SwapController>(
            create: (_) => shared,
            builder: (_, _) => FlProviderBuilder<_SwapController>(
              create: (_) => shared,
              builder: (_, _) => const SizedBox.shrink(),
            ),
          ),
        ),
      );

      expect(tester.takeException(), isAssertionError);
      expect(shared.listenerCount, 1, reason: '内层先挂了 listener 再认领失败，得把自己那个摘掉');
      expect(debugIsOwnedController(shared), isTrue, reason: '外层的认领不受影响');
    });
  });

  group('非法 aspect', () {
    testWidgets('绕开公开 API 传了不是 ID 列表的 aspect：debug 期断言', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(
        host(
          FlProviderBuilder<_SwapController>(
            create: (_) => _SwapController(),
            builder: (_, _) => const _BadAspect(),
          ),
        ),
      );

      expect(tester.takeException(), isAssertionError);
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

/// 直接对 Element 调 `dependOnInheritedElement`，传一个不是 `List<Enum>` 的
/// aspect——公开 API（`FlSelector`）走不到这里，只有绕开它才写得出来。
///
/// 自「全量依赖」那套删掉之后，这是 `updateDependencies` 里仅剩的一条非常规分支。
/// debug 期它断言；release 期断言被剥掉，登记退化成「没登记过」，由
/// `notifyDependent` 的保守分支兜住（每次通知都重建）。后一半在 debug 的测试里
/// 跑不到，所以这条用例只钉住断言这一半。
class _BadAspect extends StatelessWidget {
  const _BadAspect();

  @override
  Widget build(BuildContext context) {
    final InheritedElement element = context
        .getElementForInheritedWidgetOfExactType<
          FlInheritedWidget<_SwapController>
        >()!;
    context.dependOnInheritedElement(element, aspect: 'not a list');
    return const SizedBox.shrink();
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
    // 订了全部 ID——任何一次通知都会惊动它。
    final _SwapController c = context.selectIds<_Id, _SwapController>(
      _Id.values,
    );
    return Text('watch=${c.value}');
  }
}
