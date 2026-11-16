# AGENTS.md

给在此仓库工作的 AI 编码代理的说明。项目：**X-AnyLabeling 4.2.1**，PyQt6 跨平台桌面标注应用
（图像/视频/点云/多模态，内置大量自动标注模型）。许可证 GPL-3.0。

---

## 1. 环境（先看这条，容易踩坑）

- **PATH 里的 `python`（3.13，`AppData\Local\Programs\Python\Python313`）没装 PyQt6，不要用它跑程序或测试。**
- 本机可用开发环境：conda env **`x-anylabeling-cu12`**
  - Python 3.12，PyQt6 已装，onnxruntime 1.24.3（CUDA/TensorRT/CPU provider）
  - 直接调用：`C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe`
  - 或先 `conda activate x-anylabeling-cu12`
- 全新安装：`pip install -e ".[cpu,dev]"` 或 `".[gpu,dev]"`
  - 运行时 extras `cpu` / `gpu`(cu12) / `gpu-cu11` / `gpu-cu13` **互斥**（见 `pyproject.toml` 的 `[tool.uv].conflicts`）
  - **`onnxruntime` 与 `onnxruntime-gpu` 不能同时安装**
  - `dev` 额外带 PySide6，但应用代码用的是 **PyQt6**，不要混用两套绑定

---

## 2. 常用命令

```bash
# 运行
python anylabeling/app.py            # 也可用安装后的 xanylabeling 命令

# 测试（默认 addopts 已含 --doctest-modules --durations=30 --color=yes）
python -m pytest tests
python -m pytest tests/test_canvas          # 单目录
python -m pytest tests/test_canvas/test_xxx.py::test_yyy -x -q

# 格式 / 静态检查（移植自 pre-commit 的同款工具）
black .            # 也可 scripts/format_code.sh；line-length = 79
flake8             # max-line-length 79, max-complexity 18
pre-commit run --all-files
```

CI（`.github/workflows/release.yml`）实际跑的是：

```bash
pytest --ignore=tests/test_widgets/test_toolbar_layout.py --ignore=tests/test_pointcloud
xvfb-run -a -s "-screen 0 1920x1080x24" pytest --capture=sys tests/test_pointcloud   # 仅 Linux + xcb + 软件 GL
```

要点：

- `tests/test_widgets/test_toolbar_layout.py` 与 `tests/test_pointcloud/` **在 CI 被排除**；
  `test_pointcloud` 需要 `QT_QPA_PLATFORM=xcb` + xvfb，**在 Windows 上会失败**，别当成回归。
- `--doctest-modules` 生效：`anylabeling/` 里 docstring 写 `>>>` 的例子会被当测试执行，
  改 docstring 示例时要么保证可运行，要么别写 `>>>`。
- `tests/conftest.py` 强制 `QT_QPA_PLATFORM=offscreen`，并把每次测试的配置、工作目录、
  `QSettings` INI 全部重定向到仓库内 `.tmp/`。**测试若把配置写到 `.tmp/` 之外会被写保护断言判失败**——
  不要为了"跑通"而放宽这个 guard。
- Windows 上若遇到临时目录 ACL 残留导致的假失败，用 `.tmp` 下的独立 `--basetemp`
  （本机 `.tooling/dsh-pytest.cmd` 就是这种包装器，`.tooling/` 不入库）。

### Qt 集成测试防挂起

- `isolated_user_configuration` 在每条用例开始前清空配置会话，`QApplication`
  fixture 只提供 Qt 应用实例。直接构造 `MainWindow` 的集成测试应在隔离
  fixture 生效后，用 `get_config()` 加载 `.tmp/` 内的测试专用配置，再把
  返回的配置传给窗口。仅传配置模板、设置 `current_config_file` 或改 Qt
  fixture 的作用域都不会建立会话。保留现有配置写入保护。
