---
name: fl-page-provider
description: >-
  用 fl_page_provider 写 Flutter 页面：控制器与页面同生共死、按 ID 粒度局部重建、
  页面生命周期直接落在控制器上。凡是「新建页面/模块」「把页面逻辑从 State 挪进 Controller」
  「点一下只刷新某一块而不是整页」「列表/表单/异步三态的局部刷新」「跨页面发事件通知刷新」
  的需求都用本 skill——只要 pubspec 里有 fl_page_provider 就该用它，即使用户没提库名，
  也别退回 setState 或手写 ChangeNotifierProvider。新建页面先跑 scripts/new_page.py，别手写。
  本包是 2026 年 9 月的新包，不在你的训练数据里：context.read/watch/select、
  ChangeNotifierProvider、Consumer、notifyId 在本库里全不存在，凭印象写必错。
  关键词：FlBaseController、FlBasePage、FlBasePageState、FlProviderBuilder、FlSelector、
  FlSelectorView、context.rc、shouldNotifyIds、notifySingleListener、
  notifyMultiListeners、observeEvent、dispatchEvent、页面控制器、局部刷新、选择性重建、
  ID 粒度、事件总线、跨页面通信、PageView/TabBarView/IndexedStack 子页的控制器、页面模板。
  不适用于本库自身的审计（analyze-flutter）与发版（flutter_pub_publish）。
---

# fl_page_provider 接入指导

**对应 0.0.1。** `create` 出来的控制器由子树托管、销毁时自动 `dispose`；控制器按 ID 发通知，
只有订阅了那个 ID 的 Widget 重建；生命周期由承载方转发进控制器，逻辑不必留在 `State` 里。

## 1. 新建页面：跑脚本

```bash
python3 scripts/new_page.py user_profile --ids avatar,name,list --dir lib/pages
python3 scripts/new_page.py feed msg mine --host home     # 多页 + PageView 宿主，一次生成
```

一次生成 ID 枚举 + Controller + Page（`--split` 拆三个文件），`super` 调用、ID 登记、订阅位置
都已就位——那几处漏了不报错但静默失效。脚本顺带查 `pubspec.yaml`，没装依赖会提示，不必另外
grep；真没装就停下来问用户，别自作主张加依赖。开关：

`--ids a,b,c`（多块独立刷新）· `--stateful` · `--keep-alive`（保住滚动位置/输入）·
`--page-index`（容器子页）· `--host NAME`（连 PageView 宿主一起生成，已含 `--page-index`）·
`--app-lifecycle` · `--bus`（全局事件）· `--split` · `--stdout` · `--force`

生成后按业务改字段与 UI。只改现有页面的不必跑脚本。本包整体再导出了 `fl_page_lifecycle`
（`FlRouteObserver`、`FlPageIndexScope` 直接就有），**不要**再加那个依赖。

## 2. 承载：三选一

`FlBasePage<C>` 默认用它；需要 `State`（`TickerProvider`、`GlobalKey`、保活、页面自己还有局部
UI 状态）用 `FlBasePageState<W, C>`；只给某个子树挂控制器用 `FlProviderBuilder<C>`。
都实现 `createController`（**只调一次**，父级重建不会再造）+ `buildWithController`。

**`create` 交出的是所有权**：返回的实例会在子树销毁时被 `dispose`，共享单例意味着第一个关闭的
页面把它 dispose 了、其余子树静默冻结。要跨页共享就把 provider 提到共同祖先
（如 `MyApp extends FlBasePage<RootController>`），子页照常 `context.rc<RootController>()`。

## 3. 刷新哪一块：ID 粒度

控制器侧：用到的 ID 全登记在 `shouldNotifyIds`（通常 `XxxEvent.values`），改完数据调
`notifySingleListener(id)` / `notifyMultiListeners([...])`。**未登记的 ID 版本号恒为 0，比对永远
得出「没变」，依赖方一次都不会重建**——release 下静默失败。

**子类里不要调 `notifyListeners()`。** 它不推进任何 ID 的版本号，而依赖方全是按 ID 订阅的，
于是这次通知一个都惊动不了，页面静默停在旧数据上。debug 期有门禁直接断言拦住。

Widget 侧**只有两个入口**：

| 写法 | 建立依赖 | 重建时机 | 用在 |
|---|---|---|---|
| `context.rc<C>()` | 否 | 从不 | 取实例调方法：`onPressed: () => context.rc<C>().submit()` |
| `FlSelector<E, C>(ids:)` / `FlSelectorView<E, C>` | 是 | 仅所列 ID 被通知时 | 显示数据的那一小块 |

**没有 `context.wc`，也没有公开的 `context.selectIds`**——前者（全量依赖）已删除，后者转为包内
实现。原因是同一件事：依赖登记在**调用方那个 Element** 上，写在页面 `build` 里就是整页跟着一个
ID 抖；而 Flutter 只在 `Element.deactivate()` 时解依赖、重建时从不清理，放进条件分支就会留下
永久白重建的尾巴，全量依赖更是一旦登记就跨帧不可逆（那个 Widget 再也回不到 ID 粒度，不报错也
没日志）。包一层 Widget 两个问题一起没有：重建边界就是那层 Widget，条件不成立时它整个卸载、
依赖随之解除。所以 `FlSelector` 放进 `if` 分支是安全写法，不是坑。

