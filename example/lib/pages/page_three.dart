import 'package:flutter/material.dart';
import 'package:fl_page_provider/fl_page_provider.dart';

import '../base_page_controller.dart';
import 'login_event.dart';

class PageThree extends StatefulWidget {
  const PageThree({super.key});

  @override
  State<PageThree> createState() => _PageThreeState();
}

class _PageThreeState extends FlBasePageState<PageThree, PageThreeController> {
  @override
  PageThreeController createController(BuildContext context) {
    return PageThreeController();
  }

  @override
  bool get observePageIndex => true;

  @override
  bool get wantKeepAlive => true;

  @override
  Widget buildWithController(
    BuildContext context,
    PageThreeController controller,
  ) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const ObserveWidget(),
            const SizedBox(height: 20),
            InkWell(
              onTap: () {
                showDialog(
                  context: context,
                  builder: (cxt) {
                    return AlertDialog(
                      title: const Text('这是弹窗'),
                      actions: [
                        TextButton(
                          onPressed: () {
                            Navigator.of(
                              context,
                            ).popUntil((route) => route.settings.name == '/');
                          },
                          child: const Text('dismiss'),
                        ),
                      ],
                    );
                  },
                );
              },
              child: const Center(child: Text('DialogPage')),
            ),
          ],
        ),
      ),
    );
  }
}

enum PageThreeEvent { updateState }

class PageThreeController extends BasePageController<PageThreeEvent> {
  @override
  List<PageThreeEvent> get shouldNotifyIds => PageThreeEvent.values;

  bool _isLogin = false;

  bool get isLogin => _isLogin;

  void _setupIsLogin(bool value) {
    _isLogin = value;
    notifySingleListener(PageThreeEvent.updateState);
  }

  @override
  void onPageInit() {
    super.onPageInit();
    // 传方法引用而不是闭包字面量：重复订阅的门禁靠回调相等来识别，
    // 每次现写的闭包彼此不相等，认不出来。
    observeEvent<LoginEvent>(_onLogin);
    observeEvent<LogoutEvent>(_onLogout);
  }

  void _onLogin(LoginEvent event) => _setupIsLogin(true);

  void _onLogout(LogoutEvent event) => _setupIsLogin(false);
}

class ObserveWidget
    extends FlSelectorView<PageThreeEvent, PageThreeController> {
  const ObserveWidget({super.key});

  @override
  Widget buildWidget(
    BuildContext context,
    PageThreeController controller,
    Widget? child,
  ) {
    if (controller.isLogin) {
      return const Text('当前是登录状态');
    } else {
      return const Text('当前是未登录状态');
    }
  }

  @override
  List<PageThreeEvent> get observeIds => [PageThreeEvent.updateState];
}
