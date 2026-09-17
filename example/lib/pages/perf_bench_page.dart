import 'dart:async';
import 'dart:developer' as developer;

import 'package:fl_page_provider/fl_page_provider.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../base_page_controller.dart';

/// 传 `--dart-define=BENCH_AUTORUN=true` 时，进 App 直接跑完整套跑分并把结果
/// 打到 stdout，用于 `flutter run -d macos --profile` 这种无人值守的采集。
const bool kBenchAutorun = bool.fromEnvironment('BENCH_AUTORUN');

/// 每轮跑分固定推进多少帧。240 帧在 60Hz 上是 4 秒，在 120Hz 上是 2 秒。
const int kBenchFrames = 240;

/// 更新引擎压测台：量 `FlPageProvider` 对**帧时间**的实际影响。
///
/// ## 测什么
///
/// 屏幕上铺 N 个依赖 cell，每个 cell 按 `index % 8` 认领 8 个 ID 中的一个。
/// 然后**每帧**通知一个 ID（轮流），连续 [kBenchFrames] 帧，期间用
/// `SchedulerBinding.addTimingsCallback` 收真实的 [FrameTiming]。
///
/// 三种模式跑同样的负载，唯一的差别是 cell 怎么建立依赖：
///
/// | 模式 | cell 的写法 | 每次通知重建几个 cell |
/// |---|---|---|
/// | `selectIds` | `context.selectIds([myId])` | N/8 |
/// | `watch` | `context.wc()` | N |
/// | `read`（基线） | `context.rc()` | 0 |
///
/// `read` 那一栏是关键：它一个 cell 都不重建，量到的就是**机制本身的固定开销**
/// ——provider 元素自己重建一次，加上 `notifyClients` 对 N 个依赖方扫一遍。
/// 把它和另外两栏相减，才分得清「哪些时间花在机制上、哪些花在真正的重建上」。
///
/// ## 怎么跑
///
/// 帧时间必须在 **profile 模式的真机/桌面**上量，debug 模式的 JIT 和断言会让
/// 数字大到没有参考价值，`flutter test` 里更是连光栅化都没有：
///
/// ```sh
/// cd example
/// flutter run -d macos --profile                      # 手动点
/// flutter run -d macos --profile \
///     --dart-define=BENCH_AUTORUN=true                # 自动跑完打印结果
/// ```
///
/// macOS 跑不起来先看部署目标：`macos/Runner.xcodeproj` 里的
/// `MACOSX_DEPLOYMENT_TARGET` 还是 10.15，新版 Xcode 的下限是 12.0，不改的话
/// 连编都编不过。这里没动它——例子的部署目标该定在哪是工程决定，不是跑分要求。
///
/// 重建次数这类**确定性**指标不需要设备，见 `test/perf_bench_test.dart`。
class PerfBenchPage extends StatefulWidget {
  const PerfBenchPage({super.key});

  @override
  State<PerfBenchPage> createState() => _PerfBenchPageState();
}

// ---------------------------------------------------------------------------
// 计数与控制器
// ---------------------------------------------------------------------------

/// 所有 cell 的 build 次数总和。跑分页和 headless 测试共用。
class BenchStats {
  BenchStats._();

  static int cellBuilds = 0;

  static void reset() => cellBuilds = 0;
}

/// 8 个槽位，cell 按 `index % 8` 认领其中一个。
enum BenchId { s0, s1, s2, s3, s4, s5, s6, s7 }

class BenchController extends BasePageController<BenchId> {
  /// 不经页面（headless 跑分/测试）直接用时，页面侧的 `onPageInit` 不会来，
  /// 这里把注册补上；经页面用时 `onPageInit` 会再注册一次，幂等。
  BenchController() {
    registerIds(shouldNotifyIds);
  }

  @override
  List<BenchId> get shouldNotifyIds => BenchId.values;

  final List<int> _slots = List<int>.filled(BenchId.values.length, 0);

  int valueOf(int slot) => _slots[slot];

  /// 推进一个槽位并只通知它对应的 ID。
  void bump(int slot) {
    _slots[slot]++;
    notifySingleListener(BenchId.values[slot]);
  }
}

enum BenchMode {
  selectIds('selectIds', 'context.selectIds([myId])'),
  watch('watch', 'context.wc()'),
  read('read（基线）', 'context.rc() —— 一个 cell 都不重建');

  const BenchMode(this.label, this.detail);

  final String label;
  final String detail;
}

// ---------------------------------------------------------------------------
// 统计
// ---------------------------------------------------------------------------

