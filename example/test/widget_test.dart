import 'package:example/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 冒烟测试：真实 App 走一遍「注入 Controller → 路由跳转 → 按 ID 局部刷新」。
void main() {
  testWidgets('首页渲染，跳转 UpdatePage 后 FlSelector 跟着刷新', (tester) async {
    await tester.pumpWidget(const MyApp());
    await tester.pumpAndSettle();

    expect(find.text('Flutter 状态管理'), findsOneWidget);

    // 该卡片在默认 800x600 视口外，先滚到可见。
    await tester.dragUntilVisible(
      find.text('选择性刷新'),
      find.byType(ListView),
      const Offset(0, -100),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('选择性刷新'));
    await tester.pumpAndSettle();

    expect(find.text('UpdatePage'), findsOneWidget);
    expect(find.text('当前的值是：0'), findsOneWidget);

    await tester.tap(find.byIcon(Icons.add));
    await tester.pumpAndSettle();

    expect(find.text('当前的值是：1'), findsOneWidget);
  });

  testWidgets('PageView 子页：切页后另一页的 RootController 视图能读到更新', (tester) async {
    await tester.pumpWidget(const MyApp());
    await tester.pumpAndSettle();

    await tester.tap(find.text('PageView'));
    await tester.pumpAndSettle();

    // PageOne 里点一下，增加 RootController 的 count。
    await tester.tap(find.text('更新RootController的count'));
    await tester.pumpAndSettle();

    // 滑到 PageFour，它用 FlSelectorView 订阅 RootController。
    final PageView pageView = tester.widget<PageView>(find.byType(PageView));
    pageView.controller!.jumpToPage(3);
    await tester.pumpAndSettle();

    expect(find.text('RootController 中Count的值是：1'), findsOneWidget);
  });
}
