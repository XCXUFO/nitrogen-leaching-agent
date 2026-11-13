"""Run the eight reviewed targets with real LLM calls in an isolated fixture."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

from src.config import Settings
from src.evaluation.material_replay import replay
from src.evaluation.versioning import build_manifest
from src.llm.deepseek import DeepSeekClient


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'backend/var/handoff/2026-11-10-materials/source')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case-id', action='append', help='Only rerun this source ID; may be repeated')
    parser.add_argument('--live', action='store_true', help='Make bounded real model calls using the existing configured key')
    parser.add_argument('--starred-first-batch',action='store_true',help='Seed the provided 25 professional starred records into this isolated replay only')
    args = parser.parse_args()
    if not args.live:
        parser.error('Specify --live for real model calls; import_material_handoff.py is offline.')
    allowed = (ROOT / 'backend/var/handoff').resolve()
    if allowed not in args.output.resolve().parents:
        parser.error('Output must be a new directory under backend/var/handoff.')
    settings = Settings()
    if not settings.deepseek_api_key:
        parser.error('The existing DeepSeek key is not configured.')
    # This experiment deliberately uses managed text on the exported subset.
    frozen = settings.model_copy(update={'rag_enabled': False, 'web_search_enabled': False,
                                        'deepseek_max_retries': 0, 'deepseek_timeout_s': 60})
    llm = DeepSeekClient(api_key=frozen.deepseek_api_key, base_url=frozen.deepseek_base_url,
        model=frozen.deepseek_model, proxy=frozen.deepseek_proxy, timeout_s=60, max_retries=0,
        output_token_limit=3000, thinking_enabled=False)
    try:
        from src.evaluation.starred_content import first_batch
        await replay(args.source, args.output, llm, config_manifest=build_manifest(frozen),
            top_k=frozen.chat_top_k, max_context_chars=frozen.chat_max_context_chars, temperature=frozen.chat_temperature,
            case_ids=set(args.case_id) if args.case_id else None,starred_records=first_batch() if args.starred_first_batch else None)
    finally:
        await llm._client.close()


if __name__ == '__main__':
    asyncio.run(main())
