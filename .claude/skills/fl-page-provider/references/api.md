# fl_page_provider 0.0.1 签名表

`package:fl_page_provider/fl_page_provider.dart` 导出的**全部**内容就是下面这 9 个名字。
再加上被整体再导出的 `fl_page_lifecycle`（`FlRouteObserver`、`FlPageIndexScope`、
`FlLifecycleState`、`FlGlobalEventBus`…），那部分的签名查 fl-page-lifecycle skill 的
`references/api.md`，不要在这里找。

`FlPageProvider` / `FlInheritedWidget` / `FlNotifyMixin` / `FlEventBusMixin` / `FlIdVersions`
是 `@internal` 的包内实现，外面拿不到，也不该出现在业务代码里。

## FlBaseController\<T extends Enum>

```dart
abstract class FlBaseController<T extends Enum> extends ChangeNotifier
    with FlPageControllerMixin, FlNotifyMixin<T>, FlEventBusMixin

List<T> get shouldNotifyIds;                    // 必须实现：要追踪的全部 ID
```

通知（都是 `@protected`，只能在控制器内部调）：

```dart
void notifySingleListener(T id);                // 推进一个 ID 的版本号并通知
void notifyMultiListeners(List<T> ids);         // 多个；空列表直接返回
void onNotified(List<T> events);                // 钩子：通知发出前调用，默认空实现
```

`notifyListeners()` 从 `ChangeNotifier` 继承而来，**子类里不要调**：它不推进任何 ID 的版本号，
而依赖方全是按 ID 订阅的，逐 ID 比对一律得出「没变」——这次通知一个依赖方都惊动不了，页面
静默停在旧数据上。debug 期有门禁（不经两个通知入口进来的调用直接断言），release 里被树摇掉。
要「任何变更都刷新某一块」就专门留一个全量 ID，每次通知都把它一起列进 `notifyMultiListeners`。

事件总线（同一条全局总线，和页面侧的 `FlStateEventBusMixin` 互通）：

```dart
void observeEvent<E>(void Function(E event) onData);  // 订阅，dispose 时自动取消
void dispatchEvent<E>(E event);                       // 发布，自己也收得到
Stream<E> onEvent<E>();                               // 裸流，**订阅要自己 cancel**
```

生命周期回调来自 `FlPageControllerMixin`，由页面侧转发进来（`FlBasePage` /
`FlBasePageState` / `FlProviderBuilder` 已接好），直接 override 即可：

```dart
onPageInit  onPageContextReady(BuildContext?)  onPagePostFrame  onPageReassemble
onPageStart onPageStop  onPageResume onPagePause
onPageEnterAnimationStart/End  onPageLeaveAnimationStart/End  onPageDispose
onAppForeground onAppBackground onAppInactive onAppDetached onAppHidden
onPageIndexChanged(int from, int to)

FlLifecycleState get lifecycleState;  bool get isPageResume / isPagePause / isForeground;
String? get routeName;  Object? get arguments;
```

`onPageInit` 与 `onPageReassemble` 是 `@mustCallSuper`：ID 登记和热重载后的重新登记都在
super 里。`onPageDispose` 时 `routeName` 已是 `null`，要读路由信息在 `onPageStop` 读。

## 页面承载

```dart
abstract class FlBasePage<T extends FlBaseController> extends StatelessWidget
    with FlPageMixin<T>

abstract class FlBasePageState<S extends StatefulWidget, T extends FlBaseController>
    extends State<S> with FlPageMixin<T>, AutomaticKeepAliveClientMixin

mixin FlPageMixin<T extends FlBaseController> {
  T createController(BuildContext context);                          // 必须实现
  Widget buildWithController(BuildContext context, T controller);    // 必须实现
  bool get observeAppLifecycle => false;
  bool get observePageIndex => false;
  @protected Widget getProviderWidget(BuildContext context);         // 管道，自定义承载时才调
}

class FlProviderBuilder<T extends FlBaseController> extends StatelessWidget {
  const FlProviderBuilder({
    required T Function(BuildContext) create,
    required Widget Function(BuildContext, T) builder,
    Key? key,
    bool observePageIndex = false,
    bool observeAppLifecycle = false,
  });
}
```

`FlBasePageState` 额外有 `bool get wantKeepAlive`（默认 `false`）。覆写它的 `build` 必须调
`super.build(context)`，否则保活失效——正常写法是只实现 `buildWithController`。

## 读取与选择性重建

公开入口只有两个：`context.rc`（取实例调方法）与 `FlSelector` / `FlSelectorView`（按 ID 订阅）。

```dart
extension FlControllerContextExtension on BuildContext {
  T rc<T extends FlBaseController>();                    // 不建依赖，永不重建调用方
}

class FlSelector<E extends Enum, T extends FlBaseController<E>> extends StatelessWidget {
  const FlSelector({required List<E> ids, required FlSelectorBuilder<E, T> builder,
                    Key? key, Widget? child});
}

typedef FlSelectorBuilder<E, T> = Widget Function(BuildContext, T controller, Widget? child);

abstract class FlSelectorView<E extends Enum, T extends FlBaseController<E>>
    extends StatelessWidget {
  List<E> get observeIds;                                            // 必须实现
  Widget buildWidget(BuildContext, T controller, Widget? child);     // 必须实现
  Widget? get staticChild => null;                                   // 不参与重建的子树
}
```

**已经移除 / 不再公开的写法**（写了就是编译错误或越过 `@internal`）：

| 曾经 | 现在 |
|---|---|
| `context.wc<C>()`（全量依赖） | 已删除。要「任何变更都刷新某一块」就留一个全量 ID，每次通知都带上它，调用方 `FlSelector(ids: const [E.all])` |
| `context.selectIds<E, C>([...])` | 转为 `@internal`，改用 `FlSelector` / `FlSelectorView` |
| `FlPageProvider.of(context, listen:, aspect:)` | 参数收成 `ids:`；且 `FlPageProvider` 本就是包内实现，业务代码不该出现 |

删 `wc` 的理由：全量依赖**跨帧不可逆**——Flutter 只在 `Element.deactivate()` 时解依赖登记，
而全量依赖一旦登记，后续的 ID 登记不能再把它收窄，于是一个 Widget 只要有过一次 `wc`，
之后哪怕每帧都按 ID 订阅也回不到 ID 粒度，会一直跟着每一次通知重建直到卸载，不报错也没日志。

名字是 `rc` 而不是 `read`：`read` / `watch` 被 pub 上的 `provider` 包占着，同时导入会让每个
调用点报 `ambiguous_extension_member_access`，加导入前缀也不管用。错开名字之后两个包可以
原样共存，一个 `hide` 都不用写。

`FlSelector` / `FlSelectorView` 的上界是 `FlBaseController<E>`，把 ID 的枚举类型和控制器绑在
一起。`child` 只构建一次、每次重建原样交还，Flutter 见到同一个 Widget 实例会跳过那棵子树——
前提是它每次取值都是同一个实例（写 `const` 或缓存到字段，每次 new 等于没优化）。
