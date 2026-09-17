import 'package:fl_page_provider/fl_page_provider.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

/// 通知这一侧的契约：什么时候压根不发通知、`notifyListeners` 与按 ID 通知的
/// 区别、版本号为什么必须只增不减，以及那几条「漏了不报错、只是静默不刷新」
/// 的门禁断言到底拦不拦得住。
///
/// 与 `fl_page_provider_test.dart` 的分工：那边验「谁重建」，这边验「通知本身
/// 发没发出来、发的时候带了什么」。
void main() {
  int countOf(String key) => _builds[key] ?? 0;

  setUp(_builds.clear);

  Future<_NotifyController> pumpTree(WidgetTester tester, Widget child) async {
    late _NotifyController controller;
    await tester.pumpWidget(
      Directionality(
        textDirection: TextDirection.ltr,
        child: FlProviderBuilder<_NotifyController>(
          create: (_) => controller = _NotifyController(),
          builder: (_, _) => child,
        ),
      ),
    );
    return controller;
  }

  group('不该发出的通知', () {
    testWidgets('notifyMultiListeners([]) 是空操作：连 wc 都不重建', (
      WidgetTester tester,
    ) async {
      final _NotifyController controller = await pumpTree(
        tester,
        const Column(children: <Widget>[_WatchProbe(), _SelA()]),
      );
      expect(countOf('watch'), 1);

      controller.notifyNothing();
      await tester.pump();

      expect(countOf('watch'), 1, reason: '空列表连 notifyListeners 都不该走到');
      expect(countOf('sel-a'), 1);
    });

    test('dispose 之后再通知：不抛，监听者也收不到', () {
      final _NotifyController controller = _NotifyController();
      int heard = 0;
      controller.addListener(() => heard++);

      controller.bumpA();
      expect(heard, 1);

      controller.dispose();
      controller.bumpA();
      controller.notifyNothing();
      controller.notifyWithoutId();

      expect(heard, 1, reason: 'dispose 之后的通知一律被闸掉');
    });

    test('dispose 会清空注册表', () {
      final _NotifyController controller = _NotifyController();
      expect(controller.isRegistered(_Id.a), isTrue);

      controller.dispose();

      expect(controller.isRegistered(_Id.a), isFalse);
    });
  });

  group('直接调 notifyListeners 的门禁', () {
    test('子类直接调会断言', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);

      expect(controller.notifyWithoutId, throwsAssertionError);
    });

    test('报错信息点名了类型和该改用的入口', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);

      expect(
        controller.notifyWithoutId,
        throwsA(
          isA<AssertionError>().having(
            (AssertionError e) => e.message.toString(),
            'message',
            allOf(
              contains('_NotifyController'),
              contains('notifySingleListener'),
            ),
          ),
        ),
      );
    });

    testWidgets('被拦下之后一个依赖方都没惊动，连 wc 都没有', (WidgetTester tester) async {
      final _NotifyController controller = await pumpTree(
        tester,
        const Column(children: <Widget>[_WatchProbe(), _SelA(), _SelB()]),
      );
      expect(countOf('watch'), 1);

      expect(controller.notifyWithoutId, throwsAssertionError);
      await tester.pump();

      expect(countOf('watch'), 1, reason: '断言在 super.notifyListeners 之前');
      expect(countOf('sel-a'), 1);
      expect(countOf('sel-b'), 1);
    });

    test('走正门时门禁不挡，且调用结束后标志位复位', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);

      controller.bumpA();
      controller.bumpAB();

      expect(
        controller.notifyWithoutId,
        throwsAssertionError,
        reason: '正门那次用完就复位，不会给后面的直调放行',
      );
    });

    test('监听者抛异常也要复位标志位', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);
      controller.addListener(() => throw StateError('listener 抛了'));

      // ChangeNotifier 自己会把监听者的异常上报掉，这里把它接走，免得打到控制台。
      final void Function(FlutterErrorDetails)? previous = FlutterError.onError;
      FlutterErrorDetails? reported;
      FlutterError.onError = (FlutterErrorDetails details) =>
          reported = details;
      addTearDown(() => FlutterError.onError = previous);

      controller.bumpA();
      expect(reported, isNotNull, reason: '监听者确实抛了');

      expect(
        controller.notifyWithoutId,
        throwsAssertionError,
        reason: 'finally 里复位，否则这次越界的直调会被放过去',
      );
    });
  });

  group('版本号只增不减', () {
    testWidgets('同一帧内推进 1000 次，依赖方照样重建', (WidgetTester tester) async {
      final _NotifyController controller = await pumpTree(
        tester,
        const _SelA(),
      );

      // 早先的实现把版本号对 1000 取模：整 1000 次推进会绕回原值，比对得出
      // 「没变」，这次变更就被静默吞掉。这里正是那个窗口。
      for (int i = 0; i < 1000; i++) {
        controller.bumpA();
      }
      await tester.pump();

      expect(countOf('sel-a'), 2, reason: '绕回原值就会漏掉这次重建');
      expect(find.text('a=1000'), findsOneWidget);
    });
  });

  group('onNotified 钩子', () {
    test('拿到本次推进过的 ID，且早于监听者', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);
      controller.addListener(() => controller.log.add('listener'));

      controller.bumpA();
      controller.bumpAB();

      expect(controller.log, <String>[
        'onNotified:a',
        'listener',
        'onNotified:a,b',
        'listener',
      ]);
    });

    test('空列表不会触发 onNotified', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);

      controller.notifyNothing();

      expect(controller.log, isEmpty);
    });
  });

  group('注册表门禁', () {
    test('通知未注册的 ID 会断言', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);

      expect(controller.bumpGhost, throwsAssertionError);
    });

    test('一次 registerIds 都没调过就通知会断言', () {
      final _NotifyController controller = _NotifyController(
        autoRegister: false,
      );
      addTearDown(controller.dispose);

      expect(controller.bumpA, throwsAssertionError);
    });

    test('registerIds 是覆盖而不是追加', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);
      expect(controller.isRegistered(_Id.a), isTrue);
      expect(controller.isRegistered(_Id.b), isTrue);

      controller.registerOnly(const <_Id>[_Id.b]);

      expect(controller.isRegistered(_Id.a), isFalse, reason: '旧表被清掉');
      expect(controller.isRegistered(_Id.b), isTrue);
      expect(controller.bumpA, throwsAssertionError);
    });

    test('clearRegisteredIds 之后回到「没注册过」的状态', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);

      controller.clearIds();

      expect(controller.isRegistered(_Id.a), isFalse);
      expect(
        controller.bumpA,
        throwsAssertionError,
        reason: '_registered 也被复位',
      );
    });

    test('isRegistered 区分「没注册」和「注册了但没通知过」', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);

      expect(controller.isRegistered(_Id.a), isTrue, reason: '版本号还是 0');
      expect(controller.isRegistered(_Id.ghost), isFalse);
    });
  });

  group('版本号', () {
    test('注册后从 0 起，每次通知 +1，未注册的恒为 0', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);

      expect(controller.idVersion(_Id.a), 0, reason: '注册了但还没通知过');
      expect(controller.idVersion(_Id.ghost), 0, reason: '没注册');

      controller.bumpA();
      expect(controller.idVersion(_Id.a), 1);
      expect(controller.idVersion(_Id.b), 0, reason: 'b 没被通知');

      controller.bumpAB();
      expect(controller.idVersion(_Id.a), 2);
      expect(controller.idVersion(_Id.b), 1);
    });

    test('同一次通知里带重复 ID：推进两次，但只是一次通知', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);
      int heard = 0;
      controller.addListener(() => heard++);

      controller.notifyDuplicated();

      expect(controller.idVersion(_Id.a), 2, reason: '逐个推进，不去重');
      expect(heard, 1, reason: '一次调用就是一次通知');
    });

    test('dispose 之后版本号归 0', () {
      final _NotifyController controller = _NotifyController();
      controller.bumpA();
      expect(controller.idVersion(_Id.a), 1);

      controller.dispose();

      expect(controller.idVersion(_Id.a), 0, reason: '注册表被清空了');
    });
  });

  group('logMessage 钩子', () {
    test('注册、通知、释放各记一条', () {
      final _NotifyController controller = _NotifyController();

      controller.bumpA();
      controller.bumpAB();
      controller.dispose();

      expect(controller.logs.first, contains('[register]'));
      expect(controller.logs, contains('[notify] id: _Id.a'));
      expect(controller.logs, contains('[notify] ids: [_Id.a, _Id.b]'));
      expect(controller.logs.last, '[dispose]');
    });

    test('空列表那次不会产生日志', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);
      controller.logs.clear();

      controller.notifyNothing();

      expect(controller.logs, isEmpty, reason: '空列表在拼消息之前就返回了');
    });
  });

  group('registerIds 的边界', () {
    test('注册空列表：算注册过，但一个 ID 都没有', () {
      final _NotifyController controller = _NotifyController(
        autoRegister: false,
      );
      addTearDown(controller.dispose);

      controller.registerOnly(const <_Id>[]);

      expect(controller.isRegistered(_Id.a), isFalse);
      expect(
        controller.bumpA,
        throwsAssertionError,
        reason: '过了「注册过没有」那道，倒在「这个 ID 注册了没有」那道',
      );
    });

    test('重复注册同一批 ID 是幂等的，版本号跟着归零', () {
      final _NotifyController controller = _NotifyController();
      addTearDown(controller.dispose);
      controller.bumpA();
      expect(controller.idVersion(_Id.a), 1);

      controller.registerOnly(const <_Id>[_Id.a, _Id.b]);

      expect(controller.isRegistered(_Id.a), isTrue);
      expect(
        controller.idVersion(_Id.a),
        0,
        reason: 'registerIds 是重建整张表，不是补登记',
      );
    });
  });

  group('页面承载时自动注册', () {
    testWidgets('不在构造函数里注册也行：onPageInit 会补上', (WidgetTester tester) async {
      late _LazyController controller;
      await tester.pumpWidget(
        Directionality(
          textDirection: TextDirection.ltr,
          child: FlProviderBuilder<_LazyController>(
            create: (_) => controller = _LazyController(),
            builder: (BuildContext context, _) => const _LazySel(),
          ),
        ),
      );

      expect(controller.isRegistered(_Id.a), isTrue, reason: 'onPageInit 已注册');

      controller.bumpA();
      await tester.pump();

      expect(countOf('lazy'), 2);
    });
  });
}

