"""摆放布局求解: 在一块隔板上生成互不重叠的候选格位。

策略: 按"最大偏航下的旋转包围盒"作为格元尺寸建网格, 保证任意偏航都不越界/不重叠。
返回格位中心的板面局部坐标 (x,y)(相对板心)。上层再从中随机取若干个并加抖动/偏航。
"""

import math


def rotated_footprint(length_x, width_y, yaw_deg):
    """长方形绕 Z 转 yaw 后的轴对齐包围盒尺寸。"""
    a = math.radians(abs(yaw_deg))
    c, s = abs(math.cos(a)), abs(math.sin(a))
    return (length_x * c + width_y * s, length_x * s + width_y * c)


def _centered_positions(usable, n):
    """在 [-usable/2, usable/2] 内均匀放 n 个中心点。"""
    if n <= 1:
        return [0.0]
    step = usable / n
    start = -usable / 2 + step / 2
    return [start + i * step for i in range(n)]


def grid_cells(board_length_x, board_width_y, sku_length_x, sku_width_y,
               max_yaw_deg, gap_m, edge_margin_m):
    """返回可容纳的格位中心列表 [(x,y), ...](板面局部坐标, 相对板心)。

    格元尺寸 = 最大偏航下的旋转包围盒 + gap, 因此后续任意 |yaw|<=max_yaw 都安全。
    """
    fx, fy = rotated_footprint(sku_length_x, sku_width_y, max_yaw_deg)
    cell_x, cell_y = fx + gap_m, fy + gap_m
    usable_x = max(0.0, board_length_x - 2 * edge_margin_m)
    usable_y = max(0.0, board_width_y - 2 * edge_margin_m)
    n_x = max(0, int(usable_x // cell_x))
    n_y = max(0, int(usable_y // cell_y))
    if n_x == 0 or n_y == 0:
        return []
    xs = _centered_positions(n_x * cell_x, n_x)
    ys = _centered_positions(n_y * cell_y, n_y)
    return [(x, y) for y in ys for x in xs]
