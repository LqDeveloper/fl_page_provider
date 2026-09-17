#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flutter_pub_publish 发布前体检。

只读：不修改被检查 package 的任何文件，也不执行任何发布动作。
用法：
    python3 preflight.py <pkg路径> [--only meta,git,auth,analyze,format,test,dryrun] [--json out.json]

分组（按耗时排）：
    meta     pubspec / 版本 / CHANGELOG / 文档  —— 秒级，含一次 pub.dev 网络查询
    git      仓库状态、tag 冲突                —— 秒级
    auth     pub.dev 登录态                    —— 秒级
    format   dart format 检查                  —— 秒级到十几秒
    analyze  dart analyze                      —— 十几秒到一分钟
    test     flutter test / dart test          —— 可能几分钟
    dryrun   dart pub publish --dry-run        —— 十几秒到一分钟

默认跑全部。宿主对单条命令有时限时，用 --only 分批跑。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import pubspec as _pubspec
except ImportError:
    sys.stderr.write(
        "致命：同目录下找不到 pubspec.py。\n"
        "这个 skill 必须整个目录 cp -r 安装，只拷 preflight.py 会让 pubspec 解析\n"
        "失去可信性保证，而那正是这个脚本存在的意义。请重装完整目录。\n")
    sys.exit(2)

# ---------------------------------------------------------------- 结果模型

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
ICON = {PASS: "✓", FAIL: "✗", WARN: "!", SKIP: "-"}

# fix 取值：auto = 允许 AI 自动改（元数据/格式层）；manual = 必须人来改；none = 无需修
RESULTS = []


def add(cid, title, status, detail="", fix="none", hint=""):
    RESULTS.append({
        "id": cid, "title": title, "status": status,
        "detail": detail, "fix": fix, "hint": hint,
    })


def run(cmd, cwd=None, timeout=180):
    """执行命令，返回 (returncode, stdout+stderr)。命令不存在或超时返回 rc=None。"""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return None, "命令不存在: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return None, "超时(%ss): %s" % (timeout, " ".join(cmd))


def tail(text, n=25):
    lines = [l for l in (text or "").strip().splitlines() if l.strip()]
    return "\n".join(lines[-n:])


# ---------------------------------------------------------------- pubspec 解析

def parse_pubspec(path):
    """解析 pubspec.yaml。读不可信就抛 PubspecParseError，绝不返回可疑结果。

    实现在同目录的 pubspec.py：PyYAML 在场就用它并与内置严格解析器交叉验证；
    PyYAML 缺席则用内置严格解析器，但它必须先当场通过自检语料；两者都不可信
    就抛错。**这里没有"降级继续"这条路**——发布决策不能建立在一个可能读错的
    结果上，读不出来停下来的代价是重跑一次，读错了的代价是发错版本。
    """
    data, meta = _pubspec.load(path)
    return data, meta


VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.\-]+))?(?:\+([0-9A-Za-z.\-]+))?$")


def semver_key(v):
    """返回可比较的 key；不合法返回 None。预发布版本排在同号正式版之前。"""
    m = VER_RE.match((v or "").strip())
    if not m:
        return None
    major, minor, patch, pre = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
    if pre is None:
        return (major, minor, patch, 1, ())
    parts = []
    for p in pre.split("."):
        parts.append((0, int(p), "") if p.isdigit() else (1, 0, p))
    return (major, minor, patch, 0, tuple(parts))


# ---------------------------------------------------------------- meta 检查

PLACEHOLDER_RE = re.compile(
    r"TODO|FIXME|Add a short description|A new Flutter (project|package|plugin)"
    r"|starting point for a Flutter|<!--\s*replace", re.I)


