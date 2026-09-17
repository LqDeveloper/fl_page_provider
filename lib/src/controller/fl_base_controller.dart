import 'package:flutter/foundation.dart';

import 'package:fl_page_lifecycle/fl_page_lifecycle.dart';

import 'fl_event_bus_mixin.dart';
import 'fl_notify_mixin.dart';

/// 控制器基类，组合 [FlPageControllerMixin]（页面/App 生命周期）、
/// [FlNotifyMixin]（按 ID 选择性通知）与 [FlEventBusMixin]（全局事件总线）。
///
/// 子类只需实现 [shouldNotifyIds] 定义需要追踪的 ID 列表，
/// 页面初始化时自动注册，Hot Reload 时自动重新注册。
///
/// 生命周期事件不是自己订阅来的，而是由页面侧转发进来的——用
/// `FlBasePage` / `FlBasePageState` / `FlProviderBuilder` 承载本控制器即可，
/// 转发链路它们已经接好。
abstract class FlBaseController<T extends Enum> extends ChangeNotifier
    with FlPageControllerMixin, FlNotifyMixin<T>, FlEventBusMixin {
  @override
  @mustCallSuper
  void onPageInit() {
    super.onPageInit();
    registerIds(shouldNotifyIds);
  }

  @override
  @mustCallSuper
  void onPageReassemble() {
    super.onPageReassemble();
    logMessage(() => '[hot-reload] re-register ids: $shouldNotifyIds');
    registerIds(shouldNotifyIds);
  }

  /// 需要追踪通知的 ID 列表（被 [registerIds] 消费）
  List<T> get shouldNotifyIds;
}
