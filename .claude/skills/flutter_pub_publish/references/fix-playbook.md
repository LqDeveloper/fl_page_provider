# 修复手册

按 `preflight.py` 输出的检查项 ID 查。只在真的有项目不通过时读对应小节，不要整份读进上下文。

**分类的含义**：
- **auto** —— 只动元数据与格式，不碰 `lib/` 下的业务逻辑。用户选「AI 自动修改」时你可以直接改。
- **manual** —— 要么涉及业务代码正确性，要么涉及只有人能做的决定（法律、身份、提交历史、账号授权）。
  **即使用户选了「AI 自动修改」，这些也不能替他做**——把它们单独列出来交回给人。

---

## PKG.parser —— manual（地基，必须先解决）

意思是**这份 pubspec 在当前环境下无法被可信读取**，不是"读得有点勉强"。
所有元数据检查都依赖它，所以脚本会直接放弃整个 meta 组而不是带着可疑结果往下跑。

三种触发原因，看报错文本区分：

| 报错 | 原因 | 解决 |
|---|---|---|
| `第 N 行用了 YAML 锚点/别名 / 合并键 / 标签` | pubspec 用了内置严格解析器不担保的语法 | 装 PyYAML：`pip3 install pyyaml`（装了它就权威了）；或把那几行改成直白写法 |
| `内置严格解析器自检未通过` | 解析器自身在这台机器上行为异常 | 装 PyYAML。同时这是个真 bug，值得报给 skill 维护者 |
| `两个解析器对这份 pubspec 的理解不一致` | PyYAML 和内置解析器读出了不同结果 | **别挑一个用**。先弄清这份 pubspec 到底想表达什么——这种分歧本身说明文件写法有歧义 |
| `字段 name/version 的解析结果与原文直读不一致` | 解析器读串了行 | 同上，查清楚再说 |

**不要绕过去。** 自己 `grep '^version:'` 拿一个值继续跑，等于把脚本刚刚拒绝背书的事
换个方式做了一遍——你 grep 出来的值同样没有保证，而且丢掉了报错信息。

装 PyYAML 是最省事的解法，一条命令：

```bash
pip3 install pyyaml        # 或 python3 -m pip install --user pyyaml
```

---

## PUB.identity —— manual（对不上就停）

`dart pub publish --dry-run` 会打印 `Publishing <包名> <版本> to https://pub.dev`。
这行字是**唯一不经过任何 YAML 解析器**的权威来源——pub 就是要拿这个名字和版本号上传。

它和我们从 pubspec 读到的对不上，说明前面的版本比对、CHANGELOG 对齐、tag 冲突检查
针对的根本不是同一个东西。常见原因：跑检查的目录和 pub 解析的根目录不是同一个
（monorepo 里尤其容易），或者中途有人改了 pubspec。

**查清楚再发**，不要因为"差别不大"就放行——这里的差别只有对和错两种。

---

## PKG.pubspec / PKG.name —— manual

包名就是包的身份。改名等于换一个包，线上已有的使用者会全部失联。
名字不合规（大写、连字符、数字开头）而这个包**还没发布过**时，可以建议一个合规名字，但要由用户确认。

---

## PKG.publish_to —— manual

`publish_to: none` 是**有人主动加上去的**，通常意味着这是私有包或应用工程。
先问清楚：这个包是不是本来就不该发到 pub.dev？确认要发，再删这一行。
不要因为「它挡住了发布流程」就顺手删掉——这个字段存在往往就是为了防止误发。

---

## PKG.description —— auto

pub.dev 评分要求 60–180 字符。写法：

```yaml
description: >-
  A Flutter state lifecycle helper that binds controller disposal to widget
  lifetime, preventing leaked timers and stream subscriptions.
```

改的时候：**描述包真实做的事**，从 README 首段和 `lib/` 的导出面取事实。
不要为了凑到 60 字符加 "This package provides a simple and easy to use..." 这类废话——
pub.dev 的搜索会用这段文字，注水会让它检索不准。

---

## PKG.repository —— auto

从 git remote 取：

```bash
git -C <pkg> remote get-url origin
```

`git@github.com:user/repo.git` 要转成 `https://github.com/user/repo`。
package 在 monorepo 子目录时，指到子目录更有用：`https://github.com/user/repo/tree/main/packages/foo`。

取不到 remote 就**别编一个**——留给用户填，并说明为什么没填。

---

## PKG.env_sdk —— manual

SDK 下界要按包**实际用到的语言特性**定，不是抄一个流行值。写低了使用者编译报错，写高了白白排除一批用户。

```yaml
environment:
  sdk: ^3.5.0
  flutter: ">=3.24.0"
```

判断依据：用了 records / patterns → Dart 3.0+；用了 class modifiers（`sealed`/`interface`）→ 3.0+；
用了 `switch` 表达式 → 3.0+。拿不准就照当前开发机 SDK 的**上一个稳定大版本**写，并告诉用户这是推断值。

---

## DEP.path_git —— manual

pub.dev 不接受 `path:` / `git:` 依赖，因为使用者拿不到那些源。

