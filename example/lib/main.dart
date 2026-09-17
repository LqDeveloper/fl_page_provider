import 'package:example/page_view/bottom_nav_page.dart';
import 'package:example/page_view/tab_page.dart';
import 'package:example/pages/dialog_page.dart';
import 'package:example/pages/pop_page.dart';
import 'package:example/pages/pop_until_page.dart';
import 'package:example/pages/perf_bench_page.dart';
import 'package:example/pages/provider_lab_page.dart';
import 'package:example/pages/replace_page.dart';
import 'package:example/pages/update_page.dart';
import 'package:flutter/material.dart';
import 'package:fl_page_provider/fl_page_provider.dart';

import 'home_page.dart';
import 'root_controller.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const MyApp());
}

class MyApp extends FlBasePage<RootController> {
  const MyApp({super.key});

  @override
  RootController createController(BuildContext context) {
    return RootController();
  }

  @override
  Widget buildWithController(BuildContext context, RootController controller) {
    return MaterialApp(
      title: 'Flutter Demo',
      theme: ThemeData(primarySwatch: Colors.blue, useMaterial3: false),
      routes: {
        "/tabPage": (_) => const TabPage(),
        "/bottomNav": (_) => const BottomNavPage(),
        "/popPage": (_) => const PopPage(),
        "/popUntilPage": (_) => const PopUntilPage(),
        "/replace": (_) => const ReplacePage(),
        "/dialog": (_) => const DialogPage(),
        "/updatePage": (_) => const UpdatePage(),
        "/providerLab": (_) => const ProviderLabPage(),
        "/perfBench": (_) => const PerfBenchPage(),
      },
      // 跑分采集时直接落到压测台，省掉人工导航。
      home: kBenchAutorun ? const PerfBenchPage() : const HomePage(),
      navigatorObservers: [FlRouteObserver()],
    );
  }
}
