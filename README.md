# submit

ENGR1010J（SJTU）作业一键提交工具：一条命令完成 `git pull → 补姓名学号 → 清除非 ASCII → add → commit → push`，并可一键发 Release。

```powershell
submit lab1 t1          # 提交 lab1/t1:   feat(lab1): t1 ok[joj]
submit lab1 t3 fix      # 提交 lab1/t3:   fix(lab1): t3 ok[joj]
submit lab1             # 提交 lab1 下所有题,message 只列有改动的题: feat(lab1): t1 t3 ok[joj]
submit release lab1     # 发 Release(tag 与标题都是 lab1)
```

## 安装

需要 Git 和 Python 3.9+，并且已按课程指南配好 Gitea SSH 密钥、clone 了个人仓库。

1. 把本仓库 clone 到任意目录，例如 `D:\tools\submit-cli`。
2. 把该目录加入用户 PATH（PowerShell）：
   ```powershell
   [Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path','User') + ';D:\tools\submit-cli', 'User')
   ```
3. 新开一个终端，运行 `submit --help`。

目前只提供 Windows 入口 `submit.cmd`；macOS / Linux 可直接 `python3 submit.py ...`，或自行设 alias。

## 首次使用

第一次运行时会依次询问：

| 项目 | 说明 |
|---|---|
| 课程仓库路径 | 你 `git clone` 下来的个人作业仓库，里面有 `Readme.md`、`lab1/` 等。在仓库目录里运行时会自动带出 |
| name | 英文名或拼音，**必须自己输入** |
| 学号 | **必须自己输入** |
| jAccount | 不带 `@sjtu.edu.cn` |

name 和学号会写进每个提交的源文件，所以输入后会显示即将写入的注释，并要求输入 `y` 确认。

还没 clone 仓库的话，先按课程指南完成：用 jAccount 登录 Gitea → 配置 SSH 密钥 → 在仓库页 Code → SSH 复制地址并 `git clone`。

**使用哪个仓库**：当前目录位于某个课程仓库（origin 指向 `focs.gc.sjtu.edu.cn`）内时，本次就用它；否则用配置里记住的仓库。记住的仓库被移动或删除时，只会重新询问路径。

配置保存在本目录下的 `config.json`（已被 `.gitignore` 排除）。重新配置：`submit --config`；查看：`submit --show`。

## 用法

```
submit <lab> [<task>] [feat|fix] [noheader]
```

- `<task>` 省略时提交该 lab 下所有含源文件的题目；commit message 只列出**真正有改动**的题（例如只改了 t2 就是 `fix(lab1): t2 ok[joj]`），一题都没改时列出全部并做空提交。
- lab 不分题时（例如 `lab5/` 下只有一个 `lab5.c`，没有 `t1/` 这类子目录），`submit lab5` 提交 `lab5/` 下所有源文件（`.c` `.cpp` `.h` `.m`），message 为 `feat(lab5): ok[joj]`。
- 类型省略时为 `feat`。
- `lab` 之后的参数顺序随意。

每次提交会自动：

1. 把仓库的 `user.name` / `user.email` 设为配置中的姓名和 `<jAccount>@sjtu.edu.cn`。
2. `git pull --ff-only`。
3. **补姓名学号注释**：在每个源文件开头加
   ```matlab
   % Name: <name>
   % ID: <学号>
   ```
   （C/C++ 用 `//`）。文件前 10 个非空行已含学号则跳过。加 `noheader` 关闭。
4. **清除非 ASCII**：JOJ3 的 *Non-ASCII Characters File Check* 不允许文件中出现任何非 ASCII 字符（包括中文注释）。工具会把每段连续的非 ASCII 字符替换为 `[deleted_data]`，并去掉 BOM，同时打印被改动的文件和行号。**这会直接修改本地文件**，需要保留中文注释请先备份。
5. 只提交这些题目的路径（暂存区里其他文件不会被带上）；没有改动时做一次空提交以重新触发 JOJ3。
6. `git push`，并打印 Issues 页链接。

任一步失败即停止，不会执行后续步骤。

## Release

```powershell
submit release lab2
```

第一次还是第二次由工具判断，命令都一样。

发布前自动检查：

1. **本地和 Gitea 上的最新版是否完全一致**：有未提交的改动或新文件、有没 push 的提交、或 Gitea 上有本地没有的提交，都会逐项列出并建议先处理（`submit lab2` 交上去 / `git pull` 拉下来）。默认不发，输入 `y` 才继续。Release 指向的是 Gitea 上的最新提交，本地没交上去的东西不会包含在内。
2. Gitea 上最新提交的 scope 等于 `lab2`。

| 情况 | 行为 |
|---|---|
| 还没发过 | tag / 标题用 `lab2`，输入 `lab2` 确认 |
| `lab2` 已发过 | **第二次也是最后一次**：tag / 标题用 `lab2-2`，旧的 `lab2` 不动，输入 `lab2-2` 确认 |
| `lab2-2` 已存在 | 拒绝，两次机会都用掉了 |

依据是课程通知：每个 lab 可以 release 两次，第二次必须用 `labn-2` 作为 tag 和标题（用 `labn` 可能丢分）；这个名额是防误发的保险，用掉后不再给额外机会。通知写的是从 Lab 2 起，lab1 早已截止，工具对它不做单独限制。「已发过」指远端已有该 tag，或已有该 tag 的 Release（含草稿）。

首次使用需要 Gitea access token：在 `https://focs.gc.sjtu.edu.cn/git/user/settings/applications` 生成，权限给 repository 读写，粘贴进来即可（每个字符显示为 `*`，cmd 里可 Ctrl+V 或右键粘贴；验证通过后保存到 `config.json`）。

> 通过 API 创建的 Release 能否触发课程的 `release.yaml`（隐藏用例）尚未实测。首次使用后请到 Issues 页确认隐藏用例结果已出现。

## 注意

- 本工具只负责提交流程，不生成任何作业代码。请遵守课程 Honor Code。
- `config.json` 含 Gitea token，不要分享或提交。