/// 一组耗时样本的分布，单位微秒。
class BenchStatsLine {
  const BenchStatsLine({
    required this.mean,
    required this.p50,
    required this.p90,
    required this.p99,
    required this.max,
  });

  final double mean;
  final int p50;
  final int p90;
  final int p99;
  final int max;

  static BenchStatsLine of(List<int> samples) {
    if (samples.isEmpty) {
      return const BenchStatsLine(mean: 0, p50: 0, p90: 0, p99: 0, max: 0);
    }
    final List<int> sorted = List<int>.of(samples)..sort();
    int pick(double q) =>
        sorted[((sorted.length - 1) * q).round().clamp(0, sorted.length - 1)];
    final int total = sorted.reduce((int a, int b) => a + b);
    return BenchStatsLine(
      mean: total / sorted.length,
      p50: pick(0.50),
      p90: pick(0.90),
      p99: pick(0.99),
      max: sorted.last,
    );
  }
}

/// 一轮跑分的结果。
class BenchResult {
  const BenchResult({
    required this.mode,
    required this.cells,
    required this.frames,
    required this.cellBuilds,
    required this.build,
    required this.raster,
    required this.total,
    required this.budgetMicros,
    required this.janky,
  });

  final BenchMode mode;
  final int cells;

  /// 实际采到的帧数（不一定等于 [kBenchFrames]，采样回调是批量回调的）。
  final int frames;

  /// 这一轮里所有 cell 的 build 次数总和。
  final int cellBuilds;

  final BenchStatsLine build;
  final BenchStatsLine raster;
  final BenchStatsLine total;

  /// 当前屏幕的单帧预算，单位微秒。
  final int budgetMicros;

  /// 超出预算的帧数。
  final int janky;

  /// 平均每帧重建了几个 cell——区分三种模式的核心指标。
  double get cellBuildsPerFrame => frames == 0 ? 0 : cellBuilds / frames;

  double get jankRate => frames == 0 ? 0 : janky / frames;
}

// ---------------------------------------------------------------------------
// 页面
// ---------------------------------------------------------------------------