def check_meta(pkg, net=True):
    ps_path = os.path.join(pkg, "pubspec.yaml")
    if not os.path.isfile(ps_path):
        add("PKG.pubspec", "pubspec.yaml 存在", FAIL,
            "%s 下没有 pubspec.yaml" % pkg, "manual",
            "确认这个目录是不是 package 根目录")
        return None
    try:
        ps, pmeta = parse_pubspec(ps_path)
    except _pubspec.PubspecParseError as e:
        add("PKG.pubspec", "pubspec.yaml 存在", PASS, ps_path)
        add("PKG.parser", "pubspec 可信解析", FAIL, str(e), "manual",
            "在读懂 pubspec 之前，下面所有元数据检查都做不了——它们全都依赖这份文件。"
            "装 PyYAML（pip3 install pyyaml）后重跑，或按报错简化 pubspec 的写法")
        return None
    add("PKG.pubspec", "pubspec.yaml 存在", PASS, ps_path)
    add("PKG.parser", "pubspec 可信解析", PASS, pmeta["detail"])

    name = str(ps.get("name") or "").strip()
    version = str(ps.get("version") or "").strip()
    desc = str(ps.get("description") or "").strip()

    # publish_to
    if str(ps.get("publish_to") or "").strip() in ("none", "'none'", '"none"'):
        add("PKG.publish_to", "publish_to 未被禁用", FAIL,
            "pubspec 里有 publish_to: none，pub 会拒绝发布", "manual",
            "确认这个包本来就是要发到 pub.dev 的；是就删掉这一行，不是就别发")
    else:
        add("PKG.publish_to", "publish_to 未被禁用", PASS)

    # name
    if not name:
        add("PKG.name", "包名", FAIL, "pubspec 缺 name", "manual", "")
    elif not re.match(r"^[a-z][a-z0-9_]*$", name):
        add("PKG.name", "包名", FAIL,
            "name=%r 不符合 pub 命名规范（小写字母/数字/下划线，字母开头）" % name,
            "manual", "改名会改变包身份，必须人来定")
    else:
        add("PKG.name", "包名", PASS, name)

    # description 长度：pub.dev 评分要求 60–180 字符
    if not desc:
        add("PKG.description", "description 长度 60–180", FAIL,
            "pubspec 缺 description", "auto", "按包的真实功能写一句 60–180 字符的英文描述")
    elif not (60 <= len(desc) <= 180):
        add("PKG.description", "description 长度 60–180", FAIL,
            "当前 %d 字符：%s" % (len(desc), desc[:120]), "auto",
            "扩写或精简到 60–180 字符；内容必须是包真实做的事，不要为凑长度加废话")
    else:
        add("PKG.description", "description 长度 60–180", PASS, "%d 字符" % len(desc))

    # repository / homepage
    repo = str(ps.get("repository") or "").strip()
    home = str(ps.get("homepage") or "").strip()
    if repo:
        add("PKG.repository", "repository 字段", PASS, repo)
    elif home:
        add("PKG.repository", "repository 字段", FAIL,
            "只有 homepage=%s，缺 repository（pub.dev 评分单独看 repository）" % home,
            "auto", "从 git remote 取仓库地址填进去")
    else:
        add("PKG.repository", "repository 字段", FAIL,
            "既无 repository 也无 homepage", "auto", "从 git remote 取仓库地址填进去")

    # environment
    env = ps.get("environment") if isinstance(ps.get("environment"), dict) else {}
    if env.get("sdk"):
        add("PKG.env_sdk", "environment.sdk 约束", PASS, str(env.get("sdk")))
    else:
        add("PKG.env_sdk", "environment.sdk 约束", FAIL,
            "缺 environment.sdk，pub 无法判断兼容性", "manual",
            "SDK 下界要按包实际用到的语言特性定，猜一个会误导使用者")

    # 依赖形态：path/git 依赖发不出去
    bad = []
    for block in ("dependencies", "dev_dependencies"):
        deps = ps.get(block)
        if not isinstance(deps, dict):
            continue
        for dname, spec in deps.items():
            if isinstance(spec, dict) and ("path" in spec or "git" in spec):
                kind = "path" if "path" in spec else "git"
                bad.append("%s.%s (%s)" % (block, dname, kind))
    if bad:
        add("DEP.path_git", "无 path/git 依赖", FAIL,
            "；".join(bad), "manual",
            "这些依赖必须先各自发到 pub.dev 再换成版本号约束——顺序错了发出去的包装不上")
    else:
        add("DEP.path_git", "无 path/git 依赖", PASS)

    # 版本号合法性
    if semver_key(version) is None:
        add("VER.semver", "版本号合法", FAIL,
            "version=%r 不是合法 semver" % version, "auto", "改成 x.y.z 形式")
    else:
        add("VER.semver", "版本号合法", PASS, version)

    # 与 pub.dev 线上版本比对
    online = None
    if not name or semver_key(version) is None:
        add("VER.vs_pubdev", "版本号高于线上已发布版本", SKIP, "包名或版本号无效，无法比对")
    elif not net:
        add("VER.vs_pubdev", "版本号高于线上已发布版本", SKIP, "--no-net 指定，跳过")
    else:
        try:
            req = urllib.request.Request(
                "https://pub.dev/api/packages/%s" % name,
                headers={"Accept": "application/json", "User-Agent": "flutter-pub-publish-preflight"})
            with urllib.request.urlopen(req, timeout=20) as r:
                info = json.loads(r.read().decode("utf-8"))
            online = str(((info.get("latest") or {}).get("version")) or "").strip()
            allv = {str(v.get("version")).strip() for v in (info.get("versions") or [])}
            if version in allv:
                add("VER.vs_pubdev", "版本号高于线上已发布版本", FAIL,
                    "%s 已经发布过（线上最新 %s）" % (version, online), "auto",
                    "按改动性质提升版本号：破坏性→major，新功能→minor，修复→patch")
            elif online and semver_key(online) and semver_key(version) <= semver_key(online):
                add("VER.vs_pubdev", "版本号高于线上已发布版本", FAIL,
                    "本地 %s 不高于线上最新 %s" % (version, online), "auto",
                    "提升到高于 %s 的版本号" % online)
            else:
                add("VER.vs_pubdev", "版本号高于线上已发布版本", PASS,
                    "本地 %s > 线上 %s" % (version, online or "(无)"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                add("VER.vs_pubdev", "版本号高于线上已发布版本", PASS,
                    "pub.dev 上没有 %s，这是首次发布" % name)
            else:
                add("VER.vs_pubdev", "版本号高于线上已发布版本", SKIP,
                    "pub.dev 返回 HTTP %s" % e.code, "manual",
                    "网络受限时，人工到 pub.dev/packages/%s 确认线上版本" % name)
        except Exception as e:
            add("VER.vs_pubdev", "版本号高于线上已发布版本", SKIP,
                "查询失败：%s" % e, "manual",
                "网络受限时，人工到 pub.dev/packages/%s 确认线上版本" % name)

    # CHANGELOG
    cl_path = None
    for cand in ("CHANGELOG.md", "CHANGELOG"):
        if os.path.isfile(os.path.join(pkg, cand)):
            cl_path = os.path.join(pkg, cand)
            break
    if not cl_path:
        add("DOC.changelog", "CHANGELOG 存在", FAIL, "没有 CHANGELOG.md", "auto",
            "用 changelog_draft.py 从 git 历史取真实改动后新建")
        add("VER.changelog_match", "CHANGELOG 顶部版本 == pubspec 版本", SKIP, "无 CHANGELOG")
    else:
        add("DOC.changelog", "CHANGELOG 存在", PASS, os.path.basename(cl_path))
        cl = open(cl_path, encoding="utf-8").read()
        m = re.search(r"^\s{0,3}#{1,3}\s*\[?v?(\d+\.\d+\.\d+[0-9A-Za-z.\-+]*)\]?",
                      cl, re.M)
        top = m.group(1) if m else None
        if top is None:
            add("VER.changelog_match", "CHANGELOG 顶部版本 == pubspec 版本", FAIL,
                "CHANGELOG 里找不到形如 `## 1.2.3` 的版本标题", "auto",
                "补一个标准版本标题；pub.dev 靠它渲染版本说明")
        elif top != version:
            add("VER.changelog_match", "CHANGELOG 顶部版本 == pubspec 版本", FAIL,
                "CHANGELOG 顶部是 %s，pubspec 是 %s" % (top, version), "auto",
                "先定哪个才是要发的版本，再把另一个对齐——别默认改 CHANGELOG")
        else:
            # 顶部条目下有没有实际内容
            body = cl[m.end():]
            nxt = re.search(r"^\s{0,3}#{1,3}\s", body, re.M)
            entry = body[:nxt.start()] if nxt else body
            if not entry.strip():
                add("VER.changelog_match", "CHANGELOG 顶部版本 == pubspec 版本", FAIL,
                    "%s 的条目下是空的" % version, "auto",
                    "用 changelog_draft.py 取真实改动后填写，不要编")
            else:
                add("VER.changelog_match", "CHANGELOG 顶部版本 == pubspec 版本", PASS,
                    "%s，条目 %d 行" % (version, len(entry.strip().splitlines())))

    # README / LICENSE / example
    rd = os.path.join(pkg, "README.md")
    if not os.path.isfile(rd):
        add("DOC.readme", "README.md 齐备", FAIL, "缺 README.md", "manual",
            "README 是包的门面，内容要基于真实 API——建议用 flutter_readme skill 生成")
    else:
        rtxt = open(rd, encoding="utf-8").read()
        if len(rtxt.strip()) < 200:
            add("DOC.readme", "README.md 齐备", FAIL,
                "只有 %d 字符，过于简陋" % len(rtxt.strip()), "manual",
                "建议用 flutter_readme skill 生成")
        elif PLACEHOLDER_RE.search(rtxt):
            add("DOC.readme", "README.md 齐备", FAIL,
                "含脚手架占位文字（TODO / A new Flutter package 之类）", "manual",
                "把 flutter create 生成的模板话术换成真实内容")
        else:
            add("DOC.readme", "README.md 齐备", PASS, "%d 字符" % len(rtxt.strip()))

    lic = [f for f in ("LICENSE", "LICENSE.md", "LICENSE.txt")
           if os.path.isfile(os.path.join(pkg, f))]
    if not lic:
        add("DOC.license", "LICENSE 存在", FAIL, "缺 LICENSE 文件", "manual",
            "选哪个开源协议是法律决定，必须由你来选，AI 不代选")
    elif os.path.getsize(os.path.join(pkg, lic[0])) < 100:
        add("DOC.license", "LICENSE 存在", FAIL, "%s 内容过短" % lic[0], "manual", "")
    else:
        add("DOC.license", "LICENSE 存在", PASS, lic[0])

    ex = os.path.join(pkg, "example")
    has_ex = os.path.isdir(ex) and any(
        f.endswith(".dart") for _, _, fs in os.walk(ex) for f in fs)
    if has_ex:
        add("DOC.example", "example 存在", PASS)
    else:
        add("DOC.example", "example 存在", FAIL,
            "没有 example/ 或里面没有 .dart 文件", "manual",
            "example 是真实可运行代码，必须由懂这个包的人写，AI 生成的示例可能跑不通")

    return {"name": name, "version": version, "online": online, "pubspec": ps}


# ---------------------------------------------------------------- git / auth

BARE_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+")


def _tag_forms(name, version):
    """一个包在 monorepo 里可能用的 tag 写法。melos 的默认是 `<名>-v<版本>`。"""
    if not name:
        return []
    return ["%s-v%s" % (name, version), "%s-%s" % (name, version),
            "%s/v%s" % (name, version), "%s_v%s" % (name, version),
            "%s@%s" % (name, version), "%s@v%s" % (name, version)]


def check_git(pkg, version, name=""):
    """git 相关检查。**只看这个 package 目录下的内容。**

    git 命令默认作用于整个仓库而不是当前子目录，这在 monorepo 里会误伤：
    隔壁包有未提交改动，会让这个包的 `GIT.clean` 挂掉；隔壁包的 `v1.2.0` tag，
    会让这个包误以为版本号发过了。两者都不影响这次要发的东西，
    却会让人以为自己的包有问题——所以这里一律显式限定范围，并在输出里写明限定了什么。
    """
    root_rc, root_out = run(["git", "rev-parse", "--show-toplevel"], cwd=pkg, timeout=30)
    if root_rc != 0:
        add("GIT.repo", "在 git 仓库内", WARN,
            "不是 git 仓库，发出去的版本无法追溯到 commit", "manual",
            "建议先 git init 并提交；不用 git 的话可以忽略这条")
        add("GIT.clean", "工作区干净", SKIP, "非 git 仓库")
        add("GIT.tag", "版本 tag 未被占用", SKIP, "非 git 仓库")
        return
    root = root_out.strip()
    rel = os.path.relpath(os.path.abspath(pkg), root)
    in_subdir = rel not in (".", "")
    add("GIT.repo", "在 git 仓库内", PASS,
        root + ("（本包位于 %s，以下检查只针对这个子目录）" % rel if in_subdir else ""))

    _, br = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=pkg, timeout=30)
    br = br.strip()

    # 只看本包目录下的改动。`-- <rel>` 是关键，没有它 git 会报整个仓库的状态。
    scope = ["--", rel] if in_subdir else []
    rc, st = run(["git", "status", "--porcelain"] + scope, cwd=root, timeout=60)
    where = "（仅 %s 下）" % rel if in_subdir else ""
    if st.strip():
        n = len(st.strip().splitlines())
        add("GIT.clean", "工作区干净", FAIL,
            "分支 %s 下本包有 %d 个未提交改动%s：\n%s" % (br, n, where, tail(st, 10)),
            "manual", "提交哪些改动、写什么 commit message 是你的决定，AI 不代提交")
    else:
        add("GIT.clean", "工作区干净", PASS, "分支 %s%s" % (br, where))

    if not version:
        add("GIT.tag", "版本 tag 未被占用", SKIP,
            "版本号未知（pubspec 未解析或解析失败），无法比对", "manual",
            "先让 pubspec 能被可信解析")
        return

    _, tags = run(["git", "tag", "--list"], cwd=root, timeout=30)
    existing = set(tags.split())
    scoped = _tag_forms(name, version)
    bare = ["v%s" % version, version]

    if not in_subdir:
        # 包就在仓库根上，仓库里的 tag 都是它的，两种写法都算
        checked = bare + scoped
        hit = [t for t in checked if t in existing]
        note = ""
    else:
        # 子目录包：只有带包名的 tag 能确定属于它。裸 v1.2.0 可能是隔壁包的，
        # 拿它来判定这个包"发过了"就是在用别的包的状态给这个包定罪。
        checked = scoped
        hit = [t for t in checked if t in existing]
        bare_hit = [t for t in bare if t in existing]
        note = ""
        if bare_hit and not hit:
            owner = ""
            rc2, o = run(["git", "log", "-1", "--pretty=format:%h %s", bare_hit[0]],
                         cwd=root, timeout=30)
            if rc2 == 0 and o.strip():
                owner = "（%s）" % o.strip()[:70]
            note = ("\n仓库里另有裸 tag %s%s，但本包在子目录 %s 下，"
                    "该 tag 未必属于本包，故不作判定。" % (bare_hit[0], owner, rel))

    if not name and in_subdir:
        add("GIT.tag", "版本 tag 未被占用", SKIP,
            "包名未知，无法构造本包专属的 tag 名（子目录包不能用裸 v%s 判定）" % version,
            "manual", "先让 pubspec 能被可信解析")
        return

    if hit:
        add("GIT.tag", "版本 tag 未被占用", FAIL,
            "tag %s 已存在——这个版本号很可能已经发过了" % hit[0], "manual",
            "先确认是不是忘了升版本号")
    else:
        add("GIT.tag", "版本 tag 未被占用", PASS,
            "已查 %s，均可用%s" % (" / ".join(checked[:3]) +
                                 ("…" if len(checked) > 3 else ""), note))


def check_auth():
    """检查 pub.dev 登录态。未登录时发布会拉起浏览器 OAuth，在无人值守会话里会挂死。"""
    paths = []
    for env in ("PUB_CACHE",):
        if os.environ.get(env):
            paths.append(os.path.join(os.environ[env], "credentials.json"))
    home = os.path.expanduser("~")
    paths += [
        os.path.join(home, ".pub-cache", "credentials.json"),
        os.path.join(home, "Library", "Application Support", "dart", "pub-credentials.json"),
        os.path.join(home, ".config", "dart", "pub-credentials.json"),
        os.path.join(os.environ.get("APPDATA", ""), "dart", "pub-credentials.json"),
    ]
    found = [p for p in paths if p and os.path.isfile(p)]
    if found:
        add("AUTH.pub", "pub.dev 已登录", PASS, found[0])
    else:
        add("AUTH.pub", "pub.dev 已登录", FAIL,
            "找不到 pub 凭据文件", "manual",
            "在你自己的终端跑 `dart pub login` 完成浏览器授权——这一步必须你本人做，"
            "AI 会话里跑会卡在等待浏览器回调")


# ---------------------------------------------------------------- 工具链检查

def sdk(pkg):
    """返回 ('flutter'|'dart', 可执行文件)。Flutter 包用 flutter，纯 Dart 包用 dart。

    这里读 pubspec 的失败是可以容忍的：选错 SDK 的后果是命令跑不起来（会被
    上层记成 SKIP），而不是给出一个错误的结论。真正不能容忍的是 check_meta
    里那次——那次的结果直接决定发不发。
    """
    ps_path = os.path.join(pkg, "pubspec.yaml")
    is_flutter = False
    if os.path.isfile(ps_path):
        try:
            ps, _ = parse_pubspec(ps_path)
            deps = ps.get("dependencies")
            is_flutter = isinstance(deps, dict) and "flutter" in deps
        except _pubspec.PubspecParseError:
            # 读不出来就按"有 flutter 就用 flutter"的保守方式猜；
            # check_meta 已经就同一份文件报了 FAIL，不在这里重复报。
            is_flutter = bool(shutil.which("flutter"))
    if is_flutter and shutil.which("flutter"):
        return "flutter", "flutter"
    if shutil.which("dart"):
        return "dart", "dart"
    if shutil.which("flutter"):
        return "flutter", "flutter"
    return None, None


def ensure_pub_get(pkg):
    if os.path.isfile(os.path.join(pkg, ".dart_tool", "package_config.json")):
        return True
    kind, exe = sdk(pkg)
    if not exe:
        return False
    rc, _ = run([exe, "pub", "get"], cwd=pkg, timeout=180)
    return rc == 0


def dart_exe():
    """定位 `dart` 可执行文件。

    `format` 和 `analyze --format=machine` 都只有 `dart` 有：`flutter format`
    早就从 Flutter CLI 里移除了（Flutter 2.5 弃用，之后删除），`flutter analyze`
    也不认 `--format=machine`。所以这两项一律走 dart，即使包本身是 Flutter 包。

    PATH 上没有 dart 时，去 flutter 旁边找——Flutter SDK 自带 dart，
    两者就在同一个 bin 目录下。找不到才认输。
    """
    d = shutil.which("dart")
    if d:
        return d
    f = shutil.which("flutter")
    if f:
        cand = os.path.join(os.path.dirname(os.path.realpath(f)), "dart")
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


CHANGED_RE = re.compile(r"^Changed\s+(.+)$")


def check_format(pkg):
    dart = dart_exe()
    if not dart:
        add("CODE.format", "dart format 一致", SKIP,
            "PATH 上没有 dart，flutter 旁边也没找到", "manual",
            "装 Dart SDK，或把 Flutter 的 bin 目录加进 PATH")
        return

    rc, out = run([dart, "format", "--output=none", "--set-exit-if-changed", "."],
                  cwd=pkg, timeout=180)
    if rc is None:
        add("CODE.format", "dart format 一致", SKIP, tail(out, 5), "manual",
            "format 跑不完不能当作通过")
        return

    changed = [m.group(1) for m in
               (CHANGED_RE.match(l.strip()) for l in out.splitlines()) if m]

    if rc == 0 and not changed:
        add("CODE.format", "dart format 一致", PASS)
    elif changed:
        add("CODE.format", "dart format 一致", FAIL,
            "%d 个文件格式不一致：\n%s" % (len(changed), tail("\n".join(changed), 10)),
            "auto", "跑 `dart format .`——纯格式化，不改语义")
    elif rc == 0:
        # 退出码 0 却打出了别的东西，罕见；当通过但把原文带出来供人判断
        add("CODE.format", "dart format 一致", PASS, tail(out, 3))
    else:
        # 非零退出但一个 Changed 都没有 —— 这不是"格式不一致"，是命令本身出错了
        # （语法错误让 formatter 解析失败、SDK 版本不对、目录里没有 dart 文件……）。
        # 旧版本在这里报"0 个文件格式不一致"并标成可自动修，于是 AI 会去跑
        # `dart format .` 修一个根本不存在的格式问题，真正的错误被吞掉。
        add("CODE.format", "dart format 一致", SKIP,
            "dart format 退出码 %s，但没有报告任何待格式化文件——这不是格式问题，"
            "是命令没跑成：\n%s" % (rc, tail(out, 12)), "manual",
            "先看上面的报错。常见原因是某个 .dart 文件有语法错误导致 formatter 解析失败，"
            "那种情况 analyze 也会报，先修语法")


def check_analyze(pkg):
    # 只能用 dart：`--format=machine` 是 dart analyze 的选项，flutter analyze 不认。
    # 拿 flutter 去跑会得到一个参数错误，而下面的计数逻辑从那种输出里数不出任何
    # 问题，于是 0/0/0 —— 一个凭空捏造的"零问题"。
    dart = dart_exe()
    if not dart:
        add("CODE.analyze", "dart analyze 零问题", SKIP,
            "PATH 上没有 dart，flutter 旁边也没找到", "manual",
            "装 Dart SDK，或把 Flutter 的 bin 目录加进 PATH")
        return
    ensure_pub_get(pkg)
    rc, out = run([dart, "analyze", "--format=machine", "."], cwd=pkg, timeout=300)
    if rc is None:
        add("CODE.analyze", "dart analyze 零问题", SKIP, tail(out, 5), "manual",
            "analyze 跑不起来时不能当作通过——先解决环境问题")
        return
    counts = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    samples = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) >= 8 and parts[0] in counts:
            counts[parts[0]] += 1
            if len(samples) < 12:
                fp = parts[3]
                try:
                    r = os.path.relpath(fp, pkg)
                    # 诊断指向包外时 relpath 会给出一长串 ../../..，反而看不懂，
                    # 那种情况保留原路径
                    fp = r if not r.startswith("..") else fp
                except ValueError:      # Windows 上跨盘符
                    pass
                samples.append("%s %s:%s  %s (%s)" % (
                    parts[0], fp, parts[4], parts[7], parts[2]))
    total = sum(counts.values())
    detail = "ERROR %d / WARNING %d / INFO %d" % (counts["ERROR"], counts["WARNING"], counts["INFO"])
    if total == 0 and rc != 0:
        # analyze 用非零退出码表示"有问题"，可我们一条都没解析出来——说明它根本
        # 没在做分析（参数不对、SDK 装坏了、pub get 没成功）。此时报"零问题"
        # 就是拿一个没跑起来的命令当通过凭证，恰恰是最危险的假绿灯。
        add("CODE.analyze", "dart analyze 零问题", SKIP,
            "analyze 退出码 %s，却解析不出任何诊断行——命令没跑成：\n%s"
            % (rc, tail(out, 12)), "manual",
            "先解决环境问题（常见：pub get 没成功、SDK 版本不匹配），再重跑")
    elif total == 0:
        add("CODE.analyze", "dart analyze 零问题", PASS, detail)
    else:
        add("CODE.analyze", "dart analyze 零问题", FAIL,
            detail + "\n" + "\n".join(samples), "manual",
            "analyze 命中的是 lib 下的实际代码。`dart fix --apply` 能自动修一部分，"
            "但它会改业务代码，跑完必须由你复核 diff——本 skill 不自动执行")


