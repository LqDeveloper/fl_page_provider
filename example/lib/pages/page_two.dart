import 'package:example/pages/login_event.dart';
import 'package:flutter/material.dart';
import 'package:fl_page_provider/fl_page_provider.dart';

import '../base_page_controller.dart';

class PageTwo extends StatefulWidget {
  const PageTwo({super.key});

  @override
  State<PageTwo> createState() => _PageTwoState();
}

class _PageTwoState extends FlBasePageState<PageTwo, PageTwoController> {
  @override
  PageTwoController createController(BuildContext context) {
    return PageTwoController();
  }

  @override
  bool get observePageIndex => true;

  @override
  bool get wantKeepAlive => true;

  @override
  Widget buildWithController(
    BuildContext context,
    PageTwoController controller,
  ) {
    return Scaffold(
      body: Center(
        child: InkWell(
          onTap: () {
            Navigator.of(context).pushNamed('/popPage');
          },
          child: const Text('PageTwo'),
        ),
      ),
    );
  }
}

class PageTwoController extends BasePageController {
  @override
  void onPageStart() {
    super.onPageStart();
    debugPrint("PageTwoController ---onPageStart");
  }

  @override
  void onPageInit() {
    super.onPageInit();
    // 传方法引用而不是闭包字面量：重复订阅的门禁靠回调相等来识别，
    // 每次现写的闭包彼此不相等，认不出来。
    observeEvent<LoginEvent>(_onLogin);
    observeEvent<LogoutEvent>(_onLogout);
  }

  void _onLogin(LoginEvent event) {
    debugPrint('接收到了登录事件----${event.isLogin} -- $lifecycleState');
  }

  void _onLogout(LogoutEvent event) {
    debugPrint('接收到了退出登录事件 -- $lifecycleState');
  }
}
