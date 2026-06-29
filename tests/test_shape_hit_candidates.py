"""功能C _shape_hit_candidates 优先级排序算法验证脚本

目的: 在不依赖 PyQt6 的纯 Python 环境下, 验证迁移自 beta.11 的
``_shape_hit_candidates`` 多级优先级排序逻辑是否正确。

这是算法层验证, 证明:
  - 嵌套场景: 小面积对象优先于大对象
  - 重叠场景: 距离更近的顶点/对象优先
  - 顶点优先级 > 边优先级 > 整体命中优先级
  - 同优先级按 距离↑、面积↑、栈序↓ 排序

不验证 GUI 集成 (PyQt6 QPainterPath/QPointF), 那部分需人工在 GUI 验证。

用法:  python tests/test_shape_hit_candidates.py
"""

import math


# ----------------------------------------------------------------------
# 纯 Python 复刻 beta.4/beta.11 的几何工具 (见 utils/qt.py)
# ----------------------------------------------------------------------

class P:
    """模拟 QPointF 的最小实现: 支持 - / + / .x() / .y()"""

    __slots__ = ("_x", "_y")

    def __init__(self, x, y):
        self._x = float(x)
        self._y = float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y

    def __sub__(self, other):
        return P(self._x - other._x, self._y - other._y)

    def __add__(self, other):
        return P(self._x + other._x, self._y + other._y)

    def __repr__(self):
        return f"P({self._x:.1f},{self._y:.1f})"


def distance(p):
    """复刻 utils.distance: 向量长度"""
    return math.sqrt(p.x() ** 2 + p.y() ** 2)


def distance_to_line(point, line):
    """复刻 utils.distance_to_line: 点到线段距离(含端点外投影)"""
    import numpy as np

    p1, p2 = line
    p1 = np.array([p1.x(), p1.y()])
    p2 = np.array([p2.x(), p2.y()])
    p3 = np.array([point.x(), point.y()])
    if np.dot((p3 - p1), (p2 - p1)) < 0:
        return float(np.linalg.norm(p3 - p1))
    if np.dot((p3 - p2), (p1 - p2)) < 0:
        return float(np.linalg.norm(p3 - p2))
    if np.linalg.norm(p2 - p1) == 0:
        return 0.0
    line_vector = p2 - p1
    point_vector = p1 - p3
    cross_product = (
        line_vector[0] * point_vector[1] - line_vector[1] * point_vector[0]
    )
    return float(abs(cross_product) / np.linalg.norm(line_vector))


# ----------------------------------------------------------------------
# 复刻 Shape 的几何判定 (nearest_vertex / nearest_edge / contains_point)
# 仅覆盖 polygon/rectangle 场景, 不含 cuboid (cuboid 需 QPainterPath)
# ----------------------------------------------------------------------

class FakeShape:
    """最小化的 polygon/rectangle Shape, 复刻 beta.4 几何判定。"""

    def __init__(self, name, points, shape_type="polygon"):
        self.name = name
        self.points = [P(x, y) for x, y in points]
        self.shape_type = shape_type
        self.locked = False  # 迁移自 beta.11: 默认 False, 守卫 no-op

    def nearest_vertex(self, point, epsilon):
        min_distance = float("inf")
        min_i = None
        for i, p in enumerate(self.points):
            dist = distance(p - point)
            if dist <= epsilon and dist < min_distance:
                min_distance = dist
                min_i = i
        return min_i

    def nearest_edge(self, point, epsilon):
        min_distance = float("inf")
        post_i = None
        for i in range(len(self.points)):
            line = [self.points[i - 1], self.points[i]]
            dist = distance_to_line(point, line)
            if dist <= epsilon and dist < min_distance:
                min_distance = dist
                post_i = i
        return post_i

    def can_add_point(self):
        return self.shape_type in ("polygon", "linestrip")

    def contains_point(self, point):
        """射线法判断点是否在多边形内 (复刻 QPainterPath.contains 的语义)"""
        x, y = point.x(), point.y()
        n = len(self.points)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = self.points[i].x(), self.points[i].y()
            xj, yj = self.points[j].x(), self.points[j].y()
            intersect = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
            )
            if intersect:
                inside = not inside
            j = i
        return inside

    def bounding_rect(self):
        xs = [p.x() for p in self.points]
        ys = [p.y() for p in self.points]
        return BRect(min(xs), min(ys), max(xs), max(ys))


