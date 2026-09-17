import 'package:flutter/material.dart';
import 'package:fl_page_provider/fl_page_provider.dart';

class PopPage extends FlBasePage<PopPageController> {
  const PopPage({super.key});

  @override
  PopPageController createController(BuildContext context) {
    return PopPageController();
  }

  @override
  Widget buildWithController(
    BuildContext context,
    PopPageController controller,
  ) {
    return Scaffold(
      appBar: AppBar(title: const Text('PopPage')),
      body: InkWell(
        onTap: () {
          Navigator.of(
            context,
          ).pushNamed("/popUntilPage", arguments: {'name': '这是你传递的参数'});
        },
        child: const Center(child: Text('PopPage')),
      ),
    );
  }
}

enum PageOneEvent { none }

class PopPageController extends FlBaseController<PageOneEvent> {
  @override
  List<PageOneEvent> get shouldNotifyIds => [];

  @override
  void onPageInit() {
    super.onPageInit();
    debugPrint("$runtimeType ---onPageInit");
  }

  @override
  void onPageContextReady(BuildContext? context) {
    super.onPageContextReady(context);
    debugPrint("$runtimeType ---onPageContextReady");
  }

  @override
  void onPagePostFrame() {
    super.onPagePostFrame();
    debugPrint("$runtimeType ---onPagePostFrame");
  }

  @override
  void onPageStart() {
    super.onPageStart();
    debugPrint("$runtimeType ---onPageStart");
  }

  @override
  void onPageResume() {
    super.onPageResume();
    debugPrint("$runtimeType ---onPageResume");
  }

  @override
  void onPageEnterAnimationEnd() {
    super.onPageEnterAnimationEnd();
    debugPrint("$runtimeType ---onPageEnterAnimationEnd");
  }

  @override
  void onPagePause() {
    super.onPagePause();
    debugPrint("$runtimeType ---onPagePause");
  }

  @override
  void onPageStop() {
    super.onPageStop();
    debugPrint("$runtimeType ---onPageStop");
  }

  @override
  void onPageLeaveAnimationEnd() {
    super.onPageLeaveAnimationEnd();
    debugPrint("$runtimeType ---onPageLeaveAnimationEnd");
  }

  @override
  void onPageDispose() {
    super.onPageDispose();
    debugPrint("$runtimeType ---onPageDispose");
  }

  @override
  void onAppResume() {
    super.onAppResume();
    debugPrint("$runtimeType ---onAppResume");
  }

  @override
  void onAppPause() {
    super.onAppPause();
    debugPrint("$runtimeType ---onAppPause");
  }
}
