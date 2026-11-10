# 2026-11-10 备份节点推送与核对

日期：2026-11-10（Asia/Shanghai）。备份节点提交：`e40c537c56fcca7ff4db8c3702b02dd9c333d9f6`。

## 1. 远端引用核对

推送后重新读取远端引用，与本地逐项比对，全部一致：

| 引用 | 远端 | 本地 | 结果 |
| --- | --- | --- | --- |
| `refs/heads/backup/4.2.1-20261110-organized-baseline` | `e40c537c…` | `e40c537c…` | 一致 |
| `refs/tags/backup/4.2.1-20261110-organized-baseline`（标签对象） | `98707da8…` | `98707da8…` | 一致 |
| `refs/tags/backup/4.2.1-20261110-organized-baseline^{}`（指向提交） | `e40c537c…` | `e40c537c…` | 一致 |
| `refs/heads/codex/4.2.1-baseline-organization`（开发线） | `e40c537c…` | `e40c537c…` | 一致（`cd26f5f8..e40c537c` 快进） |

节点相对整理前保存点 `cd26f5f8`：`git diff --stat cd26f5f8 <tag>` = **103 files changed, 41309 insertions(+), 34683 deletions(-)**；`cd26f5f8` 是新节点的祖先。三条提交：

| 提交 | 内容 |
| --- | --- |
| `3ddee158` | `fix(labeling)`：数字键矩形类别保存修复、Inspector 问题导航、翻译资源重新生成、测试更新 |
| `e4430b30` | `docs(openspec)`：Inspector 重构归档、主规格同步、11-06 以来变更证据与验收 |
| `e40c537c` | `chore(workspace)`：2026-11-10 数据整理、备份与目录说明 |

核对命令（工作区根目录）：

```powershell
git ls-remote origin "refs/heads/backup/4.2.1-20261110*" "refs/tags/backup/4.2.1-20261110*"
git rev-parse refs/heads/backup/4.2.1-20261110-organized-baseline refs/tags/backup/4.2.1-20261110-organized-baseline
git merge-base --is-ancestor cd26f5f8 refs/tags/backup/4.2.1-20261110-organized-baseline
```

## 2. 本地整史 bundle

推送之外另存一份本机兜底（已在 `.gitignore` 覆盖的 `backups/` 内，不入 Git）：

| 项目 | 值 |
| --- | --- |
| 文件 | `backups/4.2.1-20261110-organized-baseline.bundle` |
| 字节 | 245,008,086 |
| SHA-256 | `AE78320093FD157DCA4B4C8DE016E0BA79ACCC6517E7FB215A426477C6D3C7DB` |
| `git bundle verify` | 通过；`The bundle records a complete history.` |
| 收据 | `backups/4.2.1-20261110-organized-baseline.receipt.json` |

bundle 含 `refs/heads/backup/...` 与 `refs/tags/backup/...` 两个引用，可直接克隆：

```powershell
git clone backups\4.2.1-20261110-organized-baseline.bundle D:\X-AnyLabeling-restored-20261110
```

## 3. 环境说明（本机推送方式）

本机自带 Git 的 schannel 后端在当前沙箱内无法取得 TLS 凭证，`gh` 能正常访问 GitHub。实际推送使用系统 Git 并显式指定代理、TLS 后端与 `gh` 凭据助手：

```bash
"/c/Program Files/Git/cmd/git.exe" -c http.proxy=http://127.0.0.1:7897 \
  -c http.sslBackend=openssl -c credential.helper='!gh auth git-credential' \
  push origin <ref>
```

本次没有改写任何 Git 全局或仓库级配置（全部为一次性 `-c` 参数）。若后续在本机直接 `git push` 报 `schannel: AcquireCredentialsHandle failed`，用上述形式即可；或在能正常访问网络的终端里推送。

## 4. 残留事项

- 分支与固定标签同名（沿用仓库既有做法，例如 `backup/refactor-data-inspector-workflow-20261102`）。普通命令会提示 refname 歧义但仍按分支优先解析；需要精确定位时用 `refs/heads/...` 或 `refs/tags/...`。
- 若希望消除歧义，可删除同名标签后只保留分支，或把标签改成 `backup-v4.2.1-20261110-organized-baseline` 之类；删除标签属于不可逆操作，本次未执行，留待用户决定。
- 推送只覆盖 `ljh725/X-AnyLabeling`；没有动 `upstream`（CVHub520）仓库。