def check_test(pkg):
    tdir = os.path.join(pkg, "test")
    if not os.path.isdir(tdir) or not any(
            f.endswith("_test.dart") for _, _, fs in os.walk(tdir) for f in fs):
        add("CODE.test", "测试全部通过", WARN, "没有 test/ 或没有 *_test.dart", "manual",
            "无测试不阻断发布，但使用者无从判断这个包是否可靠")
        return
    kind, exe = sdk(pkg)
    if not exe:
        add("CODE.test", "测试全部通过", SKIP, "找不到 dart/flutter SDK")
        return
    ensure_pub_get(pkg)
    rc, out = run([exe, "test"], cwd=pkg, timeout=900)
    if rc is None:
        add("CODE.test", "测试全部通过", SKIP, tail(out, 8), "manual",
            "测试跑不完不能当作通过")
    elif rc == 0:
        summary = [l for l in out.splitlines() if "All tests passed" in l or re.search(r"\+\d+", l)]
        add("CODE.test", "测试全部通过", PASS, tail("\n".join(summary), 3))
    else:
        add("CODE.test", "测试全部通过", FAIL, tail(out, 30), "manual",
            "测试失败说明代码有真实缺陷。改测试让它变绿不是修复，必须先搞清为什么挂")


def _crosscheck_identity(pkg, out):
    """拿 pub 自己打印的 `Publishing <name> <version>` 核对我们解析出的身份。

    这是唯一不经过任何 YAML 解析器的权威来源——pub 就是要用这个名字和版本号
    上传。两边不一致意味着我们前面所有基于 pubspec 的判断（版本比对、tag 冲突）
    都对错了对象，此时必须拦停。
    """
    m = re.search(r"Publishing\s+(\S+)\s+(\S+)\s+to\s+http", out)
    if not m:
        return
    pub_name, pub_ver = m.group(1), m.group(2)
    try:
        ps, _ = parse_pubspec(os.path.join(pkg, "pubspec.yaml"))
    except _pubspec.PubspecParseError:
        add("PUB.identity", "包身份与 pub 自述一致", SKIP,
            "pubspec 未能可信解析，无法交叉核对", "manual", "")
        return
    our_name = str(ps.get("name") or "").strip()
    our_ver = str(ps.get("version") or "").strip()
    if (pub_name, pub_ver) == (our_name, our_ver):
        add("PUB.identity", "包身份与 pub 自述一致", PASS,
            "%s %s" % (pub_name, pub_ver))
    else:
        add("PUB.identity", "包身份与 pub 自述一致", FAIL,
            "pub 说要发 %s %s，我们从 pubspec 读到的是 %s %s"
            % (pub_name, pub_ver, our_name, our_ver), "manual",
            "两边对不上说明前面的版本比对和 tag 检查针对的不是同一个东西，"
            "在查清原因前不要发布")


