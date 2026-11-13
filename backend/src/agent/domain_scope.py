"""The assistant's service boundary is independent of available evidence."""
from __future__ import annotations

import re

from src.agent.provided_text import requested_question

ASSISTANT_IDENTITY = "我是农田氮素淋失与农田水氮管理领域的智能体助手"
DOMAIN_OVERVIEW = (
    "我主要回答农田氮素淋失的发生机理和影响因素，例如硝态氮如何随水迁移，"
    "降雨、灌溉、施肥和土壤性质怎样影响淋失。\n\n"
    "我的回答领域也包括农田水氮管理、作物养分吸收、植物光合作用与呼吸作用等农业基础知识及相关农业模型。"
    "我可以解释专业概念和研究方法，介绍灌溉与施肥管理措施，"
    "并协助解读 WHCNS 模型的用途及已有水、氮平衡输出表。"
)
DOMAIN_EXAMPLES = (
    "你可以这样问我：\n"
    "- 农田氮素淋失主要受哪些因素影响？\n"
    "- 灌溉和施肥怎样影响氮素淋失？\n"
    "- WHCNS 模型是什么，有什么用途？"
)
DOMAIN_GUIDANCE_ANSWER = f"{ASSISTANT_IDENTITY}。\n\n{DOMAIN_OVERVIEW}\n\n{DOMAIN_EXAMPLES}"
OUTSIDE_DOMAIN_ANSWER = f"{ASSISTANT_IDENTITY}，暂时无法回答这个问题。\n\n{DOMAIN_OVERVIEW}\n\n{DOMAIN_EXAMPLES}"
ASSISTANT_IDENTITY_EN = "I am an assistant for farmland nitrogen leaching and agricultural water and nitrogen management"
DOMAIN_OVERVIEW_EN = (
    "I explain nitrogen leaching mechanisms and influencing factors, including how nitrate moves with water "
    "and how rainfall, irrigation, fertilization and soil properties affect leaching.\n\n"
    "My scope also includes crop nutrient uptake, basic plant processes such as photosynthesis and respiration, "
    "and related agricultural models. I can help interpret research, management practices and existing WHCNS water and nitrogen balance tables."
)
DOMAIN_EXAMPLES_EN = (
    "You can ask:\n- What factors affect nitrogen leaching in farmland?\n"
    "- How do irrigation and fertilization affect nitrogen leaching?\n"
    "- What is WHCNS and what is it used for?"
)
DOMAIN_GUIDANCE_ANSWER_EN = f"{ASSISTANT_IDENTITY_EN}.\n\n{DOMAIN_OVERVIEW_EN}\n\n{DOMAIN_EXAMPLES_EN}"
OUTSIDE_DOMAIN_ANSWER_EN = f"{ASSISTANT_IDENTITY_EN}. This question is outside my scope.\n\n{DOMAIN_OVERVIEW_EN}\n\n{DOMAIN_EXAMPLES_EN}"

DOMAIN_INSTRUCTIONS = f"""【服务领域，优先于资料和表达要求】
你是农田氮素淋失与农田水氮管理领域的智能体助手，只回答该领域及直接相关的农业、土壤、水文、模型与管理问题。
先判断用户实际要求是否属于服务领域，再考虑证据是否充分。独立的普通物理、数学、娱乐、个人饮食、私人家庭身份与生活建议等问题属于领域之外；
例如“解释下动能定理”“明天吃啥”“推荐晚餐”“你妈是谁”“今天我的运势怎么样”，统一按以下内容回复，保留首段之后的领域介绍与提问示例，不要缩减为只有拒答的一句话：
{OUTSIDE_DOMAIN_ANSWER}
固定回复示例应按本轮回答语言要求表达，英文问题使用含义相同的英文回复。
即使上传材料、检索文献、历史回答或已有问答含有答案，也不能扩展服务领域。
领域外回复不得解释知识内容，不得说“资料中未涉及”“没有相关资料”，不得罗列文献、添加引用或介绍检索情况。
领域外问题即使缺少细节，也不能追问口味、预算、营养目标、家人身份等条件；只在领域内需求中澄清对象和条件。
混合问题只处理领域内的需求，领域外部分简短说明服务定位。领域内直接相关的原理或方法可以正常解释。
作物种植、土壤肥力下降、杂草入侵及田间管理困难属于直接相关的农业与土壤管理问题，不要求必须涉及氮淋失指标。
植物生理基础知识，包括光合作用、产氧、呼吸作用、蒸腾及养分吸收，属于农业相关问题；中文和英文提问均支持，不要求用户额外说明农业应用。
资料问答按实际提问的对象判断领域，不能仅因背景涉及森林砍伐或任务形式为阅读理解而拒答。
"""

