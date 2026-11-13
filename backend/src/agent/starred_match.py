"""Auditable reuse of maintained Q&A; no answer means no coverage."""
import hashlib
import json
import re

from src.agent.understanding import canonical, CROPS, terms, explicit_tag_spans
from src.agent.routing import guidance_query
from src.agent.domain_scope import outside_domain
from src.agent.concept_intent import concept_intent

VERSION = 'starred-matching-v4'
FRESH = re.compile(r'联网|最新|新资料|重新检索|重新查|查新|查找.{0,8}(?:文献|论文)|搜索')
PROJECT_FRAME = r'(?:根据|依据|按照|按|结合)?(?:这个|这一|本|该)?(?:课题|项目)(?:的)?(?:材料|方案)?(?:中|里)?(?:提出|所述|描述)?'


def question_key(text):
    value = canonical(text)
    for pattern, replacement in (
        (r"主要受哪些因素影响|受什么影响|影响因素有哪些|有哪些影响因素|为什么会发生|原因是什么|有哪些原因", "原因"),
        (r"是什么意思|什么意思|是什么|的含义|的定义|含义是什么", "含义"),
        (r"氮素淋洗|氮素淋失|氮淋洗", "氮淋失"),
        (r"请问|请解释|解释一下|能不能|可以|帮我|一下|什么是|[\s，,。？?！!:：；;]", ""),
    ):
        value = re.sub(pattern, replacement, value)
    return value


def reuse_key(text, reuse):
    """Compare equivalent wording without discarding factual scope or conditions."""
    value = question_key(text)
    value = re.sub(r'[“”‘’"「」『』]', '', value)
    value = re.sub(r'如何|怎样|怎么', '如何', value)
    value = re.sub(r'数据[—–-]+模型[—–-]+应用', '数据模型应用', value)
    if reuse.get('profile') in {'project_plan', 'scale_models'}:
        # Maintained project answers already retain their explicit plan/source
        # boundary. A framing prefix does not add an independent requirement.
        value = re.sub('^' + PROJECT_FRAME, '', value)
    return value


def applicability(task, *, specified=False):
    query=task['query']
    if task.get('domain_scope') == 'outside' or outside_domain(query): return 'outside_supported_domain'
    if specified: return 'specified_execution'
    if guidance_query(query) or task.get('intent')=='capability': return 'capability_request'
    if task.get('intent')=='file_calculation': return 'current_file_calculation'
    if task.get('intent')=='case_search' or task.get('input_kind') in {'case','user_text'} or re.search(r'案例|指定材料|当前附件',query): return 'material_execution_required'
    if FRESH.search(query) or explicit_tag_spans(query): return 'fresh_retrieval_required'
    # An introductory question needs an explanation at the requested depth.
    # A related project Q&A is not a ready-made overview of the concept. Keep
    # explicit project questions eligible for their maintained source answer.
    if concept_intent(query) and not re.search(PROJECT_FRAME + r'|\b(?:project|thesis)\b', query, re.I):
        return 'concept_explanation_required'
    return None


def requirements(task):
    """Split independent asks inside a sentence without equating sentence count with coverage."""
    # A source-introduction clause is context for the ask, not an additional
    # uncovered request that should trigger retrieval after reusing the answer.
    query=re.sub('^(' + PROJECT_FRAME + r')[，,]\s*', r'\1', task['query'])
    scale=bool(re.search(r'(?:农田|田块).{0,12}区域|区域.{0,12}(?:农田|田块)|分尺度.{0,12}两类模型',query))
    reason=bool(re.search(r'为何|为什么|原因|理由',query))
    construction=bool(re.search(r'如何构建|怎样构建|怎么构建|如何建|怎么建|各自.{0,8}构建|结构|输入输出|耦合|验证',query))
    if scale and reason and construction:
        return [{'aspect_id':task['subtask_id']+':reason','query':'在该课题中，为什么农田尺度和区域尺度的氮素淋溶预测需要采用不同建模方案？','kind':'scale_reason'},
                {'aspect_id':task['subtask_id']+':construction','query':'该课题农田尺度和区域尺度氮素淋溶模型各自如何构建？请说明模型结构、输入输出、耦合方法和验证依据。仅以明确涉及该课题实现的资料为依据；一般文献方法另列，不推定为课题已经采用，缺少依据时说明缺口。','kind':'model_construction'}]
    parts=re.split(r'[，,]\s*(?=如何|怎么|怎样|有没有|找)|以及(?=如何|怎么|怎样|有没有|找)',query)
    subject=re.split(r'是什么|是什么意思|为何|为什么|如何|怎么|怎样',parts[0])[0]
    return [{'aspect_id':task['subtask_id']+f':aspect:{i+1}','query':part if i==0 else subject+'；'+part,'kind':'request'} for i,part in enumerate(parts) if part.strip()]


