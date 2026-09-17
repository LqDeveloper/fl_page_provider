---
name: flutter_pub_publish
description: 把一个 Flutter/Dart package 发布到 pub.dev 的完整把关流程——先清点目录树里有哪些 package 并让用户确认这次发的是哪一个（monorepo 里可能有多个，还要按包间依赖决定先后顺序），再跑一遍发布前体检（版本号是否高于线上已发布版本、CHANGELOG 顶部是否与 pubspec 对齐、README/LICENSE/example 是否齐备、依赖里有没有 path/git 依赖、dart analyze 的 error+warning+info 是否清零、dart format 是否一致、测试是否全过、dart pub publish --dry-run 是否零告警、git 工作区是否干净、pub.dev 是否已登录），不通过时让用户选「AI 自动修元数据与格式」还是「自己手动改」，选手动就停下等他，选自动就改完全量重跑；全部通过后列出包名版本文件清单等用户明确确认，才执行 dart pub publish，发布成功再打 git tag 并推送。Use this skill whenever the user says 发布/上传/publish 一个 flutter package 或 dart package 到 pub.dev、准备发版、要发新版本、升版本号发布、"帮我把这个包发出去"、"发 pub"、"pub publish 报错了"、"发布前检查一下"、"这个包能发了吗"、"版本号和 CHANGELOG 对一下"、"dry-run 有告警怎么办"——即使他们没说 pub.dev 或 skill 这些词。也适用于用户把一个 package 目录丢过来问"还差什么才能发"。不适用于发布 npm/maven 包，也不适用于纯粹写 README（那是 flutter_readme skill）。
---

# 发布 Flutter Package 到 pub.dev

你的角色：替维护者按住发布按钮的那个人。

要理解这件事的不对称性：**`dart pub publish` 不可撤销**。发出去的版本 7 天内只能 retract（标记撤回，
但文件永久留在 pub.dev），7 天后连 retract 都不行。而多花五分钟做检查的代价接近零。
所以这个 skill 的默认姿态是**拦住**，不是放行——每一次"要不要提醒一下"的犹豫，答案都是提醒。

同时也别走到另一个极端：把一堆无关紧要的建议堆给用户、每一步都问一遍，会让人绕过这个流程直接手敲命令，
那才是真正的风险。**该拦的坚决拦，能自己判断的别问。**

## 三条纪律

**发布必须人工确认。** 无论体检多干净，`dart pub publish` 前必须把 包名 / 版本号 / 文件清单 / 体积
摆出来，等用户明确说"发"。**用户没回话就不发**——这是这个 skill 里唯一一处「宁可卡住也不推进」的地方，
因为卡住的代价是等，发错的代价是永久。

**读不懂就停，不猜。** 所有元数据判断都建立在"我读懂了 pubspec"这个前提上，
所以 `PKG.parser` 是一切的地基：它 FAIL 时脚本会直接放弃整个 meta 组，因为一个可能读错的
pubspec 会让版本比对和 tag 检查全都针对错的对象。**这一条不接受"大概率没问题"**——
让用户装 PyYAML 或简化 pubspec 写法的代价是几分钟，读错版本号的代价是发错版本且不可撤销。

**只校验要发的那个包。** 选定之后，所有检查都严格限定在这个 package 目录内：
隔壁包有未提交改动、隔壁包占了某个 tag、隔壁包的 analyze 有报错，**都与这次发布无关**，
不该让这个包的体检挂掉。这一条不只是礼貌问题——把别的包的问题算到这个包头上，
人会开始怀疑体检结果本身，进而绕过整个流程。脚本已经做了限定（`git status -- <本包目录>`、
只认带包名的 tag、`git log -- <本包目录>`），你手敲 git 命令补充检查时要记得加同样的限定。

**跳过不等于通过。** 检查项因为没网、没装 SDK、命令超时而 SKIP 时，不能当作 PASS 混过去。
体检脚本会把 SKIP 单独列出来并让整体结论变成 `NOT_READY`。要么补齐环境重跑，要么明确告诉用户
"这几项我没验过，你自己确认"，然后由**用户**决定要不要继续——不是由你决定。

**自动修改只碰元数据与格式。** 版本号、CHANGELOG 条目、pubspec 字段、`dart format` 属于 auto；
`lib/` 下的业务代码、测试、LICENSE 选型、git 提交、pub 登录属于 manual，**即使用户说了"你全自动改"也不代做**——
把它们单列出来交回去。理由很直接：这些改动的对错要跑起来才知道，而你正准备把它永久发到公网上。

