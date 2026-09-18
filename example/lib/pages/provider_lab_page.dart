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
/// - `FlSelector(ids: [a])` 只在通知 A 时跳；通知 C 时全场只有「列了全部 ID」的
///   那个探针跳；
/// - 「同帧连发 A×3」只让计数 +1，三次通知在元素侧被合并成一次重建；
/// - 「在 build 中通知 A」不会抛 `setState during build`，重建推迟到下一帧；
/// - 动态探针从关心 A 改成关心 B 之后，再通知 A 它**立刻**不再跳——登记表在
///   重新登记时就被清空了，不管这次重建是谁触发的。
///
/// 最后一块摆的不是重建而是**所有权**——控制器归
/// `FlInheritedElement`，不归任何 Widget（与 `provider` 把值挂在
/// `_InheritedProviderScopeElement` 上是同一个分工）：
///
/// - 「父级 setState」按多少次，`create` 的调用次数都停在 1，控制器还是同一个
///   实例——Element 本就是跨重建活着的那个对象；
/// - 卸掉那一小块子树，控制器立刻 `dispose`；重新挂载拿到的是一个**新**实例；
/// - 同类型嵌套时，内层 `create` 里的 `rc<LabController>()` 拿到的是**外层**那个
///   实例，不是正在创建中的自己。
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
            title: 'FlSelector(ids: LabId.values)',
            subtitle: '把所有 ID 都列进来 —— 每一次通知都跳，等价于已移除的 wc',
            mode: _ProbeMode.watch,
          ),
          const _Probe(
            id: 'sel-a',
            title: 'FlSelector(ids: [a])',
            subtitle: '只认 A',
            mode: _ProbeMode.select,
            ids: <LabId>[LabId.a],
          ),
          const _Probe(
            id: 'sel-b',
            title: 'FlSelector(ids: [b])',
            subtitle: '只认 B',
            mode: _ProbeMode.select,
            ids: <LabId>[LabId.b],
          ),
          const _Probe(
            id: 'sel-ab',
            title: 'FlSelector(ids: [a, b])',
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
          const SizedBox(height: 20),
          const _SectionTitle('控制器的生死'),
          const SizedBox(height: 8),
          const _OwnershipDemo(),
          const SizedBox(height: 12),
          _NestedCreateDemo(outer: controller),
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
    // rc 不建立依赖，没有要圈的重建边界，直接读。
    if (widget.mode == _ProbeMode.read) {
      _builds++;
      return _card(context, context.rc<LabController>());
    }
    // 其余两档都经 FlSelector——它是按 ID 订阅的唯一公开入口。`watch` 这一档
    // 原先用的 `context.wc` 已移除，把所有 ID 列进来与它完全等价。
    return FlSelector<LabId, LabController>(
      ids: widget.mode == _ProbeMode.watch ? LabId.values : widget.ids,
      builder: (BuildContext context, LabController c, _) {
        _builds++;
        return _card(context, c);
      },
    );
  }

  Widget _card(BuildContext context, LabController c) {
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
          title: 'FlSelector(ids: [${_watched.name}])',
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
// 控制器的生死：所有权在 FlInheritedElement 上
// ---------------------------------------------------------------------------

/// 只为这一块存在的控制器：把自己被释放这件事报给外面。
class OwnedController extends BasePageController<LabId> {
  OwnedController({required this.onDisposed});

  /// 由 [_OwnershipDemo] 传进来，用于把「我被 dispose 了」显示到屏幕上。
  final VoidCallback onDisposed;

  @override
  List<LabId> get shouldNotifyIds => const <LabId>[LabId.a];

  @override
  void dispose() {
    onDisposed();
    super.dispose();
  }
}

/// 计数记在这个对象上，而不是 `State` 的字段上。
///
/// 卡片要读的是 `create` 跑完之后的数字，而 `create` 属于**子树**的构建，晚于
/// `_OwnershipDemo.build`。记在外面的对象上，卡片（构建更晚）就能读到当帧的值。
class _OwnershipLog {
  /// `create` 被调用过几次。父级怎么重建都不该让它动。
  int creates = 0;

  /// 控制器被 `dispose` 过几次。
  int disposes = 0;

  /// `_OwnershipDemo` 自己被 build 过几次，用来和 [creates] 对照。
  int parentBuilds = 0;

  /// 最近一次创建出来的实例的 `hashCode`，换了实例这个数就会变。
  int? lastHash;
}

/// 把「控制器归 Element」摆到屏幕上：父级反复重建不重造，子树一卸载就释放。
class _OwnershipDemo extends StatefulWidget {
  const _OwnershipDemo();

  @override
  State<_OwnershipDemo> createState() => _OwnershipDemoState();
}

class _OwnershipDemoState extends State<_OwnershipDemo> {
  final _OwnershipLog _log = _OwnershipLog();

  /// 那一小块子树还挂着吗。
  bool _attached = true;

  void _handleDisposed() {
    _log.disposes++;
    // dispose 发生在 Element 树被锁住的卸载阶段，此刻 setState 会抛
    // 「called when widget tree was locked」。所以只记数，把刷新推到下一帧。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) setState(() {});
    });
  }

  @override
  Widget build(BuildContext context) {
    _log.parentBuilds++;
    final ThemeData theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          '控制器归 FlInheritedElement，不归任何 Widget：父级怎么重建都不重造，'
          '子树一卸载就 dispose。',
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurface.withValues(alpha: 0.6),
            height: 1.5,
          ),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: <Widget>[
            _Btn('父级 setState', () => setState(() {})),
            _Btn(
              _attached ? '卸载这一小块' : '重新挂载',
              () => setState(() => _attached = !_attached),
            ),
          ],
        ),
        const SizedBox(height: 4),
        if (_attached)
          FlProviderBuilder<OwnedController>(
            create: (_) {
              _log.creates++;
              final OwnedController controller = OwnedController(
                onDisposed: _handleDisposed,
              );
              _log.lastHash = controller.hashCode;
              return controller;
            },
            // 卡片放在 builder 里：它构建于 create 之后，读到的是当帧的计数。
            builder: (_, _) => _OwnershipCard(log: _log, alive: true),
          )
        else
          _OwnershipCard(log: _log, alive: false),
      ],
    );
  }
}