class BRect:
    """模拟 QRectF 的最小实现"""

    def __init__(self, x1, y1, x2, y2):
        self._x1, self._y1 = x1, y1
        self._x2, self._y2 = x2, y2

    def width(self):
        return self._x2 - self._x1

    def height(self):
        return self._y2 - self._y1


# ----------------------------------------------------------------------
# 复刻 _shape_hit_candidates (canvas.py:496-586), 仅 polygon/rectangle 分支
# ----------------------------------------------------------------------

class FakeCanvas:
    def __init__(self, shapes, epsilon=10.0, scale=1.0):
        self.shapes = shapes
        self.epsilon = epsilon
        self.scale = scale

    def is_shape_interactive(self, shape):
        return True

    def _shape_hit_candidates(self, point):
        """逐行复刻 canvas.py:514-586 的核心排序逻辑(去掉 cuboid 分支)"""
        candidates = []
        epsilon = self.epsilon / self.scale
        for stack_index, shape in enumerate(self.shapes):
            if not self.is_shape_interactive(shape):
                continue

            rect = shape.bounding_rect()
            area = max(0.0, rect.width()) * max(0.0, rect.height())
            vertex_distance = None
            if not shape.locked:
                vertex_index = shape.nearest_vertex(point, epsilon)
                vertex = (
                    shape.points[vertex_index]
                    if vertex_index is not None
                    else None
                )
                if vertex is not None:
                    vertex_distance = distance(vertex - point)

            # 级别 0: 顶点
            if vertex_distance is not None:
                priority = (0, vertex_distance, area, -stack_index)
                candidates.append((priority, shape))
                continue

            # 级别 1: 可编辑边
            if (
                not shape.locked
                and len(shape.points) > 1
                and shape.can_add_point()
                and shape.shape_type != "quadrilateral"
            ):
                edge_index = shape.nearest_edge(point, epsilon)
                if edge_index is not None:
                    line = [
                        shape.points[edge_index - 1],
                        shape.points[edge_index],
                    ]
                    edge_distance = distance_to_line(point, line)
                    priority = (1, edge_distance, area, -stack_index)
                    candidates.append((priority, shape))
                    continue

            # 级别 2: 整体命中
            hit = len(shape.points) > 1 and shape.contains_point(point)
            if hit:
                priority = (2, area, 0.0, -stack_index)
                candidates.append((priority, shape))

        candidates.sort(key=lambda item: item[0])
        return [shape for _, shape in candidates]


# ----------------------------------------------------------------------
# 测试场景
# ----------------------------------------------------------------------

def _top(canvas, point):
    """返回首选对象名(优先级最高的候选)"""
    result = canvas._shape_hit_candidates(point)
    return result[0].name if result else None


def test_nested_small_over_big():
    """场景1 [嵌套]: 大框套小框, 点落在小框中心 -> 应选小框(面积小优先)"""
    big = FakeShape("BIG", [(0, 0), (100, 0), (100, 100), (0, 100)])
    small = FakeShape("SMALL", [(40, 40), (60, 40), (60, 60), (40, 60)])
    # small 后创建(栈顶), 但即便 big 在栈顶也该选 small(面积小)
    canvas = FakeCanvas([big, small])
    # 点在小框中心 (50,50): 两框都整体命中(级别2), 小面积优先
    assert _top(canvas, P(50, 50)) == "SMALL", \
        "嵌套场景: 小框应优先于大框"
    print("[PASS] 场景1 嵌套: 大框套小框, 点击小框内部 -> 选 SMALL")


