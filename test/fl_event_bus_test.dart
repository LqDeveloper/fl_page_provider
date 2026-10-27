import 'package:fl_page_provider/fl_page_provider.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

/// 控制器身上那条全局事件总线的契约：谁收得到、订阅什么时候被取消、
/// 以及那道挡重复订阅的断言。
///
/// 事件默认经微任务异步派发（`FlEventBus` 的 `sync: false`），所以每次
/// dispatch 之后都要 `pumpEventQueue()`，直接断言会全部落空。
void main() {
  setUp(() => _builds = 0);

  group('收发', () {
    test('自己发的事件自己也收得到', () async {
      final _Receiver receiver = _Receiver();
      addTearDown(receiver.dispose);
      receiver.subscribeLogin();

      receiver.send(const _Login('bob'));
      await pumpEventQueue();

      expect(receiver.received, <String>['login:bob']);
    });

    test('一个控制器发，另一个控制器收', () async {
      final _Sender sender = _Sender();
      final _Receiver receiver = _Receiver();
      addTearDown(sender.dispose);
      addTearDown(receiver.dispose);
      receiver.subscribeLogin();

      sender.send(const _Login('alice'));
      await pumpEventQueue();

      expect(receiver.received, <String>['login:alice']);
    });

    test('按类型过滤：不相干的事件类型收不到', () async {
      final _Receiver receiver = _Receiver();
      addTearDown(receiver.dispose);
      receiver.subscribeLogin();

      receiver.sendLogout(const _Logout());
      await pumpEventQueue();

      expect(receiver.received, isEmpty);
    });

    test('同一类型配两个不同回调：两个都收到', () async {
      final _Receiver receiver = _Receiver();
      addTearDown(receiver.dispose);
      receiver
        ..subscribeLogin()
        ..subscribeLoginAgainWithOtherCallback();

      receiver.send(const _Login('carol'));
      await pumpEventQueue();

      expect(receiver.received, <String>['login:carol', 'second:carol']);
    });
  });

  group('订阅的生命周期', () {
    test('dispose 取消订阅：之后发的事件不再回调', () async {
      final _Sender sender = _Sender();
      addTearDown(sender.dispose);
      final _Receiver receiver = _Receiver()..subscribeLogin();

      sender.send(const _Login('before'));
      await pumpEventQueue();
      expect(receiver.received, <String>['login:before']);

      receiver.dispose();
      sender.send(const _Login('after'));
      await pumpEventQueue();

      expect(receiver.received, <String>[
        'login:before',
      ], reason: 'dispose 里已经 cancel 了');
    });

    test('dispose 之后再 observeEvent：静默返回，不抛也不订阅', () async {
      final _Sender sender = _Sender();
      addTearDown(sender.dispose);
      final _Receiver receiver = _Receiver()..dispose();

      expect(receiver.subscribeLogin, returnsNormally);

      sender.send(const _Login('zombie'));
      await pumpEventQueue();

      expect(receiver.received, isEmpty);
    });

    test('dispose 只掐进来的订阅，发事件这一侧照常可用', () async {
      final _Receiver receiver = _Receiver();
      addTearDown(receiver.dispose);
      receiver.subscribeLogin();

      final _Sender sender = _Sender()..dispose();
      sender.send(const _Login('from-dead-sender'));
      await pumpEventQueue();

      expect(receiver.received, <String>[
        'login:from-dead-sender',
      ], reason: 'dispatchEvent 走的是全局总线，不经过本实例的订阅表');
    });

    test('多个控制器订阅同一事件：各收各的，dispose 一个不影响另一个', () async {
      final _Sender sender = _Sender();
      final _Receiver first = _Receiver()..subscribeLogin();
      final _Receiver second = _Receiver()..subscribeLogin();
      addTearDown(sender.dispose);
      addTearDown(second.dispose);

      sender.send(const _Login('both'));
      await pumpEventQueue();
      expect(first.received, <String>['login:both']);
      expect(second.received, <String>['login:both']);

      first.dispose();
      sender.send(const _Login('only-second'));
      await pumpEventQueue();

      expect(first.received, <String>['login:both']);
      expect(second.received, <String>['login:both', 'login:only-second']);
    });
  });

  group('重复订阅的门禁', () {
    test('同一个方法引用登记两次：断言报错，第二次被忽略', () async {
      final _Receiver receiver = _Receiver();
      addTearDown(receiver.dispose);
      receiver.subscribeLogin();

      expect(receiver.subscribeLogin, throwsAssertionError);

      receiver.send(const _Login('once'));
      await pumpEventQueue();

      expect(receiver.received, <String>[
        'login:once',
      ], reason: '被忽略掉的那次不该让回调跑两遍');
    });

    test('同一个回调登记到两个不同事件类型：都算数', () async {
      final _Receiver receiver = _Receiver();
      addTearDown(receiver.dispose);
      receiver.subscribeBothTypesWithSameCallback();

      receiver.send(const _Login('x'));
      receiver.sendLogout(const _Logout());
      await pumpEventQueue();

      expect(receiver.received, <String>[
        'any:_Login',
        'any:_Logout',
      ], reason: '门禁比的是 (事件类型, 回调) 这个组合，不是回调本身');
    });

    test('闭包字面量识别不出来，仍然会重复订阅', () async {
      final _Receiver receiver = _Receiver();
      addTearDown(receiver.dispose);
      receiver
        ..subscribeWithFreshClosure()
        ..subscribeWithFreshClosure();

      receiver.send(const _Login('dup'));
      await pumpEventQueue();

      expect(receiver.received, <String>[
        'closure:dup',
        'closure:dup',
      ], reason: '文档明说了这道门禁只拦得住方法引用');
    });
  });

  group('跨页面刷新', () {
    testWidgets('一页 dispatch，另一页的控制器收到后按 ID 局部刷新', (WidgetTester tester) async {
      late _Sender sender;
      await tester.pumpWidget(
        Directionality(
          textDirection: TextDirection.ltr,
          child: FlProviderBuilder<_Sender>(
            create: (_) => sender = _Sender(),
            builder: (_, _) => FlProviderBuilder<_FeedController>(
              create: (_) => _FeedController(),
              builder: (_, _) => const _FeedView(),
            ),
          ),
        ),
      );
      expect(_builds, 1);
      expect(find.text('feed 0'), findsOneWidget);

      sender.send(const _Login('dave'));
      // testWidgets 的时钟是假的，`pumpEventQueue` 那种 `Future.delayed` 永远
      // 不会到期；广播流走的是微任务，两次 pump 之间的 await 就足够把它放出来。
      await tester.pump();
      await tester.pump();

      expect(_builds, 2);
      expect(find.text('feed 1'), findsOneWidget);
    });

    testWidgets('页面卸载后再发事件：控制器已 dispose，不再有任何动静', (WidgetTester tester) async {
      late _Sender sender;
      await tester.pumpWidget(
        Directionality(
          textDirection: TextDirection.ltr,
          child: FlProviderBuilder<_Sender>(
            create: (_) => sender = _Sender(),
            builder: (_, _) => FlProviderBuilder<_FeedController>(
              create: (_) => _FeedController(),
              builder: (_, _) => const _FeedView(),
            ),
          ),
        ),
      );

      // 只拆掉内层那棵子树，发事件的控制器还活着。
      await tester.pumpWidget(
        Directionality(
          textDirection: TextDirection.ltr,
          child: FlProviderBuilder<_Sender>(
            create: (_) => sender = _Sender(),
            builder: (_, _) => const SizedBox.shrink(),
          ),
        ),
      );

      sender.send(const _Login('gone'));
      await tester.pump();
      await tester.pump();

      expect(tester.takeException(), isNull);
    });
  });
}

