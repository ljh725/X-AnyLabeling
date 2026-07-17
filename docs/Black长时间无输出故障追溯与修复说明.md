# Black 长时间无输出故障追溯与修复说明

## 文档信息

- 日期：2026-07-17
- 影响范围：Codex 沙箱中的 Black 命令、全仓 Black 扫描、
  pre-commit Black hook
- 相关配置：`pyproject.toml`、`.pre-commit-config.yaml`

## 故障现象

对 `anylabeling/views/labeling/label_widget.py` 执行 Black 检查时，
命令超过 60 秒没有完成，也没有持续输出。仓库中当时另有一个长期运行的
Python 进程，经检查其命令行为 `anylabeling/app.py`，与 Black 无关。

## 定位证据

1. Black 版本为 26.5.1，默认缓存目录为：
   `C:\Users\20441\AppData\Local\black\black\Cache\26.5.1`。
2. 通过 `faulthandler` 抓取阻塞栈，命令停在
   `tempfile._mkstemp_inner`，即 Black 创建缓存临时文件的阶段。
3. 系统临时目录创建临时文件耗时约 0.003 秒；在 Black 默认缓存目录中
   创建临时文件超过 10 秒仍未返回。
4. 将 `BLACK_CACHE_DIR` 指向沙箱允许写入的系统临时目录后，同一文件的
   Black 检查在 2.54 秒内完成。
5. 原 `[tool.black].exclude` 使用 TOML 原始多行字符串，却保留了双重
   反斜杠，并在正则开头包含额外的 `\\`。实际正则测试显示
   `tests/`、`.git/` 和 `anylabeling/resources/resources.py` 均未匹配。
6. 对 `anylabeling` 执行目录扫描时，本应排除的 1.8 MB 自动生成文件
   `resources.py` 被 Black 处理，共扫描 408 个 Python 文件。
7. `.pre-commit-config.yaml` 连续配置了两个相同版本的 Black hook：
   第一个执行格式化，第二个执行 `--check`，造成重复扫描。

## 根因

### 根因一：Black 缓存目录在沙箱可写范围外

Black 即使使用 `--check`，仍会读写格式化缓存。Codex 沙箱允许修改仓库和
系统临时目录，但不允许写入 Black 位于 `LOCALAPPDATA` 下的默认缓存目录。
临时文件创建因此持续重试，外部表现为 Black 长时间没有输出。

### 根因二：项目排除正则失效

`pyproject.toml` 使用 `'''...'''` TOML 原始字符串时，正则反斜杠不需要
再次转义。原配置的双反斜杠改变了正则语义，导致生成文件和测试目录没有
按预期排除，放大了每次扫描的工作量。

### 根因三：pre-commit 重复运行 Black

第二个 `--check` hook 紧跟在格式化 hook 后面，不能提供额外的提交保护，
但会再次启动 Black 并扫描同一批文件。

## 修改方案

1. 将 Black 缓存临时指向沙箱可写目录：

   ```powershell
   $env:BLACK_CACHE_DIR = Join-Path $env:TEMP 'xanylabeling-black-cache'
   ```

2. 将 `[tool.black].exclude` 改为 `extend-exclude`，只定义项目特有排除项，
   继续保留 Black 自带的默认目录排除规则：

   ```toml
   [tool.black]
   line-length = 79
   extend-exclude = '''
   (
       ^/tests/
     | ^/anylabeling/resources/resources\.py$
   )
   '''
   ```

3. 删除重复的 Black `--check` hook，只保留一次 Black hook，并对排除规则
   增加路径边界和文件扩展名转义。

4. 在 `AGENTS.md` 的 Black 开发命令和 Windows 命令规则中记录可写缓存设置，
   保证后续 Codex 会话不会再次使用沙箱外的默认缓存目录。

5. 暂不调整 Black 版本。开发环境为 26.5.1，pre-commit 固定为 23.3.0；
   后续升级应单独执行并审查全仓格式差异，避免与本次性能修复混在一起。

## 推荐执行方式

在 Codex 沙箱或其他限制用户缓存写入的环境中：

```powershell
$ErrorActionPreference = 'Stop'
$env:BLACK_CACHE_DIR = Join-Path $env:TEMP 'xanylabeling-black-cache'
$py = "$env:USERPROFILE\.conda\envs\x-anylabeling-cu12\python.exe"
& $py -m black -l 79 anylabeling
```

只检查、不改写文件：

```powershell
& $py -m black --check -l 79 anylabeling
```

环境允许写入默认缓存目录时，不需要设置 `BLACK_CACHE_DIR`。

## 验证标准

1. `pyproject.toml` 和 `.pre-commit-config.yaml` 能正常解析。
2. Black 实际扫描时忽略 `tests/` 和
   `anylabeling/resources/resources.py`。
3. `label_widget.py` 的 `--check --fast` 在可写缓存下能在合理时间内结束。
4. pre-commit 配置中只存在一个 `id: black`。
5. `AGENTS.md` 的 Black 命令在执行前设置可写缓存目录。
6. 验证命令不得改写业务源码。

## 回滚方式

如本次配置修改导致兼容问题，仅回滚以下内容：

1. 恢复 `pyproject.toml` 的原 Black 配置块。
2. 恢复 `.pre-commit-config.yaml` 中第二个 Black hook。
3. 删除本说明文档。

`BLACK_CACHE_DIR` 是进程级环境变量，关闭当前 PowerShell 会话或执行
`Remove-Item Env:BLACK_CACHE_DIR` 即可恢复默认缓存位置。
