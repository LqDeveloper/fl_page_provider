import 'package:fl_page_provider/fl_page_provider.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

/// 查找与所有权：`rc` / `wc` / `selectIds` 到底会命中哪一个 provider，
/// 以及「一个控制器只能被一个 provider 认领」这条单向所有权。
void main() {
  Widget host(Widget child) =>
      Directionality(textDirection: TextDirection.ltr, child: child);

  group('按精确泛型查找', () {
    testWidgets('provider 给的是子类，用父类型取不到', (WidgetTester tester) async {
      await tester.pumpWidget(
        host(
          FlProviderBuilder<_ChildController>(
            create: (_) => _ChildController(),
            builder: (_, _) => Builder(
              builder: (BuildContext context) {
                context.rc<_ParentController>();
                return const SizedBox.shrink();
              },
            ),
          ),
        ),
      );

      expect(tester.takeException(), isNotNull);
    });

    testWidgets('provider 给的是父类，用子类型也取不到', (WidgetTester tester) async {
      await tester.pumpWidget(
        host(
          FlProviderBuilder<_ParentController>(
            create: (_) => _ParentController(),
            builder: (_, _) => Builder(
              builder: (BuildContext context) {
                context.rc<_ChildController>();
                return const SizedBox.shrink();
              },
            ),
          ),
        ),
      );

      expect(tester.takeException(), isNotNull);
    });

    testWidgets('报错信息点名了控制器类型和发起查找的 widget', (WidgetTester tester) async {
      await tester.pumpWidget(
        host(
          Builder(
            builder: (BuildContext context) {
              context.rc<_ParentController>();
              return const SizedBox.shrink();
            },
          ),
        ),
      );

      final String message = tester.takeException().toString();
      expect(message, contains('_ParentController'));
      expect(message, contains('Builder'));
    });
  });

  group('嵌套', () {
    testWidgets('两种控制器各取各的，互不遮挡', (WidgetTester tester) async {
      late _ParentController outer;
      late _ChildController inner;
      _ParentController? readOuter;
      _ChildController? readInner;

      await tester.pumpWidget(
        host(
          FlProviderBuilder<_ParentController>(
            create: (_) => outer = _ParentController(),
            builder: (_, _) => FlProviderBuilder<_ChildController>(
              create: (_) => inner = _ChildController(),
              builder: (_, _) => Builder(
                builder: (BuildContext context) {
                  readOuter = context.rc<_ParentController>();
                  readInner = context.rc<_ChildController>();
                  return const SizedBox.shrink();
                },
              ),
            ),
          ),
        ),
      );

      expect(identical(readOuter, outer), isTrue);
      expect(identical(readInner, inner), isTrue);
    });

    testWidgets('同类型嵌套：取到的是最近的那一层', (WidgetTester tester) async {
      late _ParentController outer;
      late _ParentController inner;
      _ParentController? seen;

      await tester.pumpWidget(
        host(
          FlProviderBuilder<_ParentController>(
            create: (_) => outer = _ParentController(),
            builder: (_, _) => FlProviderBuilder<_ParentController>(
              create: (_) => inner = _ParentController(),
              builder: (_, _) => Builder(
                builder: (BuildContext context) {
                  seen = context.rc<_ParentController>();
                  return const SizedBox.shrink();
                },
              ),
            ),
          ),
        ),
      );

      expect(identical(seen, inner), isTrue);
      expect(identical(seen, outer), isFalse);
    });

    testWidgets('builder 拿到的 context 在 provider 之下：同类型嵌套也不会串台', (
      WidgetTester tester,
    ) async {
      late _ParentController inner;
      _ParentController? fromBuilderContext;

      await tester.pumpWidget(
        host(
          FlProviderBuilder<_ParentController>(
            create: (_) => _ParentController(),
            builder: (_, _) => FlProviderBuilder<_ParentController>(
              create: (_) => inner = _ParentController(),
              // 直接用 builder 给的 context 读，不再套 Builder。
              builder: (BuildContext context, _) {
                fromBuilderContext = context.rc<_ParentController>();
                return const SizedBox.shrink();
              },
            ),
          ),
        ),
      );

      expect(identical(fromBuilderContext, inner), isTrue);
    });
  });

  group('单向所有权', () {
    testWidgets('同一个实例交给两个 provider 会断言', (WidgetTester tester) async {
      final _ParentController shared = _ParentController();
      addTearDown(() {
        if (!shared.disposed) shared.dispose();
      });

      await tester.pumpWidget(
        host(
          FlProviderBuilder<_ParentController>(
            create: (_) => shared,
            builder: (_, _) => FlProviderBuilder<_ParentController>(
              create: (_) => shared,
              builder: (_, _) => const SizedBox.shrink(),
            ),
          ),
        ),
      );

      expect(tester.takeException(), isAssertionError);
    });

    testWidgets('子树重新挂载会造一个新控制器，旧的已经 dispose', (WidgetTester tester) async {
      late _ParentController first;
      late _ParentController second;

      await tester.pumpWidget(
        host(
          FlProviderBuilder<_ParentController>(
            create: (_) => first = _ParentController(),
            builder: (_, _) => const SizedBox.shrink(),
          ),
        ),
      );
      await tester.pumpWidget(host(const SizedBox.shrink()));
      await tester.pumpWidget(
        host(
          FlProviderBuilder<_ParentController>(
            create: (_) => second = _ParentController(),
            builder: (_, _) => const SizedBox.shrink(),
          ),
        ),
      );

      expect(first.disposed, isTrue);
      expect(second.disposed, isFalse);
      expect(identical(first, second), isFalse);
    });
  });

  group('create 的执行时机', () {
    testWidgets('跑在 build 里，因此能安全地读 InheritedWidget', (
      WidgetTester tester,
    ) async {
      TextDirection? seen;

      await tester.pumpWidget(
        host(
          FlProviderBuilder<_ParentController>(
            create: (BuildContext context) {
              // 若 create 跑在 initState 里，这一行会抛。
              seen = Directionality.of(context);
              return _ParentController();
            },
            builder: (_, _) => const SizedBox.shrink(),
          ),
        ),
      );

      expect(tester.takeException(), isNull);
      expect(seen, TextDirection.ltr);
    });
  });
}

enum _Id { value }

class _ParentController extends FlBaseController<_Id> {
  @override
  List<_Id> get shouldNotifyIds => const <_Id>[_Id.value];

  bool disposed = false;

  @override
  void dispose() {
    disposed = true;
    super.dispose();
  }
}

class _ChildController extends _ParentController {}
