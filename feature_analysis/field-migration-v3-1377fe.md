# 71字段迁移方案改进建议

**版本**: 1.0
**日期**: 2026-02-27
**审阅范围**: field_migration 目录下全部10个文档

---

## 一、方案整体评价

### 1.1 优点

| 方面 | 评价 |
|------|------|
| **分层设计** | ✅ 基础设施层与具体迁移分离，proxy_pattern/shadow_write/switch_config 可复用 |
| **风险分级** | ✅ 低风险字段(Batch1/2)先行，高风险字段(Batch5)后置，符合渐进式迁移原则 |
| **双写校验** | ✅ 对 shapes/selected_shapes 核心数据提供一致性校验，降低数据丢失风险 |
| **三级回撤** | ✅ L1运行时/L2代码/L3数据，覆盖不同严重程度的故障场景 |
| **灰度策略** | ✅ 10%→50%→100% 渐进式发布，可控制爆炸半径 |

### 1.2 需要改进的问题

| 问题类型 | 数量 | 严重程度 |
|----------|------|----------|
| 架构层面 | 4个 | 中 |
| 技术实现 | 5个 | 高 |
| 测试覆盖 | 3个 | 中 |
| 风险控制 | 3个 | 中 |
| 文档完整性 | 4个 | 低 |
| **版本控制** | **1个** | **高** |

---

## 二、架构层面改进建议

### 2.1 缺少总体索引文档

**问题**: 10个文档分散在3个目录，缺少入口文档串联全局。

**建议**: 在 `field_migration/` 根目录创建 `README.md`：

```markdown
# 71字段迁移方案索引

## 快速导航
- [基础设施](./infrastructure/)
  - [Property代理模式](./infrastructure/proxy_pattern.md)
  - [Shadow双写机制](./infrastructure/shadow_write.md)
  - [Switch切换配置](./infrastructure/switch_config.md)
- [核心字段专项](./critical_fields/)
  - [shapes迁移](./critical_fields/shapes_migration.md)
  - [selected_shapes迁移](./critical_fields/selected_shapes_migration.md)
- [分批迁移](./batches/)
  - [Batch1: 配置与显示](./batches/batch1_config_display.md) - 35字段
  - [Batch2: 子系统状态](./batches/batch2_subsystem.md) - 12字段
  - [Batch3: 交互状态](./batches/batch3_interaction.md) - 14字段
  - [Batch4: 悬停链路](./batches/batch4_hover.md) - 6字段
  - [Batch5: 核心数据](./batches/batch5_core_data.md) - 5字段

## 迁移顺序
Batch1 → Batch2 → Batch3 → Batch4 → Batch5
```

### 2.2 字段数量不一致

**问题**: 标题声称71个字段，但各批次加起来为 35+12+14+6+5=72个。

**建议**: 
1. 核实实际字段数量
2. 在索引文档中列出完整字段清单
3. 标注每个字段的来源（旧Canvas代码行号）

### 2.3 缺少批次依赖关系图

**问题**: 批次间的依赖关系不明确，例如 Batch5 的 `shapes` 依赖 Batch3 的 `ShapeManager`。

**建议**: 添加依赖关系图：

```
Batch1 (独立)
    │
    ▼
Batch2 (依赖 Batch1 的 ConfigManager)
    │
    ▼
Batch3 (依赖 Batch2 的 LoadingManager)
    │
    ▼
Batch4 (依赖 Batch3 的 InputHandler)
    │
    ▼
Batch5 (依赖 Batch3/4 的 ShapeManager + CanvasGraphicsView)
```

### 2.4 critical_fields 与 batch5 内容重复

**问题**: `shapes_migration.md` 和 `batch5_core_data.md` 内容高度重叠。

**建议**: 
- `critical_fields/` 聚焦于**设计决策和技术细节**
- `batches/batch5` 聚焦于**实施步骤和验收标准**
- 使用交叉引用避免重复

---

## 三、技术实现改进建议

### 3.1 ShapesProxy 性能问题

**问题**: 每次列表操作都检查全局变量 `_MIGRATION_MODE`，高频访问场景下开销大。

**当前代码**:
```python
def __len__(self):
    if _MIGRATION_MODE == MigrationMode.LEGACY:  # 每次都检查
        return len(self._legacy_list)
    return len(self._shape_manager)
```

