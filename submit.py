"""submit — 一键把 ENGR1010J 的作业提交到 Gitea、触发 JOJ3、发 Release。

用法:
    submit <lab> [<task>] [feat|fix] [noheader]
        submit lab1 t1        -> 只交 t1:            feat(lab1): t1 ok[joj]
        submit lab1 t3 fix    -> 只交 t3:            fix(lab1): t3 ok[joj]
        submit lab1           -> 交 lab1 下所有题:   feat(lab1): t1 t2 t3 t4 ok[joj]
        submit lab1 fix       -> 同上,类型为 fix
        submit lab1 t1 noheader  -> 不自动补姓名学号注释
    submit release <lab>      在 Gitea 上发 Release(tag 与标题都是 <lab>),需要确认
    submit --config           重新填写 name / 学号 / jAccount / 仓库路径 / token
    submit --show             显示当前记住的配置(token 打码)

默认在提交前给每个源文件开头补上姓名和学号注释(已有则跳过);加 noheader 则不补。
提交前总会把要交的文件里所有非 ASCII 字符(如中文注释)换成 [deleted_data],并去掉 BOM,
因为 JOJ3 的 Non-ASCII Characters File Check 不允许它们。
"""

import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

CLI_DIR = Path(__file__).resolve().parent
CONFIG = CLI_DIR / "config.json"
SOURCE_EXTS = (".m", ".c", ".cpp", ".h")
COURSE_HOST = "focs.gc.sjtu.edu.cn"
API = os.environ.get("SUBMIT_API", f"https://{COURSE_HOST}/git/api/v1")
TOKEN_PAGE = f"https://{COURSE_HOST}/git/user/settings/applications"
TYPES = ("feat", "fix")
REQUIRED = ("name", "sid", "jaccount", "repo")


def die(msg: str, code: int = 1):
    print(f"[submit] 错误: {msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str):
    print(f"[submit] {msg}")


def git(repo: Path, *args, check=True, capture=False):
    if not capture:
        info("$ git " + " ".join(args))
    res = subprocess.run(["git", "-C", str(repo), *args], text=True, encoding="utf-8",
                         errors="replace", capture_output=capture)
    if check and res.returncode != 0:
        if capture and res.stderr:
            print(res.stderr, file=sys.stderr, end="")
        die(f"git {args[0]} 失败(退出码 {res.returncode}),已停止,没有继续后面的步骤。")
    return res


def repo_root(start: Path):
    res = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                         text=True, capture_output=True)
    return Path(res.stdout.strip()) if res.returncode == 0 else None


def origin_url(repo: Path) -> str:
    res = subprocess.run(["git", "-C", str(repo), "config", "--get", "remote.origin.url"],
                         text=True, capture_output=True)
    return res.stdout.strip() if res.returncode == 0 else ""


def is_course_repo(repo: Path) -> bool:
    return COURSE_HOST in origin_url(repo)


def owner_and_name(repo: Path):
    m = re.search(r"[:/](\d+)/([^/]+)/([^/]+?)(?:\.git)?$", origin_url(repo))
    if not m:
        die(f"看不懂 origin 地址: {origin_url(repo)}")
    return m.group(2), m.group(3)


# ---------- 配置 ----------

def load_config():
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info(f"配置文件损坏,将重新填写: {CONFIG}")
    return {}


def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    info(f"已记住配置: {CONFIG}")


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{suffix}: ").lstrip("﻿").strip()
    except EOFError:
        print()
        die("输入被关闭,没能完成填写。请在终端里直接运行 submit --config。")
    return val or default


# 步骤与课程 Guide 4.1 → 4.3 → 4.4 的顺序一致
CLONE_HINT = (f"  还没 clone 的话,按课程指南:\n"
              f"    1. 在 https://{COURSE_HOST}/git/ 用 jAccount 登录(Sign in with jAccount)\n"
              f"    2. 配好 SSH 密钥(ssh-keygen,再把 id_ed25519.pub 加到 Gitea 的 SSH/GPG Keys)\n"
              f"    3. 在个人仓库页点 Code → SSH 复制地址,运行 git clone <地址>\n"
              f"  然后把 clone 出来的文件夹填到这里。")


def course_repo_at(path: Path):
    """path 位于课程仓库内则返回仓库根目录,否则 None。"""
    root = repo_root(path) if path.is_dir() else None
    return root if root and is_course_repo(root) else None