---

## 开工前：完整性门禁

这个 skill 由 SKILL.md + 4 个脚本 + 1 份手册构成。脚本缺失时你会退化成手敲一串命令再肉眼比对，
**漏掉的恰好是最容易出事的那几项**（版本号 vs 线上、CHANGELOG 对齐、SKIP 不算通过），
而用户从对话表面看不出来漏了什么。所以先查。

```bash
SKILL_DIR="$(dirname "$(find / -name SKILL.md -path '*flutter_pub_publish*' 2>/dev/null | head -1)")"
echo "skill 目录: $SKILL_DIR"
for f in scripts/find_packages.py scripts/preflight.py scripts/pubspec.py \
         scripts/changelog_draft.py references/fix-playbook.md; do
  [ -f "$SKILL_DIR/$f" ] && echo "  ✓ $f" || echo "  ✗ 缺失: $f"
done
```

后面所有 `<skill目录>` 都用 `$SKILL_DIR`。有 ✗ 就停下，让用户 `cp -r` 整个文件夹重装（不能只拷 SKILL.md）。

（`tests/` 不在门禁清单里：它是给改这个 skill 的人用的，缺了不影响发布流程。）

---

## 流程

### 第 0 步：确认发哪个 package（**任何其他动作之前**）

发错包比发错版本更糟，而且同样不可撤销。这一步不是流程的开场白，是**闸门**：
在包被选定并被用户认可之前，不跑体检、不读 pubspec 做判断、不动任何文件。

先清点，无条件跑，哪怕用户只给了一个路径：

```bash
python3 <skill目录>/scripts/find_packages.py <用户给的路径，或当前目录>
```

它会列出每个 package 的 **名字 / 版本 / 类型 / 路径**，标出哪些不可发布
（应用工程、`publish_to: none`、example 子工程）及其原因，并检出包之间的 path/git 依赖
和由此决定的**发布先后顺序**。

为什么用户已经给了路径也要跑：用户说的"这个包"可能指的是仓库根目录而不是某个子包，
也可能他自己记错了目录。多花三秒钟清点一次，比发错包便宜太多。

照脚本末尾的结论走：

| 脚本给出的情况 | 做法 |
|---|---|
| 只有一个候选 | 说一句"我给 `<包名> <版本>` 走发布检查"就开始，**不等回复** |
| 多个候选 | **必须用 AskUserQuestion 让用户选**，选项里带上 包名 + 版本 + 路径。有依赖顺序的话在选项说明里点出来 |
| 一个候选都没有 | 把排除原因摆给用户（"`apps/demo` 是应用工程、`example/` 是示例"），问他想发的到底是哪个 |
| 某个包标了「需确认」 | 连同它的原因一起交给用户，不要替他判断 |

**没人回答时停在这里等。** 这一步和这个 skill 的其他环节都不同——别处默认推断的代价是
重跑一次，这里的代价是把错误的包永久发到公网。宁可卡住。

**选定之后就锁死。** 后面每一步都用这个绝对路径，报告里也始终带着包名和版本
（`preflight.py` 的输出头会复述它们）。分组跑体检、自动修改、重跑之间隔了很多轮，
**在 monorepo 里最容易发生的事故不是选错，是中途飘到隔壁包上**——每次看到体检输出，
先扫一眼头一行的包名对不对。

**多个包都要发时，一次只走一个。** 选定一个走完全流程（含发布和打 tag），
再回来发下一个。理由是发布不可撤销：连发到一半失败，已经发出去的收不回来，
而每个包的版本号和 CHANGELOG 都需要单独判断。发完一个后主动提醒还剩哪些没发、
按什么顺序发。

**顺序不能乱。** 脚本给出的发布顺序是硬约束：`fl_core → fl_net → fl_ui` 意味着
`fl_net` 的 `dependencies` 里还有 `fl_core: {path: ../fl_core}`，必须等 `fl_core` 发到
pub.dev、拿到版本号、把这条依赖换成版本约束之后，`fl_net` 才发得出去。顺序错了
**不会发布失败**，而是发出去了但别人装不上——只能再发一版修。（体检的 `DEP.path_git`
会拦住这种情况，但那时你已经在错误的包上花了一轮。）

### 第 1 步：跑体检

分两批跑。第一批秒级，先把最常见的低级错误暴露出来：

```bash
python3 <skill目录>/scripts/preflight.py <pkg> --only meta,git,auth
```

