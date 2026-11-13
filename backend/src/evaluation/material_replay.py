"""Real-runtime diagnostics on the received corpus subset, not full-index replay."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.agent.chat_service import ChatService
from src.agent.runtime import AgentRuntime
from src.api.chat_schema import ChatRequest
from src.api.literature import LiteratureStore, PaperInput
from src.evaluation.material_handoff import read_json, verify_files
from src.rag.chunker import chunk_text
from src.storage.case_library import CaseInput, CaseStore
from src.storage.run_store import RunStore


class ManagedTextRetriever:
    """Use the existing managed full-text search; no vector/reranker claim."""
    def __init__(self, index):
        self.index = index

    def retrieve(self, query, k=5, **kwargs):
        return self.index.search(query, limit=k)[0]


def prepare_fixture(source: Path, output: Path):
    verify_files(source)
    # Never open an existing business database or replace a prior experiment.
    output.mkdir(parents=True, exist_ok=False)
    library = LiteratureStore(str(output / 'library.sqlite3'), str(output / 'files'))
    cases = CaseStore(str(output / 'cases.sqlite3'))
    at = datetime.now(timezone.utc).isoformat()
    index = read_json(source / 'index.json')
    for material in index['materials']:
        identifier = material['id']
        if material['kind'] == 'literature':
            info = read_json(source / f'literature/{identifier}.pdf-info.json')
            data = PaperInput(title=material['title'], source_url=material['url']).model_dump(exclude={'upload_id'})
            with library.write():
                library.db.execute('''INSERT INTO papers
                    (id,data,filename,sha256,registration,created_by,created_at,updated_by,updated_at)
                    VALUES (?,?,?,?,'draft','material-handoff',?,'material-handoff',?)''',
                    (identifier, json.dumps(data, ensure_ascii=False), f'{identifier}.pdf', info['sha256'], at, at))
                # Some index.full_text values were left null by the export;
                # the verified manifest and per-paper metadata include the TXT.
                text = (source / f'literature/{identifier}.txt').read_text(encoding='utf-8')
                chunks = [{'text': c.text, 'char_start': c.metadata['char_start'], 'char_end': c.metadata['char_end'],
                           'file_sha256': info['sha256']} for c in chunk_text(text, identifier, material['url'])]
                key = library.search_index.content_key(library.get_paper(identifier))
                library.db.execute("INSERT INTO literature_search_sync VALUES (?,?,?,'ready',?,NULL,'text',?)",
                    (identifier, key, str(uuid4()), at, json.dumps(chunks, ensure_ascii=False)))
            # The immutable receipt owns the PDF; a local link avoids duplicating it.
            (library.root / f'blob-{info["sha256"]}.pdf').symlink_to((source / material['original_pdf']).resolve())
        else:
            page = read_json(source / material['page_metadata'])
            versions = list((source / 'cases/historical').glob(f'{identifier}@*.json'))
            if len(versions) != 1:
                raise ValueError('expected one verified historical case body')
            historical = read_json(versions[0])['candidate']
            created = cases.create(CaseInput(title=page['title'], body=historical['snippet'], body_format='html',
                source=page['url'], enabled=True), 'material-handoff')
            with cases.lock, cases.db:
                cases.db.execute('UPDATE reference_cases SET id=?,revision=? WHERE id=?', (identifier, historical['revision'], created['id']))
    return library, cases


async def replay(source: Path, output: Path, llm, *, config_manifest, top_k=5, max_context_chars=4000, temperature=0.3, case_ids=None, starred_records=None):
    reviewed = read_json(source / 'conversations/reviewed-cases.json')['records']
    if case_ids is not None:
        if not case_ids or not set(case_ids) <= {record['id'] for record in reviewed}:
            raise ValueError('unknown or empty target selection')
        reviewed = [record for record in reviewed if record['id'] in case_ids]
    library, cases = prepare_fixture(source, output)
    config = config_manifest.get('answer_config',{})
    library.search_strategy = cases.search_strategy = config.get('retrieval_strategy','indexed')
    material_index = read_json(source / 'index.json')
    manifest = {**config_manifest, 'material_replay': {
        'scope': 'linked_materials_subset',
        'papers': sum(m['kind'] == 'literature' for m in material_index['materials']),
        'cases': sum(m['kind'] == 'case' for m in material_index['materials']),
        'retrieval': 'existing_managed_text_search',
        'thinking_enabled': getattr(llm, '_thinking_enabled', None),
        'vectors': False, 'reranker': False, 'web': False,
        'offsets': 'exported_paginated_text_not_historical_chunk_offsets',
        'source_manifest_sha256': hashlib.sha256((source / 'manifest.json').read_bytes()).hexdigest(),
        'replay_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    if starred_records is not None:
        manifest['material_replay']['starred_first_batch']={'questions':len(starred_records),
            'answers':sum(bool(q['answer']) for q in starred_records),
            'sha256':hashlib.sha256(json.dumps(starred_records,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
    version = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    manifest['manifest_sha256'] = version
    runtime = AgentRuntime(runs=RunStore(output / 'runs.sqlite3'), config_version=version, config_manifest=manifest,
                           unified_routing=config.get('unified_routing_enabled',True))
    starred_provider=None
    if starred_records is not None:
        from src.evaluation.store import EvaluationStore
        from src.evaluation.starred_content import import_first_batch
        starred=EvaluationStore(runtime.runs)
        if not import_first_batch(starred,starred_records,apply=True)['applied']: raise ValueError('Starred fixture import conflict')
        starred_provider=starred.starred_questions
    service = ChatService(ManagedTextRetriever(library.search_index), llm, top_k=top_k,
        max_context_chars=max_context_chars, temperature=temperature, literature_index=library.search_index,
        recall_fusion=config.get('retrieval_fusion','rrf'))
    rounds = read_json(source / 'index.json')['rounds']
    result = {'mode': 'current_runtime_material_subset', 'professional_review': 'pending',
              'original_reviews_changed': False, 'full_online_retrieval_reproduced': False,
              'config_manifest': manifest, 'requested_case_ids': [r['id'] for r in reviewed], 'attempts': []}
    def save():
        (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    try:
        for record in reviewed:
            original = next(r for r in rounds if r['case_id'] == record['id'] and r['turn'] == (record['target_turn'] or 1))
            raw = read_json(source / original['raw_path'])
            history = raw['request_snapshot']['history'] if record['evaluation_mode'] == 'fixed_history_target_turn' else []
            session = 'materials_' + uuid4().hex
            attempt = {'case_id': record['id'], 'status': 'running', 'evaluation_mode': record['evaluation_mode'],
                       'source_review_status': record['source_review_status'], 'professional_review': 'pending', 'steps': []}
            result['attempts'].append(attempt)
            save()
            for query in record['user_turns']:
                run_id = str(uuid4())
                entry = {'query': query, 'run_id': run_id, 'history': list(history), 'status': 'running'}
                attempt['steps'].append(entry)
                save()
                try:
                    response = await asyncio.wait_for(runtime.execute(ChatRequest(query=query, session_id=session,
                        history=history, operator_id='local-material-retest'), service=service, get_report=None,
                        case_store=cases, llm=llm, run_id=run_id,taxonomy_provider=library.matching_taxonomy,starred_provider=starred_provider), timeout=240)
                    trace = runtime.runs.get(run_id)
                    entry.update(status='completed', response=response.model_dump(mode='json'),
                        case_context=trace.case_context, actual_prompt=trace.skill_config,
                        actual_config_version=trace.config_version,execution_plan=trace.execution_plan,starred_match=trace.starred_match,
                        retrieval_summary=[{k:v for k,v in item.items() if k in {'source_type','pipeline','status','stage','adopted_chunk_ids'}} for item in trace.retrieval])
                    body_text = response.answer.removeprefix('以下回答未引用本知识库资料，属于通用知识说明。').strip()
                    if not body_text:
                        entry.update(status='failed', error_code='empty_model_answer')
                        attempt['status'] = 'failed'
                        break
                    history = history + [{'role': 'user', 'content': query}, {'role': 'assistant', 'content': response.answer}]
                except asyncio.CancelledError:
                    entry['status'] = attempt['status'] = 'interrupted'
                    save()
                    raise
                except Exception as exc:
                    # Never persist provider bodies or exception strings with credentials.
                    entry.update(status='failed', error_type=type(exc).__name__, http_status=getattr(exc, 'status_code', None))
                    attempt['status'] = 'failed'
                    break
                finally:
                    save()
            else:
                attempt['status'] = 'completed'
            save()
            print(json.dumps({'case_id': record['id'], 'status': attempt['status'], 'steps': len(attempt['steps'])}), flush=True)
        return result
    finally:
        save()
        runtime.runs.close()
        cases.close()
        library.close()