def ask_repo(default=""):
    print("课程仓库 = 你用 git clone 下来的个人作业仓库(里面有 Readme.md、lab1/ 等),\n"
          "例如 D:\\courses\\<你的仓库名>。在仓库目录里运行 submit 时会自动带出。")
    if not default:
        print(CLONE_HINT)
    while True:
        # 把文件夹拖进终端时路径会带引号
        raw = ask("课程仓库路径", default).strip("\"'")
        p = Path(raw).expanduser()
        if not raw or not p.is_dir():
            print("  找不到这个文件夹,请重新输入。")
            continue
        root = repo_root(p)
        if not root:
            print("  这个文件夹不是 git 仓库。")
            print(CLONE_HINT)
            continue
        if not is_course_repo(root):
            print(f"  这个文件夹不在课程仓库里(它所属的 git 仓库 {root} 的 origin 不是 {COURSE_HOST}),"
                  f"请重新输入。")
            continue
        if root != p.resolve():
            info(f"使用仓库根目录: {root}")
        return root


def setup(old):
    print("首次使用(或重新配置),请填写以下信息(方括号里是默认值,直接回车即采用):")
    here = course_repo_at(Path.cwd())
    root = ask_repo(str(here) if here else old.get("repo", ""))

    # 姓名和学号会写进每个提交的源文件:不给任何默认值,必须本人亲手输入并确认
    while True:
        while True:
            name = ask("name(英文名或拼音)")
            if name and name.isascii():
                break
            print("  name 不能为空,且只能用英文字符(课程要求英文名或拼音)。")
        while True:
            sid = ask("学号")
            if sid.isdigit():
                break
            print("  学号不能为空,且只能是数字。")
        print(f"\n以后提交时会在每个源文件开头写入:\n"
              f"    % Name: {name}\n"
              f"    % ID: {sid}\n")
        if ask("姓名和学号确认无误?输入 y 确认,其他任意键重新填写").lower() == "y":
            break
    while True:
        jaccount = ask("jAccount(不带 @sjtu.edu.cn)", old.get("jaccount", "")).removesuffix("@sjtu.edu.cn")
        if re.fullmatch(r"[A-Za-z0-9._-]+", jaccount):
            break
        print("  jAccount 格式不对,只能含字母、数字、. _ -")

    cfg = dict(old, name=name, sid=sid, jaccount=jaccount, repo=str(root))
    save_config(cfg)
    return cfg


def ensure_config(cfg):
    """返回 (配置, 本次使用的仓库)。当前目录在某个课程仓库里时优先用它,且不改写配置。"""
    if not all(cfg.get(k) for k in REQUIRED):
        cfg = setup(cfg)
    here = course_repo_at(Path.cwd())
    if here:
        if here != Path(cfg["repo"]):
            info(f"当前目录在课程仓库 {here} 里,本次使用它(配置里记的是 {cfg['repo']})。")
        return cfg, here
    if not course_repo_at(Path(cfg["repo"])):
        info(f"记住的仓库路径不可用了: {cfg['repo']}(被移动或删除?)")
        cfg["repo"] = str(ask_repo())
        save_config(cfg)
    return cfg, Path(cfg["repo"])


def apply_identity(repo: Path, cfg):
    email = f"{cfg['jaccount']}@sjtu.edu.cn"
    for key, want in (("user.name", cfg["name"]), ("user.email", email)):
        cur = git(repo, "config", "--local", "--get", key, check=False, capture=True).stdout.strip()
        if cur != want:
            git(repo, "config", key, want)


# ---------- 提交 ----------

def task_key(p: Path) -> int:
    return int(re.match(r"t(\d+)", p.name).group(1))


def sources_of(repo: Path, lab: str, task: str):
    """返回 (要 git add 的路径列表, 源文件列表);找不到返回 (None, None)。
    优先 lab/task/ 目录,其次 lab/task.<ext> 平铺文件。"""
    task_dir = repo / lab / task
    if task_dir.is_dir():
        srcs = sorted(f for f in task_dir.iterdir() if f.is_file() and f.suffix in SOURCE_EXTS)
        if srcs and not any(f.stem == task for f in srcs):
            info(f"提醒: {lab}/{task}/ 里没有名为 {task}.* 的文件,作业要求文件名是 {task}.m 之类。")
        return ([f"{lab}/{task}"], srcs) if srcs else (None, None)
    flat = [repo / lab / f"{task}{ext}" for ext in SOURCE_EXTS]
    flat = [f for f in flat if f.is_file()]
    return ([f"{lab}/{f.name}" for f in flat], flat) if flat else (None, None)


