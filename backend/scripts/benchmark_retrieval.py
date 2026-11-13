"""Offline, same-corpus comparison of local index and legacy scan (no LLM)."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))

from src.agent.contracts import TaskState
from src.agent.understanding import understand,map_tags
from src.evaluation.material_replay import prepare_fixture

QUERIES=['玉米氮淋失的影响因素','菜地 N₂O 排放规律','氧化亚氮排放变化',
         'WHCNS模型的氮平衡','土壤水分与硝态氮迁移','小麦氮素利用效率','灌溉施肥管理','蔬菜田氮排放规律']


def timed(fn):
    start=time.perf_counter()
    result=fn()
    return result,round((time.perf_counter()-start)*1000,3)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'backend/var/handoff/2026-11-10-materials/source')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=3,choices=range(1,11))
    args=parser.parse_args()
    if (ROOT/'backend/var/handoff').resolve() not in args.output.resolve().parents:
        parser.error('Output must be a new directory under backend/var/handoff.')
    library,cases=prepare_fixture(args.source,args.output)
    try:
        count,cold=timed(lambda:library.search_index.local.ensure(rebuild=True))
        rows=[]
        for query in QUERIES:
            context,interpret_ms=timed(lambda:understand(SimpleNamespace(query=query,case_ids=[]),
                TaskState(conversation_id='benchmark'),SimpleNamespace(run_id='benchmark',turn_id='turn'),library.matching_taxonomy()))
            mapping,mapping_ms=timed(lambda:map_tags(context,library.matching_taxonomy()))
            item={'query':query,'understanding_ms':interpret_ms,'mapping_ms':mapping_ms,'indexed_ms':[],'scan_ms':[]}
            sets={}
            for repeat in range(args.repeats):
                # Alternate order to reduce a systematic filesystem-cache advantage.
                for strategy in (['indexed','scan'] if repeat%2==0 else ['scan','indexed']):
                    library.search_strategy=strategy
                    (hits,trace),elapsed=timed(lambda:library.search_index.search(query,understanding=context,mapping=mapping,limit=20))
                    item[strategy+'_ms'].append(elapsed)
                    sets[strategy]={h.chunk_id for h in hits}
                    item[strategy+'_paper_ids']=sorted({h.metadata['paper_id'] for h in hits})
                    if strategy=='indexed': item['pipeline']=trace.diagnostics
            item['top20_chunk_overlap']=len(sets['indexed']&sets['scan'])
            rows.append(item)
            print(query+': indexed='+str(statistics.median(item['indexed_ms']))+'ms scan='+str(statistics.median(item['scan_ms']))+'ms',flush=True)
        result={'scope':'35 received linked papers only; local text recall, no vectors/reranker/web/LLM',
            'source_manifest_sha256':hashlib.sha256((args.source/'manifest.json').read_bytes()).hexdigest(),
            'top_k':20,'repeats':args.repeats,'cold_build_ms':cold,'cold_rebuilt_materials':count,
            'index_version':rows[0]['pipeline']['version'],'queries':rows,
            'indexed_median_ms':statistics.median([x for r in rows for x in r['indexed_ms']]),
            'scan_median_ms':statistics.median([x for r in rows for x in r['scan_ms']]),
            'quality_note':'Top20 overlap is diagnostic, not labelled Recall@K or professional review.',
            'code_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                [ROOT/'backend/src/retrieval/local_index.py',ROOT/'backend/src/rag/literature_index.py',ROOT/'backend/src/agent/understanding.py']}}
        (args.output/'benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k in {'indexed_median_ms','scan_median_ms','cold_build_ms','cold_rebuilt_materials'}},ensure_ascii=False),flush=True)
    finally:
        library.close();cases.close()


if __name__=='__main__': main()