enum _Id { a, b, ghost }

/// `ghost` 故意不进 [shouldNotifyIds]：留着验未注册 ID 的门禁。
class _NotifyController extends FlBaseController<_Id> {
  /// 直接用（不经页面）时页面侧的 `onPageInit` 不一定来，这里把注册补上。
  /// [autoRegister] 为 false 时留着验「一次都没注册过」那条断言。
  _NotifyController({bool autoRegister = true}) {
    if (autoRegister) registerIds(shouldNotifyIds);
  }

  @override
  List<_Id> get shouldNotifyIds => const <_Id>[_Id.a, _Id.b];

  final List<String> log = <String>[];

  int a = 0;
  int b = 0;

  void bumpA() {
    a++;
    notifySingleListener(_Id.a);
  }

  void bumpAB() {
    a++;
    b++;
    notifyMultiListeners(const <_Id>[_Id.a, _Id.b]);
  }

  void bumpGhost() => notifySingleListener(_Id.ghost);

  void notifyDuplicated() => notifyMultiListeners(const <_Id>[_Id.a, _Id.a]);

  void notifyNothing() => notifyMultiListeners(const <_Id>[]);

  void notifyWithoutId() => notifyListeners();

  void registerOnly(List<_Id> ids) => registerIds(ids);

  void clearIds() => clearRegisteredIds();

