import 'package:fl_page_provider/fl_page_provider.dart';
import 'package:flutter/material.dart';

import '../base_page_controller.dart';

/// 更新引擎实验台：把 `FlPageProvider` 的重建行为**摆到屏幕上**。
///
/// 每个探针卡片自己数自己被 build 了多少次。按下触发按钮后，哪几张卡片的计数
/// 跳了、哪几张没跳，就是这套 ID 粒度机制的全部行为。
///
/// 值得动手确认的几件事：
///
/// - `read` 探针永远停在 1，读到的值一直是第一次构建时的快照——它没建立依赖；
/// - `selectIds([a])` 只在通知 A 时跳；通知 C 时全场只有 `watch` 探针跳；
/// - 「同帧连发 A×3」只让计数 +1，三次通知在元素侧被合并成一次重建；
/// - 「在 build 中通知 A」不会抛 `setState during build`，重建推迟到下一帧；
/// - 动态探针从关心 A 改成关心 B 之后，再通知 A 它**立刻**不再跳——登记表在
///   重新登记时就被清空了，不管这次重建是谁触发的。
///
/// 页面上除动态探针外的卡片都是 `const`：页面自身 `setState` 时它们是同一个
/// Widget 实例，子树被整棵跳过，计数不会被无关的重建污染。
class ProviderLabPage extends StatefulWidget {
  const ProviderLabPage({super.key});

  @override
  State<ProviderLabPage> createState() => _ProviderLabPageState();
}

