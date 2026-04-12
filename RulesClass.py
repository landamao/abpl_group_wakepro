from typing import TypedDict, List, Union

__all__ = [
    "BaseRule",
    "自定义规则",
    "兜底规则",
    "Rule",
]

class BaseRule(TypedDict, total=True):
    """所有规则共有的字段（开关、唤醒、拦截、时间等）"""
    # 基础
    开关: bool
    备注: str

    # 唤醒方式
    艾特唤醒: bool
    引用唤醒: bool
    无艾特引用唤醒: bool
    昵称唤醒: List[str]
    概率唤醒: float
    概率方式: List[str]          # "纯文本" / "卡片分享" / "图片" / "任何消息"

    # 拦截条件
    前缀拦截: List[str]
    含有拦截: List[str]
    其余拦截: bool
    拦截json: bool
    拦截戳一戳: bool

    # 时间控制
    唤醒CD: float                # 秒，-1 表示继承兜底值
    持续活跃: float              # 秒，-1 表示继承兜底值
    活跃间隔: float              # 秒，-1 表示继承兜底值
    活跃方式: str                # "唤醒时" / "llm请求后" / "发送消息后"
    活跃范围: str                # "群聊级" / "用户级"

    # 指令控制
    禁用的指令: List[str]        # 可包含 "0所有"
    启用的指令: List[str]        # 可包含 "0所有"
    禁用系统指令: bool
    禁前唤醒: bool

    # 其他
    强力拦截: bool


class 自定义规则(BaseRule, total=True):
    """自定义规则（包含群号列表）"""
    群号: List[str]              # 必填，实际配置中一定存在


class 兜底规则(BaseRule, total=True):
    """兜底规则（无群号字段）"""
    pass


# 联合类型，用于表示任意一种规则字典
Rule = Union[自定义规则, 兜底规则, dict]