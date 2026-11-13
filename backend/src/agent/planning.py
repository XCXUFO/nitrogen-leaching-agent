"""Plans describe candidates and prerequisites; calls remain the execution truth."""
VERSION = 'task-routing-v1'


def plan(understanding, decision, *, service, llm, cases, has_file, specified=False):
    tasks=[]
    for task in understanding.get('subtasks', []):
        intent=task['intent']
        candidates = (['capability_guidance'] if intent == 'capability' else
                      ['file_inspector','whcns_analyzer'] if intent == 'file_calculation' else
                      ['case_assistant'] if task.get('input_kind') == 'case' or intent == 'case_search' else
                      list(decision.skills))
        available = {skill: ('available' if
            (skill in {'capability_guidance','clarification','file_inspector','whcns_analyzer'} or
             skill == 'concept_explanation' and (llm is not None or service is not None) or
             skill == 'knowledge_search' and service is not None or
             skill == 'case_assistant' and llm is not None and (cases is not None or task.get('input_kind') == 'user_text'))
            else 'dependency_unavailable') for skill in candidates}
        for skill in candidates:
            if skill in {'file_inspector','whcns_analyzer'} and not has_file: available[skill]='input_missing'
        tasks.append({'subtask_id':task['subtask_id'],'intent':intent,'input_kind':task.get('input_kind'),
            'depends_on':task.get('depends_on',[]),'candidate_skills':candidates,'availability':available,
            'required_inputs':['valid_attachment','supported_metric'] if 'whcns_analyzer' in candidates else [],
            'has_attachment':has_file,'status':'planned'})
    return {'version':VERSION,'mode':'specified' if specified else 'auto','understanding_version':understanding.get('version'),
        'resolved_query':understanding.get('resolved_query'),'tasks':tasks,'initial_selected_skills':list(decision.skills),
        'reason':decision.reason_code,'actual_calls':[]}
