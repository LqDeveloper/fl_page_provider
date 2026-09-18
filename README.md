# fl_page_provider

Page-scoped controllers for Flutter: the controller is created and disposed with the page, receives page and app lifecycle callbacks, and rebuilds only the widgets that registered for the ID you notified.

[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

English | [中文](README_zh.md)

---

## Contents

- [Why fl_page_provider?](#why-fl_page_provider)
- [Features](#features)
- [Use cases](#use-cases)
- [Compatibility](#compatibility)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Usage](#usage)
  - [1. Define a controller](#1-define-a-controller)
  - [2. Host it on a page](#2-host-it-on-a-page)
  - [3. Rebuild only what changed](#3-rebuild-only-what-changed)
  - [4. Two ways to read the controller](#4-two-ways-to-read-the-controller)
  - [5. Page and app lifecycle](#5-page-and-app-lifecycle)
  - [6. Pages inside PageView / TabBarView](#6-pages-inside-pageview--tabbarview)
- [API reference](#api-reference)
- [Dependencies](#dependencies)
- [Notes and caveats](#notes-and-caveats)
- [Example](#example)
- [Changelog, contributing, license](#changelog-contributing-license)

---

## Why fl_page_provider?

A page with its own state usually needs four things wired by hand: create the controller, dispose it
when the page goes away, know when the page becomes visible or hidden, and rebuild a small part of
the UI when one field changes. Doing that yourself means an `initState`/`dispose` pair, a
`RouteAware` subscription, and either `setState` (which rebuilds the whole page) or a hand-rolled
`ValueNotifier` per field.

This package collapses all four into one class:

```dart
class ProfilePage extends FlBasePage<ProfileController> {
  const ProfilePage({super.key});

  @override
  ProfileController createController(BuildContext context) => ProfileController();

  @override
  Widget buildWithController(BuildContext context, ProfileController controller) => Scaffold(...);
}
```

The controller is created on first build, disposed when the subtree is removed, and gets
`onPageStart` / `onPageResume` / `onPagePause` / `onPageStop` as the user navigates. When it calls
`notifySingleListener(ProfileId.avatar)`, only the widgets that registered `ProfileId.avatar`
rebuild — everything else in the page is untouched.

The rebuild engine compares version numbers **per ID** rather than as a combined hash, so two IDs
changing in opposite directions can never cancel out into "nothing changed" and drop a rebuild.
Notifications raised during a `build` are deferred to the end of the frame instead of throwing
`setState() or markNeedsBuild() called during build`.

## Features

- Controller lifetime tied to the page subtree — created once, disposed automatically.
- Page lifecycle (`onPageStart`, `onPageResume`, `onPagePause`, `onPageStop`, enter/leave animation
  hooks, `onPageDispose`) delivered straight to the controller; app foreground/background is opt-in
  per page.
- ID-granular rebuilds: `notifySingleListener(id)` rebuilds only the widgets that asked for that ID.
- Only two ways to read the controller, so there is nothing to get wrong: `context.rc` to call a
  method (no dependency), `FlSelector` / `FlSelectorView` to display data (rebuilds only when one of
  the listed IDs is notified). The latter takes a `child` escape hatch for the static part of a
  subtree.
- Correct behaviour for pages inside `PageView` / `TabBarView` / `IndexedStack`, driven by page
  index rather than route.
- A process-wide event bus on the controller (`observeEvent` / `dispatchEvent`) with subscriptions
  cancelled on dispose.
- Debug assertions for the mistakes that otherwise fail silently: unregistered IDs, empty `ids`,
  one controller instance handed to two providers.

## Use cases

| Situation | How this package helps |
|---|---|
| Pause a video or a poll when the page is covered by another route | `onPagePause` / `onPageResume` on the controller |
| Refresh a list after returning from a detail page | `onPageResume`, or an event dispatched by the detail page |
| A counter in an app bar that must not rebuild the whole page | `FlSelector` with the single ID the counter cares about |
| Stop a WebSocket when the app goes to the background | `observeAppLifecycle = true` plus `onAppBackground` |
| Lazy-init a tab that is not visible yet | `observePageIndex = true` plus `FlPageIndexScope` |
| Broadcast a login/logout event to every open page | `dispatchEvent` in one controller, `observeEvent` in the others |

## Compatibility

| Item | Requirement |
|---|---|
| Dart SDK | `^3.11.5` |
| Flutter | `>=3.41.9` |
| Platforms | All platforms Flutter supports — no platform-specific implementation |

No `flutter.plugin` section, and no `dart:io` / `dart:ffi` / `dart:html` / `MethodChannel` /
`Platform.is` anywhere in `lib/`.

## Installation

```yaml
dependencies:
  fl_page_provider: ^0.0.1
```

Or depend on it directly from a checkout:

```yaml
dependencies:
  fl_page_provider:
    path: ../fl_page_provider
```

```bash
flutter pub get
```

## Quick start

`FlRouteObserver` must be registered on the navigator. Without it the page lifecycle callbacks never
fire — the controller is still created and the UI still renders, so the symptom is "my `onPageResume`
never runs" rather than an error.

```dart
import 'package:fl_page_provider/fl_page_provider.dart';
import 'package:flutter/material.dart';

enum CounterId { count }

class CounterController extends FlBaseController<CounterId> {
  @override
  List<CounterId> get shouldNotifyIds => CounterId.values;

  int _count = 0;
  int get count => _count;

  void increase() {
    _count++;
    notifySingleListener(CounterId.count);
  }
}

class CounterPage extends FlBasePage<CounterController> {
  const CounterPage({super.key});

  @override
  CounterController createController(BuildContext context) => CounterController();

  @override
  Widget buildWithController(BuildContext context, CounterController controller) {
    return Scaffold(
      appBar: AppBar(title: const Text('Counter')),
      body: Center(
        child: FlSelector<CounterId, CounterController>(
          ids: const [CounterId.count],
          builder: (context, c, child) => Text('${c.count}'),
        ),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: controller.increase,
        child: const Icon(Icons.add),
      ),
    );
  }
}

void main() {
  runApp(MaterialApp(
    home: const CounterPage(),
    navigatorObservers: [FlRouteObserver()], // required
  ));
}
```

## Usage

### 1. Define a controller

**When to use**: any page that owns state, does I/O, or needs to know when it is visible.

Extend `FlBaseController<E>`, where `E` is an enum of the things this page notifies about. List those
IDs in `shouldNotifyIds`; they are registered for you when the page initialises.

```dart
import 'package:fl_page_provider/fl_page_provider.dart';

enum ProfileId { avatar, nickname, followers }

class ProfileController extends FlBaseController<ProfileId> {
  @override
  List<ProfileId> get shouldNotifyIds => ProfileId.values;

  String _nickname = '';
  int _followers = 0;

  String get nickname => _nickname;
  int get followers => _followers;

  void rename(String value) {
    _nickname = value;
    notifySingleListener(ProfileId.nickname); // one ID
  }

  void applyRemote(String name, int count) {
    _nickname = name;
    _followers = count;
    notifyMultiListeners([ProfileId.nickname, ProfileId.followers]); // several at once
  }
}
```

`notifySingleListener`, `notifyMultiListeners` and `registerIds` are `@protected`: call them from
inside the controller, not from a widget.

**Cross-page events.** Controllers share one process-wide bus. Subscribe in `onPageInit` — the
subscription is cancelled when the controller is disposed.

```dart
class FeedController extends FlBaseController<FeedId> {
  @override
  List<FeedId> get shouldNotifyIds => FeedId.values;

  @override
  void onPageInit() {
    super.onPageInit(); // required
    observeEvent<LoginEvent>(_onLogin);
  }

  void _onLogin(LoginEvent event) => notifySingleListener(FeedId.list);

  void logout() => dispatchEvent(const LogoutEvent());
}
```

Pass a method reference, not a fresh closure: the duplicate-subscription guard compares callbacks by
identity, and a closure literal is a new object every time.

### 2. Host it on a page

**When to use**: pick by what the page needs, not by preference.

| Host | Use it when |
|---|---|
| `FlBasePage<T>` | Plain page, no `State` needed |
| `FlBasePageState<S, T>` | You need `TickerProvider`, a `GlobalKey`, keep-alive, or local UI state |
| `FlProviderBuilder<T>` | You want a controller scoped to part of a subtree, not a whole page |

The stateless form is what [Quick start](#quick-start) shows. The stateful form splits into the usual
two classes:

```dart
class EditorPage extends StatefulWidget {
  const EditorPage({super.key});

  @override
  State<EditorPage> createState() => _EditorPageState();
}

class _EditorPageState extends FlBasePageState<EditorPage, ProfileController> {
  @override
  bool get wantKeepAlive => true;

  @override
  ProfileController createController(BuildContext context) => ProfileController();

  @override
  Widget buildWithController(BuildContext context, ProfileController controller) {
    return Scaffold(body: Text(controller.nickname));
  }
}
```

`FlProviderBuilder` is the same machinery without the page base class:

```dart
FlProviderBuilder<ProfileController>(
  create: (context) => ProfileController(),
  builder: (context, controller) => Text(controller.nickname),
)
```

**Parameters — `FlProviderBuilder`**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `create` | `T Function(BuildContext)` | required | Called once; the returned instance is disposed with the subtree |
| `builder` | `Widget Function(BuildContext, T)` | required | Page UI, receives the controller |
| `observePageIndex` | `bool` | `false` | Drive visibility by page index instead of route |
| `observeAppLifecycle` | `bool` | `false` | Also forward app foreground/background events |
| `key` | `Key?` | `null` | Standard widget key |

**Members to override on `FlBasePage` / `FlBasePageState` / `FlPageMixin`**

| Member | Type | Default | Description |
|---|---|---|---|
| `createController` | `T Function(BuildContext)` | required | Create the controller |
| `buildWithController` | `Widget Function(BuildContext, T)` | required | Page UI |
| `observePageIndex` | `bool` | `false` | See [section 6](#6-pages-inside-pageview--tabbarview) |
| `observeAppLifecycle` | `bool` | `false` | See [section 5](#5-page-and-app-lifecycle) |
| `wantKeepAlive` | `bool` | `false` | `FlBasePageState` only — keep the page alive in a pager |

### 3. Rebuild only what changed

**When to use**: a small part of the page changes often and rebuilding the whole page is wasteful —
a counter badge, a like button, a progress bar.

`FlSelector` depends on the IDs you list and nothing else:

```dart
FlSelector<ProfileId, ProfileController>(
  ids: const [ProfileId.followers],
  builder: (context, controller, child) => Row(
    children: [if (child != null) child, Text('${controller.followers}')],
  ),
  child: const Icon(Icons.people), // built once, handed back unchanged
)
```

**Parameters — `FlSelector`**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `ids` | `List<E>` | required | IDs to depend on; must not be empty |
| `builder` | `FlSelectorBuilder<E, T>` | required | `(context, controller, child) => Widget` |
| `child` | `Widget?` | `null` | Subtree that does not participate in rebuilds |
| `key` | `Key?` | `null` | Standard widget key |

When the fragment deserves its own class, extend `FlSelectorView` instead:

```dart
class FollowerCount extends FlSelectorView<ProfileId, ProfileController> {
  const FollowerCount({super.key});

  @override
  List<ProfileId> get observeIds => const [ProfileId.followers];

  @override
  Widget? get staticChild => const Icon(Icons.people); // must be the same instance every time

  @override
  Widget buildWidget(BuildContext context, ProfileController controller, Widget? child) {
    return Row(children: [if (child != null) child, Text('${controller.followers}')]);
  }
}
```

### 4. Two ways to read the controller

**When to use**: whenever you reach for the controller from a widget. There are only two entry
points, split by whether you want to rebuild when the data changes:

| Entry point | Creates a dependency | Rebuilds |
|---|---|---|
| `context.rc<T>()` | no | never |
| `FlSelector` / `FlSelectorView` | yes | only when one of `ids` is notified |

```dart
// In a callback — you only want to call a method, no rebuild needed.
onPressed: () => context.rc<ProfileController>().rename('new name'),

// To display data — wrap it in a FlSelector that watches just those IDs.
FlSelector<ProfileId, ProfileController>(
  ids: const [ProfileId.nickname, ProfileId.avatar],
  builder: (context, c, _) => Text(c.nickname),
)
```

`rc` is short for *read controller*. It deliberately avoids the name `read`, which the `provider`
package already defines as an extension on `BuildContext` along with `watch` — so both packages can
be imported side by side with no `hide` and no import prefix.

**There is no "rebuild on every notification" granularity.** ID granularity is the only
notification semantics this package has. When you genuinely want "refresh this block on any
change", reserve an ID for it and include it in every notification:

```dart
enum ProfileId { all, nickname, avatar }

// Controller side
notifyMultiListeners(const [ProfileId.all, ProfileId.nickname]);

// Caller side
FlSelector<ProfileId, ProfileController>(
  ids: const [ProfileId.all],
  builder: (context, c, _) => Text(c.nickname),
)
```

That keeps "what rebuilds, and why" written at the call site instead of buried in the controller.

**Subscribing by ID is only offered through a widget — there is no `BuildContext` form.** The
dependency is registered on the element that *starts* the subscription, so doing it from a page's
`build` makes the whole page shake on a single ID; and because Flutter only clears dependency
registrations on `Element.deactivate()` and never on rebuild, doing it behind a condition would
leave a permanently wasteful registration behind. `FlSelector` is itself a widget, which solves
both: the rebuild boundary is that widget, and when the condition no longer holds it unmounts and
the dependency goes with it. **Putting a `FlSelector` inside an `if` is the safe pattern**, not a
pitfall.

### 5. Page and app lifecycle

**When to use**: start work when the page becomes visible and stop it when it does not — polling,
video playback, animations, analytics dwell time.

Override the hooks on the controller. Always call `super` first.

```dart
enum VideoId { playing }

class VideoController extends FlBaseController<VideoId> {
  @override
  List<VideoId> get shouldNotifyIds => VideoId.values;

  bool _playing = false;
  bool get isPlaying => _playing;

  @override
  void onPageResume() {
    super.onPageResume();
    _playing = true; // page is visible and interactive
  }

  @override
  void onPagePause() {
    super.onPagePause();
    _playing = false; // covered by another route, or app went to background
  }

  @override
  void onAppBackground() {
    super.onAppBackground(); // needs observeAppLifecycle = true on the page
  }
}
```

Hooks available on the controller: `onPageInit`, `onPageContextReady`, `onPagePostFrame`,
`onPageReassemble`, `onPageStart`, `onPageResume`, `onPageEnterAnimationStart`,
`onPageEnterAnimationEnd`, `onPagePause`, `onPageStop`, `onPageLeaveAnimationStart`,
`onPageLeaveAnimationEnd`, `onPageDispose`, `onAppResume`, `onAppInactive`, `onAppPause`,
`onAppForeground`, `onAppBackground`, `onPageIndexChanged`.

App-level hooks only fire when the page opts in:

```dart
class VideoPage extends FlBasePage<VideoController> {
  const VideoPage({super.key});

  @override
  bool get observeAppLifecycle => true;

  @override
  VideoController createController(BuildContext context) => VideoController();

  @override
  Widget buildWithController(BuildContext context, VideoController controller) =>
      const Scaffold();
}
```

The controller also exposes read-only state: `lifecycleState`, `isPageResume`, `isPagePause`,
`isForeground`, `routeName`, `arguments`.

### 6. Pages inside PageView / TabBarView

**When to use**: the page is a child of `PageView`, `TabBarView` or `IndexedStack`. Those children are
not separate routes, so route-based visibility cannot tell which one is on screen — visibility has to
come from the page index instead.

Two halves, both required. On the child page set `observePageIndex`:

```dart
class _TabOneState extends FlBasePageState<TabOne, TabOneController> {
  @override
  bool get observePageIndex => true;

  @override
  bool get wantKeepAlive => true;

  @override
  TabOneController createController(BuildContext context) => TabOneController();

  @override
  Widget buildWithController(BuildContext context, TabOneController controller) =>
      const Scaffold();
}
```

On the host, wrap the children with `FlPageIndexScope`:

```dart
TabBarView(
  children: FlPageIndexScope.wrapChildren(
    controller: DefaultTabController.of(context),
    children: const [TabOne(), TabTwo()],
  ),
)
```

For a lazily built pager use `wrapItemBuilder` instead:

```dart
PageView.builder(
  controller: pageController,
  itemCount: 4,
  itemBuilder: FlPageIndexScope.wrapItemBuilder(
    controller: pageController,
    builder: (context, index) => TabOne(),
  ),
)
```

Both helpers take any `Listenable`, so a `TabController` and a `PageController` both work. Setting
`observePageIndex = true` without wrapping the host is not an error — the page is simply treated as
an ordinary one: visible from the first frame, and no page-switch callbacks at all.

## API reference

Everything exported by `package:fl_page_provider/fl_page_provider.dart`.

| Name | Kind | Purpose | Details |
|---|---|---|---|
| `FlBaseController<T extends Enum>` | abstract class | Controller base: lifecycle + ID notifications + event bus | [1](#1-define-a-controller) |
| `FlBasePage<T>` | abstract class | Stateless page base | [2](#2-host-it-on-a-page) |
| `FlBasePageState<S, T>` | abstract class | Stateful page base, with keep-alive support | [2](#2-host-it-on-a-page) |
| `FlPageMixin<T>` | mixin | The `createController` / `buildWithController` contract, for custom hosts | [2](#2-host-it-on-a-page) |
| `FlProviderBuilder<T>` | class | Create, own and inject a controller into a subtree | [2](#2-host-it-on-a-page) |
| `FlSelector<E, T>` | class | Rebuild on the listed IDs only | [3](#3-rebuild-only-what-changed) |
| `FlSelectorBuilder<E, T>` | typedef | `FlSelector.builder`'s signature | [3](#3-rebuild-only-what-changed) |
| `FlSelectorView<E, T>` | abstract class | `FlSelector` as a class you extend | [3](#3-rebuild-only-what-changed) |
| `FlControllerContextExtension` | extension | `context.rc` | [4](#4-two-ways-to-read-the-controller) |

Importing this package also gives you everything from `fl_page_lifecycle` — `FlRouteObserver`,
`FlPageIndexScope`, `FlLifecycleState`, `FlPageLifecycleView`, `FlGlobalEventBus` and the rest —
without adding that package to your own `dependencies`.

## Dependencies

| Package | Constraint | What it does | Used in |
|---|---|---|---|
| `fl_page_lifecycle` | `^0.0.3` | Page and app lifecycle detection, route observer, page-index visibility, global event bus | `lib/src/controller/fl_base_controller.dart`, `lib/src/widget/fl_provider_builder.dart`, `lib/src/controller/fl_event_bus_mixin.dart` |
| `meta` | `^1.17.0` | The `@internal` annotation used to keep implementation types out of the public API | `lib/src/provider/fl_page_provider.dart`, `lib/src/provider/fl_id_versions.dart` |

`fl_page_lifecycle` is re-exported in full from the package entry point, so its API is part of this
package's public surface.

## Notes and caveats

**Register `FlRouteObserver`.** Add it to `MaterialApp.navigatorObservers` (or your `Navigator`'s
`observers`). Without it the page renders fine and no error is raised, but no page lifecycle callback
ever arrives.

**Every ID you notify must be in `shouldNotifyIds`.** An unregistered ID keeps version `0` forever, so
the comparison always says "unchanged" and the dependent never rebuilds. Debug builds assert on this;
release builds fail silently.

**`ids` must not be empty.** `const []` reads like "no ID filter" but means "I care about no ID at
all", so the widget never rebuilds. If you want every notification, reserve an ID for it and include
that ID in every notification. Asserted in debug.

**`create` hands over ownership.** The instance it returns is disposed when the subtree goes away.
Returning a shared singleton means the first page to close disposes it, and every other subtree
freezes with no error. One `create`, one instance. Asserted in debug.

**Always call `super` when overriding.** In controller hooks, `onPageInit` registers your IDs and
`onPageReassemble` re-registers them after hot reload. On `FlBasePageState`, if you override `build`
at all you must call `super.build(context)` — that one belongs to `AutomaticKeepAliveClientMixin`
and keep-alive breaks without it. Page UI goes in `buildWithController`, so overriding `build` is
usually unnecessary.

**Subscribe to events once, in `onPageInit`.** `observeEvent` does not replace an existing
subscription. Calling it from `build` or `onPageResume` grows the subscription list on every rebuild,
which shows up as duplicate analytics or duplicate network calls. Pass a method reference so the
duplicate guard can recognise it.

**`observePageIndex` needs both halves.** Setting it on the page without wrapping the host with
`FlPageIndexScope` is silently ineffective — see [section 6](#6-pages-inside-pageview--tabbarview).