**建议**: 使用方法缓存或策略模式：

```python
class ShapesProxy:
    def __init__(self, shape_manager, adapter):
        self._shape_manager = shape_manager
        self._adapter = adapter
        self._legacy_list = []
        # 根据模式选择策略
        self._update_strategy()
    
    def _update_strategy(self):
        """模式变化时更新策略"""
        if _MIGRATION_MODE == MigrationMode.LEGACY:
            self._get_len = lambda: len(self._legacy_list)
            self._get_item = lambda i: self._legacy_list[i]
        else:
            self._get_len = lambda: len(self._shape_manager)
            self._get_item = lambda i: self._shape_manager[i]
    
    def __len__(self):
        return self._get_len()
    
    def __getitem__(self, index):
        return self._get_item(index)
```

### 3.2 一致性校验性能优化

**问题**: `_compute_signature` 使用 JSON 序列化 + MD5，对大量 shapes 可能很慢。

**当前代码**:
```python
def _compute_shapes_signature(shapes):
    sigs = []
    for shape in shapes:
        shape_json = json.dumps(shape.to_dict(), sort_keys=True)
        sigs.append(hashlib.md5(shape_json.encode()).hexdigest()[:16])
    return hashlib.md5(json.dumps(sorted(sigs)).encode()).hexdigest()[:32]
```

**建议**:

```python
def _compute_shapes_signature(shapes):
    """优化版：使用增量哈希"""
    if not shapes:
        return "empty"
    
    hasher = hashlib.md5()
    for shape in shapes:
        # 只哈希关键字段，避免完整序列化
        key_data = f"{shape.label}:{len(shape.points)}:{shape.shape_type}"
        hasher.update(key_data.encode())
    
    return hasher.hexdigest()[:32]

# 或使用缓存
from functools import lru_cache

@lru_cache(maxsize=128)
def _cached_shape_signature(shape_id, shape_version):
    """缓存单个形状的签名"""
    # shape_version 在形状修改时递增
    ...
```

### 3.3 信号连接设计冗余

**问题**: Batch2/3/4 中多个组件都定义了类似的信号（如 `started/finished`），缺乏统一基类。

**建议**: 提取公共基类：

```python
class StatefulComponent(QObject):
    """有状态组件基类"""
    state_changed = Signal(str, object, object)  # name, old_value, new_value
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = {}
    
    def set_state(self, name: str, value):
        old_value = self._state.get(name)
        if old_value != value:
            self._state[name] = value
            self.state_changed.emit(name, old_value, value)
    
    def get_state(self, name: str, default=None):
        return self._state.get(name, default)

# 使用示例
class LoadingManager(StatefulComponent):
    def __init__(self):
        super().__init__()
        self.set_state('is_loading', False)
        self.set_state('loading_text', 'Loading...')
```

### 3.4 双写装饰器缺少异步支持

**问题**: `shadow_write` 装饰器是同步的，对于大数据写入可能阻塞 UI。

**建议**: 添加异步双写选项：

```python
def shadow_write(field_name: str, target_component: str, async_write: bool = False):
    """双写装饰器 - 支持异步写入"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, value):
            # 同步写入旧位置
            setattr(self, f'_{field_name}_legacy', copy.deepcopy(value))
            
            if async_write:
                # 异步写入新位置
                QTimer.singleShot(0, lambda: _write_to_new(self, field_name, target_component, value))
            else:
                # 同步写入新位置
                _write_to_new(self, field_name, target_component, value)
            
            return func(self, value)
        return wrapper
    return decorator
```

### 3.5 降级后缺少自动恢复机制

**问题**: 触发降级后切换到 LEGACY 模式，但没有说明如何自动尝试恢复。

**建议**: 添加自动恢复尝试：

