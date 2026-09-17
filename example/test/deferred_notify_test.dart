import 'package:example/interop/deferred_change_notifier_provider.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

/// 钉住「在 build 阶段发通知」这一条在 pub `provider` 上的行为：
/// 裸 `ChangeNotifierProvider` 会抛，`DeferredChangeNotifierProvider` 不抛且
/// 推迟一帧兑现——也就是本库 `FlInheritedElement._handleNotify` 的那道相位判断，
/// 在 provider 侧靠公开的 `startListening` 钩子补得回来。
void main() {
  late _Counter counter;

  setUp(() {
    _Probe.builds = 0;
  });

  /// 被注入的子树：一个会在自己 build 期间发通知的触发器 + 一个 watch 探针。
  ///
  /// 探针写成 `const`，触发器 `setState` 时不会顺带重建它——重建计数才只反映
  /// 「通知兑现了几次」。
  Widget subtree(GlobalKey<_FireDuringBuildState> key) => Column(
    children: <Widget>[
      _FireDuringBuild(key: key),
      const _Probe(),
    ],
  );

  Widget host(Widget provider) =>
      Directionality(textDirection: TextDirection.ltr, child: provider);

  Widget bare(GlobalKey<_FireDuringBuildState> key) => host(
    ChangeNotifierProvider<_Counter>(
      create: (_) => counter = _Counter(),
      child: subtree(key),
    ),
  );

  Widget deferred(GlobalKey<_FireDuringBuildState> key) => host(
    DeferredChangeNotifierProvider<_Counter>(
      create: (_) => counter = _Counter(),
      child: subtree(key),
    ),
  );

  testWidgets(
    '裸 ChangeNotifierProvider：build 期通知撞上 markNeedsBuild during build',
    (tester) async {
      final GlobalKey<_FireDuringBuildState> key =
          GlobalKey<_FireDuringBuildState>();
      await tester.pumpWidget(bare(key));

      key.currentState!.arm();
      await tester.pump();

      final Object? error = tester.takeException();
      expect(
        error,
        isNotNull,
        reason: 'provider 的 markNeedsNotifyDependents 没有相位判断',
      );
      expect(
        '$error',
        contains('setState() or markNeedsBuild() called during build'),
      );
    },
  );

  testWidgets('DeferredChangeNotifierProvider：不抛异常，推迟到下一帧兑现', (tester) async {
    final GlobalKey<_FireDuringBuildState> key =
        GlobalKey<_FireDuringBuildState>();
    await tester.pumpWidget(deferred(key));
    expect(_Probe.builds, 1, reason: '首帧各构建一次');

    key.currentState!.arm();
    await tester.pump();

    expect(tester.takeException(), isNull, reason: '不该抛 setState during build');
    expect(_Probe.builds, 1, reason: '本帧不兑现——此刻 markNeedsBuild 还是非法的');

    await tester.pump();
    expect(_Probe.builds, 2, reason: '推迟一帧后照样兑现');
    expect(find.text('1'), findsOneWidget);
  });

  testWidgets('build 期同帧连发 3 次，只兑现一次重建', (tester) async {
    final GlobalKey<_FireDuringBuildState> key =
        GlobalKey<_FireDuringBuildState>();
    await tester.pumpWidget(deferred(key));

    key.currentState!.arm(3);
    await tester.pump();
    await tester.pump();

    expect(tester.takeException(), isNull);
    expect(_Probe.builds, 2, reason: '三次通知被 deferred 标志合并成一次');
    expect(find.text('3'), findsOneWidget, reason: '三次 bump 都算数，只是重建合并了');
  });

  testWidgets('非 build 阶段的通知：照常在下一帧生效，没有被推迟拖慢', (tester) async {
    final GlobalKey<_FireDuringBuildState> key =
        GlobalKey<_FireDuringBuildState>();
    await tester.pumpWidget(deferred(key));

    // 从测试里直接发通知，此刻不在 build 阶段，走的是不推迟的那条路径。
    counter.bump();
    await tester.pump();

    expect(_Probe.builds, 2);
    expect(find.text('1'), findsOneWidget);
  });

  testWidgets('子树销毁时控制器被 dispose，listener 也摘掉了', (tester) async {
    final GlobalKey<_FireDuringBuildState> key =
        GlobalKey<_FireDuringBuildState>();
    await tester.pumpWidget(deferred(key));
    final _Counter created = counter;
    expect(created.disposed, isFalse);

    await tester.pumpWidget(host(const SizedBox.shrink()));

    expect(created.disposed, isTrue);
    expect(created.hasListeners, isFalse, reason: 'startListening 返回的取消回调被调用了');
  });
}

/// 最小控制器：一个计数、一次通知。
class _Counter extends ChangeNotifier {
  int value = 0;
  bool disposed = false;

  /// 暴露给测试，用来确认 listener 已摘除。
  @override
  bool get hasListeners => super.hasListeners;

  void bump() {
    value++;
    notifyListeners();
  }

  @override
  void dispose() {
    disposed = true;
    super.dispose();
  }
}

/// watch 探针：记录自己被 build 了几次。
class _Probe extends StatelessWidget {
  const _Probe();

  static int builds = 0;

  @override
  Widget build(BuildContext context) {
    builds++;
    return Text('${context.watch<_Counter>().value}');
  }
}

/// 在**自己的 build 期间**发通知——正是 markNeedsBuild 非法的那个时刻。
class _FireDuringBuild extends StatefulWidget {
  const _FireDuringBuild({super.key});

  @override
  State<_FireDuringBuild> createState() => _FireDuringBuildState();
}

class _FireDuringBuildState extends State<_FireDuringBuild> {
  int _pending = 0;

  /// 让下一次 build 在 build 期间发 [times] 次通知。
  void arm([int times = 1]) => setState(() => _pending = times);

  @override
  Widget build(BuildContext context) {
    if (_pending > 0) {
      final int times = _pending;
      _pending = 0;
      final _Counter controller = context.read<_Counter>();
      for (int i = 0; i < times; i++) {
        controller.bump();
      }
    }
    return const SizedBox.shrink();
  }
}
