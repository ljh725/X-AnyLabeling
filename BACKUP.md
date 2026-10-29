# 4.2.1 备份节点

- 备份日期：2026-10-29（Asia/Shanghai）。
- GitHub 仓库：`ljh725/X-AnyLabeling`。
- 独立分支：`backup/4.2.1-20261029`。
- 固定标签：`backup-v4.2.1-20261029`。
- 官方基础：`v4.2.1`，提交 `6d250499d2dd81f78723b9217c7a9abf0443ca25`。
- 目的：保存当前工作区，作为后续数据集加载性能修改前的恢复点。

节点包含当前应用代码、迁移扩展、资源和翻译、测试，以及
`benchmarks/` 中的测试脚本/结果和 `reports/` 中的加载方式对比记录。
已有 `.gitignore` 继续排除运行日志、Python 缓存和其他忽略文件。

备份采用官方 4.2.1 提交作为父节点，再提交本地差异；不是重新压缩源码包，
也不替换仓库中已有分支。

## 恢复到单独目录

```powershell
git clone --branch backup-v4.2.1-20261029 https://github.com/ljh725/X-AnyLabeling.git D:\X-AnyLabeling-4.2.1-restored
```

这样会在新目录检出固定备份标签，原工作目录不受影响。
若需要从该恢复点继续修改，可在恢复目录建立新分支：

```powershell
git -C D:\X-AnyLabeling-4.2.1-restored switch -c work/from-4.2.1-backup
```

查看当前节点和相对官方版本的变化：

```powershell
git log -1 backup-v4.2.1-20261029
git diff --stat v4.2.1 backup-v4.2.1-20261029
```
