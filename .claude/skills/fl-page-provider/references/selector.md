# FlSelector 更新场景手册

先记住机制：控制器为每个注册过的 ID 维护一个只增不减的版本号，通知时推进对应 ID 的版本号；
依赖方登记自己关心的那几个 ID 和上次见到的版本号，通知到来时**逐个比对**，只有真的变了的才收到
重建。所以「刷新哪一块」这件事完全由**你怎么切 ID、怎么切 Widget** 决定。

两条贯穿全文的原则：**重建范围是 `builder` 返回的整棵子树**，所以块要拆小；**不变的部分走 `child`**，
它只构建一次、每次原样交还，Flutter 见到同一个 Widget 实例会直接跳过那棵子树。

## 选哪种写法

| 写法 | 什么时候用 |
|---|---|
| `FlSelector<E, C>(ids:, builder:, child:)` | 默认。就地包住要刷新的那一小块 |
| `class X extends FlSelectorView<E, C>` | 这一块要独立成类、复用或想让 `const` 构造生效 |
| `context.selectIds<E, C>([...])` | 整个 Widget 就是那一块，不值得再套一层；**必须无条件调用** |

`FlSelectorView` 的 `staticChild` 等价于 `FlSelector` 的 `child`，但它是 getter——**必须每次返回同一个
实例**（写成 `const` 字面量，或缓存到字段）才有意义，每次 `new` 一个等于没优化。

## 基本形

```dart
FlSelector<HomeEvent, HomeController>(
  ids: const [HomeEvent.count],
  child: const Icon(Icons.star),              // 只建一次
  builder: (_, c, child) => Row(
    children: [if (child != null) child, Text('${c.count}')],
  ),
)
```

## 一次改多个字段

控制器里改完再发**一次**通知，别连发多次：

```dart
void applyCoupon(Coupon c) {
  _coupon = c;
  _total = _recalc();
  notifyMultiListeners([OrderEvent.coupon, OrderEvent.total]);   // ✓ 一次
}
```

连发两次 `notifySingleListener` 在同一帧里其实也会被合并成一次重建（通知走
`markNeedsBuild()`，帧内合并），但语义上它表达的是「发生了两件事」，读代码的人会以为有两次刷新。
一次改完一次通知，是给人看的。

## 列表

本库的粒度单位是**枚举 ID**，不是「第几行」——没有 `family` / 参数化 ID 这种东西。所以：

```dart
enum FeedEvent { list, itemState }   // list: 增删/整体替换   itemState: 行内高频字段
```

- **整体变化**（下拉刷新、加载更多、删除一项）→ 通知 `list`，让列表那一块整体重建。
  `ListView.builder` 本身只构建可见行，整体重建的代价通常可以接受。
- **行内字段变化**（选中态、数量、点赞数）→ 通知 `itemState`。注意：**所有订阅 `itemState`
  的行都会重建**，这是 ID 语义决定的。行的 `builder` 要写得轻，重的部分（图片、复杂布局）
  放 `child`。
- **确实需要「只重建那一行」**：本库不提供，把那一行的高频字段放进控制器持有的
  `ValueNotifier` / `ValueListenable`，行内用 `ValueListenableBuilder` 订阅——两套机制可以共存，
  ID 管页面级的块，ValueNotifier 管单行。别为了这个给每行造一个 ID。

分页列表：`list`（数据）与 `loadMoreState`（底部 loading / 没有更多 / 失败重试）分成两个 ID，
底部那一条单独一个 `FlSelector`，翻页时列表不用整体重建。

## 异步三态

一个 ID 管 loading / error / data，`builder` 里按控制器的状态字段分支：

```dart
FlSelector<DetailEvent, DetailController>(
  ids: const [DetailEvent.state],
  builder: (_, c, __) => switch (c.state) {
    LoadState.loading => const Center(child: CircularProgressIndicator()),
    LoadState.error => ErrorView(onRetry: c.load),
    LoadState.data => DetailBody(data: c.data!),
  },
)
```

三态共用一个 ID，是因为它们互斥、永远一起变。拆成三个 ID 只会让每次状态切换都要发三次通知。

## 表单

一个字段一个 ID 最直观（`E.name`、`E.phone`、`E.agree`），提交按钮的可用态再给一个 `E.canSubmit`，
在任一字段变化时由控制器重算并一起通知：

```dart
void setName(String v) {
  _name = v;
  notifyMultiListeners([FormEvent.name, FormEvent.canSubmit]);
}
```

输入框本身用 `TextEditingController`（放在控制器里，`dispose` 时释放），**不要**让输入框的
每次按键都走 ID 通知去重建它自己——那会打架（光标跳动）。ID 只负责联动别处：校验提示、
提交按钮、字数统计。

## 有时不显示的那一块

```dart
if (expanded) context.selectIds<E, C>(const [E.detail]);   // ✗ 依赖登记不会被清掉
```

Flutter 只在 `Element.deactivate()` 时解除依赖登记，重建时从不清理。上面这样写，一旦 `expanded`
从 `true` 变 `false`，`E.detail` 仍留在登记表里，之后每次通知 `E.detail` 都让这个 Widget 白重建，
直到它被卸载。两种正确写法：

```dart
if (expanded) const DetailSection(),                        // ✓ 拆成独立 Widget，卸载即解依赖

FlSelector<E, C>(                                           // ✓ 或者无条件订阅，在内部分支
  ids: const [E.detail, E.expanded],
  builder: (_, c, __) => c.expanded ? DetailBody(c.detail) : const SizedBox.shrink(),
)
```

第一种更省：不显示时连订阅都没有。

## 嵌套 selector

外层订阅粗粒度、内层订阅细粒度是允许的，通知细 ID 时只有内层重建：

```dart
FlSelector<E, C>(
  ids: const [E.section],                    // 整块换数据时重建
  builder: (_, c, __) => Column(
    children: [
      Header(c.title),
      FlSelector<E, C>(                      // 只有计数变时重建这一个
        ids: const [E.count],
        builder: (_, c, __) => Text('${c.count}'),
      ),
    ],
  ),
)
```

反过来，**同一个 Widget 里 `wc` 和 `selectIds` 混用会以 `wc` 为准**（已经全量依赖的不能再被 ID 登记
收窄，否则 `wc` 那半边会漏通知）。想要局部就一处都别写 `wc`。

## 在 build 阶段发通知是安全的

控制器在某个 `build` 里改了数据并通知（例如 `builder` 中触发懒加载），本库会把「通知依赖方」
推迟到本帧收尾之后再排，不会撞上 `setState during build`。同一帧内的多次通知合并成一次重建。

安全不等于推荐：`builder` 里做副作用（发请求、改状态）容易写出「重建 → 通知 → 重建」的循环。
首屏加载放 `onPageInit` / `onPagePostFrame`，不要放在 `builder` 里。

## 不刷新时先查这三件事

1. 通知的 ID 在 `shouldNotifyIds` 里吗？不在的话版本号恒为 0，比对永远「没变」。
2. 控制器里是不是调了 `notifyListeners()`？**子类里一处都不该有它**——它不推进任何 ID 的版本号，
   `wc` 的依赖方会重建、`selectIds` / `FlSelector` 的一个都不会。通知一律走
   `notifySingleListener` / `notifyMultiListeners`。
3. `ids` 是不是写成了 `const []`？那是「一个 ID 都不关心」。

跑 `python3 scripts/verify.py lib/`，这三件事它都查。
