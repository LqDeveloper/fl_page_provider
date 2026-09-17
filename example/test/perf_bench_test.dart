import 'package:example/pages/perf_bench_page.dart';
import 'package:fl_page_provider/fl_page_provider.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 压测台的**确定性**那一半：重建量。
///
/// 帧时间只有 profile 模式的真机/桌面才量得准（见 `lib/pages/perf_bench_page.dart`
/// 顶部的说明），但「一次通知到底让多少个 widget 重建了」是确定的，不依赖硬件、
/// 不依赖 JIT，可以进 CI 当回归护栏——它才是帧时间背后真正的成本来源。
void main() {
  final int slots = BenchId.values.length; // 8

  /// 铺 [cells] 个 cell，返回控制器。
  Future<BenchController> pumpGrid(
    WidgetTester tester, {
    required BenchMode mode,
    required int cells,
  }) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    // 先整棵拆掉再铺新的。两个原因：
    // 1. FlProviderBuilder 的 create 只跑一次，原地换 widget 会继续用上一轮的
    //    controller，新建的那个根本没人听；
    // 2. 换 mode 相当于让 cell 改用另一种依赖方式，而 Flutter 只在 deactivate
    //    时解除依赖登记——不拆干净，上一轮的依赖会留在表里。
    await tester.pumpWidget(const SizedBox.shrink());

    final BenchController controller = BenchController();
    await tester.pumpWidget(
      MaterialApp(
        home: FlProviderBuilder<BenchController>(
          create: (_) => controller,
          // Wrap 不是懒构建的：不管可见与否，N 个 cell 全都会 build。
          builder: (_, _) => SingleChildScrollView(
            child: Wrap(
              children: <Widget>[
                for (int i = 0; i < cells; i++)
                  BenchCell(slot: i % slots, mode: mode),
              ],
            ),
          ),
        ),
      ),
    );
    return controller;
  }

  /// 数一次通知引发了多少个 cell 重建。
  Future<int> cellBuildsForOneNotify(
    WidgetTester tester,
    BenchController controller,
  ) async {
    BenchStats.reset();
    controller.bump(0);
    await tester.pump();
    return BenchStats.cellBuilds;
  }

  group('一次通知的重建量', () {
    testWidgets('selectIds：只重建认领了该 ID 的那 1/8', (tester) async {
      const int cells = 80;
      final BenchController c = await pumpGrid(
        tester,
        mode: BenchMode.selectIds,
        cells: cells,
      );

      expect(
        await cellBuildsForOneNotify(tester, c),
        cells ~/ slots,
        reason: '通知 slot 0，只有 index % 8 == 0 的那批该重建',
      );
    });

    testWidgets('watch：全量重建', (tester) async {
      const int cells = 80;
      final BenchController c = await pumpGrid(
        tester,
        mode: BenchMode.watch,
        cells: cells,
      );

      expect(
        await cellBuildsForOneNotify(tester, c),
        cells,
        reason: 'watch 不分 ID，每个 cell 都得重建',
      );
    });

    testWidgets('read：一个都不重建', (tester) async {
      const int cells = 80;
      final BenchController c = await pumpGrid(
        tester,
        mode: BenchMode.read,
        cells: cells,
      );

      expect(
        await cellBuildsForOneNotify(tester, c),
        0,
        reason: '这是基线：量到的帧时间里不含任何 cell 重建，只有机制本身的开销',
      );
    });
  });

  testWidgets('依赖方翻倍时，selectIds 的重建量按「关心的那部分」走', (tester) async {
    final BenchController small = await pumpGrid(
      tester,
      mode: BenchMode.selectIds,
      cells: 80,
    );
    final int at80 = await cellBuildsForOneNotify(tester, small);

    final BenchController big = await pumpGrid(
      tester,
      mode: BenchMode.selectIds,
      cells: 160,
    );
    final int at160 = await cellBuildsForOneNotify(tester, big);

    expect(at80, 10);
    expect(at160, 20);
    expect(at160, at80 * 2, reason: '重建量随「关心该 ID 的 cell 数」线性增长，而不是随依赖方总数');
  });

  testWidgets('同一帧内连发多次，只结算一次重建', (tester) async {
    final BenchController c = await pumpGrid(
      tester,
      mode: BenchMode.selectIds,
      cells: 80,
    );

    BenchStats.reset();
    c
      ..bump(0)
      ..bump(0)
      ..bump(0);
    await tester.pump();

    expect(
      BenchStats.cellBuilds,
      80 ~/ slots,
      reason: '三次通知落在同一帧，被 _notifyScheduled 合并成一次',
    );
  });

  // 之前这个文件只挂 BenchCell，从没挂过整页，于是页面自己的生命周期一次都没
  // 被跑过——下面这条断言就是这么漏掉的。
  group('页面生命周期', () {
    testWidgets('进页面不跑分就退出，不该踩 removeTimingsCallback 的断言', (tester) async {
      await tester.pumpWidget(const MaterialApp(home: PerfBenchPage()));
      await tester.pump();

      await tester.pumpWidget(const SizedBox.shrink()); // dispose
      await tester.pump();

      expect(
        tester.takeException(),
        isNull,
        reason: 'timings 回调压根没挂过，dispose 里不能无条件摘',
      );
    });

    testWidgets('跑分跑到一半退出，不报错', (tester) async {
      await tester.pumpWidget(const MaterialApp(home: PerfBenchPage()));
      await tester.pump();

      await tester.tap(find.text('跑三种模式'));
      for (int i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 16));
      }

      await tester.pumpWidget(const SizedBox.shrink()); // 跑分中途 dispose
      for (int i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 16));
      }

      expect(
        tester.takeException(),
        isNull,
        reason: 'post-frame 驱动循环要在 mounted 掉了之后自己收工',
      );
    });
  });

  // 时间数字只报不断言：debug + JIT 下的绝对值没有参考价值，CI 上更会抖。
  // 真正的帧时间请跑 profile 模式的压测台。
  testWidgets('参考数据：200 次通知的重建总量与耗时', (tester) async {
    const int cells = 400;
    const int notifies = 200;
    final StringBuffer report = StringBuffer('\n--- 重建量对照 (cells=$cells) ---');

    for (final BenchMode mode in BenchMode.values) {
      final BenchController c = await pumpGrid(
        tester,
        mode: mode,
        cells: cells,
      );
      BenchStats.reset();

      final Stopwatch sw = Stopwatch()..start();
      for (int i = 0; i < notifies; i++) {
        c.bump(i % slots);
        await tester.pump();
      }
      sw.stop();

      report.writeln(
        '\n${mode.label.padRight(14)} '
        'cell 重建 ${BenchStats.cellBuilds.toString().padLeft(6)} 次  '
        '(${(BenchStats.cellBuilds / notifies).toStringAsFixed(1)}/帧)  '
        '耗时 ${sw.elapsedMilliseconds} ms',
      );
    }

    debugPrint(report.toString());
  });
}
