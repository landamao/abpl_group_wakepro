import time, random
from pypinyin import lazy_pinyin
from astrbot.api.all import Star, Context, logger
from astrbot.api.all import Plain, Json, Poke, At, Reply
from astrbot.api.all import AstrBotConfig, EventMessageType, AstrMessageEvent
from astrbot.api.event import filter
from astrbot.core.star.filter.command_group import CommandGroupFilter, CommandFilter
from astrbot.core.star.star_handler import star_handlers_registry
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
op = time.perf_counter()
class 群自定义规则(Star):

    def __init__(self, context: Context, config: AstrBotConfig):

        super().__init__(context)
        self.config = config

        # ======获取配置======
        #应有的配置不会少，不要用get来意外修改用户配置，没有就直接错误
        try:
            self.规则列表 = config.get('自定义规则', []) #这个可能没配置列表
            self.所有指令 = self.获取所有指令()  # 原本重载时也要获取，不冲突
            self.所有指令集合 = set(self.所有指令)  # 数据量大，用集合提升性能
            self.兜底规则: dict = config['兜底规则']
            self.兜底规则['备注'] = "兜底规则"
            self.兜底开关 = self.兜底规则['开关']
            self.黑名单群聊 = [i.strip() for i in config['黑名单群聊']]
            config['黑名单群聊'] = self.黑名单群聊
        except Exception as e:
            logger.critical(f"【群唤醒增强】获取配置失败，请重新安装插件，或联系开发者\n错误信息：{str(e)}", exc_info=True)
            raise RuntimeError
        # ======获取系统配置======
        try:
            self.指令前缀 = tuple(context.get_config()["wake_prefix"])
        except Exception as e:
            logger.error(f"【群唤醒增强】获取指令前缀失败，使用默认值 '/': {e}")
            self.指令前缀 = ("/",)

        try:
            self.管理员列表 = context.get_config()["admins_id"]
        except Exception as e:
            logger.error("【群唤醒增强】获取管理员列表失败，你可在代码中手动配置管理员，错误信息：\n" + str(e))
            self.管理员列表 = []

        logger.info(f"【群唤醒增强】所有{len(self.所有指令)}个指令：\n{self.所有指令}")

        self.规则索引 = {}
        self.群组活跃间隔 = {}
        for 索引, 规则 in enumerate(self.规则列表):
            规则['群号'] = [j.strip() for j in 规则['群号']]
            for 群号 in 规则['群号']:
                if 群号 in self.规则索引:
                    logger.warning(f"【群唤醒增强】群 {群号} 已定义，请检查")
                    continue
                self.规则索引[群号] = 索引
                self.群组活跃间隔[群号] = 规则['活跃间隔']

        for i, j in self.群组活跃间隔.items():
            if j == -1:
                self.群组活跃间隔[i] = self.兜底规则['活跃间隔']

        self.系统指令 = {'alter_cmd', 'dashboard_update', 'del', 'deop', 'dwl', 'groupnew', 'help', 'history', 'key',
                         'llm', 'ls', 'model', 'new', 'op', 'persona', 'provider', 'rename', 'reset', 'sid', 'switch',
                         't2i', 'tts', 'wl'}

        self.群组活跃时间 = {}
        self.用户冷却时间 = {}
        self.群组上次唤醒时间 = {}

        ed = time.perf_counter()
        耗时 = ed - op
        logger.info(f"【群唤醒增强】启动完成，耗时{耗时:.6f}秒")

    # 更智能的扫描指令
    @filter.on_astrbot_loaded()
    async def 启动获取所有指令(self):
        """框架初次启动完成时获取所有指令"""
        self.所有指令 = self.获取所有指令()
        self.所有指令集合 = set(self.所有指令)
        logger.info(f"\n\n【群唤醒增强】所有{len(self.所有指令)}个指令：\n{self.所有指令}\n\n")

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE, priority=6666)
    async def 入口(self, event: AstrMessageEvent):
        """消息主入口"""
        if not (消息链:=event.get_messages()):
            return  # 可能会出现消息链为空的情况

        #设置额外信息
        event.set_extra("群唤醒拦截", False)

        发送者 = event.get_sender_id()
        群号 = event.get_group_id()
        当前时间 = time.time()

        if 群号 in self.黑名单群聊:
            if event.is_admin():
                return
            self.终止事件传播(event, {})
            return

        if 发送者 in self.用户冷却时间 and not event.is_admin():
            if 当前时间 < self.用户冷却时间[发送者]:
                logger.info(f"【群唤醒增强】「{发送者}触发了冷却拦截")
                self.终止事件传播(event, {})
                return
            else:  # 清理过期数据
                del self.用户冷却时间[发送者]

        规则 = self.获取当前群规(event)
        if not 规则:
            return

        # 只有这样才能获取到带有指令前缀的消息文本
        消息文本 = next((seg.text for seg in 消息链 if isinstance(seg, Plain)), '').strip()
        # 处理指令
        if 消息文本.startswith(self.指令前缀):
            指令文本 = event.get_message_str().strip().split()
            if 指令文本:
                指令文本 = 指令文本[0]
            else:
                logger.info(f"【群唤醒增强】「{规则['备注']}」触发了空指令拦截")
                self.终止事件传播(event, {})
                return
            if event.is_admin():
                if 指令文本 in self.所有指令集合:
                    return  # 管理员不受影响
                elif 规则['禁前唤醒']:
                    logger.info(f"【群唤醒增强】「{规则['备注']}」触发了前缀拦截")
                    self.终止事件传播(event, 规则)
                    return
                return
            if self.指令屏蔽(指令文本, 规则):
                logger.info(f"【群唤醒增强】「{规则['备注']}」触发了指令拦截")
                self.终止事件传播(event, 规则)
            return

        if isinstance(消息链[0], Json):
            if 规则['拦截json']:
                logger.info(f"【群唤醒增强】「{规则['备注']}」触发了json拦截（外部分享）")
                self.终止事件传播(event, 规则)
            return

        if isinstance(消息链[0], Poke):
            if 规则['拦截戳一戳']:
                logger.info(f"【群唤醒增强】「{规则['备注']}」触发了戳一戳拦截")
                self.终止事件传播(event, 规则)
            return

        # 检查是否在活跃期内且满足2秒间隔
        if 群号 in self.群组活跃时间:
            # 艾特或引用不影响
            if self.处理艾特引用(event, 规则): return
            if 当前时间 < self.群组活跃时间[群号]:
                # 在活跃期内，检查是否满足活跃间隔
                if ((当前时间 - self.群组上次唤醒时间.get(群号, 0)) <
                        self.群组活跃间隔.get(群号, self.兜底规则['活跃间隔'])):
                    logger.info(f"【群唤醒增强】「{规则['备注']}」触发了冷却拦截")
                    self.终止事件传播(event, 规则)
                    return
                else:
                    logger.info(f"【群唤醒增强】「{规则['备注']}」触发了活跃唤醒")
                    self.唤醒(event, 规则)
                    return
            else:
                # 不在活跃期内，清除活跃状态
                del self.群组活跃时间[群号]; self.群组上次唤醒时间.pop(群号, None)

        # 检查昵称唤醒
        if any(_ in 消息文本 for _ in 规则['昵称唤醒']):
            logger.info(f"【群唤醒增强】「{规则['备注']}」触发了昵称唤醒")
            self.唤醒(event, 规则)
            return

        if 规则['前缀拦截'] and any(消息文本.startswith(_) for _ in 规则['前缀拦截']):
            logger.info(f"【群唤醒增强】「{规则['备注']}」触发了前缀拦截")
            self.终止事件传播(event, 规则)
            return

        if 规则['含有拦截'] and any(_ in 消息文本 for _ in 规则['含有拦截']):
            logger.info(f"【群唤醒增强】「{规则['备注']}」触发了含有拦截")
            self.终止事件传播(event, 规则)
            return

        if self.处理艾特引用(event, 规则):
            return

        # 检查其余拦截
        if 规则['其余拦截']:
            logger.info(f"【群唤醒增强】「{规则['备注']}」触发了其余拦截")
            self.终止事件传播(event, 规则)
            return

        # 检查概率唤醒
        if 规则['概率唤醒'] and random.random() < 规则['概率唤醒']:
            logger.info(f"【群唤醒增强】「{规则['备注']}」触发了概率唤醒")
            self.唤醒(event, 规则)
            return
        return

    def 获取当前群规(self, event: AstrMessageEvent) -> dict|None:
        群号 = event.get_group_id()
        if not 群号:
            return None
        规则 = None
        if 群号 in self.规则索引:
            规则 = self.规则列表[self.规则索引[群号]]
            #没开启直接不处理也不使用兜底规则
            if not 规则['开关']:
                return None
        elif self.兜底开关:
            规则 = self.兜底规则
        return 规则

    @filter.on_llm_request(priority=66666)
    async def llm请求前(self, event: AstrMessageEvent, _):
        """兜底拦截"""
        try:
            # if next((seg.text for seg in event.get_messages() if isinstance(seg, Plain)), '').strip().startswith(self.指令前缀):
            #     logger.info(f"【群唤醒增强】用户「{event.get_sender_name()}」，消息 | {event.get_message_outline()} | 指令拦截")
            #     event.stop_event()
            #     return
            规则 = self.获取当前群规(event)
            if not 规则:
                return
            群号 = event.get_group_id()
            if 规则['禁前唤醒'] and next((seg.text for seg in event.get_messages() if isinstance(seg, Plain)), '').strip().startswith(self.指令前缀):
                event.stop_event()
                logger.info(f"【群唤醒增强】群{群号}，用户「{event.get_sender_name()}」，消息 | {event.get_message_outline()} | 拦截了llm唤醒")
            elif 规则['禁用系统指令'] and event.get_message_str() in self.系统指令:
                event.stop_event()
                logger.info(f"【群唤醒增强】群{群号}，用户「{event.get_sender_name()}」，消息 | {event.get_message_outline()} | 拦截了llm唤醒")
            elif event.get_extra("群唤醒拦截"):
                event.stop_event()
                logger.info(f"【群唤醒增强】群{群号}，用户「{event.get_sender_name()}」，消息 | {event.get_message_outline()} | 拦截了llm唤醒")
                logger.info(f"拦截了此次事件，{event.get_extra("群唤醒拦截")}")
            else:
                logger.info(f"【群唤醒增强】群{群号}，用户「{event.get_sender_name()}」，消息 | {event.get_message_outline()} | 唤醒了llm")
        except Exception as e:
            logger.error(f"【群唤醒增强】拦截出错：\n{e}", exc_info=True)

    @filter.on_llm_response()
    async def llm请求后(self, event: AstrMessageEvent, _):
        """当有 LLM 请求后的事件"""
        event.set_extra("群唤醒llm请求后", True)
        规则 = self.获取当前群规(event)
        if not 规则:
            return
        if 规则['活跃方式'] == 'llm请求后':
            self.记录群活跃(event, 规则)

    @filter.after_message_sent()
    async def 发送消息后(self, event: AstrMessageEvent):
        """在消息发送后的事件"""
        # logger.critical(f"llm请求的消息：{event.get_extra("群唤醒llm请求后", False)}")
        # logger.critical(f"群唤醒已处理：{event.get_extra("群唤醒已处理", False)}")
        if not event.get_extra("群唤醒llm请求后", False):
            return
        if event.get_extra("群唤醒已处理", False):
            return
        event.set_extra("群唤醒已处理", True)
        #测试时是分段回复插件全部发送消息完成后才会触发，不过安全起见还是设置一个标记
        规则 = self.获取当前群规(event)
        if not 规则:
            return
        if 规则['活跃方式'] == '发送消息后':
            self.记录群活跃(event, 规则)
        # logger.critical(f"群唤醒已处理：{event.get_extra("群唤醒已处理", False)}")

    def 记录群活跃(self, event: AstrMessageEvent, 规则):
        # 设置持续活跃时间
        当前时间 = time.time()
        持续活跃时间 = 规则['持续活跃']
        if 持续活跃时间 == -1:
            持续活跃时间 = self.兜底规则['持续活跃']

        if 持续活跃时间 > 0:
            logger.info(f"【群唤醒增强】「{规则['备注']}」将持续活跃{持续活跃时间}秒")
            self.群组活跃时间[event.get_group_id()] = 当前时间 + 持续活跃时间
            self.群组上次唤醒时间[event.get_group_id()] = 当前时间

        # 设置用户冷却时间
        if event.is_admin():
            return

        唤醒CD = 规则['唤醒CD']
        if 唤醒CD == -1:
            唤醒CD = self.兜底规则['唤醒CD']

        if 唤醒CD > 0:
            self.用户冷却时间[event.get_sender_id()] = 当前时间 + 唤醒CD
            logger.info(f"【群唤醒增强】用户「{event.get_sender_name()}（{event.get_sender_id()}）」将冷却{唤醒CD}秒")

    @staticmethod
    def 终止事件传播(event: AstrMessageEvent, 规则:dict):
        if 规则.get('强力拦截', False):
            event.set_extra("群唤醒拦截", True)
        logger.info(f"【群唤醒增强】「{规则.get('备注', event.get_group_id())}」终止了事件传播")
        event.stop_event()

    def 处理艾特引用(self, event: AstrMessageEvent, 规则) -> bool:
        """返回值决定调用后上一级是否也return"""
        艾特 = False
        引用 = False

        for seg in event.get_messages():

            if isinstance(seg, At) and str(seg.qq) == event.get_self_id():
                艾特 = True
                break

            if isinstance(seg, Reply) and str(seg.sender_id) == event.get_self_id():
                引用 = True

        # 处理艾特和引用唤醒
        if 艾特 or 引用:
            指令文本 = event.get_message_str().strip().split()
            if 指令文本:
                指令文本 = 指令文本[0]
            else:
                指令文本 = ""
            if not event.is_admin():
                # 检查是否为系统指令
                if 指令文本 in self.系统指令:
                    if 规则['禁用系统指令']:
                        if event.is_admin():
                            return True
                        self.终止事件传播(event, 规则)
                        return True

                # 检查指令屏蔽
                if self.指令屏蔽(指令文本, 规则, 禁前=False):
                    logger.info(f"【群唤醒增强】「{规则['备注']}」拦截了指令")
                    self.终止事件传播(event, 规则)
                    return True

                if 指令文本 in self.所有指令集合:
                    return True

            # 检查各种唤醒条件
            if 规则['引用唤醒'] and 艾特 and 引用:
                logger.info(f"【群唤醒增强】「{规则['备注']}」触发了艾特引用唤醒")
                self.唤醒(event, 规则)
                return True

            if 规则['艾特唤醒'] and 艾特:
                logger.info(f"【群唤醒增强】「{规则['备注']}」触发了艾特唤醒")
                self.唤醒(event, 规则)
                return True

            if 规则['无艾特引用唤醒'] and 引用:
                logger.info(f"【群唤醒增强】「{规则['备注']}」触发了无艾特引用唤醒")
                self.唤醒(event, 规则)
                return True

            logger.info(f"【群唤醒增强】「{规则['备注']}」拦截了此次艾特或引用唤醒")
            self.终止事件传播(event, 规则)
            return True
        return False

    def 唤醒(self, event: AstrMessageEvent, 规则):
        """设置唤醒状态"""
        event.is_at_or_wake_command = True
        if 规则['活跃方式'] == "唤醒时":
            self.记录群活跃(event, 规则)

    def 指令屏蔽(self, 指令文本, 规则, 禁前=True) -> bool:
        """检查指令是否被屏蔽"""
        # 检查系统指令
        if 规则.get('禁用系统指令') and 指令文本 in self.系统指令:
            return True

        # 检查禁用指令列表
        if 规则['禁用的指令']:
            if '0所有' in 规则['禁用的指令']:
                if 禁前:
                    return True
                elif 指令文本 in self.所有指令集合:
                    return True
                else:
                    return False
            elif 指令文本 in 规则['禁用的指令']:
                return True

        # 检查启用指令列表
        if 规则['启用的指令']:
            if '0所有' in 规则['启用的指令']:
                return False
            elif 指令文本 not in 规则['启用的指令']:
                return True

        # 检查禁前唤醒
        if 禁前 and 规则['禁前唤醒'] and (指令文本 not in self.所有指令集合):
            return True

        return False

    @filter.command("所有指令")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def 指令菜单(self, event: AstrMessageEvent):
        """查看所有指令"""
        yield event.plain_result('/' + '\n/'.join(self.所有指令))

    @filter.command("刷新指令")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def 刷新指令(self, event: AstrMessageEvent):
        """刷新指令"""
        刷新前 = len(self.所有指令)
        self.所有指令 = self.获取所有指令()
        self.所有指令集合 = set(self.所有指令)
        差值 = len(self.所有指令) - 刷新前
        yield event.plain_result(f"✅ 已刷新所有指令，新增{差值}个")

    def 获取所有指令(self) -> list:
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
        所有指令 = list(set(l指令 + self.config['额外指令']))
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

    @filter.command("设置群规")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def 设置群规(self, event: AstrMessageEvent, 键: str, 值: str, 群号: str = None, 操作: str = "null"):
        """设置群规配置项，用法：/设置群规 <键> <值> [群号] [操作]
        操作参数仅对列表类型有效：add(追加，默认)、del(删除)、rep(替换)
        示例：
            /设置群规 开关 on
            /设置群规 昵称唤醒 机器人,AI
            /设置群规 昵称唤醒 机器人 add        # 追加“机器人”
            /设置群规 昵称唤醒 机器人 del        # 删除“机器人”
            /设置群规 昵称唤醒 AI助手 rep        # 替换为仅“AI助手”
            /设置群规 禁用的指令 help,status rep
            /设置群规 概率唤醒 0.3
            /设置群规 持续活跃 60
            /设置群规 艾特唤醒 off 兜底规则
        """
        原群号 = 群号
        # 1. 智能解析群号和操作（兼容旧用法）
        # 如果群号参数实际上是操作值（add/del/rep）且群号为None，则交换\
        if 群号 is not None:
            群号 = str(群号).strip() #傻杯框架会把数字转为整数传入，框架自己都知道函数已声明str
            if 群号.lower() in ('add', 'del', 'rep') and 操作 == "null":
                # 用户可能将操作写在了群号位置，例如：/设置群规 键 值 add
                操作 = 群号.lower()
                群号 = None

        # 确定目标群号
        if 群号 is None:
            群号 = event.get_group_id()
            if not 群号:
                yield event.plain_result("❌ 请在群聊中使用，或通过参数指定群号（或“兜底规则”）")
                return
        群号 = str(群号).strip()
        键 = str(键).strip()
        值 = str(值).strip()
    
        # 2. 获取目标规则字典
        规则列表 = self.config.get('自定义规则', [])
        规则 = None
        来源 = None
    
        if 群号 == '兜底规则':
            规则 = self.config['兜底规则']
            if not 规则:
                yield event.plain_result("❌ 未找到兜底规则配置")
                return
            来源 = "兜底规则"
        else:
            for r in 规则列表:
                if 群号 in r['群号']:
                    规则 = r
                    来源 = f"群 {群号}"
                    break
            if not 规则:
                yield event.plain_result(f"❌ 未找到群 {群号} 的规则，请先使用 /添加群规 添加")
                return
    
        # 3. 检查键是否存在
        if 键 not in 规则:
            可用的键 = list(规则.keys())
            if '__template_key' in 可用的键:
                可用的键.remove('__template_key')
            if 可用的键:
                tips = '\n'.join(可用的键)
            else:
                tips = '无可用键'
            yield event.plain_result(f"❌ 规则中不存在键「{键}」，可用的键有：\n{tips}")
            return
    
        # 4. 获取原值类型并转换
        原值 = 规则[键]
        原类型 = type(原值)
        try:
            if 原类型 is bool:
                if 操作 != "null":
                    yield event.plain_result(f"⚠️ 键「{键}」为布尔类型，不支持操作参数「{操作}」，已忽略")
                值小写 = 值.lower()
                if 值小写 in ('开', 'true', '1', 'on'):
                    转换后 = True
                elif 值小写 in ('关', 'false', '0', 'off'):
                    转换后 = False
                else:
                    raise ValueError(f"无法解析为布尔值: {值}，支持：开/关，1/0，on/off，true/false")
            elif 原类型 is float:
                if 操作 != "null":
                    yield event.plain_result(f"⚠️ 键「{键}」为浮点数类型，不支持操作参数「{操作}」，已忽略")
                转换后 = float(值)
            elif 原类型 is list:
                值 = 值.replace("，", ",")
                if 值.strip() == "":
                    新列表 = []
                else:
                    新列表 = [item.strip() for item in 值.split(',') if item.strip()]
                实际操作 = "add" if 操作 == "null" else 操作
                if 实际操作 == "add":
                    转换后 = 原值 + 新列表
                    # 去重保留顺序
                    转换后 = list(dict.fromkeys(转换后))
                elif 实际操作 == "del":
                    # 找出原列表里不存在的那些
                    not_exist = [x for x in 新列表 if x not in 原值]
                    if not_exist:
                        yield event.plain_result(f"❌ 原列表中不存在：{'，'.join(not_exist)}")
                        return
                    转换后 = [item for item in 原值 if item not in 新列表]
                elif 实际操作 == "rep":
                    转换后 = 新列表
                else:
                    yield event.plain_result(f"❌ 不支持的操作类型: {操作}，请使用 add/del/rep")
                    return
            elif 原类型 is str:
                if 操作 != "null":
                    yield event.plain_result(f"⚠️ 键「{键}」为字符串类型，不支持操作参数「{操作}」，已忽略")
                转换后 = 值
            else:
                yield event.plain_result(f"❌ 不支持的类型: {原类型}")
                return
        except Exception as e:
            yield event.plain_result(f"⚠️ 类型转换失败：{e}\n期望类型：{原类型.__name__}")
            return

        # 5. 赋值并保存配置
        规则[键] = 转换后
        self.config.save_config()
        # 不需要重建索引

        输出行 = [f"✅ 已更新 {来源} 的规则：{键} = {转换后}"]
        if 操作 in ('add', 'del', 'rep') and 原类型 is list:
            输出行.append(f"• 操作模式：{操作}")
        if len(规则.get('群号', [])) > 1:
            if 原群号 is None:
                输出行.append(f"• 还有{len(规则['群号'])-1}个群也使用了此规则")
            else:
                输出行.append(f"• 还有群{规则['群号']}也使用了此规则")
        if 规则['开关'] is False and 键 != '开关':
            输出行.append("• ⚠️ 该规则已关闭，若要使用请开启开关")
    
        yield event.plain_result('\n'.join(输出行))


    @filter.command("添加群规")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def 添加群规(self, event: AiocqhttpMessageEvent, 群号: str=None, 备注: str = None):
        """为指定群号添加新的自定义规则。
        用法：/添加群规 <群号列表（用逗号分隔）> [备注]
        示例：
            /添加群规 123456789
            /添加群规 987654321,111222333 测试群规则
        """
        # 解析群号列表（支持逗号分隔）
        if 群号 is None:
            群号列表 = [event.get_group_id()]
        else:
            群号 = str(群号)
            群号列表 = [g.strip() for g in 群号.split(',') if g.strip()]
            if not 群号列表:
                yield event.plain_result("❌ 请提供有效的群号")
                return

        # 检查每个群号是否已存在规则
        已存在群号 = []
        for g in 群号列表:
            if g in self.规则索引:
                已存在群号.append(g)
        if 已存在群号:
            yield event.plain_result(f"❌ 群号{已存在群号}已存在自定义规则，请使用 /设置群规 修改")
            return

        # 获取默认规则模板
        规则模板 = self.config.schema['自定义规则']['templates']['自定义']['items']
        默认规则 = {key: item['default'] for key, item in 规则模板.items()}

        # 确保必要字段存在
        默认规则['__template_key'] = '自定义'  #内部字段，否则WebUI无法识别

        # 创建新规则
        新规则 = 默认规则.copy()
        新规则['群号'] = 群号列表
        if not 备注 and len(群号列表) == 1:
            try:
                备注 = (await event.bot.get_group_info(group_id=int(群号列表[0])))['group_name']
                新规则['备注'] = 备注
            except Exception as e:
                logger.warning(e, exc_info=True)
                新规则['备注'] = f"群 {','.join(群号列表)} 的自定义规则"
        else:
            新规则['备注'] = 备注

        # 添加到配置
        规则列表 = self.config.get('自定义规则', [])
        规则列表.append(新规则)
        self.config['自定义规则'] = 规则列表
        self.config.save_config()

        # 重建内部索引
        self._重建规则索引()

        yield event.plain_result(
            f"✅ 已为以下群号添加自定义规则：{', '.join(群号列表)}\n"
            f"备注：{新规则['备注']}\n"
            f"可使用 /设置群规 修改具体配置项。/群规则 查看当前群规")

    def _重建规则索引(self):
        """重新构建规则索引和群组活跃间隔映射（供内部调用）"""
        self.规则索引.clear()
        self.群组活跃间隔.clear()
        for 索引, 规则 in enumerate(self.规则列表):
            规则['群号'] = [j.strip() for j in 规则['群号']]
            for 群号 in 规则['群号']:
                if 群号 in self.规则索引:
                    logger.warning(f"【群唤醒增强】群 {群号} 已存在规则，跳过重复")
                    continue
                self.规则索引[群号] = 索引
                self.群组活跃间隔[群号] = 规则['活跃间隔']
        # 更新兜底规则的活跃间隔引用
        for 群号, 间隔 in self.群组活跃间隔.items():
            if 间隔 == -1:
                self.群组活跃间隔[群号] = self.兜底规则['活跃间隔']

    @filter.command("群规则")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def 查看群规则(self, event: AstrMessageEvent, 群号:str=None):
        """查看指定群聊的规则配置"""
        # 解析参数
        原群号 = 群号
        if 群号 is None:
            if not (群号:=event.get_group_id()):
                yield event.plain_result("❌ 请在群里中使用或传入群号参数")
                return
        群号 = str(群号).strip()

        # 查找规则
        if 群号 in self.规则索引:
            规则 = self.规则列表[self.规则索引[群号]]
            来源 = "自定义规则"
        elif 群号 == "兜底规则":
            规则 = self.兜底规则
            来源 = "兜底规则"
        elif self.兜底开关:
            规则 = self.兜底规则
            来源 = "兜底规则"
        else:
            yield event.plain_result(f"❌ 未找到群 {群号} 的规则配置（兜底规则已关闭）")
            return

        def f(键) -> str:
            if 规则[键] == -1:
                return f"• {键}：{self.兜底规则[键]}秒（使用兜底值）"
            else:
                return f"• {键}：{规则[键]}秒"

        # 格式化输出
        输出行 = [f"📋 群 {群号} 的规则配置（{来源}）", f"• 备注：{规则['备注']}",
                f"• 总开关：{'✅ 开启' if 规则['开关'] else '❌ 关闭'}",
                f"• 昵称唤醒：{', '.join(规则['昵称唤醒']) or '无'}",
                f"• 艾特唤醒：{'✅' if 规则['艾特唤醒'] else '❌'}",
                f"• 引用唤醒：{'✅' if 规则['引用唤醒'] else '❌'}",
                f"• 无艾特引用唤醒：{'✅' if 规则['无艾特引用唤醒'] else '❌'}",
                f"• 前缀拦截：{', '.join(规则['前缀拦截']) or '无'}",
                f"• 含有拦截：{', '.join(规则['含有拦截']) or '无'}",
                f"• 其余拦截：{'✅' if 规则['其余拦截'] else '❌'}",
                f"• 拦截JSON：{'✅' if 规则['拦截json'] else '❌'}",
                f"• 拦截戳一戳：{'✅' if 规则['拦截戳一戳'] else '❌'}",
                f"• 概率唤醒：{规则['概率唤醒'] * 100:.0f}%",
                f('持续活跃'),
                f('活跃间隔'),
                f('唤醒CD'),
                f"• 禁前唤醒：{'✅' if 规则['禁前唤醒'] else '❌'}",
                f"• 禁用系统指令：{'✅' if 规则['禁用系统指令'] else '❌'}",
                f"• 禁用的指令：{', '.join(规则['禁用的指令']) or '未配置'}",
                f"• 启用的指令：{', '.join(规则['启用的指令']) or '未配置'}"]
        if len(规则.get('群号', [])) > 1:
            if 原群号 is None:
                输出行.append(f"• 还有{len(规则['群号']) - 1}个群也使用了此规则")
            else:
                输出行.append(f"• 还有群{规则['群号']}也使用了此规则")

        yield event.plain_result('\n'.join(输出行))

    @filter.command("群规帮助")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def 群规帮助(self, event: AstrMessageEvent):
        """显示群自定义规则插件的帮助文档"""
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
        yield event.plain_result(帮助文本)