```python
class MigrationConfig:
    def __init__(self):
        self._degradation_time = None
        self._recovery_attempts = 0
        self._max_recovery_attempts = 3
        self._recovery_interval = 300  # 5分钟
    
    def trigger_degradation(self, field_name, reason):
        """触发降级"""
        self._degradation_time = time.time()
        self.set_mode(MigrationMode.LEGACY)
        
        # 启动恢复定时器
        if self._config.get('auto_recovery_interval', 0) > 0:
            QTimer.singleShot(
                self._recovery_interval * 1000,
                self._attempt_recovery
            )
    
    def _attempt_recovery(self):
        """尝试恢复到 SHADOW 模式"""
        if self._recovery_attempts >= self._max_recovery_attempts:
            logger.warning("Max recovery attempts reached, staying in LEGACY mode")
            return
        
        self._recovery_attempts += 1
        logger.info(f"Attempting recovery to SHADOW mode (attempt {self._recovery_attempts})")
        
        try:
            # 运行一致性检查
            if self._run_consistency_check():
                self.set_mode(MigrationMode.SHADOW)
                logger.info("Recovery successful!")
            else:
                # 再次尝试
                QTimer.singleShot(
                    self._recovery_interval * 1000,
                    self._attempt_recovery
                )
        except Exception as e:
            logger.error(f"Recovery failed: {e}")
```

---

## 四、测试覆盖改进建议

### 4.1 缺少可执行的自动化测试

**问题**: 文档中只有测试用例描述，没有可执行的测试代码。

**建议**: 为每个批次创建对应的测试文件：

```
tests/
├── test_batch1_config_display.py
├── test_batch2_subsystem.py
├── test_batch3_interaction.py
├── test_batch4_hover.py
├── test_batch5_core_data.py
└── test_migration_infrastructure.py
```

示例测试代码：

```python
# tests/test_batch5_core_data.py
import pytest
from anylabeling.views.labeling.canvas_adapter import CanvasAdapter
from anylabeling.views.labeling.migration_config import MigrationMode

class TestShapesMigration:
    @pytest.fixture
    def adapter(self):
        return CanvasAdapter()
    
    def test_shapes_dual_write(self, adapter):
        """测试 shapes 双写"""
        shapes = [Shape(label="test")]
        adapter.shapes = shapes
        
        # 验证旧位置
        assert len(adapter._shapes_legacy) == 1
        # 验证新位置
        assert len(adapter._shape_manager.shapes) == 1
    
    def test_shapes_consistency_check(self, adapter):
        """测试一致性校验"""
        # 制造不一致
        adapter._shapes_legacy = [Shape(label="old")]
        adapter._shape_manager._shapes = [Shape(label="new")]
        
        # 触发校验
        _ = adapter.shapes
        
        # 验证计数器递增
        assert adapter._inconsistency_counters['shapes'] == 1
    
    def test_auto_degradation(self, adapter):
        """测试自动降级"""
        # 连续触发不一致
        for _ in range(3):
            adapter._shapes_legacy = [Shape(label="old")]
            adapter._shape_manager._shapes = [Shape(label="new")]
            _ = adapter.shapes
        
        # 验证降级到 LEGACY
        assert MigrationConfig().mode == MigrationMode.LEGACY
```

### 4.2 缺少性能基准测试

**问题**: 声称"性能损耗<5%"但没有测量方法。

**建议**: 添加性能基准测试：

```python
# tests/test_performance_benchmark.py
import time
import pytest

class TestMigrationPerformance:
    @pytest.fixture
    def large_shapes(self):
        """生成大量测试形状"""
        return [Shape(label=f"shape_{i}") for i in range(1000)]
    
    def test_shapes_access_performance(self, adapter, large_shapes):
        """测试 shapes 访问性能"""
        adapter.shapes = large_shapes
        
        # 基准：直接访问列表
        start = time.perf_counter()
        for _ in range(1000):
            _ = len(adapter._shapes_legacy)
        baseline = time.perf_counter() - start
        
        # 测试：通过 property 访问
        start = time.perf_counter()
        for _ in range(1000):
            _ = len(adapter.shapes)
        with_proxy = time.perf_counter() - start
        
        # 验证性能损耗 < 5%
        overhead = (with_proxy - baseline) / baseline
        assert overhead < 0.05, f"Performance overhead {overhead:.2%} exceeds 5%"
    
    def test_consistency_check_performance(self, adapter, large_shapes):
        """测试一致性校验性能"""
        adapter.shapes = large_shapes
        
        start = time.perf_counter()
        adapter._check_shapes_consistency(
            adapter._shapes_legacy,
            adapter._shape_manager.shapes
        )
        duration = time.perf_counter() - start
        
        # 校验应在 10ms 内完成
        assert duration < 0.01, f"Consistency check took {duration*1000:.2f}ms"
```