def all_tasks(repo: Path, lab: str):
    lab_dir = repo / lab
    if not lab_dir.is_dir():
        die(f"找不到目录 {lab}/(仓库: {repo})。")
    names = {p.name for p in lab_dir.iterdir() if p.is_dir() and re.fullmatch(r"t\d+", p.name)}
    names |= {p.stem for p in lab_dir.iterdir()
              if p.is_file() and p.suffix in SOURCE_EXTS and re.fullmatch(r"t\d+", p.stem)}
    return sorted(names, key=lambda n: int(n[1:]))


def ensure_header(f: Path, cfg) -> bool:
    """在文件开头补「姓名 / 学号」注释。前 10 个非空行里已出现学号就不动。
    按字节操作:保留 BOM、换行风格和原有编码。"""
    data = f.read_bytes()
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    body = data[len(bom):]
    head = [ln for ln in body[:4000].decode("utf-8", "replace").splitlines() if ln.strip()][:10]
    if any(cfg["sid"] in ln for ln in head):
        return False
    nl = "\r\n" if b"\r\n" in body else "\n"
    c = "%" if f.suffix == ".m" else "//"
    header = f"{c} Name: {cfg['name']}{nl}{c} ID: {cfg['sid']}{nl}".encode("ascii")
    f.write_bytes(bom + header + body)
    return True


NON_ASCII = re.compile(r"[^\x00-\x7f]+")
ASCII_EXTS = SOURCE_EXTS + (".md",)


def to_ascii(f: Path):
    """JOJ3 不允许文件里有任何非 ASCII 字符:去掉 BOM,每段连续的非 ASCII 字符换成
    [deleted_data]。返回 (是否去了 BOM, 被替换的行号列表);文件本来就是纯 ASCII 则返回 None。"""
    data = f.read_bytes()
    if data.isascii():
        return None
    bom = data.startswith(b"\xef\xbb\xbf")
    body = data[3:] if bom else data
    for enc in ("utf-8", "gbk"):
        try:
            text = body.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = body.decode("latin-1")  # 认不出编码:每个高位字节各算一个字符
    lines = sorted({text.count("\n", 0, m.start()) + 1 for m in NON_ASCII.finditer(text)})
    f.write_bytes(NON_ASCII.sub("[deleted_data]", text).encode("ascii"))
    return bom, lines


def make_ascii(repo: Path, paths):
    # 已提交过的文件也要处理:旧提交里的非 ASCII 同样会让检查失败
    listed = git(repo, "ls-files", "-c", "-o", "--exclude-standard", "-z", "--", *paths,
                 capture=True).stdout.split("\0")
    for rel in filter(None, listed):
        f = repo / rel
        if f.suffix not in ASCII_EXTS or not f.is_file():
            continue
        res = to_ascii(f)
        if res is None:
            continue
        bom, lines = res
        what = []
        if bom:
            what.append("去掉了 BOM")
        if lines:
            what.append("第 " + ", ".join(map(str, lines)) + " 行的非 ASCII 字符换成了 [deleted_data]")
        info(f"{rel}: " + ";".join(what) + "。")


def collect(repo: Path, lab, task):
    """返回 [(题号, 要 git add 的路径, 源文件)]。task 为 None 表示整个 lab。"""
    if task:
        paths, srcs = sources_of(repo, lab, task)
        if not paths:
            die(f"{lab}/{task} 下没有源文件({', '.join(SOURCE_EXTS)})。")
        return [(task, paths, srcs)]
    found = []
    for t in all_tasks(repo, lab):
        p, s = sources_of(repo, lab, t)
        if p:
            found.append((t, p, s))
        else:
            info(f"跳过 {lab}/{t}: 里面没有源文件。")
    if not found:
        die(f"{lab}/ 下没有找到任何题目(t1/、t2/ … 或 t1.m …)。")
    return found


def add_headers(repo: Path, srcs, cfg):
    for f in srcs:
        rel = f.relative_to(repo).as_posix()
        if ensure_header(f, cfg):
            info(f"已在 {rel} 开头补上姓名和学号注释。")
        else:
            info(f"{rel} 开头已有学号,跳过。")