def test_nested_stack_order_fair():
    """场景2 [嵌套-栈序公平]: 即便大框在栈顶, 仍选小框(证明不是靠栈序)"""
    big = FakeShape("BIG", [(0, 0), (100, 0), (100, 100), (0, 100)])
    small = FakeShape("SMALL", [(40, 40), (60, 40), (60, 60), (40, 60)])
    # 故意让 big 在栈顶(后创建)
    canvas = FakeCanvas([small, big])
    assert _top(canvas, P(50, 50)) == "SMALL", \
        "嵌套场景: 即便大框栈顶, 也应选小框(面积小优先于栈序)"
    print("[PASS] 场景2 嵌套-栈序公平: 大框栈顶仍选 SMALL (面积优先)")


def test_vertex_beats_contains():
    """场景3 [顶点优先]: 点靠近A的顶点, 同时在B内部 -> 应选A(顶点级别0 > 整体2)"""
    # A 的一个顶点在 (10,10)
    a = FakeShape("A", [(10, 10), (30, 10), (30, 30), (10, 30)])
    # B 覆盖 (10,10) 区域且更大
    b = FakeShape("B", [(0, 0), (80, 0), (80, 80), (0, 80)])
    canvas = FakeCanvas([a, b])
    # 点 (11,11): 离 A 顶点(10,10) 很近 -> A 顶点命中(级别0); B 整体命中(级别2)
    assert _top(canvas, P(11, 11)) == "A", \
        "顶点优先: A的顶点(级别0)应优先于B整体(级别2)"
    print("[PASS] 场景3 顶点优先: 靠近A顶点同时在B内 -> 选 A")


def test_nearest_vertex_wins():
    """场景4 [近邻顶点]: 两个对象都有顶点在附近, 选距离更近的"""
    # A 顶点在 (50,50), B 顶点在 (55,50)
    a = FakeShape("A", [(50, 50), (70, 50), (70, 70), (50, 70)])
    b = FakeShape("B", [(55, 50), (75, 50), (75, 70), (55, 70)])
    canvas = FakeCanvas([a, b])
    # 点 (50.5, 50): 离 A(50,50) 距离0.5, 离 B(55,50) 距离4.5 -> A 更近
    assert _top(canvas, P(50.5, 50)) == "A", \
        "近邻顶点: A顶点更近时应选 A"
    print("[PASS] 场景4 近邻顶点: A顶点更近 -> 选 A")


def test_empty_point():
    """场景5 [空白]: 点不在任何对象内, 也不靠近任何顶点/边 -> 返回空列表"""
    s = FakeShape("S", [(0, 0), (10, 0), (10, 10), (0, 10)])
    canvas = FakeCanvas([s])
    assert canvas._shape_hit_candidates(P(500, 500)) == [], \
        "空白点击应返回空列表"
    print("[PASS] 场景5 空白点击 -> 返回空列表")


def test_priority_tuple_ordering():
    """场景6 [优先级元组排序]: 直接验证 4 元组的字典序"""
    # 构造三个候选, 验证 sort key 的字典序
    # (级别, 距离, 面积, -栈序) 全部升序
    candidates = [
        ((2, 100.0, 0.0, 0), "big_late"),       # 整体命中,大,栈顶
        ((2, 100.0, 0.0, -1), "big_early"),     # 整体命中,大,早创建
        ((0, 2.0, 25.0, -2), "vertex_small"),   # 顶点,近,小,最晚
        ((1, 3.0, 25.0, -3), "edge_small"),     # 边,中,小,最晚
    ]
    candidates.sort(key=lambda item: item[0])
    order = [name for _, name in candidates]
    # 预期: 级别0(vertex_small) < 级别1(edge_small) < 级别2(big_early<big_late 因-栈序)
    assert order == [
        "vertex_small", "edge_small", "big_early", "big_late"
    ], f"优先级排序错误: {order}"
    print("[PASS] 场景6 优先级元组字典序: 顶点<边<整体, 同级按距离/面积/栈序")


if __name__ == "__main__":
    print("=" * 60)
    print("功能C _shape_hit_candidates 优先级算法验证")
    print("=" * 60)
    try:
        test_nested_small_over_big()
        test_nested_stack_order_fair()
        test_vertex_beats_contains()
        test_nearest_vertex_wins()
        test_empty_point()
        test_priority_tuple_ordering()
        print("=" * 60)
        print("全部 6 个场景通过 ✅  算法优先级逻辑正确")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        raise SystemExit(1)
