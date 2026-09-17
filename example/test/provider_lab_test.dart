import 'package:example/pages/provider_lab_page.dart';
import 'package:fl_page_provider/fl_page_provider.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 把实验台自己写在页面文档里的那几条断言跑一遍——demo 声称什么，这里就验什么。
void main() {
  /// 读某个探针当前的 build 计数。
  int builds(WidgetTester tester, String id) {
    final Text text = tester.widget<Text>(
      find.byKey(ValueKey<String>('builds:$id')),
    );
    return int.parse(text.data!);
  }

  /// 一次性把所有静态探针的计数抓下来。
  Map<String, int> snapshot(WidgetTester tester) => <String, int>{
    for (final String id in <String>[
      'read',
      'watch',
      'sel-a',
      'sel-b',
      'sel-ab',
    ])
      id: builds(tester, id),
  };

  Future<void> tap(WidgetTester tester, String label) async {
    await tester.ensureVisible(find.text(label));
    await tester.tap(find.text(label));
    await tester.pumpAndSettle();
  }

  Future<void> pumpLab(WidgetTester tester) async {
    // 实验台整页比默认的 800x600 视口高得多，而 ListView 是懒构建的：视口不放大
    // 的话，下半屏的探针压根不会被 build，计数也就无从读起。
    tester.view.physicalSize = const Size(1400, 4000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      MaterialApp(
        home: const ProviderLabPage(),
        navigatorObservers: <NavigatorObserver>[FlRouteObserver()],
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('首帧：每个探针各构建一次', (tester) async {
    await pumpLab(tester);

    expect(snapshot(tester), <String, int>{
      'read': 1,
      'watch': 1,
      'sel-a': 1,
      'sel-b': 1,
      'sel-ab': 1,
    });
  });

  testWidgets('通知 A：只有关心 A 的探针重建，read 纹丝不动', (tester) async {
    await pumpLab(tester);
    final Map<String, int> before = snapshot(tester);

    await tap(tester, '通知 A');

    expect(builds(tester, 'read'), before['read'], reason: 'read 不建立依赖');
    expect(builds(tester, 'sel-b'), before['sel-b'], reason: 'B 没被通知');
    expect(builds(tester, 'watch'), before['watch']! + 1);
    expect(builds(tester, 'sel-a'), before['sel-a']! + 1);
    expect(builds(tester, 'sel-ab'), before['sel-ab']! + 1);
  });

  testWidgets('通知 C：无人关心，只有 watch 重建', (tester) async {
    await pumpLab(tester);
    final Map<String, int> before = snapshot(tester);

    await tap(tester, '通知 C（无人关心）');

    expect(
      builds(tester, 'watch'),
      before['watch']! + 1,
      reason: 'watch 不分 ID',
    );
    for (final String id in <String>['read', 'sel-a', 'sel-b', 'sel-ab']) {
      expect(builds(tester, id), before[id], reason: '$id 不该被 C 惊动');
    }
  });

  testWidgets('A+B 一起：关心 [a, b] 的探针只跳一次', (tester) async {
    await pumpLab(tester);
    final Map<String, int> before = snapshot(tester);

    await tap(tester, 'A+B 一起');

    expect(
      builds(tester, 'sel-ab'),
      before['sel-ab']! + 1,
      reason: '一次通知推进两个 ID，仍然只是一次重建',
    );
    expect(builds(tester, 'sel-a'), before['sel-a']! + 1);
    expect(builds(tester, 'sel-b'), before['sel-b']! + 1);
  });

  testWidgets('同帧连发 A×3：三次通知合并成一次重建', (tester) async {
    await pumpLab(tester);
    final Map<String, int> before = snapshot(tester);

    await tap(tester, '同帧连发 A×3');

    expect(
      builds(tester, 'sel-a'),
      before['sel-a']! + 1,
      reason: '同一帧内的三次通知被 _notifyScheduled 合并',
    );
    expect(builds(tester, 'watch'), before['watch']! + 1);
  });

  testWidgets('在 build 中通知 A：不抛异常，推迟到下一帧兑现', (tester) async {
    await pumpLab(tester);
    final int before = builds(tester, 'sel-a');

    await tap(tester, '在 build 中通知 A');

    expect(tester.takeException(), isNull, reason: '不该抛 setState during build');
    expect(builds(tester, 'sel-a'), before + 1, reason: '推迟一帧后照样兑现');
  });

  testWidgets('动态探针换了 ids 之后，旧 ID 立刻不再触发它重建', (tester) async {
    await pumpLab(tester);

    // 起始关心 A：通知 A 会让它重建。
    final int atStart = builds(tester, 'sel-dynamic');
    await tap(tester, '通知 A');
    expect(builds(tester, 'sel-dynamic'), atStart + 1);

    // 切到关心 B。这一下是父级驱动的重建，计数 +1。
    await tap(tester, '关心 B');
    final int afterSwitch = builds(tester, 'sel-dynamic');

    // 旧 ID 不该再触发它——登记表在重新登记时已经整表清空。
    await tap(tester, '通知 A');
    expect(
      builds(tester, 'sel-dynamic'),
      afterSwitch,
      reason: '换了 ids 之后 A 就不是依赖了，不必等下一轮',
    );

    // 新 ID 正常生效。
    await tap(tester, '通知 B');
    expect(builds(tester, 'sel-dynamic'), afterSwitch + 1);
  });

  testWidgets('FlSelector 的 child 不参与重建', (tester) async {
    await pumpLab(tester);
    expect(find.text('builder 调用次数：1   (A=0)'), findsOneWidget);
    expect(find.textContaining('child 构建次数：1'), findsOneWidget);

    await tap(tester, '通知 A');

    expect(find.text('builder 调用次数：2   (A=1)'), findsOneWidget);
    expect(
      find.textContaining('child 构建次数：1'),
      findsOneWidget,
      reason: 'child 是同一个 Widget 实例，子树整棵跳过',
    );
  });
}
