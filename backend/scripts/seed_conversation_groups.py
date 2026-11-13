"""Package saved benchmark conversations, retaining source/expectation provenance.

Dry-run by default. Does not replay models or mark any case accepted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'backend/var/eval'
BATCHES = [
    'github-benchmark-20261112', 'multiturn-benchmark-20261112',
    'failed-runs-retest-final-20261112', 'user-record-final-20261113',
    'answer-language-final-20261112', 'boundary-final-20261112',
    'language-edge-final-20261113', 'answer-language-edge-confirm-20261113',
]


def collect():
    records = {}
    failed = set()
    for batch in BATCHES:
        path = BASE / batch
        for case in json.loads((path / 'cases.json').read_text()):
            identifier = case['case_id']
            snapshot = path / 'results' / f'{identifier}-session.json'
            if not snapshot.exists():
                continue
            session = json.loads(snapshot.read_text())
            records[identifier] = {'definition': case, 'session': session, 'batch': batch, 'snapshot': snapshot}
            if batch == 'failed-runs-retest-final-20261112':
                failed.add(identifier)
    groups = {
        '发版必测 · 已修复的运行异常': sorted(failed),
        '专业问答 · AgriEval 与 AgXQA': [k for k in sorted(records) if k.startswith('GHB-') and int(k[4:]) <= 12],
        '边界与安全 · 权威题集及产品边界': [k for k in sorted(records) if k.startswith('GHB-') and int(k[4:]) >= 13],
        '多轮对话 · 条件记忆与指代': [k for k in sorted(records) if k.startswith('MT-')],
        '语言与附件 · 英问英答及中文默认': [k for k in sorted(records) if k.startswith('LANG-')],
    }
    return records, groups


def expected_for(record):
    case = record['definition']
    definitions = case.get('turns') or [{'expected': case.get('expected', '')}]
    lines = []
    for i, turn in enumerate(definitions):
        expected = turn.get('expected', '')
        if isinstance(expected, str) and expected in {'en', 'zh'}:
            expected = '严格使用英文回答。' if expected == 'en' else '使用中文回答；语言不明确时中文优先。'
        if not isinstance(expected, str):
            expected = json.dumps(expected, ensure_ascii=False)
        lines.append(f'第 {i+1} 轮：{expected}')
    return '\n'.join(lines)[:5000]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    records, groups = collect()
    summary = {'unique_conversations': len(records), 'turns': sum(len(r['session']['turns']) for r in records.values()),
        'groups': {k: {'conversations': len(v), 'turns': sum(len(records[i]['session']['turns']) for i in v)} for k, v in groups.items()}}
    if not args.apply:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    from src.config import settings
    from src.storage.run_store import RunStore
    from src.evaluation.conversation_cases import GroupInput, CaptureInput
    import sqlite3
    # This tool is for an idle single-worker installation only. A RunStore must
    # not be opened alongside running conversation batch jobs.
    db = sqlite3.connect(settings.agent_trace_db)
    if db.execute("SELECT COUNT(*) FROM chat_submissions WHERE status IN ('accepted','running')").fetchone()[0]:
        raise SystemExit('Active chat runs: wait for idle before importing.')
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversation_batches'").fetchone()
    if exists and db.execute("SELECT COUNT(*) FROM conversation_batches WHERE json_extract(payload,'$.status') IN ('queued','running')").fetchone()[0]:
        raise SystemExit('Active conversation batch: wait for idle before importing.')
    db.close()
    runs = RunStore(settings.agent_trace_db)
    try:
        store = runs.conversation_cases
        existing = {g['title']: g for g in store.groups()}
        imported = []
        for title, identifiers in groups.items():
            group = existing.get(title) or store.create_group(GroupInput(title=title, notes=
                '整理自2026-11-12至13日的真实评测会话。完整保留原始提问、原回答和附件。权威原题、改写题及产品合成题分别标注来源；运行完成不代表内容已验收。'), 'benchmark-import')
            for identifier in identifiers:
                record = records[identifier]
                definition = record['definition']
                session = runs.session(record['session']['session_id'])
                if not session:
                    raise RuntimeError(f'Missing saved session: {identifier}')
                notes = (f"来源编号：{identifier}\n题集：{definition.get('dataset', '')}\n原题编号：{definition.get('source_id', '')}\n"
                    f"改写说明：{definition.get('adaptation', '见原批次manifest及cases.json')}\n"
                    f"原批次：{record['batch']}\n原记录：{record['snapshot'].relative_to(ROOT)}\n"
                    '来源的固定版本、文件哈希和权威链接见原批次manifest.json。预期标准仅供人工验收，不发送给Agent。')
                case = store.capture(group['group_id'], CaptureInput(session_id=session['session_id'],
                    title=f"{identifier} · {definition.get('category', session['topic'])}", expected=expected_for(record), notes=notes), 'benchmark-import')
                imported.append({'group_id': group['group_id'], 'case_id': case['case_id'], 'source_id': identifier, 'session_id': session['session_id']})
        summary['memberships'] = imported
        summary['applied'] = True
        output = BASE / 'conversation-groups-20261113.json'
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps({k: v for k, v in summary.items() if k != 'memberships'}, ensure_ascii=False, indent=2))
    finally:
        runs.close()


if __name__ == '__main__':
    main()