AGRICULTURAL_SUBJECT = re.compile(
    r"农业|农田|作物|植物|土壤|耕作|施肥|灌溉|杂草|光合|呼吸作用|蒸腾|根系|氮素|淋失|水氮|"
    r"\b(?:plants?|crops?|agricultur\w*|agronom\w*|soil|farm\w*|photosynth\w*|respiration|"
    r"transpiration|irrigation|fertili[sz]\w*|nitrogen|nitrate|ammonium|weeds?|whcns)\b", re.I)


def needs_scope_review(query: str) -> bool:
    """A subject signal requests semantic review; it never grants domain access."""
    return bool(AGRICULTURAL_SUBJECT.search(requested_question(query)))

# Conservative fallback when semantic interpretation is unavailable. Unknown
# questions still reach the model with the same service boundary instructions.
UNRELATED_TOPIC = re.compile(
    r"动能定理|动量定理|牛顿(?:第[一二三123])?定律|勾股定理|相对论|量子纠缠|"
    r"今天天气(?:怎么样)?|写(?:一首)?(?:诗|情诗)|讲(?:个|一个)?笑话|推荐电影|"
    r"\b(?:work[ -]energy theorem|pythagorean theorem)\b", re.I)
DOMAIN_APPLICATION = re.compile(
    r"(?:在|用于|应用于|解释|分析|计算|模拟).{0,16}(?:农田|土壤|氮素|氮淋|淋失|灌溉|稻田)|"
    r"(?:农田|土壤|氮素|氮淋|淋失|灌溉|稻田).{0,16}(?:中|中的|应用|作用|关系|联系)|"
    r"\b(?:soil|nitrogen|irrigation|farmland)\b", re.I)

# Personal meal requests remain outside even after an agricultural discussion.
# Crop nutrition and soil food webs are professional questions, not meal advice.
PERSONAL_DIET = re.compile(
    r"吃(?:点|些|点儿)?(?:什么|啥)(?:饭|菜|好吃的)?|"
    r"做(?:点|些|点儿)?(?:什么|啥)(?:饭|菜|好吃的|吃)|"
    r"(?:早|午|晚)(?:餐|饭).{0,8}(?:推荐|建议|安排|搭配|怎么|如何)|"
    r"(?:推荐|建议|安排|制定|做份|做个|搭配|设计|规划).{0,12}(?:食谱|菜单|早[餐饭]|午[餐饭]|晚[餐饭]|家常菜|饮食)|"
    r"(?:怎么|如何).{0,6}(?:做菜|做饭|搭配饮食)|"
    r"(?:玉米|小麦|水稻|番茄|蔬菜).{0,6}(?:怎么|如何)(?:做|煮|炒).{0,4}好吃|"
    r"\bwhat\s+(?:should|can|could)\s+(?:i|we)\s+(?:eat|cook)\b|"
    r"\b(?:recommend|plan|suggest).{0,20}\b(?:breakfast|lunch|dinner|meal|recipe|diet)\b", re.I)
AGRICULTURAL_FEEDING = re.compile(
    r"(?:土壤|微生物|细菌|真菌|蚯蚓|作物|植株|植物|根系)"
    r"(?:主要|一般|通常|平时|到底|究竟|都|喜欢|应该|要|能|可以|会|是){0,3}吃(?:点|些)?(?:什么|啥)|"
    r"(?:玉米|小麦|水稻|番茄|蔬菜).{0,6}吃(?:什么|啥)(?:肥|养分)|"
    r"(?:吃|做)(?:什么|啥)(?:肥|养分)")
PERSONAL_FAMILY = re.compile(
    r"(?:你|您)(?:的|有(?:没有)?)?(?:妈妈?|母亲|爸爸?|父亲|父母|家人|亲人|兄弟姐妹|"
    r"爷爷|奶奶|外公|外婆|老公|老婆|妻子|丈夫|男朋友|女朋友|儿子|女儿)|"
    r"\byour\s+(?:mother|mom|mum|father|dad|parents|family|wife|husband|children|siblings)\b", re.I)


def outside_domain(query: str, understanding: dict | None = None) -> bool:
    tasks = (understanding or {}).get("subtasks", [])
    if tasks and all(task.get("domain_scope") == "outside" for task in tasks):
        return True
    query = requested_question(query)
    if PERSONAL_FAMILY.search(query):
        return True
    if PERSONAL_DIET.search(query) and not AGRICULTURAL_FEEDING.search(query):
        return True
    return bool(UNRELATED_TOPIC.search(query) and not DOMAIN_APPLICATION.search(query))