### 4.3 缺少回归测试套件

**问题**: 没有定义哪些现有功能需要回归测试。

**建议**: 创建回归测试清单：

```python
# tests/test_regression_suite.py
"""
迁移回归测试套件
覆盖所有可能受迁移影响的核心功能
"""

REGRESSION_TEST_CASES = [
    # 基础操作
    ("打开图片", "test_open_image"),
    ("保存标注", "test_save_annotation"),
    ("撤销/重做", "test_undo_redo"),
    
    # 形状操作
    ("创建矩形", "test_create_rectangle"),
    ("创建多边形", "test_create_polygon"),
    ("移动形状", "test_move_shape"),
    ("删除形状", "test_delete_shape"),
    ("复制粘贴", "test_copy_paste"),
    
    # 选择操作
    ("单选形状", "test_select_single"),
    ("多选形状", "test_select_multiple"),
    ("全选", "test_select_all"),
    ("取消选择", "test_deselect"),
    
    # 悬停操作
    ("悬停高亮", "test_hover_highlight"),
    ("右键菜单", "test_context_menu"),
    
    # 配置操作
    ("切换显示选项", "test_toggle_display"),
    ("修改配置", "test_modify_config"),
]
```

---

## 五、风险控制改进建议

### 5.1 灰度控制粒度不足

**问题**: 只按用户ID灰度，无法按功能模块控制。

**建议**: 支持多维度灰度：

```python
class GradualRollout:
    def __init__(self):
        self._user_percentage = 0
        self._feature_flags = {}
    
    def is_enabled_for(self, user_id: str, feature: str = None) -> bool:
        """多维度灰度判断"""
        # 1. 检查功能级开关
        if feature and feature in self._feature_flags:
            return self._feature_flags[feature]
        
        # 2. 检查用户级灰度
        hash_val = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
        return (hash_val % 100) < self._user_percentage
    
    def set_feature_flag(self, feature: str, enabled: bool):
        """设置功能级开关"""
        self._feature_flags[feature] = enabled

# 使用示例
rollout = GradualRollout()
rollout.set_feature_flag('shapes_new_logic', True)   # 强制启用
rollout.set_feature_flag('hover_new_logic', False)   # 强制禁用
```

### 5.2 监控指标不完整

**问题**: 只有 `ShadowMetrics` 数据类，缺少实际的监控上报。

**建议**: 添加监控上报接口：

```python
class MigrationMonitor:
    """迁移监控器"""
    
    def __init__(self):
        self._metrics = defaultdict(ShadowMetrics)
        self._report_interval = 60  # 每分钟上报
        self._start_reporting()
    
    def record_access(self, field_name: str, access_type: str):
        """记录字段访问"""
        self._metrics[field_name].access_count += 1
    
    def record_inconsistency(self, field_name: str):
        """记录不一致"""
        self._metrics[field_name].inconsistency_count += 1
    
    def record_degradation(self, field_name: str, reason: str):
        """记录降级事件"""
        self._metrics[field_name].degradation_events.append({
            'time': time.time(),
            'reason': reason
        })
    
    def _start_reporting(self):
        """启动定期上报"""
        self._report_timer = QTimer()
        self._report_timer.timeout.connect(self._report_metrics)
        self._report_timer.start(self._report_interval * 1000)
    
    def _report_metrics(self):
        """上报指标"""
        report = {
            'timestamp': time.time(),
            'mode': MigrationConfig().mode.value,
            'fields': {
                name: {
                    'access_count': m.access_count,
                    'inconsistency_count': m.inconsistency_count,
                    'degradation_count': len(m.degradation_events)
                }
                for name, m in self._metrics.items()
            }
        }
        
        # 写入本地日志
        logger.info(f"Migration metrics: {json.dumps(report)}")
        
        # TODO: 上报到监控系统
        # self._send_to_monitoring_system(report)
```

### 5.3 回撤演练缺少自动化

**问题**: L1/L2/L3 回撤演练是手动的，容易遗漏。

**建议**: 创建回撤演练脚本：

