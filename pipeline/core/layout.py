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


def max_footprint(length_x, width_y, max_yaw_deg):
    """|yaw|<=max_yaw 范围内 AABB 的最大尺寸。

    注意: AABB 的 x/y 分量各自在某个中间角取极大(x 分量峰值在 atan(W/L)), 并非在极值角,
    因此不能只看 max_yaw 处的值(否则跨过峰值角时会低估, 导致格子过密而碰撞)。
    """
    m = math.radians(abs(max_yaw_deg))
    ax = math.atan2(width_y, length_x)      # x 分量峰值角
    ay = math.atan2(length_x, width_y)      # y 分量峰值角

    def fx(a):
        return length_x * abs(math.cos(a)) + width_y * abs(math.sin(a))

    def fy(a):
        return length_x * abs(math.sin(a)) + width_y * abs(math.cos(a))

    xs = [0.0, m] + ([ax] if 0.0 <= ax <= m else [])
    ys = [0.0, m] + ([ay] if 0.0 <= ay <= m else [])
    return (max(fx(a) for a in xs), max(fy(a) for a in ys))


def _obb(cx, cy, lx, ly, yaw_deg):
    """返回 (两条局部轴, 四个角点), 用于 SAT 重叠判定。"""
    a = math.radians(yaw_deg)
    c, s = math.cos(a), math.sin(a)
    ux, uy = (c, s), (-s, c)
    hx, hy = lx / 2.0, ly / 2.0
    corners = [(cx + ux[0] * sx * hx + uy[0] * sy * hy,
                cy + ux[1] * sx * hx + uy[1] * sy * hy)
               for sx in (-1, 1) for sy in (-1, 1)]
    return (ux, uy), corners


def obb_overlap(a, b, margin=0.0):
    """两个旋转矩形是否重叠(分离轴定理)。a,b = (cx,cy,lx,ly,yaw_deg)。

    margin>0 时把两者各向外扩 margin/2, 即要求彼此至少间隔 margin。
    """
    a = (a[0], a[1], a[2] + margin, a[3] + margin, a[4])
    b = (b[0], b[1], b[2] + margin, b[3] + margin, b[4])
    (axa, aya), ca = _obb(*a)
    (axb, ayb), cb = _obb(*b)
    for ax in (axa, aya, axb, ayb):
        pa = [c[0] * ax[0] + c[1] * ax[1] for c in ca]
        pb = [c[0] * ax[0] + c[1] * ax[1] for c in cb]
        if max(pa) < min(pb) or max(pb) < min(pa):
            return False
    return True


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
    fx, fy = max_footprint(sku_length_x, sku_width_y, max_yaw_deg)
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
