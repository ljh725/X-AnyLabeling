# 执行记录：按 final_report 第 8 节执行 A / B

- 执行时间：2026-11-09 11:12–11:30（Asia/Shanghai）
- 执行人：Lead（DSH 0.2.2-rc.1，profile=desktop）
- 用户指令：「执行报告第八节中 A、B 两个选项」
- 性质：**首次非只读操作**（安装插件 + 新增本地脚本）。未改全局环境变量，未改项目源码。

---

## A. 新增安装（3 个）—— ✅ 全部完成

安装方式：`plugin_manager` 工具的 `install_bundle`（桌面 profile 被 Electron 独占，CLI 会 EPERM；GUI 市场等价）。

| 插件 | 版本 | 安装结果 | 证据 |
|---|---|---|---|
| `dsh-doublecheck` | **0.9.30** | ✅ 已加入 dependencies + bundles，`application: applied` | pnpm 输出 `+ dsh-doublecheck 0.9.30`，日志 `~/.dsh/profiles/desktop/.plugin-manager/logs/operation-Lkn3Qe/pnpm.log` |
| `dsh-diff-approval` | **0.37.4** | ✅ 同上（+47 个依赖包） | 日志 `operation-ZgPWJA/pnpm.log` |
| `dsh-computer-use-win` | **0.5.5** | ✅ 同上（+1 包） | 日志 `operation-ufy0Ll/pnpm.log` |

**安装后已可观察到的生效迹象（部分热加载）：**
- 技能目录新增：`grill-requirements`、`red-green-tdd`、`delivery-review`、`delivery-proof`（来自 dsh-doublecheck）；`dsh-diff-approval-annotate`、`dsh-diff-approval-comment`（来自 dsh-diff-approval）→ 【实测】
- `mcp__wincu__windows_computer_use_health` 调用成功：platform=Windows、PowerShell 5.1.19041.4170、UIA=true、screenshot=true、ocr=lazy、browserLane.enabled=true → 【实测】

**注意（待重启后确认）**：本次会话在安装前就已经存在 `mcp__wincu__*` 工具（来源未查明：profile 依赖里当时没有该包，asar 里也没有该包；疑似宿主进程残留/应用层预置）。**重启 DSH 后应核对：wincu 工具只应有一套**；若出现重复或冲突，卸掉 `dsh-computer-use-win` 即可回到安装前状态。

**装完需重启 DSH** 才能确保 3 个 bundle 完整加载（当前只是热加载了一部分能力）。

---

## B. 配置修复（2 项）

### B-1 修 modlens provider —— ⚠️ 阻塞（无可用凭据）

执行与实测：

| 尝试 | 结果 | 说明 |
|---|---|---|
| `claude-cli` | ❌ `provider failed with code 1` | Claude Code 2.1.177 已装，但 `~/.claude.json` 无 `oauthAccount`（**无订阅、未登录**） |
| `kimi-cli` | ❌ `spawn EPERM` | Kimi CLI 本身可直接运行（`kimi.EXE --version` 正常），但 modlens 在其宿主上下文中 spawn 被拒；且用户确认**无 Kimi 订阅** |
| `gemini-api` / `openai` / `anthropic` | ❌ missing | 无 API Key |
| `antigravity-cli` | ❌ 未安装 | — |

结论：**modlens 本身没坏，是没有任何一个可用的"眼睛"**。需要用户在下列方案中选择（安装/申请凭据属于新决定，未擅自执行）：

1. **免费 Gemini Key**（推荐，最快）：到 <https://aistudio.google.com> 领取 → `modlens config set gemini-api.apiKey` → `modlens config set provider gemini-api`；5–10 秒/张。
2. **dsh-vision-router**（免 Key，但要联网、图片上传到 OVHcloud 法国、`engines.node>=24.9` 需确认）。
3. **本地视觉模型**（不出网、免费，需下载数 GB、较慢）。
4. **不配视觉**：离屏截图 + Pillow 像素断言 + Windows OCR 认字（离线、零成本，但不能"理解界面"）。
5. 另一个零成本待测路径：在 DSH 界面把模型切到 **`z-ai/glm-5.3-flash`**（原生多模态），直接粘贴截图看是否走通（走你现有 commandcode 额度）。

### B-2 固定测试环境 —— ✅ 完成（用更安全的"包装脚本"替代全局 setx）