```yaml
dependencies:
  fl_core: ^1.0.0        # 对
  fl_core:               # 错，发布会被拒
    path: ../fl_core
```

**这不是改一行的事，是发布顺序问题**：被依赖的包必须**先**发到 pub.dev，拿到版本号，
再回来把这里换成版本约束。monorepo 里就是从叶子往根发。

`find_packages.py` 已经把这个顺序算好了，直接照着走：

```bash
python3 <skill目录>/scripts/find_packages.py <仓库根>
```

输出里的「发布顺序」一行就是答案。它检出循环依赖时会明说——那种情况下没有合法顺序，
得先把循环拆掉（通常是把公共部分抽成第三个包），这是架构决定，交给用户。

顺序搞错的后果不是发布失败，而是发出去了但别人装不上——这时候只能再发一个修订版。

---

## VER.semver / VER.vs_pubdev —— auto

版本号按**改动性质**提，不是按「改了多少」：

| 情况 | 提法 |
|---|---|
| 删了/改了公开 API 签名、改了默认行为 | major（`1.4.2` → `2.0.0`） |
| 只加了新 API，老代码原样能跑 | minor（`1.4.2` → `1.5.0`） |
| 只修 bug、改文档、调依赖上界 | patch（`1.4.2` → `1.4.3`） |
| 1.0.0 之前（`0.x.y`） | 破坏性改动提 minor（`0.4.2` → `0.5.0`），其余提 patch |

判断"是不是破坏性"要看 `changelog_draft.py` 输出的**公开 API 面增删**那一节：
出现 `-` 开头的 `export` / 类 / 方法签名，就是破坏性。

**改完版本号，CHANGELOG 的顶部标题要同步改**——这两个必须一致，见下一节。

---

## VER.changelog_match —— auto（但内容必须来自 git）

先判断**哪个才是要发的版本**，再对齐另一个。默认改 CHANGELOG 是错的：
如果 pubspec 忘了升版本，正确做法是升 pubspec，不是把 CHANGELOG 标题改小。

格式（pub.dev 靠这个渲染版本说明页）：

```markdown
## 1.5.0

* 新增 `FlLifecycle.autoDispose()`，widget 销毁时自动释放注册的 controller。
* 修复 响应体缺 `data` 字段时 `parseResponse` 抛 `NoSuchMethodError`。

## 1.4.2
...
```

**内容必须先跑 `changelog_draft.py` 拿到真实 commit 和 diff**，再归纳成使用者视角的一句话。
禁止从版本号差值反推「本次为功能更新」这类空话——使用者读 CHANGELOG 是为了决定要不要升级，
一条看不出改了什么的条目等于没写。

破坏性变更单独标，并给迁移方式：

```markdown
## 2.0.0

* **BREAKING** 移除 `FlState.attach(context)`，改用 `FlState.of(context)`。
  迁移：把 `attach(context)` 替换为 `of(context)`，返回值类型不变。
```

---

## DOC.changelog（文件缺失）—— auto

新建 `CHANGELOG.md`。首次发布写：

```markdown
## 0.1.0

* 首次发布。
* <这里列包提供的核心能力，从 lib/ 导出面取>
```

---

## DOC.readme —— manual

README 是包的门面，也是唯一被反复引用的文档，内容必须基于真实 API。
这个仓库里有专门的 `flutter_readme` skill 干这件事，**建议让用户先用它生成，再回来发布**。

不要在发布流程里顺手糊一份 README——糊出来的文档里编造的 API 会一直留在 pub.dev 上。

---

## DOC.license —— manual

**选哪个开源协议是法律决定，AI 不代选。** 把常见选项和差别摆给用户，让他挑：

| 协议 | 大意 |
|---|---|
| MIT | 最宽松，保留版权声明即可 |
| BSD-3-Clause | 类似 MIT，额外禁止用作者名背书 |
| Apache-2.0 | 含专利授权条款，企业使用更放心 |

用户选定后，从 SPDX 取标准全文，填对年份和著作权人。**不要凭记忆手打协议全文**——
协议文本一个字都不能改，改了就不是那个协议了。

---

## DOC.example —— manual

`example/` 里是真实可运行的代码，也是 pub.dev 首页"Example"标签页的内容。
AI 生成的示例很容易调到不存在的方法或跑不通——**必须由懂这个包的人写或至少跑通一遍**。

最小可接受形态：`example/lib/main.dart` 一个能 `flutter run` 起来的 app，
或纯 Dart 包的 `example/example.dart` 一个能 `dart run` 的脚本。

---

## CODE.format —— auto

```bash
cd <pkg> && dart format .
```

纯格式化，不改语义，可以直接跑。跑完在 git diff 里确认**只有空白和换行变化**——
如果 diff 里出现了别的东西，说明你跑错命令了。

**必须是 `dart format`，不是 `flutter format`。** 后者早就从 Flutter CLI 里移除了
（Flutter 2.5 弃用，之后删除），现在跑它只会得到 `Could not find a command named "format"`。
Flutter 包也一样用 `dart format`——Flutter SDK 自带 dart，就在 `flutter` 旁边的 bin 目录里。

