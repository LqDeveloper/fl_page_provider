import 'package:example/root_controller.dart';
import 'package:flutter/material.dart';
import 'package:fl_page_provider/fl_page_provider.dart';

import '../base_page_controller.dart';

class PageFour extends StatefulWidget {
  const PageFour({super.key});

  @override
  State<PageFour> createState() => _PageFourState();
}

class _PageFourState extends FlBasePageState<PageFour, PageFourController> {
  @override
  PageFourController createController(BuildContext context) {
    return PageFourController();
  }

  @override
  bool get observePageIndex => true;

  @override
  bool get wantKeepAlive => true;

  @override
  Widget buildWithController(
    BuildContext context,
    PageFourController controller,
  ) {
    return const Scaffold(body: Center(child: _CountWidget()));
  }
}

enum PageFourEvent { none }

class PageFourController extends BasePageController<PageFourEvent> {}

class _CountWidget extends FlSelectorView<RootEvent, RootController> {
  const _CountWidget();

  @override
  Widget buildWidget(
    BuildContext context,
    RootController controller,
    Widget? child,
  ) {
    return Text('RootController 中Count的值是：${controller.count}');
  }

  @override
  List<RootEvent> get observeIds => [RootEvent.updateStatus];
}