def compatible(query, question, understanding, reuse):
    normalized,other=canonical(query),canonical(question)
    crops={crop for crop in CROPS if crop in normalized}
    other_crops={crop for crop in CROPS if crop in other}
    if other_crops and crops!=other_crops: return False
    if re.findall(r'\d+(?:\.\d+)?',normalized)!=re.findall(r'\d+(?:\.\d+)?',other): return False
    if bool(re.search(r'没有|不要|排除|不适用|不考虑|不是|不种',normalized)) != bool(re.search(r'没有|不要|排除|不适用|不考虑|不是|不种',other)): return False
    for condition in understanding.get('conditions',[]):
        if condition.get('source')=='current_user' and condition.get('category') in {'region','explicit_scope'} and condition['value'] not in other:
            return False
    if reuse.get('profile') in {'project_plan','scale_models'} and re.search(r'当前.{0,8}助手|你.{0,5}能做|已(?:经)?(?:实现|部署|验证)|实际效果|现在能',query): return False
    if reuse.get('profile')=='whcns_intro' and re.search(r'全剖面|地下水|几百|百米|版本|深度|精度|优劣|优于|比.{0,10}(?:好|强)|运行|执行|仿真',query): return False
    return True


def match_starred(understanding, questions, *, specified=False, semantic=None):
    if questions is not None and (not isinstance(questions,list) or any(not isinstance(q,dict) or not isinstance(q.get('question'),str) or not isinstance(q.get('answer',''),str) or not q.get('question_id') or not isinstance(q.get('reuse',{}),dict) for q in questions)):
        raise ValueError('Invalid starred provider output')
    results,covered,remaining=[],[],[]
    assessments={row['aspect_id']:{m['question_id']:m for m in row['matches']}
                 for row in (semantic or {}).get('assessments',[])}
    for task in understanding['subtasks']:
        skip=applicability(task,specified=specified)
        if skip:
            results.append({'subtask_id':task['subtask_id'],'coverage':'not_applicable','reason':skip,'candidates':[],
                            'covered_aspects':[],'uncovered_aspects':[task['query']]})
            remaining.append(dict(task)); continue
        candidates,uncovered,covered_aspects=[],[],[]
        for requirement in requirements(task):
            query=requirement['query']
            aspect_candidates=[]
            for item in questions or []:
                reuse=item.get('reuse',{})
                aliases=[item['question'],*reuse.get('variants',[])]
                key=reuse_key(query,reuse)
                alias_keys=[reuse_key(text,reuse) for text in aliases]
                overlap=max((len(terms(query)&terms(text)) for text in aliases),default=0)
                exact=bool(key) and key in alias_keys
                match_method='normalized_question' if exact else 'term_overlap'
                if not exact and key.endswith('含义'):
                    exact=any(key.removesuffix('含义')==text.removesuffix('含义') for text in alias_keys)
                    if exact: match_method='definition_variant'
                if reuse.get('profile')=='scale_models' and requirement['kind']=='scale_reason':
                    exact=True; match_method='scale_reason'
                if reuse.get('profile')=='whcns_intro' and re.fullmatch(r'whcns(?:模型)?(?:是什么|主要有哪些过程模块|主要模拟哪些过程)?[？?。\s]*',query,re.I):
                    exact=True; match_method='maintained_profile'
                broad=bool(reuse.get('original_question') and reuse_key(reuse['original_question'],reuse)==key and reuse_key(item['question'],reuse)!=key)
                decision=assessments.get(requirement['aspect_id'],{}).get(item['question_id'])
                if requirement['aspect_id'] in assessments:
                    exact=bool(decision and decision['coverage']=='complete')
                    broad=bool(decision and decision['coverage']=='partial')
                    if decision: match_method='semantic_coverage'
                if not overlap and not exact and not broad: continue
                allowed=compatible(task['query'],item['question'],understanding,reuse)
                if decision and any(crop in canonical(task['query']) and crop not in canonical(item['question']+' '+item.get('answer','')) for crop in CROPS):
                    allowed=False
                answer=item.get('answer','').strip()
                state=reuse.get('reuse_status','unknown')
                placeholder=re.sub(r'[\s，,。.]','',answer)
                ready=state in {'unknown','reference','partial'} and bool(answer) and not re.fullmatch(r'(?:有)?(?:待审核|待补充|待补|暂无答案)|无待补',placeholder)
                status=('not_applicable' if not allowed else 'conflict' if state=='conflict' and (exact or broad) else
                        'empty_answer' if not answer and (exact or broad) else 'not_ready' if not ready and (exact or broad) else
                        'adopted' if ready and exact else 'partial' if ready and broad else 'candidate_only')
                snapshot={k:item.get(k) for k in ('question_id','revision','question','answer','updated_at','reuse','source_batch','source_sq_id')}
                fingerprint=hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                record={'question_id':item['question_id'],'aspect_id':requirement['aspect_id'],'status':status,'overlap':overlap,
                        'match_method':match_method,
                        'reason':{'adopted':'需求与已维护范围相符；只按参考答复复用','partial':'原宽题仅有较窄参考答复，其他要求继续处理',
                                  'not_applicable':'条件、版本或对象不适用','conflict':'材料存在冲突，争议答案不复用','empty_answer':'答案为空，继续原任务',
                                  'not_ready':'内容未就绪，不作为正式答复','candidate_only':'仅相近候选，尚不能确认覆盖'}[status],
                        'fingerprint':fingerprint,'snapshot':snapshot}
                if decision: record['semantic_reason']=decision['reason']
                aspect_candidates.append(record)
            aspect_candidates.sort(key=lambda row:(row['status'] in {'adopted','partial'},row['status']=='adopted',row['overlap']),reverse=True)
            competing=[row for row in aspect_candidates if row['status'] in {'adopted','partial'}]
            if any(row['status']=='adopted' for row in competing):
                competing=[row for row in competing if row['status']=='adopted']
            elif semantic is not None:
                # Different incomplete answers may discuss complementary parts;
                # that alone is not a contradiction. The rest still continues.
                competing=[]
            if len({row['snapshot']['answer'].strip() for row in competing})>1:
                for row in competing:
                    row['status'],row['reason']='conflict','同一需求有不同维护答复，未选择任一结论，继续核对'
            selected=next((row for row in aspect_candidates if row['status'] in {'adopted','partial'}),None)
            candidates.extend(aspect_candidates)
            if selected:
                snapshot=selected['snapshot']; reuse=snapshot.get('reuse') or {}
                aspect=reuse.get('coverage_scope') or query
                covered_aspects.append(aspect)
                covered.append({'subtask_id':task['subtask_id'],'aspect_id':requirement['aspect_id'],'query':query,
                    'question_id':selected['question_id'],'revision':snapshot.get('revision'),'answer':snapshot['answer'],
                    'fingerprint':selected['fingerprint'],'snapshot':snapshot,'covered_aspects':[aspect],
                    'source_refs':reuse.get('source_refs',[]),'reuse_status':reuse.get('reuse_status','unknown'),
                    'professional_review':reuse.get('professional_review','unknown')})
                if selected['status']=='partial' or reuse.get('reuse_status')=='partial':
                    uncovered.append('只补充尚未覆盖的需求：'+query+'；重点核对：'+(reuse.get('excluded_scope') or '参考答复未覆盖的条件和内容'))
            else: uncovered.append(query)
        coverage='partial' if covered_aspects and uncovered else 'complete' if covered_aspects else 'none'
        results.append({'subtask_id':task['subtask_id'],'candidates':candidates,'coverage':coverage,
                        'covered_aspects':covered_aspects,'uncovered_aspects':uncovered})
        if uncovered:
            remaining.append({**task,'query':'；'.join(uncovered),'retrieval_query':'；'.join(uncovered),
                              'semantic_query':'；'.join(uncovered)} if covered_aspects else dict(task))
    statuses={c['status'] for row in results for c in row['candidates']}
    status=('full' if covered and not remaining else 'partial' if covered else
            'not_applicable' if all(row['coverage']=='not_applicable' for row in results) else
            'unavailable' if questions is None else 'empty_library' if not questions else
            'conflict' if 'conflict' in statuses else 'empty_answer' if 'empty_answer' in statuses else 'not_ready' if 'not_ready' in statuses else 'no_match')
    return {'version':VERSION,'run_id':understanding['run_id'],'turn_id':understanding['turn_id'],'status':status,
            'tasks':results,'adopted':covered,'remaining_tasks':remaining,'remaining_subtask_ids':[task['subtask_id'] for task in remaining],
            'covered_aspects':[aspect for row in results for aspect in row['covered_aspects']],
            'uncovered_aspects':[aspect for row in results for aspect in row['uncovered_aspects']]}
