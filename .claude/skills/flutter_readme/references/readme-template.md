# README 骨架与逐节写作要点

两份文档同构：`README.md`（英文）与 `README_zh.md`（中文）章节一一对应、示例代码完全相同，
只有叙述文字换语言。代码注释跟随所在文档的语言。

---

## 骨架

```markdown
# <package_name>

<一句话说清这个包是什么、给谁用。20–40 字，别写"一个强大的、优雅的…">

[![pub package](https://img.shields.io/pub/v/<name>.svg)](https://pub.dev/packages/<name>)
[![license](https://img.shields.io/badge/license-<MIT>-blue.svg)](LICENSE)

English | [中文](README_zh.md)

---

## Why <package_name>?        ← 中文版：为什么需要它

<2–4 段或一组对照。说清：不用它的时候得手写什么、容易错在哪；用了以后变成什么样。
 这一节决定读者要不要继续看，别一上来就贴 API。>

## Features                    ← 核心能力

<6–10 条，每条一句。写"能做什么"，不写"我们很优秀"。
 每条尽量对应下面某一节的锚点，方便跳转。>

## Use cases                   ← 适用场景

| 场景 | 这个包怎么帮上忙 |
|---|---|
| ... | ... |

## Compatibility               ← 环境要求与平台支持

| 项 | 要求 |
|---|---|
| Dart SDK | <照抄 pubspec environment.sdk> |
| Flutter | <照抄 pubspec environment.flutter> |
| 平台 | <按扫描结论写> |

## Installation                ← 安装

```yaml
dependencies:
  <name>: ^<pubspec 里的 version>
```

<非 pub.dev 发布的包，这里写 git / path 依赖的完整写法。>

```bash
flutter pub get
```

## Quick start                 ← 快速开始

<一个最小可运行片段：从 import 到看见效果。20–40 行，能直接粘进新工程跑起来。
 如果这个包必须先做全局注册（注册 observer、初始化单例），快速开始里必须包含这一步——
 漏了它，使用者第一次跑就是"没反应"，这是这类包最高频的求助。>

## Usage                       ← 核心能力用法（本文档的主体）

### 1. <能力名>

**什么时候用**：<一两句话，讲具体处境，不是复述 API 名字>

```dart
<完整片段：import 齐全、类型对得上、能编译>
```

**参数**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|

**注意**

- <会踩的坑、限制、和别的 API 的配合关系>

### 2. <下一个能力>
...

## API reference               ← 完整导出面速查

| 名称 | 类型 | 作用 | 详见 |
|---|---|---|---|
| FlXxx | class | ... | [用法](#1-xxx) |

<导出面里所有公开类型都要在这张表里出现，哪怕上面没展开写。
 这是"所有对外导出的 API 都有交代"这条要求的落点。>

## Dependencies                ← 第三方依赖

| 依赖 | 版本约束 | 作用 | 本包用在哪 |
|---|---|---|---|
| provider | ^6.1.5+1 | ... | lib/src/widget/fl_state_builder.dart |

<只写第三方；flutter / dart: 官方库不写。零第三方依赖时明写这一点。>

## Notes & caveats             ← 注意事项与避坑

<按主题分小节或列表。写真会出错的东西：初始化顺序、生命周期时机、
 和常见三方库的冲突、release 与 debug 的差异、什么情况下不该用这个包。>

## FAQ

<可选。真实会被问到的问题才写。>

## Example

<example/ 目录的运行方式，一两句。>

## Changelog / Contributing / License

<链接到 CHANGELOG.md、LICENSE，一两句话带过。>
```

---

## 逐节要点

### 标题区

- 徽章只放能验证的：pub 版本徽章仅在包真的发布到 pub.dev 时才放（`publish_to: none` 就别放）；
  license 徽章要和 LICENSE 文件里的实际协议一致。CI / codecov 这类徽章，仓库里没有对应配置就不要放。
- 语言切换链接放在徽章下面第一行，两份文档互指。

### Why 这一节

新手看 README 的第一个问题是"这跟我有什么关系"。直接列 API 的 README 会把人劝退。
好的写法是先描述**没有这个包时的具体麻烦**（要手写哪些样板、哪一步容易忘、出错时表现成什么样），
再说这个包把它变成了什么。素材来自源码本身：一个 mixin 封装了什么样板、
一个 assert 拦住了什么误用，都是现成的"痛点证据"。

### Compatibility

照抄 `pubspec.yaml` 的 `environment`，不要自己换算 Dart↔Flutter 的对应版本——记错版本对照表
比不写更糟。两个约束同时存在且明显不一致时（比如 Dart `^3.10.3` 配 Flutter `>=3.0.0`，
后者对应的 Dart 远低于 3.10），按更严格的那个写实际下限，并在注意事项里提一句这个不一致，
让维护者知道该修 pubspec。

平台一行只写扫描能支撑的结论：没有 `flutter.plugin`、没有 `dart:io`/`dart:ffi`/`MethodChannel`
的纯 Dart 包，写"Flutter 支持的全部平台（未使用平台特定 API）"是准确的；
写"已在 Android/iOS/Web 上验证"就是编的——你没跑过。

### Usage 主体

**选 3–6 个能力展开**，不是每个类一节。判断标准：使用者接入时一定会用到的、
或者不看说明一定会用错的。剩下的类进速查表。一个 12 个类的包写 12 节，
读者反而找不到重点。

**示例代码的来源优先级**：`example/` 里的真实代码 > 按 API 签名自己写 > 不写。
example 里的代码是编译跑通过的，改编它比自己造安全得多。自己写时逐行核对扫描输出里的签名：
类名对不对、参数名对不对、哪些是 required、泛型约束是什么。

**每个示例都要能独立粘贴运行**：import 写全，用到的自定义类型（枚举、Controller 子类）
在片段里定义出来，不要出现 `// ... 你的代码`。片段长度 15–40 行为宜。

**参数表只写公开构造函数和公开方法的参数**。标了 `@internal` / `@visibleForTesting` 的
成员不是给使用者用的，不要写进来；`@protected` 的钩子写成"在子类里覆写"，不要写成"调用它"。

### Dependencies

每个第三方依赖回答三件事：**做什么用的**（这个库本身是干嘛的）、
**版本约束**（照抄 pubspec）、**本包在哪用到它**（给出 lib 下的文件路径，扫描输出里有）。
用途不要靠包名猜——`meta` 常见于提供 `@protected`/`@internal` 注解，
但也可能只是被间接引入；扫描输出会告诉你它到底在哪些文件里被 import。

如果包再导出了别的包（`export 'package:x/x.dart';`），要单独说明：
使用者 import 本包后能直接拿到 x 的 API，不用再单独加依赖。这是使用者最容易困惑的一点。

### Notes & caveats

这一节的价值密度最高，因为它是别处查不到的。素材来源：
源码里的 `assert` 消息（它们直接告诉你什么是误用）、`@Deprecated` 标注、
dartdoc 里写了"注意/必须/仅在…"的句子、生命周期类 API 的时序约束、
以及 `CHANGELOG.md` 里 breaking change 的迁移说明。

---

## 篇幅

| 导出的公开类型数 | 目标行数 | 说明 |
|---|---|---|
| ≤ 8 | 200–350 | 不加目录 |
| 9–20 | 350–550 | 加目录 |
| > 20 | ≤ 700 | 加目录；Usage 只展开最核心的，其余靠速查表 |

超长 README 的下场是没人读完。宁可把细节留给 dartdoc 和 example，
README 负责"让人在十分钟内接入并知道去哪找更多"。
