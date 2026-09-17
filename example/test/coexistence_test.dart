// 两个包原样各自导入，一个 hide、一个前缀、一次显式扩展应用都不需要——
// 本库用 rc / wc / selectIds，provider 用 read / watch，名字不重叠。
import 'package:example/interop/deferred_change_notifier_provider.dart';
import 'package:fl_page_provider/fl_page_provider.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

/// 一棵树里同时挂两种注入：外层 `FlPageProvider`，内层 provider。
/// 四个短名在同一个 build 里共存，且各自的重建粒度互不干扰。
void main() {
  late _FlCounter fl;
  late _PkgCounter pkg;

  setUp(() {
    _Mixed.builds = 0;
    _FlWatch.builds = 0;
    _ReadOnly.builds = 0;
  });

  Future<void> pumpTree(WidgetTester tester) async {
    await tester.pumpWidget(
      Directionality(
        textDirection: TextDirection.ltr,
        child: FlProviderBuilder<_FlCounter>(
          create: (_) => fl = _FlCounter(),
          builder: (_, _) => DeferredChangeNotifierProvider<_PkgCounter>(
            create: (_) => pkg = _PkgCounter(),
            child: const Column(
              children: <Widget>[_Mixed(), _FlWatch(), _ReadOnly()],
            ),
          ),
        ),
      ),
    );
  }

  testWidgets('首帧：两套 API 在同一个 build 里各取各的', (tester) async {
    await pumpTree(tester);

    expect(find.text('sel fl.a=0 | watch pkg=0'), findsOneWidget);
    expect(find.text('wc fl.b=0'), findsOneWidget);
    expect(find.text('rc fl.a=0 | read pkg=0'), findsOneWidget);
    expect(
      <int>[_Mixed.builds, _FlWatch.builds, _ReadOnly.builds],
      <int>[1, 1, 1],
    );
  });

  testWidgets('通知本库的 a：selectIds 与 wc 重建，provider 那半边不受惊动', (tester) async {
    await pumpTree(tester);

    fl.bumpA();
    await tester.pump();

    expect(find.text('sel fl.a=1 | watch pkg=0'), findsOneWidget);
    expect(_Mixed.builds, 2, reason: 'selectIds 认领了 a');
    expect(_FlWatch.builds, 2, reason: 'wc 不分 ID');
    expect(_ReadOnly.builds, 1, reason: 'rc / read 都不建立依赖');
  });

  testWidgets('通知本库的 b：selectIds 只认领了 a，一次都不该重建', (tester) async {
    await pumpTree(tester);

    fl.bumpB();
    await tester.pump();

    expect(_Mixed.builds, 1, reason: '和 provider 同处一棵树，ID 粒度照样精确');
    expect(_FlWatch.builds, 2);
    expect(_ReadOnly.builds, 1);
  });

  testWidgets('通知 provider 侧：只有 watch 那半边重建，本库的依赖登记毫发无伤', (tester) async {
    await pumpTree(tester);

    pkg.bump();
    await tester.pump();

    expect(find.text('sel fl.a=0 | watch pkg=1'), findsOneWidget);
    expect(_Mixed.builds, 2);
    expect(_FlWatch.builds, 1, reason: 'fl 控制器没发通知');
    expect(_ReadOnly.builds, 1);
  });
}

enum _Id { a, b }

/// 本库这一侧的控制器。构造里补一次 registerIds——这棵树没走 FlBasePage，
/// 页面侧的 onPageInit 不会来。
class _FlCounter extends FlBaseController<_Id> {
  _FlCounter() {
    registerIds(shouldNotifyIds);
  }

  @override
  List<_Id> get shouldNotifyIds => _Id.values;

  int a = 0;
  int b = 0;

  void bumpA() {
    a++;
    notifySingleListener(_Id.a);
  }

  void bumpB() {
    b++;
    notifySingleListener(_Id.b);
  }
}

/// provider 这一侧的控制器。
class _PkgCounter extends ChangeNotifier {
  int value = 0;

  void bump() {
    value++;
    notifyListeners();
  }
}

/// 本库的 ID 粒度 + provider 的 watch，同一个 build 里。
class _Mixed extends StatelessWidget {
  const _Mixed();

  static int builds = 0;

  @override
  Widget build(BuildContext context) {
    builds++;
    final _FlCounter counter = context.selectIds<_Id, _FlCounter>(const <_Id>[
      _Id.a,
    ]);
    final int value = context.watch<_PkgCounter>().value;
    return Text('sel fl.a=${counter.a} | watch pkg=$value');
  }
}

/// 本库的全量订阅。
class _FlWatch extends StatelessWidget {
  const _FlWatch();

  static int builds = 0;

  @override
  Widget build(BuildContext context) {
    builds++;
    return Text('wc fl.b=${context.wc<_FlCounter>().b}');
  }
}

/// 两边都只读不订阅。
class _ReadOnly extends StatelessWidget {
  const _ReadOnly();

  static int builds = 0;

  @override
  Widget build(BuildContext context) {
    builds++;
    final _FlCounter counter = context.rc<_FlCounter>();
    final _PkgCounter value = context.read<_PkgCounter>();
    return Text('rc fl.a=${counter.a} | read pkg=${value.value}');
  }
}
