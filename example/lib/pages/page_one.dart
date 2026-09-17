import 'package:example/pages/login_event.dart';
import 'package:example/root_controller.dart';
import 'package:flutter/material.dart';
import 'package:fl_page_provider/fl_page_provider.dart';

import '../base_page_controller.dart';

class PageOne extends StatefulWidget {
  const PageOne({super.key});

  @override
  State<PageOne> createState() => _PageOneState();
}

class _PageOneState extends FlBasePageState<PageOne, PageOneController> {
  @override
  PageOneController createController(BuildContext context) {
    return PageOneController();
  }

  @override
  bool get observePageIndex => true;

  @override
  bool get wantKeepAlive => true;

  @override
  Widget buildWithController(
    BuildContext context,
    PageOneController controller,
  ) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            InkWell(
              onTap: controller.sendLoginEvent,
              child: const Text('登录事件'),
            ),
            const SizedBox(height: 60),
            InkWell(
              onTap: controller.sendLogoutEvent,
              child: const Text('退出登录事件'),
            ),
            const SizedBox(height: 60),
            InkWell(
              onTap: context.rc<RootController>().increase,
              child: const Text('更新RootController的count'),
            ),
          ],
        ),
      ),
    );
  }
}

class PageOneController extends BasePageController {
  void sendLoginEvent() {
    dispatchEvent(const LoginEvent(true));
  }

  void sendLogoutEvent() {
    dispatchEvent(const LogoutEvent());
  }
}