def check_dryrun(pkg):
    kind, exe = sdk(pkg)
    if not exe:
        add("PUB.dry_run", "pub publish --dry-run 通过", SKIP, "找不到 dart/flutter SDK")
        return
    ensure_pub_get(pkg)
    rc, out = run([exe, "pub", "publish", "--dry-run"], cwd=pkg, timeout=300)
    _crosscheck_identity(pkg, out)
    if rc is None:
        add("PUB.dry_run", "pub publish --dry-run 通过", SKIP, tail(out, 8), "manual",
            "dry-run 是权威检查，跑不了就不能发")
        return
    warn_n = len(re.findall(r"^\s*(Warning|Package validation found)", out, re.M))
    if rc == 0 and "0 warnings" in out.replace("no warnings", "0 warnings"):
        add("PUB.dry_run", "pub publish --dry-run 通过", PASS, tail(out, 6))
    elif rc == 0 and not re.search(r"warning", out, re.I):
        add("PUB.dry_run", "pub publish --dry-run 通过", PASS, tail(out, 6))
    elif rc == 0:
        add("PUB.dry_run", "pub publish --dry-run 通过", FAIL,
            "退出码 0 但有告警：\n" + tail(out, 30), "manual",
            "逐条看告警内容，多数是 pubspec 字段或打包文件问题")
    else:
        add("PUB.dry_run", "pub publish --dry-run 通过", FAIL, tail(out, 40), "manual",
            "这是 pub 自己的裁决，它说不行就是不行")

    # 打包体积与文件数：dry-run 输出里带文件清单
    m = re.search(r"Total compressed archive size:\s*([\d.]+\s*\w+)", out)
    if m:
        add("PUB.size", "打包体积", PASS, m.group(1))