class _ProviderLabPageState
    extends FlBasePageState<ProviderLabPage, LabController> {
  /// 置位后下一次 build 会在 build 期间发一次通知。
  bool _fireDuringBuild = false;

  @override
  LabController createController(BuildContext context) => LabController();

  @override
  Widget buildWithController(BuildContext context, LabController controller) {
    if (_fireDuringBuild) {
      _fireDuringBuild = false;
      // 此刻正处在 build 阶段，markNeedsBuild 是非法的。
      // FlInheritedElement 检测到 persistentCallbacks，把重建推迟到本帧收尾之后。
      controller.bumpA();
    }

    return Scaffold(
      appBar: AppBar(title: const Text('更新引擎实验台')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: <Widget>[
          const _Intro(),
          const SizedBox(height: 16),
          _TriggerCard(
            controller: controller,
            onFireDuringBuild: () => setState(() => _fireDuringBuild = true),
          ),
          const SizedBox(height: 20),
          const _SectionTitle('探针：谁重建了'),
          const SizedBox(height: 8),
          const _Probe(
            id: 'read',
            title: 'context.rc()',
            subtitle: '不建依赖 —— 永远停在 1，读数永远是第一帧的快照',
            mode: _ProbeMode.read,
          ),
          const _Probe(
            id: 'watch',
            title: 'context.wc()',
            subtitle: '全量依赖 —— 每一次通知都跳，不分 ID',
            mode: _ProbeMode.watch,
          ),
          const _Probe(
            id: 'sel-a',
            title: 'context.selectIds([a])',
            subtitle: '只认 A',
            mode: _ProbeMode.select,
            ids: <LabId>[LabId.a],
          ),
          const _Probe(
            id: 'sel-b',
            title: 'context.selectIds([b])',
            subtitle: '只认 B',
            mode: _ProbeMode.select,
            ids: <LabId>[LabId.b],
          ),
          const _Probe(
            id: 'sel-ab',
            title: 'context.selectIds([a, b])',
            subtitle: 'A 或 B 任一变化都跳；A+B 同时推进也只跳一次',
            mode: _ProbeMode.select,
            ids: <LabId>[LabId.a, LabId.b],
          ),
          const SizedBox(height: 20),
          const _SectionTitle('登记表会跟着 ids 变'),
          const SizedBox(height: 8),
          const _DynamicProbeSection(),
          const SizedBox(height: 20),
          const _SectionTitle('FlSelector 的 child'),
          const SizedBox(height: 8),
          const _ChildHoistDemo(),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Controller
// ---------------------------------------------------------------------------

enum LabId { a, b, c }

class LabController extends BasePageController<LabId> {
  @override
  List<LabId> get shouldNotifyIds => LabId.values;

  int _a = 0;
  int _b = 0;
  int _c = 0;
  int _notifies = 0;

  int get a => _a;
  int get b => _b;
  int get c => _c;

  /// 控制器一共喊了多少嗓子，用来和探针的重建次数对照。
  int get notifies => _notifies;

  void bumpA() {
    _a++;
    _notifies++;
    notifySingleListener(LabId.a);
  }

  void bumpB() {
    _b++;
    _notifies++;
    notifySingleListener(LabId.b);
  }

  /// 没有任何探针关心 C：除 `watch` 外应当全场不动。
  void bumpC() {
    _c++;
    _notifies++;
    notifySingleListener(LabId.c);
  }

  /// 同步连发三次。三次通知落在同一帧，元素侧合并成一次重建。
  void bumpAThrice() {
    bumpA();
    bumpA();
    bumpA();
  }

  /// 一次推进 A 和 B。关心 [a, b] 的探针只跳一次，不是两次。
  void bumpAB() {
    _a++;
    _b++;
    _notifies++;
    notifyMultiListeners(const <LabId>[LabId.a, LabId.b]);
  }
}

// ---------------------------------------------------------------------------
// 探针
// ---------------------------------------------------------------------------

enum _ProbeMode { read, watch, select }

/// 自己数自己被 build 了几次的卡片。
class _Probe extends StatefulWidget {
  const _Probe({
    required this.id,
    required this.title,
    required this.subtitle,
    required this.mode,
    this.ids = const <LabId>[],
  });

  /// 计数文本的 key 后缀，让 widget test 能定位到具体某个探针。
  final String id;
  final String title;
  final String subtitle;
  final _ProbeMode mode;
  final List<LabId> ids;

  @override
  State<_Probe> createState() => _ProbeState();
}

class _ProbeState extends State<_Probe> {
  int _builds = 0;

  @override
  Widget build(BuildContext context) {
    _builds++;
    final LabController c = switch (widget.mode) {
      _ProbeMode.read => context.rc<LabController>(),
      _ProbeMode.watch => context.wc<LabController>(),
      _ProbeMode.select => context.selectIds<LabId, LabController>(widget.ids),
    };

    final ThemeData theme = Theme.of(context);
    final bool frozen = widget.mode == _ProbeMode.read;

    return Card(
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 4),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: theme.dividerColor.withValues(alpha: 0.3)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        child: Row(
          children: <Widget>[
            _BuildCountBadge(count: _builds, muted: frozen, id: widget.id),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    widget.title,
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w600,
                      fontFamily: 'monospace',
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    widget.subtitle,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurface.withValues(alpha: 0.5),
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'A=${c.a}   B=${c.b}   C=${c.c}   ·   控制器已喊 ${c.notifies} 次',
                    style: theme.textTheme.bodySmall?.copyWith(
                      fontFamily: 'monospace',
                      color: frozen
                          ? theme.colorScheme.error
                          : theme.colorScheme.onSurface.withValues(alpha: 0.8),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _BuildCountBadge extends StatelessWidget {
  const _BuildCountBadge({
    required this.count,
    required this.id,
    this.muted = false,
  });

  final int count;
  final String id;
  final bool muted;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Color color = muted
        ? theme.colorScheme.onSurface.withValues(alpha: 0.3)
        : theme.colorScheme.primary;
    return Container(
      width: 46,
      height: 46,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: <Widget>[
          Text(
            '$count',
            key: ValueKey<String>('builds:$id'),
            style: theme.textTheme.titleMedium?.copyWith(
              color: color,
              fontWeight: FontWeight.w700,
              height: 1,
            ),
          ),
          Text(
            'build',
            style: theme.textTheme.labelSmall?.copyWith(
              color: color,
              fontSize: 9,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 动态 ID 探针：演示登记表在重新登记时被清空
// ---------------------------------------------------------------------------

/// 自带 `setState` 的一小块，切换时**只**重建这一段，不惊动上面那些探针。
class _DynamicProbeSection extends StatefulWidget {
  const _DynamicProbeSection();

  @override
  State<_DynamicProbeSection> createState() => _DynamicProbeSectionState();
}

class _DynamicProbeSectionState extends State<_DynamicProbeSection> {
  LabId _watched = LabId.a;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          '切换它关心的 ID，然后去通知**旧的**那个——计数不该再跳。\n'
          '（切换本身会让它 +1：那是父级驱动的重建。）',
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurface.withValues(alpha: 0.6),
          ),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          children: <Widget>[
            for (final LabId id in <LabId>[LabId.a, LabId.b])
              ChoiceChip(
                label: Text('关心 ${id.name.toUpperCase()}'),
                selected: _watched == id,
                onSelected: (_) => setState(() => _watched = id),
              ),
          ],
        ),
        const SizedBox(height: 4),
        _Probe(
          id: 'sel-dynamic',
          title: 'context.selectIds([${_watched.name}])',
          subtitle: '登记表随 ids 变化整表重来，旧 ID 不会多活一轮',
          mode: _ProbeMode.select,
          ids: <LabId>[_watched],
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// FlSelector 的 child：静态子树被摘出重建范围
// ---------------------------------------------------------------------------

class _ChildHoistDemo extends StatefulWidget {
  const _ChildHoistDemo();

  @override
  State<_ChildHoistDemo> createState() => _ChildHoistDemoState();
}

class _ChildHoistDemoState extends State<_ChildHoistDemo> {
  int _builderCalls = 0;
  int _childBuilds = 0;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Card(
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 4),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: theme.dividerColor.withValues(alpha: 0.3)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        child: FlSelector<LabId, LabController>(
          ids: const <LabId>[LabId.a],
          // 这个 child 只构建一次，之后每次重建都把同一个实例交还给 builder，
          // Flutter 见到同一个 Widget 实例就整棵跳过。
          child: Builder(
            builder: (_) {
              _childBuilds++;
              return Text(
                'child 构建次数：$_childBuilds  ← 通知 A 时它不动',
                style: theme.textTheme.bodySmall?.copyWith(
                  fontFamily: 'monospace',
                  color: theme.colorScheme.onSurface.withValues(alpha: 0.5),
                ),
              );
            },
          ),
          builder: (_, LabController controller, Widget? child) {
            _builderCalls++;
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  'builder 调用次数：$_builderCalls   (A=${controller.a})',
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontFamily: 'monospace',
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 4),
                child!,
              ],
            );
          },
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 触发区 & 杂项
// ---------------------------------------------------------------------------

class _TriggerCard extends StatelessWidget {
  const _TriggerCard({
    required this.controller,
    required this.onFireDuringBuild,
  });

  final LabController controller;
  final VoidCallback onFireDuringBuild;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Card(
      elevation: 0,
      color: theme.colorScheme.primary.withValues(alpha: 0.04),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: theme.colorScheme.primary.withValues(alpha: 0.2),
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(
              '触发通知',
              style: theme.textTheme.titleSmall?.copyWith(
                fontWeight: FontWeight.w600,
                color: theme.colorScheme.primary,
              ),
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: <Widget>[
                _Btn('通知 A', controller.bumpA),
                _Btn('通知 B', controller.bumpB),
                _Btn('通知 C（无人关心）', controller.bumpC),
                _Btn('A+B 一起', controller.bumpAB),
                _Btn('同帧连发 A×3', controller.bumpAThrice),
                _Btn('在 build 中通知 A', onFireDuringBuild),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Btn extends StatelessWidget {
  const _Btn(this.label, this.onPressed);

  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton(
      onPressed: onPressed,
      style: OutlinedButton.styleFrom(
        visualDensity: VisualDensity.compact,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
      child: Text(label),
    );
  }
}

class _Intro extends StatelessWidget {
  const _Intro();

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Text(
      '每张卡片左侧是它自己的 build 次数。按下面的按钮，观察哪些卡片跳了、'
      '哪些没跳——那就是 ID 粒度重建的全部行为。',
      style: theme.textTheme.bodySmall?.copyWith(
        color: theme.colorScheme.onSurface.withValues(alpha: 0.6),
        height: 1.5,
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Text(
      text,
      style: theme.textTheme.titleSmall?.copyWith(
        color: theme.colorScheme.primary,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.5,
      ),
    );
  }
}