```python
# scripts/migration_rollback_drill.py
"""
迁移回撤演练脚本
定期执行以验证回撤机制有效
"""

def drill_l1_runtime_rollback():
    """L1 运行时回退演练"""
    print("=== L1 Runtime Rollback Drill ===")
    
    # 1. 记录当前状态
    original_mode = MigrationConfig().mode
    
    # 2. 模拟降级
    MigrationConfig().trigger_degradation('shapes', 'drill')
    
    # 3. 验证降级生效
    assert MigrationConfig().mode == MigrationMode.LEGACY
    
    # 4. 恢复原状态
    MigrationConfig().set_mode(original_mode)
    
    print("✅ L1 drill passed")

def drill_l2_code_rollback():
    """L2 代码回滚演练"""
    print("=== L2 Code Rollback Drill ===")
    
    # 1. 检查 git 状态
    result = subprocess.run(['git', 'status', '--porcelain'], capture_output=True)
    if result.stdout:
        print("⚠️ Working directory not clean, skipping L2 drill")
        return
    
    # 2. 创建测试分支
    subprocess.run(['git', 'checkout', '-b', 'drill/l2-test'])
    
    # 3. 模拟回滚
    subprocess.run(['git', 'revert', '--no-commit', 'HEAD'])
    
    # 4. 验证回滚
    # ... 运行测试 ...
    
    # 5. 清理
    subprocess.run(['git', 'checkout', '-'])
    subprocess.run(['git', 'branch', '-D', 'drill/l2-test'])
    
    print("✅ L2 drill passed")

if __name__ == '__main__':
    drill_l1_runtime_rollback()
    drill_l2_code_rollback()
```

---

## 六、文档完整性改进建议

### 6.1 缺少实际代码位置引用

**问题**: 文档中的代码示例是伪代码，没有标注实际文件位置。

**建议**: 添加代码位置引用：

```markdown
### 实际代码位置

| 组件 | 文件路径 | 行号范围 |
|------|----------|----------|
| CanvasAdapter | `anylabeling/views/labeling/canvas_adapter.py` | L1-L500 |
| ShapeManager | `anylabeling/views/labeling/shape_manager.py` | L1-L300 |
| MigrationConfig | `anylabeling/views/labeling/migration_config.py` | L1-L150 |
```

### 6.2 缺少变更日志模板

**建议**: 添加变更日志模板：

```markdown
## 变更日志

### [Batch5] 2026-02-XX
- ✅ 实现 shapes 双写机制
- ✅ 实现 selected_shapes 双写机制
- ✅ 添加一致性校验
- ⏳ 灰度发布中 (当前 10%)

### [Batch4] 2026-02-XX
- ✅ 实现悬停链路迁移
- ✅ 验证右键菜单联动
```

### 6.3 缺少故障排查指南

**建议**: 添加故障排查文档：

```markdown
## 故障排查指南

### 问题1: shapes 不一致告警频繁

**症状**: 日志中频繁出现 `shapes inconsistency detected`

**排查步骤**:
1. 检查是否有外部代码直接修改 `_shapes_legacy`
2. 检查 ShapeManager 的信号是否正确连接
3. 启用 `_DEBUG_MIGRATION` 查看访问来源

**解决方案**:
- 如果是外部代码问题，修改外部代码使用 property
- 如果是信号问题，检查 `connect()` 调用
```

### 6.4 缺少术语表

**建议**: 添加术语表：

```markdown
## 术语表

| 术语 | 定义 |
|------|------|
| Property 代理 | 通过 Python property 将字段访问转发到新架构组件 |
| Shadow 双写 | 同时写入新旧两个存储位置，用于校验一致性 |
| 灰度发布 | 按比例逐步启用新逻辑，控制风险 |
| L1 回退 | 运行时切换配置，立即生效 |
| L2 回滚 | Git revert 代码变更 |
| L3 恢复 | 从数据快照恢复 |
```

---

## 七、GitHub 分支推送方案

### 7.1 分支策略设计

为确保每个批次的修改可独立回退，采用以下分支策略：

```
main (稳定分支)
  │
  ├── develop (开发主分支)
  │     │
  │     ├── migrate/infrastructure (基础设施)
  │     │     ├── migrate/infra-proxy-pattern
  │     │     ├── migrate/infra-shadow-write
  │     │     └── migrate/infra-switch-config
  │     │
  │     ├── migrate/batch1-config-display (35字段)
  │     │
  │     ├── migrate/batch2-subsystem (12字段)
  │     │
  │     ├── migrate/batch3-interaction (14字段)
  │     │
  │     ├── migrate/batch4-hover (6字段)
  │     │
  │     └── migrate/batch5-core-data (5字段)
  │           ├── migrate/batch5a-backups
  │           ├── migrate/batch5b-scale-pixmap
  │           ├── migrate/batch5c-shapes
  │           └── migrate/batch5d-selected-shapes
  │
  └── release/vX.X.X (发布分支)
```