第二批要跑工具链，慢，而且宿主对单条命令通常有时限，分开跑避免整批超时：

```bash
python3 <skill目录>/scripts/preflight.py <pkg> --only format
python3 <skill目录>/scripts/preflight.py <pkg> --only analyze
python3 <skill目录>/scripts/preflight.py <pkg> --only test
python3 <skill目录>/scripts/preflight.py <pkg> --only dryrun
```

环境宽松（没有命令时限）时可以一次跑完：`preflight.py <pkg>`。

脚本检查这些项，**每一项都是阻断项**——这是用户选定的严格度，不要自行放宽：

| 组 | 检查 |
|---|---|
| meta | **pubspec 可信解析**、`publish_to` 未被禁用、包名合规、description 60–180 字符、repository 字段、`environment.sdk`、**依赖里无 path/git**、版本号合法、**版本号高于 pub.dev 线上最新版**、CHANGELOG 存在且顶部版本与 pubspec 一致且条目非空、README 非模板、LICENSE、example |
| git | 在 git 仓库内、**本包目录下**工作区干净、本包专属的版本 tag 未被占用 |
| auth | pub.dev 凭据存在 |
| format | `dart format` 零差异 |
| analyze | `dart analyze` 的 **error + warning + info 全部为 0** |
| test | `flutter test` / `dart test` 全过 |
| dryrun | `dart pub publish --dry-run` 零告警；**`PUB.identity`**：pub 自己打印的 `Publishing <名> <版本>` 与我们从 pubspec 读到的一致 |

**`dryrun` 是权威裁决**，它说不行就是不行，优先级高于脚本其他所有判断。反过来，
它通过**不代表**可以发——版本号和 CHANGELOG 对不对，dry-run 一概不查，那正是 meta 组的价值。

`PKG.parser` FAIL 时不要试图绕过去（比如自己 grep 版本号继续跑）。它的意思是这份 pubspec
在当前环境下无法被可信读取，你手工 grep 出来的值同样没有保证。正确做法是照报错提示
让用户装 PyYAML（`pip3 install pyyaml`）或简化 pubspec 写法，然后重跑。

体检脚本只读，不改被检查 package 的任何文件，也不会触发任何发布动作。

**范围**：所有检查都只针对给定的这个 package 目录。monorepo 里尤其要注意 git 那两项——
`GIT.clean` 只看本包目录下的改动（`git status -- <本包目录>`），`GIT.tag` 在子目录包上
只认 `<包名>-v<版本>` 这类带包名的 tag，仓库里裸的 `v1.2.0` 会作为提示列出但**不作判定**，
因为它可能属于隔壁包。唯一无法完全隔离的是 `test`：跑测试必然要编译 path 依赖的兄弟包，
那里的编译错误会以测试失败的形式冒出来——遇到这种情况看清报错来自哪个包，
如果是兄弟包的问题，那是"先发被依赖方"的顺序问题，不是这个包的缺陷。

### 第 2 步：全部通过 → 直接跳到第 5 步

结论是 `READY`（0 个 FAIL 且 0 个 SKIP）时，不要为了显得尽责再补一堆建议，直接进确认环节。

有 SKIP 时**不算 READY**：先尝试补齐（装 SDK、跑 `pub get`、换网络），补不齐就把
"这几项没验过、因此存在什么风险"讲清楚，问用户是继续还是先解决环境。**这个决定归用户**。

### 第 3 步：有不通过项 → 摆出来，让用户选

先把体检结果整理成一张表交给用户。表要能一眼看完，所以：**先讲不通过的，通过的一行带过**。

```
体检结果：3 项不通过

✗ VER.vs_pubdev        本地 1.4.2 不高于 pub.dev 线上最新 1.4.2
✗ VER.changelog_match  CHANGELOG 顶部是 1.4.1，pubspec 是 1.4.2
✗ CODE.analyze         ERROR 0 / WARNING 2 / INFO 5
                       lib/src/client.dart:88  use_build_context_synchronously
                       ...

其余 14 项通过。
```

然后给出选择。**这是用户明确要求的一道岔口，必须问，不能替他决定**——即使不通过的项全是
可自动修的，也要问，因为"改哪个版本号"这类判断只有他知道背景。用 AskUserQuestion 给三个选项：

| 选项 | 你做什么 |
|---|---|
| **AI 自动修改** | 修 auto 类的项 → 说明改了什么 → **回到第 1 步全量重跑** → 通过则进第 5 步 |
| **我自己手动改** | **立刻停止 skill**，把待办清单和每项的修法交给他，说明改完可以再喊你 |
| **这次先不发了** | 停止，什么都不改 |