- 窗口初始化期间保存偏好失败时，测试可能卡在 offscreen 的模态错误弹窗。
  先单跑相关用例，例如
  `tests/test_canvas/test_navigation.py::test_image_switch_restores_fractional_zoom_and_pan_and_fit_resets`，
  通过后再跑文件、受影响目录及全量。验证窗口初始化时保留真实的配置保存路径。
- 对可能弹窗的用例和全量回归，用 `-vv -o faulthandler_timeout=30`
  记录用例与堆栈，并用外层进程设置符合测试范围的硬超时
  （例如 Python 的 `subprocess.run(..., timeout=...)`）。
  `faulthandler_timeout` 只打印堆栈，结束进程靠外层超时。若堆栈卡在
  `QMessageBox.critical()`，保留用例名、原始错误和堆栈，查清触发路径后再重跑。

---

## 3. 目录结构

```
anylabeling/
  app.py                 入口（argparse、Qt 初始化、main()）
  app_info.py            __appname__ / __version__（版本号唯一来源，pyproject 动态读取）
  config.py              全局配置读写
  views/                 界面层
    mainwindow.py        主窗口（很薄，转发到 labeling 视图）
    labeling/            标注核心：label_widget.py（约 1.1 万行，画布/交互主战场）
                         另有 shape.py、label_file.py、label_converter.py、
                         editing_commands.py、settings/、widgets/、pointcloud/、
                         chatbot/、vqa/、ppocr/、classifier/、inspector/、dense_review/ 等
    common/              toaster、device_manager、converter、checks
    training/            训练相关界面
  services/              后端逻辑
    auto_labeling/       每个模型一个模块 + 对应 configs；model.py / model_manager.py 为调度核心
    auto_training/  inspection/  dense_review/  correction_metrics/  updates/
  configs/
    models.yaml          自动标注模型注册表
    xanylabeling_config.yaml  默认应用配置
    auto_labeling/*.yaml 每个模型一份参数配置
  resources/
    resources.qrc        Qt 资源定义
    resources.py         **由 qrc 编译生成，不要手改**
    images/ translations/
tests/                   约 236 个 py，按功能分目录，基本与 anylabeling 子模块一一对应
scripts/                 开发脚本（compile_languages.py 编译 qrc + 翻译、format_code.sh 等）
packaging/               pyinstaller / linux / windows 打包配置
docs/
  custom_changes/        对上游功能的改动记录（编号 CUSTOM-xxx + 日期-主题.md + TEMPLATE.md）
  development/           本机开发环境与工具记录（与产品功能无关）
  version-management/    工作区/版本整理记录
openspec/                spec-driven 变更方案（changes/ specs/ PENDING_TASKS.md）
reports/ perf_reports/ benchmarks/   验证证据、性能报告、基准记录
samples/ images/ assets/ examples/    样本/截图/资源/示例（保留现有引用路径）
.tmp/ .local/ .tooling/ .installers/  本机临时与工具目录，已 gitignore
```

---

## 4. 代码风格

- **行宽 79**（black + flake8 一致），black `target-version = py311`。
- flake8：`max-complexity = 18`；忽略 `E203,E266,E501,W503,F403,F401,B905,E402`；
  启用 `B,C,E,F,W,T4,B9`。pre-commit 还挂了 `flake8-docstrings` / `pydocstyle`，
  所以公开函数**写有意义的 docstring**（别写空壳）。
- 排除生成文件：`anylabeling/resources/resources.py`；black 不处理 `tests/`。
- 导入顺序与既有文件保持一致（Qt 导入通常集中在文件头，项目没强制 isort）。
- 中文注释、中文文档在本仓库很常见，与周边文件语言保持一致即可。
- 提交前：`black . && flake8`（或 `pre-commit run --all-files`，它还会查行尾空格、换行、codespell）。
- 生成/维护注意：改 `resources.qrc` 或翻译后要重跑 `scripts/compile_languages.py`；
  `resources.py` 的改动应来自编译而非手写。

---

## 5. 改动约定（本仓库特有，务必遵守）