class _PerfBenchPageState
    extends FlBasePageState<PerfBenchPage, BenchController> {
  late final BenchController _controller;

  int _cells = 400;
  BenchMode _mode = BenchMode.selectIds;

  /// 非 null 表示正在跑分。
  BenchMode? _running;
  int _framesLeft = 0;
  int _slot = 0;

  final List<int> _buildMicros = <int>[];
  final List<int> _rasterMicros = <int>[];
  final List<int> _totalMicros = <int>[];

  final List<BenchResult> _results = <BenchResult>[];

  @override
  BenchController createController(BuildContext context) =>
      _controller = BenchController();

  @override
  void initState() {
    super.initState();
    if (kBenchAutorun) {
      SchedulerBinding.instance.addPostFrameCallback((_) => _autorun());
    }
  }

  @override
  void dispose() {
    _unhookTimings();
    super.dispose();
  }

  /// timings 回调此刻是否挂着。
  ///
  /// `removeTimingsCallback` 会断言「这个回调必须先挂过」，而它只在跑分期间挂：
  /// 进了页面什么都不点就退出，无条件摘就会踩中那条断言。
  bool _timingsHooked = false;

  void _hookTimings() {
    if (_timingsHooked) return;
    _timingsHooked = true;
    SchedulerBinding.instance.addTimingsCallback(_onTimings);
  }

  void _unhookTimings() {
    if (!_timingsHooked) return;
    _timingsHooked = false;
    SchedulerBinding.instance.removeTimingsCallback(_onTimings);
  }

  int get _budgetMicros {
    final double hz = WidgetsBinding
        .instance
        .platformDispatcher
        .views
        .first
        .display
        .refreshRate;
    return hz > 0 ? (1000000 / hz).round() : 16667;
  }

  void _onTimings(List<FrameTiming> timings) {
    for (final FrameTiming t in timings) {
      _buildMicros.add(t.buildDuration.inMicroseconds);
      _rasterMicros.add(t.rasterDuration.inMicroseconds);
      _totalMicros.add(t.totalSpan.inMicroseconds);
    }
  }

  // ---- 跑分驱动 ----------------------------------------------------------

  Future<BenchResult> _runOnce(BenchMode mode) async {
    // 先把这一模式的 cell 挂上，空跑几帧让首建和布局的开销沉下去。
    setState(() {
      _mode = mode;
      _running = mode;
    });
    await _settle(10);

    BenchStats.reset();
    _buildMicros.clear();
    _rasterMicros.clear();
    _totalMicros.clear();
    _slot = 0;
    _framesLeft = kBenchFrames;

    _hookTimings();
    await _drive();
    _unhookTimings();

    // 采样回调是批量投递的，末尾那几帧要等一等才收得齐。
    await _settle(5);

    final int budget = _budgetMicros;
    final BenchResult result = BenchResult(
      mode: mode,
      cells: _cells,
      frames: _totalMicros.length,
      cellBuilds: BenchStats.cellBuilds,
      build: BenchStatsLine.of(_buildMicros),
      raster: BenchStatsLine.of(_rasterMicros),
      total: BenchStatsLine.of(_totalMicros),
      budgetMicros: budget,
      janky: _totalMicros.where((int t) => t > budget).length,
    );

    if (mounted) setState(() => _running = null);
    return result;
  }

  /// 每帧推进一个槽位，连续 [kBenchFrames] 帧。
  Future<void> _drive() {
    final Completer<void> done = Completer<void>();
    void step(Duration _) {
      // post-frame 回调是挂在 binding 上的，跟本 Element 没关系：跑分中途退出
      // 页面，这个循环还会自顾自跑完剩下的帧。mounted 一掉就收工。
      if (!mounted || _framesLeft <= 0) {
        done.complete();
        return;
      }
      _framesLeft--;
      _controller.bump(_slot++ % BenchId.values.length);
      SchedulerBinding.instance
        ..addPostFrameCallback(step)
        // read 模式下没有 cell 变脏，靠 bump 本身排的那次元素重建也会带出帧；
        // 显式再排一次，保证节奏稳定在「一帧一次通知」。
        ..scheduleFrame();
    }

    SchedulerBinding.instance
      ..addPostFrameCallback(step)
      ..scheduleFrame();
    return done.future;
  }

  Future<void> _settle(int frames) async {
    for (int i = 0; i < frames; i++) {
      final Completer<void> c = Completer<void>();
      SchedulerBinding.instance
        ..addPostFrameCallback((_) => c.complete())
        ..scheduleFrame();
      await c.future;
    }
  }

  Future<void> _runAll() async {
    for (final BenchMode mode in BenchMode.values) {
      final BenchResult r = await _runOnce(mode);
      if (!mounted) return;
      setState(() => _results.add(r));
    }
  }

  Future<void> _autorun() async {
    developer.log(
      'bench: 开跑，cells=$_cells frames=$kBenchFrames',
      name: 'bench',
    );
    await _runAll();
    // ignore: avoid_print  —— 这是跑分报告，就是要出现在 stdout 里
    print(_reportText());
  }

  String _reportText() {
    final StringBuffer b = StringBuffer()
      ..writeln('')
      ..writeln('===== FL_CORE_PROVIDER BENCH =====')
      ..writeln(
        'mode=${kDebugMode ? "debug" : (kProfileMode ? "profile" : "release")}  '
        'cells=$_cells  frames/run=$kBenchFrames  '
        'budget=${(_budgetMicros / 1000).toStringAsFixed(2)}ms',
      )
      ..writeln('')
      ..writeln(
        '| 模式 | 帧数 | 重建 cell/帧 | build p50 | build p90 | build p99 | '
        'raster p50 | total p99 | 超预算帧 |',
      )
      ..writeln('|---|---|---|---|---|---|---|---|---|');
    for (final BenchResult r in _results) {
      String ms(int micros) => (micros / 1000).toStringAsFixed(2);
      b.writeln(
        '| ${r.mode.label} | ${r.frames} | ${r.cellBuildsPerFrame.toStringAsFixed(1)} '
        '| ${ms(r.build.p50)} | ${ms(r.build.p90)} | ${ms(r.build.p99)} '
        '| ${ms(r.raster.p50)} | ${ms(r.total.p99)} '
        '| ${r.janky} (${(r.jankRate * 100).toStringAsFixed(1)}%) |',
      );
    }
    b.writeln('===== END BENCH =====');
    return b.toString();
  }

  // ---- UI ----------------------------------------------------------------

  @override
  Widget buildWithController(BuildContext context, BenchController controller) {
    final ThemeData theme = Theme.of(context);
    final bool busy = _running != null;

    return Scaffold(
      appBar: AppBar(title: const Text('更新引擎压测台')),
      body: Column(
        children: <Widget>[
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                if (kDebugMode)
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(10),
                    margin: const EdgeInsets.only(bottom: 10),
                    decoration: BoxDecoration(
                      color: theme.colorScheme.error.withValues(alpha: 0.08),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      'debug 模式：JIT + 断言会把帧时间放大若干倍，这里的绝对值没有参考价值。\n'
                      '量帧率请用 flutter run -d macos --profile',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.error,
                      ),
                    ),
                  ),
                Wrap(
                  spacing: 8,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: <Widget>[
                    const Text('cell 数'),
                    for (final int n in <int>[100, 400, 1000])
                      ChoiceChip(
                        label: Text('$n'),
                        selected: _cells == n,
                        onSelected: busy
                            ? null
                            : (_) => setState(() => _cells = n),
                      ),
                    const SizedBox(width: 12),
                    FilledButton(
                      onPressed: busy ? null : _runAll,
                      child: Text(busy ? '跑分中：${_running!.label}…' : '跑三种模式'),
                    ),
                    if (_results.isNotEmpty && !busy)
                      TextButton(
                        onPressed: () => setState(_results.clear),
                        child: const Text('清空结果'),
                      ),
                  ],
                ),
              ],
            ),
          ),
          if (_results.isNotEmpty) _ResultTable(results: _results),
          const Divider(height: 1),
          Expanded(
            child: ClipRect(
              child: SingleChildScrollView(
                // key 随模式变：换模式时整棵 cell 子树**重建**而不是原地更新。
                // 必须这样——Flutter 只在 Element.deactivate() 时解除依赖登记，
                // 原地更新的话上一轮（比如 watch 的全量依赖）会留在登记表里，
                // 基线那一栏就不再是 0 重建，量出来的东西全是错的。
                child: Wrap(
                  key: ValueKey<BenchMode>(_mode),
                  children: <Widget>[
                    for (int i = 0; i < _cells; i++)
                      BenchCell(slot: i % BenchId.values.length, mode: _mode),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 依赖 cell
// ---------------------------------------------------------------------------

/// 一个依赖 cell。公开是为了让 `test/perf_bench_test.dart` 能不经整页直接搭
/// 场景——重建次数那类确定性指标不需要真机。
class BenchCell extends StatelessWidget {
  const BenchCell({required this.slot, required this.mode, super.key});

  final int slot;
  final BenchMode mode;

  @override
  Widget build(BuildContext context) {
    BenchStats.cellBuilds++;
    final BenchController c = switch (mode) {
      BenchMode.selectIds => context.selectIds<BenchId, BenchController>(
        <BenchId>[BenchId.values[slot]],
      ),
      BenchMode.watch => context.wc<BenchController>(),
      BenchMode.read => context.rc<BenchController>(),
    };
    final int v = c.valueOf(slot);
    return Container(
      width: 22,
      height: 22,
      margin: const EdgeInsets.all(1),
      alignment: Alignment.center,
      color: Color.lerp(
        const Color(0xFFE3F2FD),
        const Color(0xFF1565C0),
        (v % 10) / 10,
      ),
      child: Text(
        '${v % 10}',
        style: const TextStyle(fontSize: 10, color: Colors.black87),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 结果表
// ---------------------------------------------------------------------------

class _ResultTable extends StatelessWidget {
  const _ResultTable({required this.results});

  final List<BenchResult> results;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    String ms(int micros) => (micros / 1000).toStringAsFixed(2);

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(
          headingRowHeight: 34,
          dataRowMinHeight: 30,
          dataRowMaxHeight: 34,
          columnSpacing: 18,
          columns: const <DataColumn>[
            DataColumn(label: Text('模式')),
            DataColumn(label: Text('帧数')),
            DataColumn(label: Text('重建 cell/帧')),
            DataColumn(label: Text('build p50')),
            DataColumn(label: Text('build p90')),
            DataColumn(label: Text('build p99')),
            DataColumn(label: Text('raster p50')),
            DataColumn(label: Text('超预算帧')),
          ],
          rows: <DataRow>[
            for (final BenchResult r in results)
              DataRow(
                cells: <DataCell>[
                  DataCell(Text(r.mode.label)),
                  DataCell(Text('${r.frames}')),
                  DataCell(
                    Text(
                      r.cellBuildsPerFrame.toStringAsFixed(1),
                      style: theme.textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  DataCell(Text(ms(r.build.p50))),
                  DataCell(Text(ms(r.build.p90))),
                  DataCell(Text(ms(r.build.p99))),
                  DataCell(Text(ms(r.raster.p50))),
                  DataCell(
                    Text(
                      '${r.janky} (${(r.jankRate * 100).toStringAsFixed(1)}%)',
                    ),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}
