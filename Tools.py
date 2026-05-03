import random
from pypinyin import lazy_pinyin
from astrbot.api.all import Plain, Json, Image
from astrbot.core.star.star_handler import star_handlers_registry
from astrbot.core.star.filter.command_group import CommandGroupFilter, CommandFilter


def 获取所有指令(额外指令) -> list:
    # 遍历所有注册的处理器获取所有命令，包括别名
    l指令 = []
    for handler in star_handlers_registry:
        for i in handler.event_filters:
            if isinstance(i, CommandFilter):
                l指令.append(i.command_name)
                # 获取别名 - 属性名是 alias，类型是 set
                if hasattr(i, 'alias') and i.alias:
                    l指令.extend(list(i.alias))
            elif isinstance(i, CommandGroupFilter):
                l指令.append(i.group_name)
    所有指令 = list(set(l指令 + 额外指令))
    中文指令 = []
    英文指令 = []
    for 指令 in 所有指令:
        if 指令 and '\u4e00' <= 指令[0] <= '\u9fff':
            中文指令.append(指令)
        else:
            英文指令.append(指令)
    # 排序
    中文指令.sort(key=lambda x: lazy_pinyin(x))
    英文指令.sort(key=lambda x: x.lower())
    # 合并列表
    所有指令 = 中文指令 + 英文指令
    return 所有指令

_类型映射 = {
    '纯文本': Plain,
    '图片': Image,
    '卡片分享': Json,
}

def 概率通过(消息链, 概率值, 启用列表) -> bool:
    """检查概率及类型是否通过概率唤醒"""
    if random.random() >= 概率值:
        return False
    if '任何消息' in 启用列表:
        return True

    #优化算法
    # 提取对应的类型，组成元组
    启用类型列表 = tuple(_类型映射[类型文本] for 类型文本 in 启用列表 if 类型文本 in _类型映射)

    if not 启用类型列表:
        return False

    # 特殊规则：仅纯文本时要求严格单条消息
    if 启用类型列表 == (Plain,):
        return len(消息链) == 1 and isinstance(消息链[0], Plain)

    for seg in 消息链:
        if isinstance(seg, 启用类型列表):
            return True
    return False

帮助文本 = """
📖 **群自定义规则插件 - 帮助文档**

本插件用于精细控制群聊消息的唤醒与拦截，支持为不同群组配置独立规则。

--- 管理员命令 ---
• `/所有指令` - 查看当前所有可用的机器人指令（含别名）
• `/刷新指令` - 重新扫描并刷新指令列表（新增插件命令后使用）
• `/群规则 <群号>` - 查看指定群（或当前群）的规则配置详情
• `/添加群规 <群号列表> <备注>` - 为群组添加新规则（群号逗号分隔）
  示例：/添加群规 123456789,987654321 测试群
• `/设置群规 <键> <值> <群号或"兜底规则">` - 修改指定规则的配置项
  示例：/设置群规 开关 true
       /设置群规 昵称唤醒 机器人,AI助手
       /设置群规 概率唤醒 0.3
       /设置群规 持续活跃 60
       /设置群规 禁用的指令 help,status
       /设置群规 艾特唤醒 false 兜底规则
• `/删除群规 <单个群号>`从自定义规则中移除该群号，若该规则只有这一个群号，则会设为无，再执行/`删除群规 无`，确认删除整条规则

--- 规则配置项说明 ---
【基础】
  - 开关 (bool)            : 是否启用该规则
  - 备注 (str)             : 规则描述
【唤醒方式】
  - 昵称唤醒 (list)        : 消息包含关键词即唤醒，如 ["机器人","AI"]
  - 艾特唤醒 (bool)        : @机器人即唤醒
  - 引用唤醒 (bool)        : 既@又引用机器人消息才唤醒
  - 无艾特引用唤醒 (bool)   : 仅引用机器人消息即唤醒
  - 概率唤醒 (float)       : 0~1，随机概率唤醒
  - 概率方式 (list)        : 概率唤醒的方式，可选值有：纯文本/卡片分享/图片/任何消息
【拦截条件】
  - 前缀拦截 (list)        : 消息以指定前缀开头则拦截
  - 含有拦截 (list)        : 消息包含指定词则拦截
  - 其余拦截 (bool)        : 未匹配任何唤醒条件时拦截
  - 拦截json (bool)        : 拦截外部分享的JSON卡片
  - 拦截戳一戳 (bool)      : 拦截戳一戳消息
【时间控制】
  - 持续活跃 (秒)          : 唤醒后群组保持活跃的时间，-1表示使用兜底值
  - 活跃间隔 (秒)          : 活跃期内两次唤醒的最小间隔
  - 唤醒CD (秒)            : 单个用户唤醒后的冷却时间，-1使用兜底值
  - 活跃方式 (str)         : 活跃方式，可选：唤醒时/llm请求后/发送消息后
  - 活跃范围 (str)         : 群聊级/用户级，用户级时忽略群组冷却，仅使用用户冷却
【指令控制】
  - 禁前唤醒 (bool)        : 禁止前缀唤醒llm
  - 禁用系统指令 (bool)    : 禁止使用系统指令（如 /help）
  - 禁用的指令 (list)      : 黑名单指令，["0所有"]表示禁用所有指令
  - 启用的指令 (list)      : 白名单指令，["0所有"]表示放行所有指令

--- 特殊值说明 ---
• 兜底规则：未配置自定义规则的群自动生效的规则
• -1 ：表示继承兜底规则的对应数值（仅适用于时间类配置）
• 0所有 ：在禁用/启用指令列表中使用，表示全部指令
• list类型可以使用 add/del/rep 参数
--- 注意事项 ---
• 管理员不受大部分拦截规则影响
• 修改配置后立即生效，无需重启
• 群号参数为字符串，如 "123456789"，兜底规则用 "兜底规则"
        """.strip()