**必须区分 auto 和 manual。** 脚本已经在结论里分好了：`可由 AI 自动修` 和 `必须人工处理`。
即使用户选了"AI 自动修改"，manual 那批也要单独列出来说"这几项我不动，需要你处理"——
选择"自动修改"表达的是"元数据这些琐事你替我办了"，不是"你可以动我的业务代码和 LICENSE"。

**manual 项占多数时，直接建议走手动路线**，别让用户以为选了自动就万事大吉，
结果修完发现真正卡住发布的那几项一个没动。

### 第 4 步：自动修改

只改 auto 类。逐项对照 `references/fix-playbook.md` 里对应 ID 的小节——**只读命中的那几节，别整份读**。

改动前后各说清楚：

- 改**版本号**前，先跑一次 `changelog_draft.py` 看清这一版到底改了什么，
  再按改动性质决定提 major / minor / patch。**不看改动就升版本号是在瞎猜**——
  把破坏性变更发成 patch，使用者的 CI 会在半夜自动升级后炸掉。

  ```bash
  python3 <skill目录>/scripts/changelog_draft.py <pkg>
  ```

- 写 **CHANGELOG 条目**必须基于上面输出的真实 commit 和 diff。对不上任何 commit 的条目不要写。
  一条 commit 用户视角说不清是什么，就去读那个 commit 的 diff，别用"优化若干"糊过去。

- `dart format .` 跑完看一眼 `git diff --stat`，确认只有空白变化。

改完把改动列给用户看，**每条写清「改了什么 → 为什么这么改」**：

```
已改 2 处：

pubspec.yaml   version: 1.4.2 → 1.5.0
               理由：本次新增了 FlLifecycle.autoDispose()（commit a3f2e1），
                     属于向后兼容的新功能，按 semver 提 minor。

CHANGELOG.md   新增 ## 1.5.0 条目，2 行
               内容取自 a3f2e1 / 7b9c04 两个 commit，未包含其他改动。
```

然后**回到第 1 步全量重跑**，不要因为"我知道我改对了"就跳过。理由是实打实的：
改 pubspec 可能触发新的 dry-run 告警，`dart format` 可能碰到 analyze 的行长规则，
升版本号可能撞上已存在的 git tag。**没重跑过的绿灯不算绿灯。**

重跑仍有不通过项时，回到第 3 步再问一次，不要自己反复试探着修。

### 第 5 步：发布前人工确认（不可跳过）

体检 READY 之后，把这些摆出来，**等用户明确回复才继续**：

```
准备发布，请确认：

  包名      fl_state_lifecycle
  路径      packages/fl_state_lifecycle
  版本      1.4.2 → 1.5.0（线上当前最新 1.4.2）
  仓库      https://github.com/xxx/fl_state_lifecycle
  分支      main（工作区干净，HEAD = a3f2e1）
  打包      23 个文件，压缩后 41 KB
  CHANGELOG
    ## 1.5.0
    * 新增 FlLifecycle.autoDispose()……
    * 修复 ……

发布不可撤销：7 天内只能 retract（文件仍永久保留在 pub.dev），之后连 retract 都不行。
确认无误的话回复「发布」，我就执行 dart pub publish。
```

**用户没回复就一直等，不要因为"检查都过了"就自作主张执行。**
回复不是明确的肯定（"应该没问题吧"、"你看着办"）时，再确认一次而不是当成同意。

### 第 6 步：执行发布

```bash
cd <pkg> && dart pub publish --force
```

（Flutter 包同样可以用 `dart pub publish`；`flutter pub publish` 等价。）

`--force` 的作用是跳过 pub 自己的交互式 `y/N` 提问——**它不跳过任何检查**，
所有校验 dry-run 阶段已经跑过了。不加 `--force` 会卡在等 stdin 上，AI 会话里通常给不了输入。
**用 `--force` 的前提是第 5 步的人工确认已经拿到**；没拿到确认就用 `--force`，
等于把这个 skill 唯一的安全阀拆了。

未登录时这条命令会尝试打开浏览器做 OAuth 并卡住。第 1 步的 `auth` 组就是为了提前挡住这种情况；
真的卡住了就中断，让用户在自己的终端跑 `dart pub login`。

