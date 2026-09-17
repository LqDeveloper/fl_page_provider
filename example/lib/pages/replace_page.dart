import 'package:flutter/material.dart';
import 'package:fl_page_provider/fl_page_provider.dart';

import '../base_page_controller.dart';

class ReplacePage extends FlBasePage<ReplacePageController> {
  const ReplacePage({super.key});

  @override
  ReplacePageController createController(BuildContext context) {
    return ReplacePageController();
  }

  @override
  Widget buildWithController(
    BuildContext context,
    ReplacePageController controller,
  ) {
    return Scaffold(
      appBar: AppBar(title: const Text('ReplacePage')),
      body: InkWell(
        onTap: () {
          Navigator.of(context).pushReplacementNamed("/popPage");
        },
        child: const Center(child: Text('ReplacePage')),
      ),
    );
  }
}

class ReplacePageController extends BasePageController {
  @override
  void onPageEnterAnimationEnd() {
    super.onPageEnterAnimationEnd();
    debugPrint("$runtimeType ---onPageEnterAnimationEnd");
  }

  @override
  void onPageLeaveAnimationEnd() {
    super.onPageLeaveAnimationEnd();
    debugPrint("$runtimeType ---onPageLeaveAnimationEnd");
  }
}
