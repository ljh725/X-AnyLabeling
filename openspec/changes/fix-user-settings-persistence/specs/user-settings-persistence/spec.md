## Purpose

为本地用户设置提供可预测的读取和写入目标、可合并的并发更新、完整文件保存和明确失败恢复，使用户已确认保存的快捷键及其他偏好能够在重新启动后可靠恢复。

## ADDED Requirements

### Requirement: Configuration source and persistence target are deterministic
系统 SHALL 在默认启动时读写用户工作目录的 `.xanylabelingrc`，在指定 `--work-dir` 时读写该目录的文件，在文件型 `--config` 时读写所选文件；不得悄悄改写另一目录。内联 YAML 和其他命令行覆盖 SHALL 视为临时启动值，只有用户明确修改并保存的字段才写入对应持久目标。

#### Scenario: Default Anaconda terminal startup
- **WHEN** 用户通过 `Python anylabeling/app.py` 启动，保存快捷键并以相同方式重启
- **THEN** 从同一用户配置位置恢复快捷键，工作目录变化不改变默认用户配置位置

#### Scenario: Work directory and file override
- **WHEN** 用户分别使用 `--work-dir` 或文件型 `--config` 启动并保存修改
- **THEN** 保存及后续读取使用选定目标，未选择的用户配置文件不被修改；两个参数同时指定时文件型 `--config` 决定配置目标

#### Scenario: Transient overrides remain transient
- **WHEN** 用户使用内联配置或命令行临时覆盖启动，随后保存一个不相关设置
- **THEN** 仅该明确修改被保存到工作目录配置，其他临时覆盖不会顺带固化

### Requirement: Concurrent saves preserve independent changes and detect conflicts
系统 SHALL 在同一配置目标上串行完成最新内容读取、冲突检查与提交。不同字段的更新 SHALL 合并；同一字段自编辑基线变化且与拟提交值不同时 MUST 拒绝静默覆盖并报告冲突；等值提交 SHALL 可安全重复。无法获得保存权时 SHALL 在有限等待后报告可重试状态。

#### Scenario: Two processes save independent fields
- **WHEN** 两个应用进程同时保存不同快捷键或数字映射与显示设置
- **THEN** 最终文件同时包含两份修改，双方未修改的有效配置和未知扩展字段保留

#### Scenario: Two processes conflict on one field
- **WHEN** 两个进程从同一基线给同一数字映射保存不同类别
- **THEN** 首次成功的内容保留，后续冲突可见，文件始终可解析，后续进程可重新载入后重试

### Requirement: Saving is atomic and failures remain visible
保存成功 SHALL 表示完整配置已提交到目标文件；失败 MUST 保留原有效文件、可重试修改和错误提示，不得显示成功或清除待保存状态。非法或损坏的原配置 MUST 保留，不得在下一次普通保存中被默认值静默替换。

#### Scenario: Replacement or write fails
- **WHEN** 保存遇到权限拒绝、写入失败或文件替换失败
- **THEN** 上一份有效配置仍可读取，界面报告失败并保留修改，解除故障后可重试

#### Scenario: Existing configuration is malformed
- **WHEN** 保存前发现目标配置损坏或结构不兼容
- **THEN** 保存停止并说明问题，原内容保留；恢复备份或重建必须经过用户明确选择

### Requirement: A valid previous configuration is available for recovery
系统 SHALL 保留最近一份经过解析验证的先前配置备份，提供可定位的备份位置及恢复说明；首次创建无旧配置时不得伪称存在备份。普通保存失败不得损坏原文件和已有有效备份，恢复操作 MUST 明确告知将采用的版本。

#### Scenario: Recover after external configuration damage
- **WHEN** 用户的当前配置被外部操作损坏并明确选择恢复有效备份
- **THEN** 可以恢复备份中的映射及快捷键，原损坏内容仍有保留依据，不推断备份中不存在的历史映射