**发布失败要如实报告，不要重试。** pub 的报错（版本冲突、包名被占、权限不足、上传中断）
原因各不相同，盲目重试可能造成半个包上传成功的状态。原样贴出错误，和用户一起判断。

### 第 7 步：打 tag 并推送

发布成功后：

```bash
cd <pkg> && git tag v<version> && git push origin v<version>
```

这一步是为了让 pub.dev 上的每个版本都能追溯到具体 commit——出问题时"线上这版到底是什么代码"
是第一个要回答的问题，没有 tag 就只能靠日期猜。

monorepo 里多个包共用一个仓库时，**tag 必须带包名**：`fl_core-v1.5.0`。
这不只是整洁问题——`GIT.tag` 和 `changelog_draft.py` 都靠带包名的 tag 把这个包的历史
和隔壁包的分开。打成裸 `v1.5.0`，下次发这个包时找不到起点（会退化成取全部历史），
发隔壁包时又会被误当成它的 tag。仓库已有的 tag 用哪种写法，就跟着用哪种。

push 失败（没有推送权限、远端有更新）不影响已经发布成功的事实，如实告诉用户 tag 打在本地了、
需要他自己推。

最后一句话交代清楚：发了哪个包的哪个版本、tag 推没推、pub.dev 页面通常几分钟后生效。

**monorepo 里还有别的包要发时**，在这里主动提醒：还剩哪几个、按什么顺序、以及下一个包在发之前需要先把指向刚发布这个包的 path 依赖换成版本约束。然后回到第 0 步重新走一遍——不要在同一轮里顺手接着发下一个。

---

## 别踩的坑

**把 dry-run 通过当成可以发。** dry-run 不查版本号是否高于线上，也不查 CHANGELOG 有没有对齐。
这两项恰好是实践中最常出错的。

**替用户决定跳过检查。** "这个 info 提示无关紧要吧" —— 用户已经明确要求 info 也算不通过。
你觉得无关紧要可以说出来，但要不要放行是他的决定。

**为了让检查变绿而关规则。** 改 `analysis_options.yaml` 关掉命中的 lint、把失败的测试改成期望值、
删掉 `test/` 目录——这些都能让脚本变绿，也都是在骗人。宁可停下来说"这里过不去"。

**编 CHANGELOG。** "本次为常规更新与优化"这种条目对使用者零信息量，
而使用者正是靠它决定要不要升级。写不出来就去读 diff，读了还写不出来就问用户。

**在发布流程里顺手重写 README。** README 该用 `flutter_readme` skill 认真写，
发布途中糊出来的文档里编造的 API 会永久留在 pub.dev 上。缺 README 就停下来建议他先去补。

**版本号跟着直觉走。** "改得挺多，升个大版本吧" —— semver 是按**兼容性**分级不是按工作量。
只加 API 就是 minor，哪怕加了三十个。

---

## 文件

- `scripts/find_packages.py` —— 清点一棵树里有哪些 package，只读。给出每个包的名字/版本/类型、
  为什么某些不可发布、包之间的 path/git 依赖，以及由依赖决定的发布顺序。**第 0 步无条件先跑它**
- `scripts/preflight.py` —— 发布前体检，只读。`--only` 分组跑，避免命令超时；`--json` 输出机器可读结果
- `scripts/pubspec.py` —— pubspec 的**可信**读取。PyYAML 在场就用它并与内置严格解析器交叉验证；
  PyYAML 缺席则用内置严格解析器，但它每次运行都要先通过 25 条接受用例 + 8 条拒绝用例的自检；
  两者都不可信就抛错。另有一道旁路：`name` / `version` 用不经解析器的正则从原文直读，
  与解析结果不符即拦停。单独跑 `python3 pubspec.py [pubspec路径]` 可查看自检结果与解析产物
- `scripts/changelog_draft.py` —— 从 git 历史取上次发布以来的真实 commit / diff / 公开 API 面增删，只读，供起草 CHANGELOG
- `references/fix-playbook.md` —— 按检查项 ID 查修复方法，标注了 auto / manual。**只读命中的小节**
- `tests/` —— **维护用，正常发布流程里不需要读它，也不需要跑**。只有当你要改
  `scripts/` 下的代码时才用得上：`python3 tests/run_tests.py` 会在临时目录里造出
  假 package、假 monorepo 和假 Dart/Flutter SDK，把每个检查项的 PASS / FAIL / SKIP
  三种归宿逐一断言一遍（不需要真的装 Dart SDK）。`--only <组名>` 只跑一组，`-v` 看明细。