**看到 `CODE.format` 是 SKIP 而不是 FAIL 时**，说明 `dart format` 非零退出却一个待格式化
文件都没报——那不是格式问题，是命令没跑成。最常见的原因是某个 `.dart` 有语法错误让
formatter 解析不了（报错里会指出文件和行号）。这种情况**不要去跑 `dart format .`**，
它同样会失败；先按报错修语法，analyze 那一项通常也会报同一处。

---

## CODE.analyze —— manual

analyze 命中的是 `lib/` 下的实际代码，属于业务逻辑层，本 skill 不自动改。

同样必须用 `dart analyze --format=machine`：`flutter analyze` 不认 `--format=machine`，
拿它去跑会得到一个参数错误，而从那种输出里数不出任何诊断——结果是一个凭空捏造的"零问题"。
`CODE.analyze` 显示 SKIP 且提示"解析不出任何诊断行"时就是这一类，**它不等于通过**，
先解决环境问题（常见：`pub get` 没成功、SDK 版本不匹配）再重跑。

`dart fix --apply` 能自动修一部分（未使用的 import、缺 `const`、`prefer_final` 等），
**但它会改业务代码**。要用就明确告诉用户：

> `dart fix --apply` 能自动处理其中 N 条。它会直接改 lib 下的代码，
> 跑完你需要看一遍 `git diff` 再决定要不要留。要我跑吗？

得到明确同意再跑，跑完把 diff 摘要给用户看。**没跑过测试之前不要声称 fix 是安全的。**

剩下修不掉的（真实的类型错误、`use_build_context_synchronously` 之类）是代码缺陷，
交给用户，不要为了让检查变绿去改 `analysis_options.yaml` 关规则——
**关掉规则不等于问题消失，只等于你看不见它了**。

---

## CODE.test —— manual

测试失败说明代码有真实缺陷。**改测试让它变绿不是修复。**
把失败的用例名和报错原样贴给用户，让他决定是修代码还是这一版先不发。

---

## PUB.dry_run —— 视具体告警而定

这是 pub 自己的裁决，权威性高于本脚本的所有其他检查。常见告警：

| 告警 | 处理 |
|---|---|
| `Package has no example` | 见 DOC.example |
| `pubspec.yaml has no "repository"` | 见 PKG.repository，auto |
| `... is not in the allowed list of licenses` | LICENSE 文件不是 SPDX 标准全文，重新取一份 |
| `Package validation found the following error: ... size` | 打包超 100MB。查 `.pubignore`，把 assets/截图/示例产物排除掉 |
| `... will be ignored / not tracked by git` | 有文件被 `.gitignore` 排除但代码需要它，或反过来 |

`.pubignore` 写法和 `.gitignore` 一致，放 package 根目录，用来排除**不该进包**的东西
（设计稿、录屏、大图、内部脚本）。它不影响 git，只影响发布的产物。

---

## GIT.clean —— manual

**提交哪些改动、写什么 commit message 是用户的决定，AI 不代提交。**
把 `git status` 的内容列出来，让用户提交或 stash 后再回来。

这一项**只看本包目录下的改动**。monorepo 里隔壁包脏着不影响这个包发布，
所以脚本跑的是 `git status --porcelain -- <本包目录>`。你要手动复查时记得带上 `-- <目录>`，
否则会把整个仓库的改动算到这个包头上。

工作区脏就发布，发出去的版本对不上任何一个 commit，
以后出问题时没法回到"线上这一版到底是什么代码"。

---

## GIT.tag —— manual

这个包专属的版本 tag 已存在，几乎总是意味着**这个版本号已经发过了**，忘了升版本。
先跟用户核对：是忘了升版本，还是上次打了 tag 但发布失败？两种情况处理方式完全不同。

**查的是哪些 tag**：包在仓库根上时查 `v<版本>` / `<版本>`；包在子目录里时只查带包名的写法
（`<名>-v<版本>`、`<名>/v<版本>`、`<名>@<版本>` 等）。子目录包看到仓库里有裸 `v<版本>` 时，
脚本会把它连同所属 commit 一起列出来当提示，但**不据此判定**——那个 tag 很可能是隔壁包的，
拿它给这个包定罪，等于用别人的状态拦下你的发布。

反过来说，如果你们的 monorepo 一直用裸 tag，这个检查就漏了。解决办法是改用带包名的 tag
（见 SKILL.md 第 7 步），而不是放宽检查——裸 tag 在多包仓库里本来就会互相覆盖。

---

## AUTH.pub —— manual（必须用户本人做）

```bash
dart pub login
```

会打开浏览器做 Google OAuth。**这一步必须用户在自己的终端里完成**——
在 AI 会话里跑会卡在等待浏览器回调上，而且授权凭据不该经过第三方。

CI 环境用 `PUB_TOKEN` + `dart pub token add https://pub.dev --env-var PUB_TOKEN`，
但那是用户自己配的，不在本 skill 范围内。
