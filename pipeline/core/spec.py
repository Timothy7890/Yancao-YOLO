"""SceneSpec: 描述"一帧"的可序列化规格。

纯数据 + (反)序列化。Blender 侧按此实现场景; 后处理侧按此写标注。
坐标约定: 摆放坐标 (x,y) 为"板面局部米", 原点=该层隔板中心, X 沿板长, Y 沿板宽;
烟盒底面贴板(自身 z=0), 只绕世界 Z 偏航 yaw_deg。
"""

from dataclasses import asdict, dataclass, field
from typing import List, Tuple


@dataclass
class Placement:
    sku: str                     # SKU 名(= data/yanhe 下 blend 文件名/对象名)
    x: float                     # 板面局部 X(米), 相对板心
    y: float                     # 板面局部 Y(米), 相对板心
    yaw_deg: float               # 绕世界 Z 偏航


@dataclass
class CameraPose:
    distance: float              # 沿光轴反向到目标点的距离(米)
    yaw_off_deg: float = 0.0     # 相对标定安装角的偏航抖动
    pitch_off_deg: float = 0.0   # 相对标定安装角的俯仰抖动
    pos_off: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # 目标点位置抖动(米)


@dataclass
class Lights:
    top_power: float             # 顶部条形灯功率(W)
    ambient: float               # 环境光强度


@dataclass
class SceneSpec:
    frame_id: int
    seed: int
    layer: int                             # 摆放/取景所在层
    camera: CameraPose
    lights: Lights
    placements: List[Placement] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        return SceneSpec(
            frame_id=d["frame_id"],
            seed=d["seed"],
            layer=d["layer"],
            camera=CameraPose(**d["camera"]),
            lights=Lights(**d["lights"]),
            placements=[Placement(**p) for p in d["placements"]],
        )