  @override
  void onNotified(List<_Id> events) {
    log.add('onNotified:${events.map((_Id e) => e.name).join(',')}');
    super.onNotified(events);
  }

  /// 收到的调试日志。钩子收的是闭包，这里求值一次存下来——顺带钉住
  /// 「没人 override 时那些字符串压根不会被拼出来」这件事的另一半。
  final List<String> logs = <String>[];

  @override
  void logMessage(String Function() message) {
    logs.add(message());
    super.logMessage(message);
  }
}

/// 构造函数里不注册，全靠 `FlBaseController.onPageInit` 那一次。
class _LazyController extends FlBaseController<_Id> {
  @override
  List<_Id> get shouldNotifyIds => const <_Id>[_Id.a];

  int a = 0;

  void bumpA() {
    a++;
    notifySingleListener(_Id.a);
  }
}

final Map<String, int> _builds = <String, int>{};

void _count(String key) => _builds[key] = (_builds[key] ?? 0) + 1;

class _WatchProbe extends StatelessWidget {
  const _WatchProbe();

  @override
  Widget build(BuildContext context) {
    _count('watch');
    return Text('watch a=${context.wc<_NotifyController>().a}');
  }
}

class _SelA extends StatelessWidget {
  const _SelA();

  @override
  Widget build(BuildContext context) {
    _count('sel-a');
    final _NotifyController c = context.selectIds<_Id, _NotifyController>(
      const <_Id>[_Id.a],
    );
    return Text('a=${c.a}');
  }
}

class _SelB extends StatelessWidget {
  const _SelB();

  @override
  Widget build(BuildContext context) {
    _count('sel-b');
    final _NotifyController c = context.selectIds<_Id, _NotifyController>(
      const <_Id>[_Id.b],
    );
    return Text('b=${c.b}');
  }
}

class _LazySel extends StatelessWidget {
  const _LazySel();

  @override
  Widget build(BuildContext context) {
    _count('lazy');
    final _LazyController c = context.selectIds<_Id, _LazyController>(
      const <_Id>[_Id.a],
    );
    return Text('lazy a=${c.a}');
  }
}
