## Why

数据集标签缩略图中的数字快捷键改标在提交前已经进行影响范围确认，但提交完成后仍使用模态结果框要求用户再次点击，打断连续复核。与此同时，简单改用主窗口状态栏会在独立缩略图窗口中不可见，并会隐藏当前唯一展示的恢复清单路径，因此需要在不削弱预检、失败可见性和恢复能力的前提下移除第二次阻塞。

## What Changes

- 保留现有 dirty 处理、预检统计和提交前确认；数字快捷键仍不得无提示直接写盘。
- 让统一对象改标流程把结构化终态结果交给调用方呈现；缩略图入口不再使用通用 `QMessageBox.information`，改为窗口内独立、持久、非模态的结果条，而现有非缩略图入口继续保持其结果反馈。主反馈不使用主窗口状态栏或短时 Toast。
- 为全成功、无需写入、混合成功、部分失败、全部失败以及不同取消阶段定义确定的结果级别和文案。
- 成功项从选择中移除，失败/冲突项继续保留选择和逐项错误 overlay；结构化部分失败不再弹模态框。
- 在索引同步和当前页重载完成前设置缩略图本地刷新屏障，禁止按钮和数字快捷键再次发起改标，避免基于旧页面重复操作。
- 在成功或部分成功结果条中显示“恢复本次…”入口，直接绑定本次 `manifest_path`，不要求用户通过文件对话框自行寻找；同时展示或允许复制恢复清单路径。
- 将“恢复本次”明确为文件级事务恢复而非普通撤销，并在恢复前验证数据集归属、dirty 状态和提交后的文件状态，避免静默覆盖后续编辑。
- 保留无可信结构化结果的致命异常提示；普通成功、取消和结构化失败均由缩略图窗口内结果条承载。
- 补充 PyQt offscreen 测试、事务/恢复测试和中英文翻译资源。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `dataset-label-thumbnail-browser`: 将缩略图改标的终态反馈改为窗口内非模态结果条，规定刷新屏障、失败项保留、恢复入口及确定文案。
- `cross-image-object-relabel`: 调整统一对象改标流程的结果呈现契约，并加强从具体事务清单恢复时对提交后文件变化的保护。

## Impact

- 主要影响 `anylabeling/views/labeling/widgets/dataset_thumbnail/browser.py`、`anylabeling/views/labeling/widgets/object_relabel_dialog.py`、`anylabeling/views/labeling/label_widget.py`、`anylabeling/views/labeling/widgets/label_batch.py` 及相关测试。
- 不改变数字快捷键共享映射、对象身份匹配、预检确认、JSON 事实来源、原子提交流程或普通画布撤销语义。
- 需要新增结果条 UI 状态、事务结果格式化、索引刷新完成协调和恢复安全校验；无需新增第三方依赖。
