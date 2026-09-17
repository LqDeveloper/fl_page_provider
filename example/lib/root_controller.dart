import 'package:flutter/material.dart';
import 'package:fl_page_provider/fl_page_provider.dart';

enum RootEvent { updateStatus }

class RootController extends FlBaseController<RootEvent> {
  @override
  List<RootEvent> get shouldNotifyIds => RootEvent.values;

  int _count = 0;

  int get count => _count;

  void increase() {
    _count++;
    notifySingleListener(RootEvent.updateStatus);
  }

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
  void onAppForeground() {
    super.onAppForeground();
    debugPrint("$runtimeType ---onAppForeground");
  }

  @override
  void onAppBackground() {
    super.onAppBackground();
    debugPrint("$runtimeType ---onAppBackground");
  }
}