# ---------------------------------------------------------------- 输出

def report(pkg, as_json=None):
    order = {FAIL: 0, WARN: 1, SKIP: 2, PASS: 3}
    print("\n" + "=" * 72)
    # 每次输出都复述一遍"体检的到底是谁"。分组跑时会有好几段输出，中间还夹着
    # 自动修改和重跑；只有路径的话，很容易在 monorepo 里把 A 包的体检结果
    # 当成 B 包的通过凭证。名字和版本号写在最上面，对不上一眼就能看出来。
    ident = ""
    try:
        _ps, _ = parse_pubspec(os.path.join(pkg, "pubspec.yaml"))
        _n = str(_ps.get("name") or "").strip()
        _v = str(_ps.get("version") or "").strip()
        if _n:
            ident = "  ——  %s %s" % (_n, _v or "(版本未知)")
    except Exception:  # noqa  报告头不该因为读不出身份而崩溃，PKG.parser 已经报过了
        ident = "  ——  (包身份未知：pubspec 未能可信解析)"
    print("发布前体检：%s%s" % (os.path.abspath(pkg), ident))
    print("=" * 72)
    for r in RESULTS:
        print("  %s [%-18s] %s" % (ICON[r["status"]], r["id"], r["title"]))
        if r["detail"]:
            for line in r["detail"].splitlines():
                print("        %s" % line)
        if r["status"] in (FAIL, WARN) and r["hint"]:
            print("        → 修复：%s" % r["hint"])
    fails = [r for r in RESULTS if r["status"] == FAIL]
    warns = [r for r in RESULTS if r["status"] == WARN]
    skips = [r for r in RESULTS if r["status"] == SKIP]
    auto = [r for r in fails if r["fix"] == "auto"]
    manual = [r for r in fails if r["fix"] != "auto"]

    print("\n" + "-" * 72)
    print("结论：%d 项不通过 / %d 项告警 / %d 项跳过 / %d 项通过"
          % (len(fails), len(warns), len(skips), len(RESULTS) - len(fails) - len(warns) - len(skips)))
    if auto:
        print("  可由 AI 自动修（元数据与格式层）：%s" % ", ".join(r["id"] for r in auto))
    if manual:
        print("  必须人工处理：%s" % ", ".join(r["id"] for r in manual))
    if skips:
        print("  ⚠ 跳过的项不等于通过：%s" % ", ".join(r["id"] for r in skips))
    print("READY" if not fails and not skips else "NOT_READY")
    print("-" * 72)

    if as_json:
        with open(as_json, "w", encoding="utf-8") as f:
            json.dump({"package": os.path.abspath(pkg), "results": RESULTS,
                       "fail": len(fails), "warn": len(warns), "skip": len(skips),
                       "ready": not fails and not skips}, f, ensure_ascii=False, indent=2)
        print("JSON 已写入 %s" % as_json)
    return 1 if (fails or skips) else 0