def submit(cfg, repo: Path, lab, task, ctype, with_header):
    info(f"仓库: {repo}")
    apply_identity(repo, cfg)
    git(repo, "pull", "--ff-only")

    found = collect(repo, lab, task)
    paths = [p for _, ps, _ in found for p in ps]
    srcs = [s for _, _, ss in found for s in ss]
    if with_header:
        add_headers(repo, srcs, cfg)
    else:
        info("noheader: 不补姓名学号注释。")
    make_ascii(repo, paths)

    git(repo, "add", "--", *paths)
    ignored = git(repo, "status", "--porcelain", "--ignored", "--", *paths,
                  capture=True).stdout.splitlines()
    ignored = [ln[3:] for ln in ignored if ln.startswith("!! ")]
    if ignored:
        info("以下文件被 .gitignore 白名单挡住,不会上传: " + ", ".join(ignored))

    # commit message 只写真正有改动的题;一题都没改(空提交重跑 JOJ3)时写全部
    changed = [t for t, ps, _ in found
               if git(repo, "diff", "--cached", "--quiet", "--", *ps,
                      check=False, capture=True).returncode != 0]
    message = f"{ctype}({lab}): {' '.join(changed or [t for t, _, _ in found])} ok[joj]"
    info(f"commit message: {message}")

    if changed:
        staged = git(repo, "diff", "--cached", "--name-status", "--", *paths, capture=True).stdout
        info("本次提交的文件:\n" + "".join("    " + ln + "\n" for ln in staged.splitlines()))
        # 带 pathspec 提交:只提交这些题,暂存区里别的东西原样留着
        git(repo, "commit", "-m", message, "--", *paths)
    else:
        if git(repo, "diff", "--cached", "--quiet", check=False, capture=True).returncode != 0:
            die("要交的题相对上次提交没有改动,而暂存区里有别的文件;"
                "为了不把它们误带上去,不做空提交。请先处理暂存区(git status 查看)。")
        info("没有改动,做一次空提交来重新触发 JOJ3。")
        git(repo, "commit", "--allow-empty", "-m", message)

    git(repo, "push")
    owner, name = owner_and_name(repo)
    info(f"完成。JOJ3 结果: https://{COURSE_HOST}/git/{owner}/{name}/issues")


# ---------- Release ----------

def api(method, path, token, body=None):
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"token {token}", "Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("message", "")
        except ValueError:
            msg = ""
        return e.code, {"message": msg}
    except urllib.error.URLError as e:
        die(f"连不上 Gitea API({e.reason})。校外可能需要先连 SJTU VPN。")


def ensure_token(cfg, owner, name):
    token = cfg.get("token")
    while True:
        if not token:
            print(f"发 Release 需要一个 Gitea access token(只需填一次):\n"
                  f"  1. 打开 {TOKEN_PAGE}\n"
                  f"  2. Generate New Token,权限里把 repository 设为 Read and Write\n"
                  f"  3. 把生成的 token 粘贴到这里(输入时不显示)")
            try:
                # Windows 的 getpass 直接读控制台;输入来自管道时退回普通读取
                token = (getpass.getpass("token: ") if sys.stdin.isatty()
                         else input("token: ")).strip()
            except EOFError:
                die("输入被关闭,没能读取 token。")
            if not token:
                die("没有输入 token。")
        status, data = api("GET", f"/repos/{owner}/{name}", token)
        if status == 200:
            if cfg.get("token") != token:
                cfg["token"] = token
                save_config(cfg)
            return token
        info(f"token 不可用(HTTP {status} {data.get('message', '')}),请重新输入。")
        token = None


