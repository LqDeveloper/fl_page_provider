import 'dart:async';

import 'package:fl_page_provider/fl_page_provider.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 页面 → 控制器的生命周期转发链路。
///
/// 本包自己不产生这些事件，它只保证「`FlBasePage` / `FlBasePageState` /
/// `FlProviderBuilder` 承载的控制器一定收得到」。断言钉的是这条链路有没有接好，
/// 以及与控制器所有权的先后顺序（`onPageDispose` 必须早于 `dispose`）。
void main() {
  setUp(() {
    _log.clear();
    _keepControllers.clear();
    _created = 0;
  });

  Widget app({
    Widget home = const _HomePage(),
    Map<String, WidgetBuilder>? routes,
  }) => MaterialApp(
    navigatorObservers: <NavigatorObserver>[FlRouteObserver()],
    home: home,
    routes: routes ?? const <String, WidgetBuilder>{},
  );

  NavigatorState navOf(WidgetTester tester) =>
      tester.state<NavigatorState>(find.byType(Navigator));

  /// `pushNamed` 返回的 Future 要**等到这条路由被 pop 才完成**，直接 await 会把
  /// 用例挂死在这里。push 完立刻返回，推进靠后面的 `pumpAndSettle`。
  void push(WidgetTester tester, String name, {Object? arguments}) {
    unawaited(navOf(tester).pushNamed<Object?>(name, arguments: arguments));
  }

  group('FlBasePage', () {
    testWidgets('首帧按 init → contextReady → postFrame → start → resume 转发', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();

      expect(_log, <String>[
        'home.onPageInit',
        'home.onPageContextReady',
        'home.onPagePostFrame',
        'home.onPageStart',
        'home.onPageResume',
      ]);
    });

    testWidgets('createController 只跑一次，buildWithController 拿到的就是那个实例', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      expect(_created, 1);

      // 换一个同类型的 home，强制外层重建一次。
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();

      expect(_created, 1, reason: '控制器要跨父级重建活下来');
      expect(_seenInBuild, isNotNull);
      expect(identical(_seenInBuild, _lastController), isTrue);
    });

    testWidgets('onPageInit 已经把 shouldNotifyIds 注册好，页面里可以直接 selectIds', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      expect(find.text('count=0'), findsOneWidget);

      _lastController!.bump();
      await tester.pump();

      expect(find.text('count=1'), findsOneWidget);
    });
  });

  group('被覆盖与返回', () {
    testWidgets('push 新页面：旧页 pause + stop，新页走完整首帧', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(
        app(
          routes: <String, WidgetBuilder>{
            '/second': (_) => const _SecondPage(),
          },
        ),
      );
      await tester.pumpAndSettle();
      _log.clear();

      push(tester, '/second', arguments: <String, int>{'id': 7});
      await tester.pumpAndSettle();

      expect(_log.take(2), <String>['home.onPagePause', 'home.onPageStop']);
      expect(
        _log,
        containsAllInOrder(<String>[
          'second.onPageInit',
          'second.onPageContextReady',
          'second.onPageStart',
          'second.onPageResume',
        ]),
      );
    });

    testWidgets('pop 回来：旧页 start + resume，新页 stop 后 dispose', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(
        app(
          routes: <String, WidgetBuilder>{
            '/second': (_) => const _SecondPage(),
          },
        ),
      );
      await tester.pumpAndSettle();
      push(tester, '/second');
      await tester.pumpAndSettle();
      _log.clear();

      navOf(tester).pop();
      await tester.pumpAndSettle();

      expect(
        _log,
        containsAllInOrder(<String>[
          'second.onPagePause',
          'second.onPageStop',
          'home.onPageStart',
          'home.onPageResume',
          'second.onPageDispose',
          'second.dispose',
        ]),
      );
    });

    testWidgets('被弹窗盖住只 pause 不 stop——页面其实还看得见', (WidgetTester tester) async {
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      _log.clear();

      unawaited(
        showDialog<void>(
          context: navOf(tester).context,
          builder: (_) => const SizedBox.shrink(),
        ),
      );
      await tester.pumpAndSettle();

      expect(_log, <String>['home.onPagePause']);

      navOf(tester).pop();
      await tester.pumpAndSettle();

      expect(_log, <String>['home.onPagePause', 'home.onPageResume']);
    });
  });

  group('路由参数', () {
    testWidgets('routeName 与 arguments 转发到控制器', (WidgetTester tester) async {
      await tester.pumpWidget(
        app(
          routes: <String, WidgetBuilder>{
            '/second': (_) => const _SecondPage(),
          },
        ),
      );
      await tester.pumpAndSettle();

      push(tester, '/second', arguments: 42);
      await tester.pumpAndSettle();

      expect(_secondController!.routeName, '/second');
      expect(_secondController!.arguments, 42);
    });

    testWidgets('首页拿到的是默认路由名，没传参数时 arguments 为 null', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();

      expect(_lastController!.routeName, '/');
      expect(_lastController!.arguments, isNull);
    });

    testWidgets('没挂 FlRouteObserver：路由参数照样到，断的是被覆盖时那对 pause / stop', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(
        // 故意不挂 navigatorObservers。
        MaterialApp(
          home: const _HomePage(),
          routes: <String, WidgetBuilder>{
            '/second': (_) => const _SecondPage(),
          },
        ),
      );
      await tester.pumpAndSettle();

      expect(
        _lastController!.routeName,
        '/',
        reason: '路由参数读的是 ModalRoute.settings，与 observer 无关',
      );
      _log.clear();

      push(tester, '/second');
      await tester.pumpAndSettle();

      expect(
        _log.where((String e) => e.startsWith('home.')),
        isEmpty,
        reason: '「我被盖住了」这条消息来自 observer 的路由通知，漏挂就一条都收不到',
      );
    });
  });

  group('热重载', () {
    // 事件本身由页面侧在 `State.reassemble` 里发出（仅 debug），那是
    // fl_page_lifecycle 的活；这里直接把事件喂进转发入口，验本库这一端的反应
    // ——`tester.binding.reassembleApplication()` 要等一帧画完才返回，而帧要
    // 靠 pump 推，await 它会把用例锁死。
    testWidgets('onPageReassemble 会把 ids 重新注册一遍', (WidgetTester tester) async {
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      final _LogController controller = _lastController!;
      expect(controller.isRegistered(_Id.count), isTrue);

      // 模拟热重载前注册表已经失效的状态——真实场景里是控制器类的
      // shouldNotifyIds 改了，这里用清空来等价表达。
      controller.forgetIds();
      expect(controller.isRegistered(_Id.count), isFalse);
      _log.clear();

      controller.onLifecycleChanged(FlLifecycleState.onPageReassemble);

      expect(_log, <String>['home.onPageReassemble']);
      expect(
        controller.isRegistered(_Id.count),
        isTrue,
        reason: 'FlBaseController.onPageReassemble 里重新 registerIds',
      );
    });

    testWidgets('重新注册之后，按 ID 的局部刷新照常工作', (WidgetTester tester) async {
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      final _LogController controller = _lastController!;

      controller
        ..forgetIds()
        ..onLifecycleChanged(FlLifecycleState.onPageReassemble)
        ..bump();
      await tester.pump();

      expect(find.text('count=1'), findsOneWidget);
      expect(_created, 1, reason: '热重载不该把控制器重造一个');
    });
  });

  group('控制器回调抛异常', () {
    testWidgets('异常被上报而不是打断转发链，后续回调照常到达', (WidgetTester tester) async {
      await tester.pumpWidget(app(home: const _BoomPage()));
      expect(
        tester.takeException(),
        isA<StateError>(),
        reason: 'FlLifecycleGuard 上报而不是吞掉',
      );

      await tester.pumpAndSettle();

      expect(
        _log,
        containsAllInOrder(<String>[
          'boom.onPageInit',
          'boom.onPageStart',
          'boom.onPageResume',
        ]),
        reason: 'onPageInit 抛了，但它后面的回调一个都不能丢',
      );
      expect(find.text('boom'), findsOneWidget, reason: '页面照常渲染');
    });
  });

  group('销毁顺序', () {
    testWidgets('onPageStop → onPageDispose → controller.dispose', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      _log.clear();

      await tester.pumpWidget(const SizedBox.shrink());

      expect(_log, <String>[
        'home.onPagePause',
        'home.onPageStop',
        'home.onPageDispose',
        'home.dispose',
      ], reason: 'onPageDispose 里控制器必须还活着');
    });
  });

  group('App 前后台', () {
    testWidgets('observeAppLifecycle 默认关：切后台控制器收不到任何 App 事件', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(app(home: const _QuietPage()));
      await tester.pumpAndSettle();
      _log.clear();

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();

      expect(_log, isEmpty);
    });

    testWidgets('打开之后，后台与回前台都转发到控制器', (WidgetTester tester) async {
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      _log.clear();

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pumpAndSettle();

      expect(
        _log,
        containsAllInOrder(<String>[
          'home.onAppInactive',
          'home.onAppBackground',
          'home.onAppPause',
        ]),
      );
      _log.clear();

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();

      expect(
        _log,
        containsAllInOrder(<String>[
          'home.onAppResume',
          'home.onAppForeground',
        ]),
      );
    });
  });

  group('FlBasePageState', () {
    testWidgets('与 FlBasePage 走同一条转发链路', (WidgetTester tester) async {
      await tester.pumpWidget(app(home: const _StatefulHomePage()));
      await tester.pumpAndSettle();

      expect(_log, <String>[
        'stateful.onPageInit',
        'stateful.onPageContextReady',
        'stateful.onPagePostFrame',
        'stateful.onPageStart',
        'stateful.onPageResume',
      ]);
    });

    testWidgets('wantKeepAlive 默认 false', (WidgetTester tester) async {
      await tester.pumpWidget(app(home: const _StatefulHomePage()));
      await tester.pumpAndSettle();

      final FlBasePageState<_StatefulHomePage, _LogController> state = tester
          .state<_StatefulHomePageState>(find.byType(_StatefulHomePage));

      expect(state.wantKeepAlive, isFalse);
    });
  });

  group('FlProviderBuilder 直接用', () {
    testWidgets('不经 FlBasePage 也能收到生命周期', (WidgetTester tester) async {
      await tester.pumpWidget(
        app(
          home: FlProviderBuilder<_LogController>(
            create: (_) => _LogController('raw'),
            builder: (_, _) => const Scaffold(body: Text('raw')),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(_log, <String>[
        'raw.onPageInit',
        'raw.onPageContextReady',
        'raw.onPagePostFrame',
        'raw.onPageStart',
        'raw.onPageResume',
      ]);
    });
  });

  group('PageView 子页', () {
    testWidgets('observePageIndex + FlPageIndexScope：切页驱动 start / stop', (
      WidgetTester tester,
    ) async {
      final PageController pageController = PageController();
      addTearDown(pageController.dispose);

      await tester.pumpWidget(
        app(
          home: Scaffold(
            body: PageView(
              controller: pageController,
              children: FlPageIndexScope.wrapChildren(
                controller: pageController,
                children: const <Widget>[_TabPage(0), _TabPage(1)],
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        _log,
        containsAllInOrder(<String>['tab0.onPageStart', 'tab0.onPageResume']),
      );
      expect(
        _log.where((String e) => e.startsWith('tab1.onPageStart')),
        isEmpty,
        reason: '第 1 页还没露面，不该发 start',
      );
      _log.clear();

      pageController.jumpToPage(1);
      await tester.pumpAndSettle();

      expect(
        _log,
        containsAllInOrder(<String>['tab0.onPageStop', 'tab1.onPageStart']),
      );
    });

    testWidgets('页码变化转发到控制器的 onPageIndexChanged', (WidgetTester tester) async {
      // 用 IndexedStack + ValueNotifier 而不是 PageView：页码变更只发给**变更
      // 时仍挂着**的页，而 PageView 翻页会把离开的那页整个销毁，它那条
      // onPageIndexChanged 没有收件人。IndexedStack 的子页全程都在树上。
      final ValueNotifier<int> index = ValueNotifier<int>(0);
      addTearDown(index.dispose);

      await tester.pumpWidget(
        app(
          home: Scaffold(
            body: ValueListenableBuilder<int>(
              valueListenable: index,
              builder: (_, int current, _) => IndexedStack(
                index: current,
                children: FlPageIndexScope.wrapChildren(
                  controller: index,
                  children: const <Widget>[_TabPage(0), _TabPage(1)],
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      _log.clear();

      index.value = 1;
      await tester.pumpAndSettle();

      expect(
        _log,
        containsAll(<String>[
          'tab0.onPageIndexChanged:0->1',
          'tab1.onPageIndexChanged:0->1',
        ]),
        reason: '页码变更与可见性是分开的两条，每个还挂着的子页都收得到',
      );
      expect(
        _log,
        containsAllInOrder(<String>['tab0.onPageStop', 'tab1.onPageStart']),
        reason: '可见性那条照常：先发完 hide 再发 show',
      );
    });

    testWidgets('observePageIndex 开着但宿主没包 Scope：退化成普通页面，首帧即可见', (
      WidgetTester tester,
    ) async {
      // 只做一半——页面侧开了开关，宿主侧没有 FlPageIndexScope。文档说这时
      // 不报错，但页码那条链路完全无效，页面按普通页面走。
      await tester.pumpWidget(app(home: const _TabPage(9)));
      await tester.pumpAndSettle();

      // 只看本页的那几条：上一个用例的树是在本用例开始之后才拆的，它的
      // 销毁日志会落在 _log 开头。
      expect(_log.where((String e) => e.startsWith('tab9.')), <String>[
        'tab9.onPageInit',
        'tab9.onPageContextReady',
        'tab9.onPagePostFrame',
        'tab9.onPageStart',
        'tab9.onPageResume',
      ]);
      expect(
        _log.where((String e) => e.contains('onPageIndexChanged')),
        isEmpty,
        reason: '没有 Scope，页码那条链路整条不存在',
      );
    });
  });

  group('保活', () {
    testWidgets('wantKeepAlive 为 true 的子页翻走也不 dispose，false 的照常释放', (
      WidgetTester tester,
    ) async {
      final PageController pageController = PageController();
      addTearDown(pageController.dispose);

      await tester.pumpWidget(
        app(
          home: Scaffold(
            body: PageView(
              controller: pageController,
              children: const <Widget>[
                _KeepPage(tag: 'keep', keepAlive: true),
                _KeepPage(tag: 'drop', keepAlive: false),
                SizedBox.shrink(),
              ],
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // 先让第 1 页建出来，再翻到第 2 页，让前两页都离开视口。
      pageController.jumpToPage(1);
      await tester.pumpAndSettle();
      expect(_keepControllers.containsKey('drop'), isTrue);

      pageController.jumpToPage(2);
      await tester.pumpAndSettle();

      expect(
        _keepControllers['keep']!.disposed,
        isFalse,
        reason: 'wantKeepAlive 为 true，State 连同控制器一起留着',
      );
      expect(
        _keepControllers['drop']!.disposed,
        isTrue,
        reason: '默认不保活，离开视口即整棵子树销毁',
      );
    });
  });
}

final List<String> _log = <String>[];
int _created = 0;
_LogController? _lastController;
_LogController? _secondController;
_LogController? _seenInBuild;

enum _Id { count }

/// 把每一个生命周期回调如实记到 [_log] 里，前缀是页面的 tag。
class _LogController extends FlBaseController<_Id> {
  _LogController(this.tag) {
    _created++;
  }

  final String tag;

  @override
  List<_Id> get shouldNotifyIds => const <_Id>[_Id.count];

  int count = 0;
  bool disposed = false;

  void bump() {
    count++;
    notifySingleListener(_Id.count);
  }

  /// 把注册表清空，用来验热重载那一下会不会补回来。
  void forgetIds() => clearRegisteredIds();

  void _add(String name) => _log.add('$tag.$name');

  @override
  void onPageInit() {
    super.onPageInit();
    _add('onPageInit');
  }

  @override
  void onPageContextReady(BuildContext? context) {
    super.onPageContextReady(context);
    _add('onPageContextReady');
  }

  @override
  void onPagePostFrame() {
    super.onPagePostFrame();
    _add('onPagePostFrame');
  }

  @override
  void onPageReassemble() {
    super.onPageReassemble();
    _add('onPageReassemble');
  }

  @override
  void onPageStart() {
    super.onPageStart();
    _add('onPageStart');
  }

  @override
  void onPageResume() {
    super.onPageResume();
    _add('onPageResume');
  }

  @override
  void onPagePause() {
    super.onPagePause();
    _add('onPagePause');
  }

  @override
  void onPageStop() {
    super.onPageStop();
    _add('onPageStop');
  }

  @override
  void onPageDispose() {
    super.onPageDispose();
    _add('onPageDispose');
  }

  @override
  void onAppInactive() {
    super.onAppInactive();
    _add('onAppInactive');
  }

  @override
  void onAppPause() {
    super.onAppPause();
    _add('onAppPause');
  }

  @override
  void onAppResume() {
    super.onAppResume();
    _add('onAppResume');
  }

  @override
  void onAppForeground() {
    super.onAppForeground();
    _add('onAppForeground');
  }

  @override
  void onAppBackground() {
    super.onAppBackground();
    _add('onAppBackground');
  }

  @override
  void onPageIndexChanged(int from, int to) {
    super.onPageIndexChanged(from, to);
    _add('onPageIndexChanged:$from->$to');
  }

  @override
  void dispose() {
    _add('dispose');
    disposed = true;
    super.dispose();
  }
}

/// 在 `onPageInit` 里抛——验异常不会把它后面的回调一起带走。
class _BoomController extends _LogController {
  _BoomController() : super('boom');

  @override
  void onPageInit() {
    // 先让 super 把 ids 注册完，再抛：要验的是「链路不断」，不是「注册没做完」。
    super.onPageInit();
    throw StateError('controller 回调里抛了');
  }
}

class _BoomPage extends FlBasePage<_BoomController> {
  const _BoomPage();

  @override
  _BoomController createController(BuildContext context) => _BoomController();

  @override
  Widget buildWithController(
    BuildContext context,
    _BoomController controller,
  ) => const Scaffold(body: Text('boom'));
}

/// 按 tag 索引的保活用控制器，供 `wantKeepAlive` 用例事后查生死。
final Map<String, _LogController> _keepControllers = <String, _LogController>{};

class _KeepPage extends StatefulWidget {
  const _KeepPage({required this.tag, required this.keepAlive});

  final String tag;
  final bool keepAlive;

  @override
  State<_KeepPage> createState() => _KeepPageState();
}

class _KeepPageState extends FlBasePageState<_KeepPage, _LogController> {
  @override
  bool get wantKeepAlive => widget.keepAlive;

  @override
  _LogController createController(BuildContext context) =>
      _keepControllers[widget.tag] = _LogController(widget.tag);

  @override
  Widget buildWithController(BuildContext context, _LogController controller) =>
      Center(child: Text(widget.tag));
}

class _HomePage extends FlBasePage<_LogController> {
  const _HomePage();

  @override
  bool get observeAppLifecycle => true;

  @override
  _LogController createController(BuildContext context) =>
      _lastController = _LogController('home');

  @override
  Widget buildWithController(BuildContext context, _LogController controller) {
    _seenInBuild = controller;
    return const Scaffold(body: _CountText());
  }
}

/// 跟 [_HomePage] 一样，只是没打开 App 前后台开关。
class _QuietPage extends FlBasePage<_LogController> {
  const _QuietPage();

  @override
  _LogController createController(BuildContext context) =>
      _lastController = _LogController('home');

  @override
  Widget buildWithController(BuildContext context, _LogController controller) =>
      const Scaffold(body: Text('quiet'));
}

class _SecondPage extends FlBasePage<_LogController> {
  const _SecondPage();

  @override
  _LogController createController(BuildContext context) =>
      _secondController = _LogController('second');

  @override
  Widget buildWithController(BuildContext context, _LogController controller) =>
      const Scaffold(body: Text('second'));
}

class _CountText extends StatelessWidget {
  const _CountText();

  @override
  Widget build(BuildContext context) {
    final _LogController c = context.selectIds<_Id, _LogController>(const <_Id>[
      _Id.count,
    ]);
    return Text('count=${c.count}');
  }
}

class _StatefulHomePage extends StatefulWidget {
  const _StatefulHomePage();

  @override
  State<_StatefulHomePage> createState() => _StatefulHomePageState();
}

class _StatefulHomePageState
    extends FlBasePageState<_StatefulHomePage, _LogController> {
  @override
  _LogController createController(BuildContext context) =>
      _lastController = _LogController('stateful');

  @override
  Widget buildWithController(BuildContext context, _LogController controller) =>
      const Scaffold(body: Text('stateful'));
}

class _TabPage extends FlBasePage<_LogController> {
  const _TabPage(this.index);

  final int index;

  @override
  bool get observePageIndex => true;

  @override
  _LogController createController(BuildContext context) =>
      _LogController('tab$index');

  @override
  Widget buildWithController(BuildContext context, _LogController controller) =>
      Center(child: Text('tab$index'));
}