GROUPS = ["meta", "git", "auth", "format", "analyze", "test", "dryrun"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pkg")
    ap.add_argument("--only", default="all",
                    help="逗号分隔：%s" % ",".join(GROUPS))
    ap.add_argument("--json", default=None)
    ap.add_argument("--no-net", action="store_true", help="跳过 pub.dev 版本查询")
    a = ap.parse_args()

    pkg = os.path.abspath(a.pkg)
    only = GROUPS if a.only == "all" else [g.strip() for g in a.only.split(",")]
    bad = [g for g in only if g not in GROUPS]
    if bad:
        print("未知分组：%s；可选 %s" % (bad, GROUPS)); return 2

    info = None
    if "meta" in only:
        info = check_meta(pkg, net=not a.no_net)
        if info is None:
            return report(pkg, a.json)
    # 单独跑 --only git 时没经过 check_meta，得自己拿版本号。这个值决定 GIT.tag
    # 检查的成败，所以读不可信就置空，让下游 SKIP，而不是拿一个可疑值去比对。
    version = (info or {}).get("version") or ""
    if not version:
        ps_path = os.path.join(pkg, "pubspec.yaml")
        if os.path.isfile(ps_path):
            try:
                version = str(parse_pubspec(ps_path)[0].get("version") or "").strip()
            except _pubspec.PubspecParseError as e:
                if "meta" not in only:
                    add("PKG.parser", "pubspec 可信解析", FAIL, str(e), "manual",
                        "版本号读不出来，依赖它的检查只能跳过。"
                        "装 PyYAML（pip3 install pyyaml）后重跑")
                version = ""

    if "git" in only:
        pkg_name = (info or {}).get("name") or ""
        if not pkg_name:
            try:
                pkg_name = str(parse_pubspec(
                    os.path.join(pkg, "pubspec.yaml"))[0].get("name") or "").strip()
            except Exception:  # noqa  读不出来时 check_git 会据此 SKIP tag 检查
                pkg_name = ""
        check_git(pkg, version, pkg_name)
    if "auth" in only:
        check_auth()
    if "format" in only:
        check_format(pkg)
    if "analyze" in only:
        check_analyze(pkg)
    if "test" in only:
        check_test(pkg)
    if "dryrun" in only:
        check_dryrun(pkg)
    return report(pkg, a.json)


if __name__ == "__main__":
    sys.exit(main())