class _Login {
  const _Login(this.name);

  final String name;
}

class _Logout {
  const _Logout();
}

enum _Id { feed }

/// 只发不收。
class _Sender extends FlBaseController<_Id> {
  _Sender() {
    registerIds(shouldNotifyIds);
  }

  @override
  List<_Id> get shouldNotifyIds => const <_Id>[_Id.feed];

  void send(_Login event) => dispatchEvent<_Login>(event);
}

class _Receiver extends FlBaseController<_Id> {
  _Receiver() {
    registerIds(shouldNotifyIds);
  }

  @override
  List<_Id> get shouldNotifyIds => const <_Id>[_Id.feed];

  final List<String> received = <String>[];

  void _handleLogin(_Login event) => received.add('login:${event.name}');

  void _handleLoginTwice(_Login event) => received.add('second:${event.name}');

  /// 传方法引用——同一个实例上的 tear-off 彼此相等，门禁认得出。
  void subscribeLogin() => observeEvent<_Login>(_handleLogin);

  void subscribeLoginAgainWithOtherCallback() =>
      observeEvent<_Login>(_handleLoginTwice);

  /// 每次现写一个闭包：两次的实例不相等，门禁识别不出来。
  void subscribeWithFreshClosure() =>
      observeEvent<_Login>((_Login e) => received.add('closure:${e.name}'));

  void _handleAny(Object event) => received.add('any:${event.runtimeType}');

  /// 同一个方法引用挂到两个事件类型上——门禁按 (类型, 回调) 组合去重，不该拦。
  void subscribeBothTypesWithSameCallback() {
    observeEvent<_Login>(_handleAny);
    observeEvent<_Logout>(_handleAny);
  }

  void send(_Login event) => dispatchEvent<_Login>(event);

  void sendLogout(_Logout event) => dispatchEvent<_Logout>(event);
}

/// 收到登录事件就推进自己的 ID，让订阅了它的 widget 重建。
class _FeedController extends FlBaseController<_Id> {
  @override
  List<_Id> get shouldNotifyIds => const <_Id>[_Id.feed];

  int refreshCount = 0;

  @override
  void onPageInit() {
    super.onPageInit();
    observeEvent<_Login>(_onLogin);
  }

  void _onLogin(_Login event) {
    refreshCount++;
    notifySingleListener(_Id.feed);
  }
}

int _builds = 0;

class _FeedView extends FlSelectorView<_Id, _FeedController> {
  const _FeedView();

  @override
  List<_Id> get observeIds => const <_Id>[_Id.feed];

  @override
  Widget buildWidget(
    BuildContext context,
    _FeedController controller,
    Widget? child,
  ) {
    _builds++;
    return Text('feed ${controller.refreshCount}');
  }
}