**没有**用 `setx` 改全局 `PYTHONPATH` / `QT_QPA_PLATFORM`（全局设置会污染其他 Python 程序，且 `QT_QPA_PLATFORM=offscreen` 会让手动启动的 GUI 变成不可见）。改为在仓库内新增两个包装脚本：

| 文件 | 用途 |
|---|---|
| `.tooling/dsh-pytest.cmd` | Windows 命令行用：固定 `PYTHONPATH=%~dp0pytest-shim`、`QT_QPA_PLATFORM=offscreen`、`--basetemp=<仓库>\.tmp\pytest-bt\<随机>` |
| `.tooling/dsh-pytest.sh` | MSYS bash 用：同上（basetemp 带时间戳+pid），附加 `"$@"` |

**第一版有一个坑（已修）**：最初 basetemp 固定为 `.tmp/pytest-bt`，该目录里残留着早前失败运行留下的 `0o700` ACL 子目录（`rm -rf` 都删不掉），pytest 复用它时又会 `PermissionError`。**改为每次运行使用唯一 basetemp 目录**后稳定通过。

**红→绿记录（同一条命令，只差包装器）：**
```
红：裸 pytest tests/test_inspection/test_inspector_dialog.py
    → 21 errors in 2.68s（PermissionError: WinError 5, AppData\Local...）
绿：.tooling/dsh-pytest.sh tests/test_inspection/test_inspector_dialog.py
    → 21 passed in 52.75s  ✅
```
另：`tests/test_settings/test_schema.py` 用包装器 → **7 passed in 2.12s**。

以后跑测试统一用：
- bash：`.tooling/dsh-pytest.sh <测试路径>`
- cmd：`.tooling\dsh-pytest.cmd <测试路径>`

**绿门复核（2026-11-09 11:45，改动后再次确认）**：
```
.tooling/dsh-pytest.sh tests/test_settings tests/test_inspection/test_models.py tests/test_inspection/test_progress_and_rule_access.py
→ 100 passed, 1 skipped, 9 subtests passed in 32.74s   ✅
```

> 残留问题：`.tmp/pytest-bt` 本身是一个删不掉的受限目录（早期失败运行的遗留）。包装器已绕开它（改用其下的唯一子目录）；若要彻底清理，需要用 ACL 修复脚本处理（不急）。

---

## 当前状态与下一步

### 重启后三插件验证矩阵（2026-11-09 12:00–12:05，DSH 已重启，GUI 端口 4661）

| 插件 | 已安装 | 已启用 | 工具已加载 | **实测可用** | 证据 |
|---|---|---|---|---|---|
| dsh-doublecheck | ✅ | ✅ dep `^0.9.30` + bundles | ✅ `doublecheck_skills/spec/report` 在工具表 | ✅ `doublecheck_skills` 实调返回 4 个技能；4 个双检技能已进本会话技能目录 | 本会话两次工具调用输出 |
| dsh-diff-approval | ✅ | ✅ dep `^0.37.4` + bundles | ✅ `diff_approval_annotate` 等 | ✅ 实调 annotate 成功：`execution_log.md:34-38` 生成审查卡 `2e089162`，用户可在面板看到并回复 | 卡片 ID 2e089162-…-d4b67d719537 |
| dsh-computer-use-win | ✅ | ✅ dep `^0.5.5` + bundles | ✅ `mcp__wincu__*`（且只有一套） | ✅ 重启后 `health` OK（UIA/截图/OCR/浏览器通道全 true）+ `list_windows` 读到真实桌面：任务栏、Chrome 多窗口、**DSH 自己的主窗口**（有键盘焦点） | wincu 调用输出 |

**尚未实测（下次验收补）**：
1. doublecheck 的 `/gate` 红绿灯在真实需求上的走向（做 6.3 端到端时验证）；
2. diff-approval 在**代码 diff**（而非 md 行）上的 Keep/Revert 面板；
3. CUW 对 **PyQt 应用**的 UIA 控件树暴露程度——需要先启动 X-AnyLabeling 真实 GUI（当前未运行，窗口列表里只有 DSH/Chrome/系统窗口）；
4. 视觉链仍不可用（用户已决定不装新插件；像素断言 + OCR 兜底）。



## 回滚办法

- 卸任一个：GUI 插件市场卸载，或退出 DSH 后 `dsh plugin --profile desktop remove <包名>`。
- 卸载后需重启。
- profile 既有两个备份：`.backup-20261103-101037`、`.backup-manual-20261103-142641`。
- 删除本机新增的包装脚本：`.tooling/dsh-pytest.cmd`、`.tooling/dsh-pytest.sh`。