def release(cfg, repo: Path, lab):
    owner, name = owner_and_name(repo)
    info(f"仓库: {repo}")

    # 1. 本地与远端必须完全一致:Release 发的是远端最新提交
    git(repo, "fetch", "origin")
    head = git(repo, "rev-parse", "HEAD", capture=True).stdout.strip()
    up = git(repo, "rev-parse", "@{u}", check=False, capture=True)
    if up.returncode != 0:
        die("当前分支没有对应的远端分支。")
    if head != up.stdout.strip():
        die("本地与远端不一致(有没 push 的提交,或远端有新提交)。先 submit 或 git pull,再来 release。")
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD", capture=True).stdout.strip()

    # 2. 最新提交的 scope 必须等于 tag
    subject = git(repo, "log", "-1", "--format=%s", capture=True).stdout.strip()
    m = re.match(r"[a-z]+\(([^)]+)\):", subject)
    if not m or m.group(1) != lab:
        die(f"最新提交是「{subject}」,scope 不是 {lab}。课程要求最新提交的 scope 与 Release tag 一致。\n"
            f"         先运行 submit {lab}(没改动也会做一次空提交),等 JOJ3 出结果后再 release。")

    # 3. 不能已经 release 过
    if git(repo, "ls-remote", "--tags", "origin", f"refs/tags/{lab}", capture=True).stdout.strip():
        die(f"远端已经有 tag {lab},说明已经 release 过。\n"
            f"         Guide 5.4 与 Lab 说明规定只能 release 一次;仓库 Readme 2.5 另有「先在网页上删除\n"
            f"         旧 Release 和 tag 再重发」的流程。两者不一致,重发前请先问助教。工具不会替你删除。")
    token = ensure_token(cfg, owner, name)
    status, rels = api("GET", f"/repos/{owner}/{name}/releases?limit=50", token)
    if status != 200:
        die(f"查询已有 Release 失败(HTTP {status} {rels.get('message', '')})。")
    if any(r.get("tag_name") == lab for r in rels):
        die(f"已经存在 tag 为 {lab} 的 Release(可能是草稿),请到网页上检查。")

    # 4. 人工确认
    print(f"\n即将发布 Release:\n"
          f"    仓库        {owner}/{name}\n"
          f"    Tag / 标题  {lab}\n"
          f"    指向提交    {head[:8]}  {subject}\n"
          f"注意: Guide 5.4 与 Lab 说明规定每个 lab 只能 release 一次,发布后不要再改 {lab} 的文件。\n"
          f"      请确认 JOJ3 的 push 结果已经出来并且满意。")
    if ask(f"确认发布请输入 {lab}") != lab:
        die("没有确认,已取消,什么都没发。")

    status, data = api("POST", f"/repos/{owner}/{name}/releases", token, {
        "tag_name": lab, "name": lab, "target_commitish": branch,
        "draft": False, "prerelease": False})
    if status not in (200, 201):
        die(f"发布失败(HTTP {status} {data.get('message', '')})。可到网页上手动发。")
    info(f"Release 已发布: {data.get('html_url', '')}")
    info(f"隐藏用例结果稍后出现在: https://{COURSE_HOST}/git/{owner}/{name}/issues")


# ---------- 入口 ----------

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if argv else 2)
    cfg = load_config()
    if argv[0] == "--config":
        cfg = setup(cfg)
        if ask("要重新填写 release 用的 token 吗?(y/N)", "n").lower() == "y":
            cfg.pop("token", None)
            save_config(cfg)
            ensure_token(cfg, *owner_and_name(Path(cfg["repo"])))
        return
    if argv[0] == "--show":
        shown = dict(cfg)
        if shown.get("token"):
            shown["token"] = shown["token"][:4] + "…(已打码)"
        print(json.dumps(shown, ensure_ascii=False, indent=2) if shown else "还没有配置。")
        return

    if argv[0] == "release":
        if len(argv) != 2 or not re.fullmatch(r"lab\d+", argv[1]):
            die("用法: submit release lab1")
        release(*ensure_config(cfg), argv[1])
        return

    lab, rest = argv[0], argv[1:]
    if not re.fullmatch(r"lab\d+", lab):
        die(f"作业名应形如 lab1,收到: {lab}")
    # lab 之后的 task / 类型 / noheader 顺序随意,每种最多一个
    tasks = [a for a in rest if re.fullmatch(r"t\d+", a)]
    types = [a.lower() for a in rest if a.lower() in TYPES]
    flags = [a for a in rest if a.lower().lstrip("-") == "noheader"]
    if len(tasks) > 1 or len(types) > 1 or len(tasks) + len(types) + len(flags) != len(rest):
        die("用法: submit <lab> [<task>] [feat|fix] [noheader],例如 submit lab1 t1 fix")
    task = tasks[0] if tasks else None
    ctype = types[0] if types else "feat"
    with_header = not flags
    submit(*ensure_config(cfg), lab, task, ctype, with_header)


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        print()
        die("已取消。", 130)