**要「任何变更都刷新某一块」**：在枚举里专门留一个全量 ID，控制器每次通知都把它一起列进
`notifyMultiListeners(const [E.all, E.name])`，调用方照常 `FlSelector(ids: const [E.all])`。
这样「谁会因为什么而重建」始终写在调用点上。

`FlSelector` 的常见更新场景：一块 UI 跟一个字段就 `ids: const [E.count]`，跟多个就都列上（任一
变就重建这一块）；一次改多个字段在控制器里 `notifyMultiListeners([E.a, E.b])` 发**一次**；块里
大片不变的 UI 摘到 `child` 参数（`builder` 里原样用回去，那棵子树不重建）；要独立成类就继承
`FlSelectorView<E, C>`（`observeIds` + `buildWidget` + `staticChild`）；异步 loading/error/data
三态共用一个 ID、在 `builder` 里分支。列表、分页、表单、嵌套 selector、build 阶段发通知 →
`references/selector.md`。

硬规矩：`ids` **不能是空列表**（那是「一个 ID 都不关心」，永远不重建；要全量刷新用上面那个全量
ID 的写法）；重建范围是 `builder` 返回的整棵子树，块要拆小；名字是 `rc` 不是 `read`
（`read` / `watch` 被 `provider` 包占着，错开后两个包可以共存）。

## 4. 跨页面通信：全局事件总线

控制器内 `dispatchEvent(const LoginEvent(true))` 发、`observeEvent<LoginEvent>(_onLogin)` 收，
发送方自己也收得到，取消由基类在 `dispose` 里做。两条硬规矩：**只在 `onPageInit` 里订阅一次**
（它不解除已有订阅，放在会重复执行的地方订阅数随重建线性增长，症状是埋点重复上报或接口重复
请求）；**传方法引用，别传闭包字面量**（重复订阅的拦截靠回调相等识别，闭包每次都是新对象）。

## 5. 生命周期：直接写在控制器上

18 个回调由承载方转发进来，override 即可。覆写 `onPageInit` / `onPageReassemble` **必须调 super**
（ID 登记和热重载后的重新登记在里面）。

最关键的判断——**弹窗（dialog / bottomSheet）盖住页面时，这件事该不该继续？**

- 该继续 → `onPageStart` / `onPageStop`：轮询、WebSocket、曝光埋点与停留时长、倒计时。
- 该停 → `onPageResume` / `onPagePause`：视频音频、动画、相机、定位、传感器。

（dialog 只发 `pause`，不发 `stop`。轮询用错这对，症状是「一弹筛选面板刷新就断了」。）

**根 `Navigator` 必须注册 `FlRouteObserver()`**（`MaterialApp.navigatorObservers`）。漏了不报错，
页面照常渲染，生命周期回调一个都不来。要 App 前后台事件还要 `observeAppLifecycle => true`。

## 6. PageView / TabBarView / IndexedStack / 嵌套 Navigator

本库这一侧三件事：子页 `observePageIndex => true`；要保住滚动位置/输入就用 `FlBasePageState` +
`wantKeepAlive => true`（`IndexedStack` 本身保活，`ValueNotifier<int>` 驱动时不用开）；切页回调
落在控制器的 `onPageIndexChanged(from, to)`。宿主侧用 `--host` 生成，别手写
（`FlPageIndexScope.wrapChildren` 的 `controller` / `children` **都是命名参数**）。
**只开子页开关、宿主没包 Scope 是静默无效**：首帧全部 start，切页一个事件都不来。

`wrapItemBuilder`、嵌套容器每层都要包、滚动容器停稳才提交事件、嵌套 `Navigator` 各 new 一个
`FlRouteObserverProxy()`（不能复用 `FlRouteObserver()` 单例）、`popUntil` / `pushAndRemoveUntil`、
go_router / auto_route 的注册位置、转场动画时序 —— 属于 fl_page_lifecycle，
**直接读 fl-page-lifecycle skill**，别凭印象写。

## 交付前自检

**行为不对先跑脚本，不要先翻文档**——它专查「编译得过、`analyze` 也不报、但 UI 静默不刷新」的
十几种接错，`❌` 给出原因和改法照着改即可，`⚠️` 取决于扫描范围、再确认一眼。

```bash
python3 scripts/verify.py lib/ --analyze    # 顺带跑掉 flutter analyze，一次调用两份结果
```

脚本查不到的只剩三件事，交付前自己过一遍：起停按「弹窗期间该不该继续」选对了那一对；
容器子页的 Scope 包在了宿主侧（脚本只在扫描范围内能看见时才判定）；以及跟用户交代清楚改了
哪些文件、每个回调里放了什么、observer 注册在哪。

## 按需去读哪个文件

| 要做的事 | 读 |
|---|---|
| FlSelector 更多写法、列表/表单/分页的刷新粒度 | `references/selector.md` |
| 查签名、某个类有哪些成员 | `references/api.md` |
| 改完行为不对，按症状倒查 | `references/pitfalls.md` |
| 容器包裹、observer 注册、生命周期时序 | fl-page-lifecycle skill |

公开 API 只有 `api.md` 里那 9 个名字，一律以 `Fl` 开头。拿不准就查，别拼。