### 7.2 分支命名规范

| 分支类型 | 命名格式 | 示例 |
|----------|----------|------|
| 基础设施 | `migrate/infra-{component}` | `migrate/infra-proxy-pattern` |
| 批次主分支 | `migrate/batch{N}-{name}` | `migrate/batch1-config-display` |
| 批次子分支 | `migrate/batch{N}{sub}-{name}` | `migrate/batch5c-shapes` |
| 修复分支 | `migrate/fix-{issue}` | `migrate/fix-shapes-consistency` |

### 7.3 推送流程

#### Step 1: 创建基础设施分支

```bash
# 从 develop 创建基础设施分支
git checkout develop
git pull origin develop

# 创建并推送基础设施分支
git checkout -b migrate/infrastructure
git push -u origin migrate/infrastructure

# 实现 proxy_pattern
git checkout -b migrate/infra-proxy-pattern
# ... 编写代码 ...
git add .
git commit -m "feat(migrate): implement property proxy pattern

- Add proxy template for 71 fields
- Support simple/logging/validation modes
- Add batch generation script"
git push -u origin migrate/infra-proxy-pattern

# 创建 PR: migrate/infra-proxy-pattern → migrate/infrastructure
```

#### Step 2: 按批次推送

```bash
# Batch 1: 配置与显示
git checkout migrate/infrastructure
git checkout -b migrate/batch1-config-display

# 实现 ConfigManager
git add anylabeling/views/labeling/config_manager.py
git commit -m "feat(migrate/batch1): add ConfigManager for 7 config fields"

# 实现 DisplayOptionsManager
git add anylabeling/views/labeling/display_options_manager.py
git commit -m "feat(migrate/batch1): add DisplayOptionsManager for 8 display fields"

# 实现 Property 代理
git add anylabeling/views/labeling/canvas_adapter.py
git commit -m "feat(migrate/batch1): add property proxies for 35 fields"

# 添加测试
git add tests/test_batch1_config_display.py
git commit -m "test(migrate/batch1): add unit tests for config/display migration"

# 推送并创建 PR
git push -u origin migrate/batch1-config-display
# PR: migrate/batch1-config-display → develop
```

#### Step 3: Batch 5 子分支推送（高风险批次）

```bash
# Batch 5 主分支
git checkout develop
git checkout -b migrate/batch5-core-data

# 5a: shapes_backups（低风险子批次）
git checkout -b migrate/batch5a-backups
# ... 实现 ...
git push -u origin migrate/batch5a-backups
# PR: migrate/batch5a-backups → migrate/batch5-core-data

# 5b: scale + pixmap
git checkout migrate/batch5-core-data
git merge migrate/batch5a-backups
git checkout -b migrate/batch5b-scale-pixmap
# ... 实现 ...
git push -u origin migrate/batch5b-scale-pixmap
# PR: migrate/batch5b-scale-pixmap → migrate/batch5-core-data

# 5c: shapes（极高风险）
git checkout migrate/batch5-core-data
git merge migrate/batch5b-scale-pixmap
git checkout -b migrate/batch5c-shapes
# ... 实现 ...
git push -u origin migrate/batch5c-shapes
# PR: migrate/batch5c-shapes → migrate/batch5-core-data

# 5d: selected_shapes（极高风险）
git checkout migrate/batch5-core-data
git merge migrate/batch5c-shapes
git checkout -b migrate/batch5d-selected-shapes
# ... 实现 ...
git push -u origin migrate/batch5d-selected-shapes
# PR: migrate/batch5d-selected-shapes → migrate/batch5-core-data
```

### 7.4 回退操作指南

#### 场景1: 单个批次回退

```bash
# 假设 Batch 3 出现问题，需要回退

# 方法1: Revert PR（推荐）
# 在 GitHub 上找到 Batch 3 的 PR，点击 "Revert" 按钮

# 方法2: 手动 Revert
git checkout develop
git revert --no-commit <batch3-merge-commit>
git commit -m "revert(migrate/batch3): rollback interaction migration due to #123"
git push origin develop
```

