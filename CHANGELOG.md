## 0.0.1

Initial release.

- `FlBaseController<T extends Enum>` — controller base class. Created and disposed with the page
  subtree, receives page and app lifecycle callbacks, and notifies listeners per ID.
- `FlBasePage<T>`, `FlBasePageState<S, T>`, `FlPageMixin<T>` — page hosts. Implement
  `createController` and `buildWithController` to get a page with a controller and lifecycle
  already wired.
- `FlProviderBuilder<T>` — scope a controller to part of a subtree instead of a whole page.
- `FlSelector<E, T>`, `FlSelectorView<E, T>` — rebuild only when the listed IDs are notified, with
  a `child` parameter that keeps the static part of the subtree out of the rebuild.
- `context.rc` / `context.wc` / `context.selectIds` — read the controller with no dependency, with
  a dependency on every notification, or with a dependency on specific IDs only. The names avoid
  `read` and `watch` so this package can be imported alongside `provider` without a `hide` or an
  import prefix.
- Rebuild dispatch compares version numbers per ID rather than as a combined hash, so two IDs
  changing in opposite directions cannot cancel out and drop a rebuild. Notifications raised
  during a `build` are deferred to the end of the frame instead of throwing
  `setState() or markNeedsBuild() called during build`.
- Debug assertions for the failure modes that are otherwise silent: notifying an ID that is not in
  `shouldNotifyIds`, an empty `ids` list, and handing one controller instance to two providers.
- Re-exports `fl_page_lifecycle` in full, so `FlRouteObserver`, `FlPageIndexScope`,
  `FlLifecycleState` and the rest are available without adding that dependency yourself.
