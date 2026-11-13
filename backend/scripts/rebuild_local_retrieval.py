"""Rebuild local SQLite recall indexes atomically, preserving IDs and vectors."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))

from src.api.literature import LiteratureStore
from src.storage.case_library import CaseStore
from src.retrieval.local_index import VERSION


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--literature-db',type=Path)
    parser.add_argument('--literature-root',type=Path)
    parser.add_argument('--case-db',type=Path)
    args=parser.parse_args()
    if not (args.literature_db or args.case_db): parser.error('Specify at least one existing database.')
    if args.literature_db and not args.literature_root: parser.error('--literature-root is required.')
    for path in (args.literature_db,args.case_db):
        if path and not path.is_file(): parser.error('Database must already exist: '+str(path))
    stores=[]
    try:
        if args.literature_db:
            store=LiteratureStore(str(args.literature_db),str(args.literature_root))
            stores.append(('literature',store,store.search_index.local))
        if args.case_db:
            store=CaseStore(str(args.case_db))
            stores.append(('case',store,store.search_index))
        for name,store,index in stores:
            start=time.perf_counter()
            if index is None: raise RuntimeError('Local '+name+' index unavailable; old retrieval remains selectable.')
            count=index.ensure(rebuild=True)
            print(json.dumps({'kind':name,'version':VERSION,'rebuilt_materials':count,'elapsed_ms':round((time.perf_counter()-start)*1000,3)}))
    finally:
        for _,store,_ in stores: store.close()


if __name__=='__main__': main()
