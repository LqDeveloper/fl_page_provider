import 'package:flutter/material.dart';

class HomePage extends StatelessWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Flutter 状态管理', style: TextStyle(color: Colors.blue)),
        centerTitle: true,
        elevation: 0,
        backgroundColor: theme.colorScheme.surface,
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
        children: [
          _SectionHeader(
            icon: Icons.live_tv_outlined,
            title: '生命周期场景',
            theme: theme,
          ),
          const SizedBox(height: 8),
          _NavCard(
            icon: Icons.tab,
            title: 'TabBar',
            subtitle: 'TabBarView 页面切换，观察生命周期流转',
            onTap: () => _push(context, '/tabPage'),
          ),
          _NavCard(
            icon: Icons.swap_horiz,
            title: 'PageView',
            subtitle: '滑动翻页 + BottomNavigation，页面缓存与恢复',
            onTap: () => _push(context, '/bottomNav'),
          ),
          const SizedBox(height: 20),
          _SectionHeader(
            icon: Icons.navigation_outlined,
            title: '导航场景',
            theme: theme,
          ),
          const SizedBox(height: 8),
          _NavCard(
            icon: Icons.arrow_forward,
            title: 'Push / Pop',
            subtitle: '入栈出栈，完整页面生命周期',
            onTap: () => _push(context, '/popPage'),
          ),
          _NavCard(
            icon: Icons.arrow_back_ios,
            title: 'PopUntil',
            subtitle: '批量出栈回到根页面',
            onTap: () => _push(context, '/popUntilPage'),
          ),
          _NavCard(
            icon: Icons.swap_horiz_rounded,
            title: 'Replace',
            subtitle: '页面替换，触发 Dispose',
            onTap: () => _push(context, '/replace'),
          ),
          _NavCard(
            icon: Icons.pages,
            title: 'Dialog',
            subtitle: '弹窗覆盖，触发 onPagePause',
            onTap: () => _push(context, '/dialog'),
          ),
          const SizedBox(height: 20),
          _SectionHeader(
            icon: Icons.tune_outlined,
            title: 'UI 刷新',
            theme: theme,
          ),
          const SizedBox(height: 8),
          _NavCard(
            icon: Icons.refresh,
            title: '选择性刷新',
            subtitle: 'FlSelector 精准控制重建范围',
            onTap: () => _push(context, '/updatePage'),
          ),
          _NavCard(
            icon: Icons.speed_outlined,
            title: '更新引擎压测台',
            subtitle: '真实帧时间：selectIds / watch / 基线三种模式对比',
            onTap: () => _push(context, '/perfBench'),
          ),
          _NavCard(
            icon: Icons.science_outlined,
            title: '更新引擎实验台',
            subtitle: 'read / watch / selectIds 逐个计重建次数，看清谁被刷新了',
            onTap: () => _push(context, '/providerLab'),
          ),
        ],
      ),
    );
  }

  void _push(BuildContext context, String route) {
    Navigator.of(context).pushNamed(route);
  }
}

class _SectionHeader extends StatelessWidget {
  final IconData icon;
  final String title;
  final ThemeData theme;

  const _SectionHeader({
    required this.icon,
    required this.title,
    required this.theme,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 4, top: 8, bottom: 4),
      child: Row(
        children: [
          Icon(icon, size: 16, color: theme.colorScheme.primary),
          const SizedBox(width: 6),
          Text(
            title,
            style: theme.textTheme.titleSmall?.copyWith(
              color: theme.colorScheme.primary,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}

class _NavCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  const _NavCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 4),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: theme.dividerColor.withValues(alpha: 0.3)),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: theme.colorScheme.primary.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, color: theme.colorScheme.primary),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: theme.textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurface.withValues(
                          alpha: 0.5,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              Icon(
                Icons.chevron_right,
                size: 20,
                color: theme.colorScheme.onSurface.withValues(alpha: 0.25),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