- 功能改动、修复、迁移**都要留记录**，写到 `docs/custom_changes/<YYYY-MM-DD>-<主题>.md`，
  参照 `docs/custom_changes/TEMPLATE.md`，并在该目录 `README.md` 的索引表里登记 `CUSTOM-xxx`。
  记录中区分状态：方案 / 实施中 / 已实现待验证 / 已验证 / 已回退——**"方案"不能当"已完成"用**。
- 较大的新功能先在 `openspec/` 写方案（proposal / tasks / specs），再实施。
- 验证证据、性能数据放 `reports/`、`perf_reports/`、`benchmarks/`，不要塞进源码目录。
- 一次性实验放 `.tmp/`，本机工具脚本放 `.local/` / `.tooling/`（均不入库），不要散落到仓库根目录。
- `CHANGELOG.md` 是上游变更日志，本项目定制不要往里混写。

---

## 6. 修改时的实用提示

- `anylabeling/views/labeling/label_widget.py` 是超大文件（约 1.1 万行），
  改动要**外科手术式**定位，先 grep 定位再到函数级 diff，避免大范围重排。
- 新增自动标注模型的最小改动面：`services/auto_labeling/<model>.py`
  + `configs/auto_labeling/<model>.yaml` + 在 `configs/models.yaml` 注册。
- 单测大量依赖 Qt：跑测试前确认用的是 conda `x-anylabeling-cu12` 环境，否则会因缺 PyQt6 直接失败。
- 提 PR / 交付前至少跑一遍受影响的测试目录，并说明是否跑了被 CI 排除的那两项。

---

## 7. 版本管理与提交（约束）

- **不直接改 `versions/4.2.1`**（版本入口分支）。功能在本工作自己的分支上做；
  仓库没有长期 develop 分支，`main` 只是目录首页，不要往 `main` 合程序代码。
- 当前 4.2.1 的集成分支为 `codex/4.2.1-baseline-organization`。
  开工时核对实际分支状态，从包含任务所需依赖的已保存节点建立工作分支，
  记录起点提交号、验证状态和合入目标。继续同一任务时沿用已有工作分支。
  用户指定其他起点或目标时按其要求执行，并记录差异。
- 开工先检查 `git status` 和差异，明确已有改动的归属。
  **当前已授权任务的改动可以继续处理**。其他工作的改动应保留，
  可在独立工作区开展本任务。归属不清或操作可能覆盖已有成果时再询问。
  提交前核对暂存区内容，避免把其他任务的改动一起提交。
- 按**可独立验证的最小批次**提交，一个提交只说清一件事。
  拆分混合改动或回退前，先保留包含所需源码、新文件和文档的可恢复保存点，
  核对后续提交对目标改动的依赖。单功能提交可用 `git revert` 撤销，
  有依赖时一并处理必要调整，并运行受影响的测试。
  仅撤销某项功能时，应针对具体改动提交修复，避免整体撤销历史混合快照
  （如 `chore(snapshot)`）或恢复整个旧文件而连带覆盖其他功能。
- 提交信息沿用 `feat|fix|docs|test|chore|perf(scope): 中文说明`。
- 每个功能的"说明"写 `docs/custom_changes/`（CUSTOM-xxx），仓库级操作登记
  `docs/version-management/操作记录.md`。两者都要写，不要另起一套台账。
- 分支/标签沿用现有习惯：`codex/4.2.1/<功能名>`、
  `backup/4.2.1-YYYYMMDD-<用途>`（日期用北京时间）。
- 代理负责本任务的本地提交。**推送、开 PR、合入按用户明确授权执行**，
  在已授权的范围内继续完成，已有授权无需重复确认。
  推送后核对远端提交号，合入时核对目标分支及验证状态。
  交付时分别报告本地提交、远端推送、合入目标的实际状态，
  以及验证范围和未覆盖项。
- 人看的完整流程见 `GitHub操作说明.md`，这里不复述。
