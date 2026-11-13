"""Task strategy layers; shared evidence/output rules remain in each caller."""
from contextvars import ContextVar
import json
from typing import Literal

from pydantic import Field, field_validator
from src.agent.contracts import Contract

TaskScope = Literal['concept_explanation', 'knowledge_search', 'case_assistant']
CONCEPT_EXPLANATION_GUIDANCE = (
    '\n【概念解释的默认展开】\n'
    '用户没有要求简答时，把基础概念当作一次小讲解，通常展开为4至6个自然段，约500至800个汉字。'
    '首段给定义并解释其中的关键词；接着用通俗语言讲清主要过程及前后衔接；'
    '再用一个具体的日常或农业场景说明它的用途或意义；最后按需澄清一个常见误解。'
    '例如情景应写清发生什么变化、为什么有这种变化，不能只用“影响产量”等抽象词带过。'
    '这是内容组织建议，无需机械生成标题；有依据、易理解和解释完整比凑齐段数重要。'
    '常识性示例用“例如”等自然引入，不虚构实测结果或引用。用户指定简短、一句话或字数时优先遵守。'
)
DEFAULT_TASKS = {
    'concept_explanation': '先用第一段解释概念是什么、主要涉及什么或有什么用途，再按需补背景和例子。名词或模型名称也可直接解释，不以补全问句、提供田块参数为前置。对新手说的“这个模型”，结合历史简短区分本问答助手与农业模拟模型，不擅自认定具体模型；先说明可理解的实际用途，再按需问一个问题。工作应用场景可解释，但不预测个人考试、求职结果。通用原理自然解释，具体专业数值和适用性没有依据时不编造。' + CONCEPT_EXPLANATION_GUIDANCE,
    'knowledge_search': '先回答材料可支持的规律或结论，再说明研究条件、证据和具体缺口。一次检索未命中不等于没有相关研究；区分未命中、材料不足和正文不支持。保留作物、场景、时间尺度和指标口径，不把一般机理当作某次峰值的确定成因。',
    'case_assistant': '承接实际展示或用户指定的对象，按查找、解释、比较或效果取证任务回答。材料做法、可能理由和效果证据分别说明；没有实测对照不推断有效或更优，不将案例推荐量当作用户田块处方。解释粘贴材料和表格时保留来源、表头、单位、单次与合计。',
}
active_task_prompts = ContextVar('active_task_prompts', default=None)
active_task_usage = ContextVar('active_task_usage', default=None)


class TaskExample(Contract):
    source_case: str = Field(min_length=1, max_length=160)
    source_revision: str = Field(min_length=1, max_length=160)
    review_scope: str = Field(min_length=1, max_length=1000)
    confirmed: Literal[True]
    query: str = Field(min_length=1, max_length=3000)
    answer: str = Field(min_length=1, max_length=6000)


class TaskPromptInput(Contract):
    scope: TaskScope
    label: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=16000)
    examples: list[TaskExample] = Field(default_factory=list, max_length=3)

    @field_validator('label', 'text')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('名称和任务规则不能为空')
        # No runtime template engine: reject placeholders instead of silently using missing variables.
        if '{{' in value or '{%' in value:
            raise ValueError('任务规则不支持未解析的模板变量，请使用普通文字')
        return value


def task_instructions(scope: str) -> str:
    selected = (active_task_prompts.get() or {}).get(scope)
    if selected is None:
        selected = {'scope': scope, 'text': DEFAULT_TASKS[scope], 'version': 'builtin-task-v1', 'examples': []}
    usage = active_task_usage.get()
    if usage is not None and not any(x['scope'] == scope and x['version'] == selected['version'] for x in usage):
        usage.append({**{k: selected[k] for k in ('scope', 'version', 'prompt_id', 'sha256') if k in selected},
                      'shot_mode': 'few-shot' if selected.get('examples') else 'zero-shot',
                      'example_count': len(selected.get('examples', []))})
    text = '\n【任务策略：' + scope + '】\n' + selected['text']
    if selected.get('examples'):
        text += '\n【表达示例，仅示范任务方式，不是当前问题的事实或引用依据】\n' + json.dumps(selected['examples'], ensure_ascii=False)
    return text
