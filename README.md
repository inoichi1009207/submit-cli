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
submit release lab1
```

发布前自动检查：本地与远端一致、最新提交的 scope 等于 `lab1`。通过后需**手动输入 `lab1` 确认**才会发布。

**重新 release**：如果 `lab1` 已经发过（远端已有 tag 或同名 Release，含草稿），工具会明确提示，并按仓库 Readme 2.5 的流程操作：需输入 `rerelease lab1` 确认，然后依次删除旧 Release、删除 tag `lab1`（API 失败时改用 `git push` 删除）、清掉本地残留的同名 tag，最后用当前最新提交重新发布。任一步失败即停止，不会发布。

> 课程 Guide 5.4 与 Lab 说明写的是每个 lab **只能 release 一次**，与仓库 Readme 2.5 不一致。本工具按 Readme 2.5 实现，并在重发确认时提示这一点。

首次使用需要 Gitea access token：在 `https://focs.gc.sjtu.edu.cn/git/user/settings/applications` 生成，权限给 repository 读写，粘贴进来即可（输入不回显，验证通过后保存到 `config.json`）。

> 通过 API 创建的 Release 能否触发课程的 `release.yaml`（隐藏用例）尚未实测。首次使用后请到 Issues 页确认隐藏用例结果已出现。

## 注意

- 本工具只负责提交流程，不生成任何作业代码。请遵守课程 Honor Code。
- `config.json` 含 Gitea token，不要分享或提交。