class _OwnershipCard extends StatelessWidget {
  const _OwnershipCard({required this.log, required this.alive});

  final _OwnershipLog log;

  /// 子树还挂着（控制器还活着）。
  final bool alive;

  @override
  Widget build(BuildContext context) {
    final int? hash = log.lastHash;
    return Card(
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 4),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: Theme.of(context).dividerColor.withValues(alpha: 0.3),
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            _StatRow(
              label: 'create 调用次数',
              value: '${log.creates}',
              valueKey: 'own:creates',
              hint: '父级已重建 ${log.parentBuilds} 次',
              hintKey: 'own:parent',
            ),
            _StatRow(
              label: '控制器实例',
              value: hash == null ? '—' : '#${hash.toRadixString(16)}',
              valueKey: 'own:identity',
              hint: alive ? '还活着' : '已 dispose',
            ),
            _StatRow(
              label: 'dispose 已触发',
              value: '${log.disposes}',
              valueKey: 'own:disposes',
              hint: '子树卸载时由 Element 释放',
            ),
          ],
        ),
      ),
    );
  }
}

/// 一行「名字 —— 值 —— 备注」。值和备注都带 key，好让 widget test 直接读。
class _StatRow extends StatelessWidget {
  const _StatRow({
    required this.label,
    required this.value,
    required this.valueKey,
    this.hint,
    this.hintKey,
  });

  final String label;
  final String value;
  final String valueKey;
  final String? hint;
  final String? hintKey;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final String? hint = this.hint;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: <Widget>[
          Expanded(
            child: Text(
              label,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurface.withValues(alpha: 0.7),
              ),
            ),
          ),
          Text(
            value,
            key: ValueKey<String>(valueKey),
            style: theme.textTheme.titleSmall?.copyWith(
              fontFamily: 'monospace',
              fontWeight: FontWeight.w700,
              color: theme.colorScheme.primary,
            ),
          ),
          if (hint != null) ...<Widget>[
            const SizedBox(width: 8),
            Text(
              hint,
              key: hintKey == null ? null : ValueKey<String>(hintKey!),
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurface.withValues(alpha: 0.45),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// 同类型嵌套：内层 `create` 里读同类型控制器，拿到的是**外层**那一个。
///
/// 控制器归 Element，而 `InheritedElement` 自己那份 `_inheritedElements` 里含它
/// 自己，所以不加处理的话这一行会命中正在创建中的自己。`FlInheritedElement`
/// 覆写了 `getElementForInheritedWidgetOfExactType` 把本层跳开——`provider` 在
/// `_InheritedProviderScopeElement` 上做的是同一件事。
class _NestedCreateDemo extends StatefulWidget {
  const _NestedCreateDemo({required this.outer});

  /// 页面自己那一层的控制器（`FlBasePageState` 铺的那个）。
  final LabController outer;

  @override
  State<_NestedCreateDemo> createState() => _NestedCreateDemoState();
}

class _NestedCreateDemoState extends State<_NestedCreateDemo> {
  /// 内层 `create` 里读到的那个实例。
  LabController? _seenInCreate;

  @override
  Widget build(BuildContext context) {
    return FlProviderBuilder<LabController>(
      create: (BuildContext context) {
        _seenInCreate = context.rc<LabController>();
        return LabController();
      },
      builder: (_, LabController inner) {
        final ThemeData theme = Theme.of(context);
        final bool seesOuter = identical(_seenInCreate, widget.outer);
        final bool innerIsNew = !identical(inner, widget.outer);
        return Card(
          elevation: 0,
          margin: const EdgeInsets.symmetric(vertical: 4),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: BorderSide(color: theme.dividerColor.withValues(alpha: 0.3)),
          ),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  '同类型嵌套：再铺一层 FlProviderBuilder<LabController>',
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                    fontFamily: 'monospace',
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  seesOuter
                      ? '内层 create 里的 rc<LabController>() → 拿到外层实例 ✓'
                      : '内层 create 里的 rc<LabController>() → 不是外层实例 ✗',
                  key: const ValueKey<String>('nested:verdict'),
                  style: theme.textTheme.bodySmall?.copyWith(
                    fontFamily: 'monospace',
                    color: seesOuter
                        ? theme.colorScheme.primary
                        : theme.colorScheme.error,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  innerIsNew ? '内层自己 new 的那个与外层不是同一个 ✓' : '内层拿到的竟是外层那一个 ✗',
                  key: const ValueKey<String>('nested:distinct'),
                  style: theme.textTheme.bodySmall?.copyWith(
                    fontFamily: 'monospace',
                    color: innerIsNew
                        ? theme.colorScheme.onSurface.withValues(alpha: 0.6)
                        : theme.colorScheme.error,
                  ),
                ),
              ],
            ),
          ),
        );
      },
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