#### 场景2: 子批次回退（Batch 5）

```bash
# 假设 Batch 5c (shapes) 出现问题

# 1. 切换到 batch5 主分支
git checkout migrate/batch5-core-data

# 2. 重置到 5b 状态
git reset --hard migrate/batch5b-scale-pixmap

# 3. 强制推送（需要权限）
git push --force-with-lease origin migrate/batch5-core-data

# 4. 通知团队
echo "⚠️ Batch 5c reverted, please re-pull migrate/batch5-core-data"
```

#### 场景3: 紧急全量回退

```bash
# 所有迁移出现严重问题，需要回退到迁移前状态

# 1. 找到迁移前的 commit
git log --oneline | grep "before migration"
# 假设是 abc1234

# 2. 创建紧急回退分支
git checkout -b hotfix/revert-all-migration abc1234

# 3. 推送并创建紧急 PR
git push -u origin hotfix/revert-all-migration
# PR: hotfix/revert-all-migration → main (紧急合并)
```

### 7.5 PR 模板

```markdown
## 迁移 PR 模板

### 批次信息
- **批次**: Batch X - {name}
- **字段数量**: X 个
- **风险等级**: 低/中/高/极高

### 变更内容
- [ ] 新增组件: {component_name}
- [ ] Property 代理: {field_count} 个
- [ ] 单元测试: {test_count} 个

### 测试验证
- [ ] 单元测试通过
- [ ] 基线测试通过
- [ ] 性能测试通过（损耗 < 5%）

### 回退方案
- L1: `MigrationConfig().set_mode(MigrationMode.LEGACY)`
- L2: `git revert {this-commit}`

### 依赖
- 依赖 PR: #{pr_number}
- 被依赖: #{pr_number}

### 灰度计划
- [ ] 10% 灰度 (2天)
- [ ] 50% 灰度 (3天)
- [ ] 100% 全量
```

### 7.6 CI/CD 集成

```yaml
# .github/workflows/migration-ci.yml
name: Migration CI

on:
  push:
    branches:
      - 'migrate/**'
  pull_request:
    branches:
      - develop
      - 'migrate/**'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: pip install -r requirements-dev.txt
      
      - name: Run migration tests
        run: |
          pytest tests/test_batch*.py -v --tb=short
      
      - name: Run performance benchmark
        run: |
          pytest tests/test_performance_benchmark.py -v
      
      - name: Check migration mode
        run: |
          python -c "
          from anylabeling.views.labeling.migration_config import MigrationConfig, MigrationMode
          config = MigrationConfig()
          print(f'Current mode: {config.mode}')
          assert config.mode in [MigrationMode.LEGACY, MigrationMode.SHADOW, MigrationMode.NEW]
          "

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Run flake8
        run: |
          pip install flake8
          flake8 anylabeling/views/labeling/ --max-line-length=120
```

### 7.7 分支保护规则

在 GitHub 仓库设置中配置：

| 分支 | 保护规则 |
|------|----------|
| `main` | 需要 2 人 review，禁止强制推送，需要 CI 通过 |
| `develop` | 需要 1 人 review，禁止强制推送，需要 CI 通过 |
| `migrate/*` | 需要 1 人 review，允许维护者强制推送（用于回退） |

---

## 八、总结

### 改进优先级

| 优先级 | 改进项 | 预计工时 |
|--------|--------|----------|
| P0 | GitHub 分支推送方案 | 0.5天 |
| P0 | 创建总体索引文档 | 0.5天 |
| P1 | ShapesProxy 性能优化 | 1天 |
| P1 | 添加自动化测试 | 2天 |
| P2 | 一致性校验性能优化 | 1天 |
| P2 | 添加监控上报 | 1天 |
| P3 | 完善故障排查指南 | 0.5天 |
| P3 | 添加术语表 | 0.5天 |

### 下一步行动

1. **立即执行**: 创建 `README.md` 索引文档
2. **本周完成**: 实现 GitHub 分支策略，创建基础设施分支
3. **下周完成**: 添加自动化测试框架
4. **持续改进**: 根据实际迁移过程中的问题更新文档

---

*文档版本: 1.0 | 最后更新: 2026-02-27*
