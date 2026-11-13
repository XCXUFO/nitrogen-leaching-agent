"""Preview or import the supplied 25 professional Q&As into a local database."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))

from src.config import Settings
from src.evaluation.starred_content import first_batch,import_first_batch
from src.evaluation.store import EvaluationStore
from src.storage.run_store import RunStore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=Path(Settings().agent_trace_db))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--apply',action='store_true',help='Back up the local database, then create/bind missing records without overwriting answers.')
    args=parser.parse_args()
    if not args.db.is_file(): parser.error('An existing local database is required.')
    if ROOT.resolve() not in args.db.resolve().parents: parser.error('Only a database in this workspace may be imported.')
    if (ROOT/'backend/var/handoff').resolve() not in args.output.resolve().parents: parser.error('Output must be a new handoff directory.')
    args.output.mkdir(parents=True,exist_ok=False)
    with sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro',uri=True) as original:
        if args.apply:
            with sqlite3.connect(args.output/'before.sqlite3') as backup: original.backup(backup)
            runs=RunStore(args.db)
        else:
            runs=RunStore()
            original.backup(runs._connection)
    try:
        store=EvaluationStore(runs)
        result=import_first_batch(store,first_batch(),apply=args.apply)
        result.update(database=str(args.db),online_written=False)
        (args.output/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps({'existing_count':result['existing_count'],'planned':len(result['records']),
            'conflicts':len(result['conflicts']),'applied':result['applied'],'online_written':False}))
        if result['conflicts']: raise SystemExit(2)
    finally: runs.close()


if __name__=='__main__': main()
