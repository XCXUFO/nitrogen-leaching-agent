"use client";

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { conversationCaseHref } from '@/lib/evaluation-navigation';
import { useEvaluationSession } from './evaluation-shell';
import { MarkdownAnswer } from './chat/markdown-answer';
import { conversationApi as api, statusLabels as labels, type CaseGroup, type ConversationCase,
  type ConversationBatch, type ConversationIssue, type CaseResult } from '@/lib/conversation-evaluation';

const button = "wb-button";
const field = "wb-field";
const panel = "wb-panel space-y-4";
const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败，请重试。';
const date = (value: string) => new Date(value).toLocaleString('zh-CN');

export function CaptureConversation({ token, sessionId, title, readOnly = false, onSaved }: {
  token: string; sessionId: string; title: string; readOnly?: boolean; onSaved?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState<CaseGroup[]>([]);
  const [groupId, setGroupId] = useState('');
  const [newTitle, setNewTitle] = useState('');
  const [expected, setExpected] = useState('');
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');
  const [busy, setBusy] = useState(false);
  async function show() {
    setOpen(true); setError('');
    try { const result = await api<CaseGroup[]>(token, '/case-groups'); setGroups(result); setGroupId(result[0]?.group_id ?? ''); }
    catch (error) { setError(errorText(error)); }
  }
  async function save() {
    setBusy(true); setError('');
    try {
      let target = groupId;
      if (newTitle.trim()) {
        const group = await api<CaseGroup>(token, '/case-groups', { title: newTitle });
        target = group.group_id; setGroupId(target); setNewTitle(''); setGroups((old) => [group, ...old]);
      }
      if (!target) throw new Error('请选择用例组，或填写新组名称。');
      await api(token, `/case-groups/${target}/cases`, { session_id: sessionId, title, expected });
      setSaved(target); setOpen(false); onSaved?.();
    } catch (error) { setError(errorText(error)); } finally { setBusy(false); }
  }
  return <div className="space-y-2">
    {!readOnly && <button className={button} onClick={() => void show()}>加入用例组</button>}
    {saved && <p role="status" className="text-sm text-emerald-800">完整会话已保存。<Link className="underline" href={`/evaluation/case-groups/${saved}`}>查看用例组</Link></p>}
    {open && <section aria-label="保存会话用例" className="space-y-3 rounded-lg border border-emerald-200 bg-emerald-50/50 p-4">
      <p className="text-sm">保存当前整段会话，包含所有轮次、上下文和原附件。原会话后续新增内容不会改动已保存的用例。</p>
      <label className="block text-sm">用例组<select className={field} value={groupId} onChange={(e) => setGroupId(e.target.value)}><option value="">请选择</option>{groups.map((g) => <option key={g.group_id} value={g.group_id}>{g.title}</option>)}</select></label>
      <label className="block text-sm">或新建一个组<input className={field} maxLength={100} value={newTitle} onChange={(e) => setNewTitle(e.target.value)} /></label>
      <label className="block text-sm">预期表现<textarea className={field} rows={3} maxLength={5000} placeholder="可以先收藏；验收前需明确通过标准。" value={expected} onChange={(e) => setExpected(e.target.value)} /></label>
      {error && <p role="alert" className="text-sm text-red-800">{error}</p>}
      <div className="flex gap-2"><button className={button} disabled={busy || (!groupId && !newTitle.trim())} onClick={() => void save()}>保存完整会话</button><button className={button} disabled={busy} onClick={() => setOpen(false)}>取消</button></div>
    </section>}
  </div>;
}

function CaseComparison({ id, token, canEdit, allowReplay = true }: { id: string; token: string; canEdit: boolean; allowReplay?: boolean }) {
  const router = useRouter();
  const [value, setValue] = useState<ConversationCase | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState('');
  const submission = useRef('');
  useEffect(() => {
    let active = true;
    api<ConversationCase>(token, `/conversation-cases/${id}`).then((c) => { if (active) { setValue(c); setSelected((c.versions ?? []).slice(0, 2).map((v) => v.batch_id)); } }).catch((e) => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, [token, id]);
  async function save() {
    if (!value) return;
    setBusy(true); setError('');
    try { const result = await api<ConversationCase>(token, `/conversation-cases/${id}`, { title: value.title, expected: value.expected, notes: value.notes, expected_revision: value.revision }, 'PUT'); setValue({ ...result, versions: value.versions }); setEditing(false); }
    catch (error) { setError(errorText(error)); } finally { setBusy(false); }
  }
  return <section aria-label="会话用例与版本回答" className={panel}>
    {error && <p role="alert" className="text-red-800">{error}</p>}
    {!value ? <p>正在读取会话用例…</p> : <>
      <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">{value.title}</h3><Link className="text-sm text-emerald-800 underline" href={`/evaluation/runs/${value.source_session_id}`}>原始会话</Link></div>
      {editing ? <div className="space-y-3">
        <label className="block text-sm">用例标题<input className={field} value={value.title} maxLength={200} onChange={(e) => setValue({ ...value, title: e.target.value })} /></label>
        <label className="block text-sm">预期表现<textarea className={field} rows={4} value={value.expected} maxLength={5000} onChange={(e) => setValue({ ...value, expected: e.target.value })} /></label>
        <label className="block text-sm">补充说明<textarea className={field} rows={2} value={value.notes} maxLength={3000} onChange={(e) => setValue({ ...value, notes: e.target.value })} /></label>
        <button className={button} disabled={busy || !value.title.trim()} onClick={() => void save()}>保存标准</button>
        <p className="text-xs text-slate-500">标准更新用于下次重跑，已运行版本的标准保留原样。</p>
      </div> : <><p className="whitespace-pre-wrap break-words text-sm">预期：{value.expected || '尚未填写，通过验收前需要补充。'}</p>{value.notes && <p className="whitespace-pre-wrap break-words text-sm text-slate-500">{value.notes}</p>}{canEdit && <button className={button} onClick={() => setEditing(true)}>编辑预期标准</button>}</>}
      {canEdit && !allowReplay && <Link className="inline-block text-sm text-emerald-800 underline" href={`/evaluation/case-groups/versions?case=${encodeURIComponent(id)}`}>前往版本管理验证此会话</Link>}
      {canEdit && allowReplay && <div className="flex flex-wrap gap-2"><input aria-label="此会话的验证版本" className={`${field} max-w-sm`} maxLength={100} value={version} onChange={(e) => { setVersion(e.target.value); submission.current = ''; }} placeholder="填写版本名称，只验证此会话" /><button className={button} disabled={busy || !version.trim()} onClick={async () => {
        setBusy(true); setError(''); if (!submission.current) submission.current = crypto.randomUUID();
        try { const b = await api<ConversationBatch>(token, '/conversation-batches', { submission_id: submission.current, case_ids: [id], version_name: version }); submission.current = ''; router.push(`/evaluation/case-groups/versions?case=${encodeURIComponent(id)}&batch=${encodeURIComponent(b.batch_id)}`); }
        catch (error) { setError(errorText(error)); } finally { setBusy(false); }
      }}>重跑完整会话</button></div>}
      {!!value.seed_history.length && <details className="text-sm"><summary>会话起点前的历史上下文（{value.seed_history.length} 条）</summary>{value.seed_history.map((h, i) => <p key={i} className="mt-2 whitespace-pre-wrap">{h.role}：{h.content}</p>)}</details>}
      <div className="flex flex-wrap gap-3 text-sm" aria-label="选择对比版本"><span>前后版本回答：</span>{(value.versions ?? []).map((v) => <label key={v.batch_id} className="flex items-center gap-1"><input type="checkbox" checked={selected.includes(v.batch_id)} onChange={(e) => setSelected(e.target.checked ? [...selected, v.batch_id] : selected.filter((id) => id !== v.batch_id))} />{v.version_name} · {date(v.created_at)}</label>)}{!value.versions?.length && <span className="text-slate-500">重跑后会在这里保留各版本回答。</span>}</div>
      <div className="flex gap-4 overflow-x-auto pb-2">
        <section className="min-w-72 flex-1 space-y-3 rounded-lg bg-slate-50 p-3"><h4 className="text-sm font-medium">保存时的原回答 · {value.turns.length} 轮</h4>{value.turns.map((t, i) => <div key={i} className="space-y-2 border-t pt-3 text-sm"><p className="font-medium">第 {i + 1} 轮：{t.query}</p>{!!t.attachments.length && <p className="text-xs text-slate-500">附件：{t.attachments.map((a) => a.filename).join('、')}</p>}<MarkdownAnswer content={t.baseline_answer || '原运行未完成'} /><p className="break-all text-xs text-slate-500">{t.baseline_config}</p></div>)}</section>
        {(value.versions ?? []).filter((v) => selected.includes(v.batch_id)).map((v) => <section key={v.batch_id} className="min-w-72 flex-1 space-y-3 rounded-lg border p-3"><h4 className="text-sm font-medium">{v.version_name} · {labels[v.result.status]} · {v.result.judgment ? labels[v.result.judgment.conclusion] : '待验收'}</h4><p className="break-all text-xs text-slate-500">{v.config_version}</p><p className="whitespace-pre-wrap break-words text-xs text-slate-500">本次标准：{v.result.case.expected || '未填写'}</p>{v.result.turns.map((t, i) => <div key={t.run_id} className="space-y-2 border-t pt-3 text-sm"><p className="font-medium">第 {i + 1} 轮：{t.query}</p><MarkdownAnswer content={t.response?.answer || '本轮未完成'} /><Link className="text-xs text-emerald-800 underline" href={`/evaluation/runs/${v.result.session_id}`}>运行记录</Link></div>)}{v.result.error && <p className="text-sm text-red-800">{v.result.error}</p>}{v.result.judgment && <p className="text-sm">验收依据：{v.result.judgment.note}</p>}</section>)}
      </div>
    </>}
  </section>;
}

function BatchResult({ result, batch, token, canEdit, onChange, onCompare }: { result: CaseResult; batch: ConversationBatch; token: string; canEdit: boolean; onChange: (b: ConversationBatch) => void; onCompare: () => void }) {
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function judge(conclusion: string) {
    setBusy(true); setError('');
    try { onChange(await api<ConversationBatch>(token, `/conversation-batches/${batch.batch_id}/cases/${result.case.case_id}/judgments`, { conclusion, note })); }
    catch (error) { setError(errorText(error)); } finally { setBusy(false); }
  }
  return <section className={panel}>
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium">{result.case.title} · {result.case.turns.length} 轮</h3><span className="text-sm">{labels[result.status]} · {result.judgment ? labels[result.judgment.conclusion] : '待验收'}</span></div>
    <p className="whitespace-pre-wrap break-words text-sm">本次预期：{result.case.expected || '尚未填写；需要补充后重新验证。'}</p>
    <div className="flex gap-3 text-sm"><button className="text-emerald-800 underline" onClick={onCompare}>查看前后版本回答</button><Link className="text-emerald-800 underline" href={`/evaluation/runs/${result.session_id}`}>本次完整运行</Link></div>
    {result.error && <p role="alert" className="text-sm text-red-800">{result.error}</p>}
    <details open={batch.case_count === 1 || undefined}><summary className="cursor-pointer text-sm">本次全部回答（{result.turns.length} 轮）</summary><div className="mt-3 space-y-4">{result.turns.map((t, i) => <div key={t.run_id} className="space-y-2 border-t pt-3 text-sm"><p className="font-medium">第 {i + 1} 轮：{t.query}</p><MarkdownAnswer content={t.response?.answer || labels[t.status]} /></div>)}</div></details>
    {result.judgment && <p className="whitespace-pre-wrap break-words text-sm text-slate-600">{result.judgment.actor}：{result.judgment.note}</p>}
    {canEdit && batch.status === 'completed' && result.status === 'succeeded' && <div className="space-y-2"><textarea aria-label={`验收依据：${result.case.title}`} className={field} rows={2} maxLength={5000} placeholder="核对预期后，填写验收依据" value={note} onChange={(e) => setNote(e.target.value)} /><div className="flex flex-wrap gap-2">{[['pass', '符合预期'], ['fail', '仍有问题'], ['pending', '撤回验收']].map(([value, title]) => <button key={value} className={button} disabled={busy || !note.trim() || (value === 'pass' && !result.case.expected.trim())} onClick={() => void judge(value)}>{title}</button>)}</div></div>}
    {error && <p role="alert" className="text-sm text-red-800">{error}</p>}
  </section>;
}

export function ConversationCaseWorkspace({ caseId }: { caseId: string }) {
  const { token, user } = useEvaluationSession();
  return <CaseComparison key={caseId} id={caseId} token={token} canEdit={user.role !== 'tester'} allowReplay={false} />;
}

export function ConversationCasesWorkspace({ detail = '' }: { detail?: string }) {
  const { token, user } = useEvaluationSession();
  const canEdit = user.role !== 'tester';
  const router = useRouter();
  const [groups, setGroups] = useState<CaseGroup[]>([]);
  const [group, setGroup] = useState<CaseGroup | null>(null);
  const [newTitle, setNewTitle] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  async function refresh() {
    if (detail) setGroup(await api<CaseGroup>(token, `/case-groups/${detail}`));
    else setGroups(await api<CaseGroup[]>(token, '/case-groups'));
  }
  useEffect(() => {
    let active = true;
    const request = detail
      ? api<CaseGroup>(token, `/case-groups/${detail}`).then((g) => { if (active) setGroup(g); })
      : api<CaseGroup[]>(token, '/case-groups').then((g) => { if (active) setGroups(g); });
    request.catch((e) => { if (active) setError(errorText(e)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token, detail]);
  async function create() {
    setBusy(true); setError('');
    try { const g = await api<CaseGroup>(token, '/case-groups', { title: newTitle }); router.push(`/evaluation/case-groups/${g.group_id}`); }
    catch (error) { setError(errorText(error)); } finally { setBusy(false); }
  }
  return <div className="space-y-4">
    {!canEdit && <p className="text-sm text-slate-500">当前账号仅可查看；专家和开发者可执行日常评测。</p>}
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {loading && <p role="status" className="text-sm text-slate-500">正在读取用例组…</p>}
    {detail ? group && <section className={panel}>
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">{group.title}</h2><p className="text-sm text-slate-500">{group.case_count} 段会话 · {group.turn_count} 轮</p></div><Link className={button} href={`/evaluation/case-groups/versions?group=${encodeURIComponent(group.group_id)}`}>{canEdit ? '验证此组' : '查看版本记录'}</Link></div>
      {group.notes && <p className="whitespace-pre-wrap break-words text-sm">{group.notes}</p>}
      {!group.case_count && <p className="text-sm">在运行记录或问题详情中，点击“加入用例组”保存会话。</p>}
      <ul aria-label="会话用例" className="divide-y">{group.cases?.map((c) => <li key={c.case_id} className="flex items-start justify-between gap-3 py-3">
        <div className="min-w-0 flex-1 space-y-2">
          <Link className="inline-block max-w-full text-left text-sm text-emerald-800 underline [overflow-wrap:anywhere]" href={conversationCaseHref(c.case_id, detail)}>{c.title} · {c.turns.length} 轮{!c.expected && ' · 待补充预期'}</Link>
          <ol className="space-y-1 text-sm leading-6">{c.turns.map((turn, index) => <li key={index} className="whitespace-pre-wrap [overflow-wrap:anywhere]">第 {index + 1} 轮：{turn.query}</li>)}</ol>
        </div>
        {canEdit && <button className="shrink-0 text-xs text-slate-500 underline" onClick={async () => { try { await api(token, `/case-groups/${detail}/cases/${c.case_id}`, {}, 'DELETE'); await refresh(); } catch (error) { setError(errorText(error)); } }}>移出此组</button>}
      </li>)}</ul>
    </section> : <section className={panel}>
      <div className="grid gap-3 md:grid-cols-2">{groups.map((g) => <div key={g.group_id} className="space-y-3 rounded-lg border p-4"><Link className="block text-sm font-medium text-emerald-800 underline" href={`/evaluation/case-groups/${g.group_id}`}>{g.title} · {g.case_count} 段会话 / {g.turn_count} 轮</Link>{g.notes && <p className="line-clamp-2 text-sm text-slate-500">{g.notes}</p>}<Link className="inline-block text-sm text-emerald-800 underline" href={`/evaluation/case-groups/versions?group=${encodeURIComponent(g.group_id)}`}>{canEdit ? '验证此组' : '查看版本记录'}</Link></div>)}</div>
      {!loading && !groups.length && <p className="text-sm text-slate-500">还没有用例组。新建一个组，或从运行记录保存完整会话。</p>}
      {canEdit && <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); void create(); }}><input aria-label="新用例组名称" className={`${field} max-w-sm`} value={newTitle} maxLength={100} placeholder="新用例组名称" onChange={(e) => setNewTitle(e.target.value)} /><button className={button} disabled={busy || !newTitle.trim()}>新建用例组</button></form>}
    </section>}
  </div>;
}

export function ConversationVersionsWorkspace({ initialGroup = '', initialCase = '', initialBatch = '' }: { initialGroup?: string; initialCase?: string; initialBatch?: string }) {
  const pendingBatch = useRef<{ fingerprint: string; id: string } | null>(null);
  const { token, user } = useEvaluationSession();
  const canEdit = user.role !== 'tester';
  const [groups, setGroups] = useState<CaseGroup[]>([]);
  const [batches, setBatches] = useState<ConversationBatch[]>([]);
  const [batch, setBatch] = useState<ConversationBatch | null>(null);
  const [caseId, setCaseId] = useState(initialCase);
  const [selection, setSelection] = useState<string[]>(initialGroup ? [initialGroup] : []);
  const [historyGroup, setHistoryGroup] = useState(initialGroup);
  const [version, setVersion] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function refresh() {
    const [g, b] = await Promise.all([api<CaseGroup[]>(token, '/case-groups'), api<ConversationBatch[]>(token, '/conversation-batches')]);
    setGroups(g); setBatches(b);
  }
  useEffect(() => {
    let active = true;
    Promise.all([api<CaseGroup[]>(token, '/case-groups'), api<ConversationBatch[]>(token, '/conversation-batches')])
      .then(([g, b]) => { if (active) { setGroups(g); setBatches(b); } }).catch((e) => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, [token]);
  useEffect(() => {
    if (!initialBatch) return;
    let active = true;
    api<ConversationBatch>(token, `/conversation-batches/${initialBatch}`).then((b) => { if (active) setBatch(b); }).catch((e) => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, [initialBatch, token]);
  const runningId = batch && ['queued', 'running'].includes(batch.status) ? batch.batch_id : '';
  useEffect(() => {
    if (!runningId) return;
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const b = await api<ConversationBatch>(token, `/conversation-batches/${runningId}`); if (!active) return; setBatch(b); if (['queued', 'running'].includes(b.status)) timer = setTimeout(poll, 1500); else { const all = await api<ConversationBatch[]>(token, '/conversation-batches'); if (active) setBatches(all); } }
      catch (error) { if (active) setError(errorText(error)); }
    }
    timer = setTimeout(poll, 1000);
    return () => { active = false; clearTimeout(timer); };
  }, [runningId, token]);
  async function start() {
    setBusy(true); setError('');
    const fingerprint = JSON.stringify([selection, version]);
    if (pendingBatch.current?.fingerprint !== fingerprint) pendingBatch.current = { fingerprint, id: crypto.randomUUID() };
    try { const b = await api<ConversationBatch>(token, '/conversation-batches', { submission_id: pendingBatch.current.id, group_ids: selection, version_name: version }); pendingBatch.current = null; setBatch(b); await refresh(); }
    catch (error) { setError(errorText(error)); } finally { setBusy(false); }
  }
  const visibleBatches = batches.map((b) => b.batch_id === batch?.batch_id ? batch : b)
    .filter((b) => !historyGroup || b.group_ids.includes(historyGroup));
  return <div className="space-y-4">
    {!canEdit && <p className="text-sm text-slate-500">当前账号仅可查看；专家和开发者可执行日常评测。</p>}
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {canEdit && <section className={panel}>
      <div className="grid gap-3 md:grid-cols-2">{groups.map((g) => <label key={g.group_id} className="flex cursor-pointer items-center gap-3 rounded-lg border p-3"><input aria-label={`选择用例组：${g.title}`} type="checkbox" checked={selection.includes(g.group_id)} onChange={(e) => setSelection(e.target.checked ? [...selection, g.group_id] : selection.filter((id) => id !== g.group_id))} /><span className="text-sm">{g.title}<span className="block text-xs text-slate-500">{g.case_count} 段会话 / {g.turn_count} 轮</span></span></label>)}</div>
      {!groups.length && <p className="text-sm text-slate-500">请先在用例组管理中准备会话用例。</p>}
      <div className="flex flex-wrap gap-2"><input aria-label="待验证版本名称" className={`${field} max-w-sm`} value={version} maxLength={100} placeholder="例如 v0.3.2 候选版" onChange={(e) => setVersion(e.target.value)} /><button className={button} disabled={busy || !!runningId || !version.trim() || !selection.length} onClick={() => void start()}>重跑所选用例组（{selection.length}）</button></div><p className="text-xs text-slate-500">运行完成后需逐个会话验收。版本确认与配置恢复仅向开发者开放。</p>
    </section>}
    <section className="wb-panel space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold">版本验证记录</h2>
        <label className="flex min-w-0 items-center gap-2 text-sm">筛选用例组<select className="wb-field w-auto min-w-0" value={historyGroup} onChange={(e) => setHistoryGroup(e.target.value)}><option value="">全部用例组</option>{groups.map((g) => <option key={g.group_id} value={g.group_id}>{g.title}</option>)}</select></label>
      </div>
      <div className="wb-table-wrap">
        <table className="wb-table" aria-label="版本验证记录">
          <thead><tr>
            <th scope="col">版本名称</th>
            <th scope="col">评测用例组</th>
            <th scope="col" className="wb-numeric">已完成 / 会话数</th>
            <th scope="col">运行状态</th>
            <th scope="col">验收状态</th>
            <th scope="col">创建时间</th>
            <th scope="col">操作</th>
          </tr></thead>
          <tbody>
            {visibleBatches.map((b) => <tr key={b.batch_id}>
              <td className="min-w-32 max-w-60 break-words font-medium">{b.version_name}</td>
              <td><ul className="min-w-48 max-w-sm space-y-1">{b.group_titles.length ? b.group_titles.map((title, index) => <li key={`${index}:${title}`} className="break-words">{title}</li>) : <li className="text-muted-foreground">{b.group_ids.length ? '未记录用例组名称' : '单会话评测'}</li>}</ul></td>
              <td className="wb-numeric whitespace-nowrap">{b.completed_cases} / {b.case_count}</td>
              <td className="whitespace-nowrap">{labels[b.status] ?? b.status}</td>
              <td><span className="wb-status" data-status={b.acceptance === 'pass' ? 'passed' : b.acceptance === 'fail' ? 'needs_changes' : b.acceptance}>{labels[b.acceptance] ?? b.acceptance}</span></td>
              <td className="whitespace-nowrap text-muted-foreground">{date(b.created_at)}</td>
              <td><button type="button" className="wb-button" aria-label={`查看版本：${b.version_name}`} aria-pressed={batch?.batch_id === b.batch_id} onClick={async () => { try { setBatch(await api<ConversationBatch>(token, `/conversation-batches/${b.batch_id}`)); } catch (error) { setError(errorText(error)); } }}>{batch?.batch_id === b.batch_id ? '当前查看' : '查看'}</button></td>
            </tr>)}
            {!visibleBatches.length && <tr><td colSpan={7} className="wb-empty">还没有验证记录。</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
    {batch && <section aria-label="本次版本验证" className="space-y-3"><div className={panel}><h2 className="font-semibold">{batch.version_name} · {labels[batch.status]} · {labels[batch.acceptance]}</h2><p className="text-sm text-slate-500">{batch.group_titles.join('、')} · {batch.completed_cases}/{batch.case_count} 段会话</p><p className="break-all text-xs text-slate-500">服务版本：{batch.config_version}</p>{canEdit && runningId && <button className={button} onClick={async () => { try { await api(token, `/conversation-batches/${batch.batch_id}/cancel`, {}); } catch (error) { setError(errorText(error)); } }}>取消本次运行</button>}{user.role === 'developer' && <VersionConfirmation token={token} batch={batch} />}</div>{batch.results?.map((r) => <BatchResult key={r.case.case_id} result={r} batch={batch} token={token} canEdit={canEdit} onChange={setBatch} onCompare={() => setCaseId(r.case.case_id)} />)}</section>}
    {caseId && <CaseComparison key={caseId + ':' + (batch?.status ?? '')} id={caseId} token={token} canEdit={canEdit} />}
  </div>;
}

function VersionConfirmation({ token, batch }: { token: string; batch: ConversationBatch }) {
  const [note, setNote] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<{ action: string; batch_id: string; actor: string; at: string; note: string }[]>([]);
  async function refreshEvents() { setEvents(await api<typeof events>(token, '/conversation-version-events')); }
  useEffect(() => { let active = true; api<typeof events>(token, '/conversation-version-events').then((all) => { if (active) setEvents(all); }).catch((e) => { if (active) setMessage(errorText(e)); }); return () => { active = false; }; }, [token, batch.batch_id]);
  return <details className="text-sm"><summary className="cursor-pointer">开发者版本确认与回退</summary><div className="mt-3 space-y-2"><p className="text-slate-500">确认记录保留这次验收及配置快照；当前服务代码部署仍使用现有发布流程。回退可恢复已确认的 Prompt 与表达配置，不回退服务代码或资料库。</p><textarea aria-label="版本确认说明" className={field} value={note} maxLength={3000} onChange={(e) => setNote(e.target.value)} placeholder="版本确认或回退说明" /><div className="flex flex-wrap gap-2"><button className={button} disabled={busy || batch.acceptance !== 'pass' || !note.trim()} onClick={async () => { setBusy(true); try { await api(token, `/conversation-batches/${batch.batch_id}/confirm`, { note }); await refreshEvents(); setMessage('已记录开发者确认。'); } catch (e) { setMessage(errorText(e)); } finally { setBusy(false); } }}>确认此版本</button><button className={button} disabled={busy || !note.trim() || !events.some((e) => e.batch_id === batch.batch_id && e.action === 'confirm')} onClick={async () => { setBusy(true); try { await api(token, `/conversation-batches/${batch.batch_id}/restore`, { note }); await refreshEvents(); setMessage('已恢复此已确认版本的 Prompt 与表达配置。'); } catch (e) { setMessage(errorText(e)); } finally { setBusy(false); } }}>恢复此已确认版本的配置</button></div>{message && <p role="status">{message}</p>}{events.filter((e) => e.batch_id === batch.batch_id).map((e, i) => <p key={i} className="text-xs text-slate-600">{date(e.at)} · {e.actor} · {e.action === 'confirm' ? '确认版本' : '恢复配置'}：{e.note}</p>)}</div></details>;
}

export function ConversationIssuesWorkspace({ detail = '' }: { detail?: string }) {
  const { token, user } = useEvaluationSession();
  const canEdit = user.role !== 'tester';
  const [issues, setIssues] = useState<ConversationIssue[]>([]);
  const [batches, setBatches] = useState<ConversationBatch[]>([]);
  const [selected, setSelected] = useState(detail);
  const [status, setStatus] = useState('');
  const [source, setSource] = useState('');
  const [note, setNote] = useState('');
  const [nextStatus, setNextStatus] = useState('in_progress');
  const [category, setCategory] = useState('其他');
  const [assignee, setAssignee] = useState('');
  const [verification, setVerification] = useState('');
  const [caseId, setCaseId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function refresh() { const [i, b] = await Promise.all([api<ConversationIssue[]>(token, '/conversation-issues'), api<ConversationBatch[]>(token, '/conversation-batches')]); setIssues(i); setBatches(b); }
  useEffect(() => {
    let active = true;
    Promise.all([api<ConversationIssue[]>(token, '/conversation-issues'), api<ConversationBatch[]>(token, '/conversation-batches')])
      .then(([i, b]) => { if (active) { setIssues(i); setBatches(b); } }).catch((e) => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, [token]);
  const issue = issues.find((i) => i.issue_id === selected);
  const sources: Record<string, string> = { conversation: '运行记录标记', feedback: '前台反馈', execution: '历史执行问题' };
  async function update() {
    if (!issue) return;
    setBusy(true); setError('');
    try {
      if (issue.legacy_id) {
        const created = await api<ConversationIssue>(token, '/conversation-issues', { session_id: issue.session_id, run_id: issue.run_id, note: issue.note, origin_execution_issue_id: issue.legacy_id });
        setSelected(created.issue_id);
      } else await api(token, `/conversation-issues/${issue.issue_id}`, { status: nextStatus, category, assignee, note, expected_revision: issue.revision, verification_batch_id: verification || null }, 'PUT');
      await refresh(); setNote('');
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <div className="space-y-4">{error && <p role="alert" className="text-red-800">{error}</p>}
    <section className={panel}><div className="flex flex-wrap gap-3"><label className="text-sm">处理状态<select className={field} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">全部</option>{['open', 'in_progress', 'ready_for_retest', 'closed'].map((s) => <option key={s} value={s}>{labels[s]}</option>)}</select></label><label className="text-sm">问题来源<select className={field} value={source} onChange={(e) => setSource(e.target.value)}><option value="">全部</option>{Object.entries(sources).map(([s, title]) => <option key={s} value={s}>{title}</option>)}</select></label><button className={button} onClick={() => void refresh().catch((e) => setError(errorText(e)))}>刷新问题</button></div>
      <ul className="divide-y">{issues.filter((i) => (!status || i.status === status) && (!source || i.source === source)).map((i) => <li key={i.issue_id} className="py-3"><button className="w-full text-left" onClick={() => { setSelected(i.issue_id); setCategory(i.category); setAssignee(i.assignee); setNextStatus(i.status); setVerification(i.verification_batch_id ?? ''); setNote(''); setCaseId(''); }}><p className="line-clamp-2 text-sm font-medium">{i.note}</p><p className="mt-1 text-xs text-slate-500">{sources[i.source]} · {labels[i.status]} · {i.category} · {i.assignee || '未指派'} · {i.groups.map((g) => g.title).join('、') || '尚未归组'}</p></button></li>)}</ul>{!issues.length && <p className="text-sm text-slate-500">暂无问题。</p>}</section>
    {issue && <section className={panel}><h2 className="font-semibold">问题处理 · {labels[issue.status]}</h2><p className="whitespace-pre-wrap break-words text-sm">{issue.note}</p><Link className="inline-block text-sm text-emerald-800 underline" href={`/evaluation/runs/${issue.session_id}`}>查看完整原会话</Link>
      <CaptureConversation token={token} sessionId={issue.session_id} title={issue.note.slice(0, 100)} readOnly={!canEdit} onSaved={() => void refresh()} />
      <div className="flex flex-wrap gap-3 text-sm">{issue.groups.map((g) => <Link className="text-emerald-800 underline" key={g.group_id} href={`/evaluation/case-groups/versions?group=${encodeURIComponent(g.group_id)}`}>{g.title} · 重跑此组</Link>)}{issue.cases.map((c) => <button key={c.case_id} className="text-emerald-800 underline" onClick={() => setCaseId(c.case_id)}>查看前后版本回答：{c.title}</button>)}</div>
      {canEdit && <div className="space-y-3 rounded-lg bg-slate-50 p-3">{!issue.legacy_id && <><div className="flex flex-wrap gap-3"><label className="text-sm">状态<select className={field} value={nextStatus} onChange={(e) => setNextStatus(e.target.value)}>{['open', 'in_progress', 'ready_for_retest', 'closed'].map((s) => <option key={s} value={s}>{labels[s]}</option>)}</select></label><label className="text-sm">归类<input className={field} maxLength={50} value={category} onChange={(e) => setCategory(e.target.value)} /></label><label className="text-sm">处理人<input className={field} maxLength={80} value={assignee} onChange={(e) => setAssignee(e.target.value)} /></label></div>
        {nextStatus === 'closed' && <label className="block text-sm">验收通过的版本验证记录<select className={field} value={verification} onChange={(e) => setVerification(e.target.value)}><option value="">请选择</option>{batches.filter((b) => b.status === 'completed' && (b.source_session_ids?.includes(issue.session_id) || b.group_ids.some((id) => issue.groups.some((g) => g.group_id === id)))).map((b) => <option key={b.batch_id} value={b.batch_id}>{b.version_name} · {labels[b.acceptance]}</option>)}</select></label>}
        <textarea aria-label="问题处理说明" className={field} rows={3} value={note} maxLength={5000} onChange={(e) => setNote(e.target.value)} placeholder="记录修改内容或核对依据" /></>}
        <button className={button} disabled={busy || (!issue.legacy_id && !note.trim())} onClick={() => void update()}>{issue.legacy_id ? '转入会话问题处理' : '保存处理结果'}</button></div>}
      {!!issue.history.length && <details><summary className="cursor-pointer text-sm">处理历史</summary>{issue.history.map((h, i) => <p key={i} className="mt-2 whitespace-pre-wrap break-words text-sm">{date(h.at)} · {h.actor} · {labels[h.status ?? ''] ?? h.status}：{h.note}</p>)}</details>}
    </section>}{caseId && <CaseComparison key={caseId} id={caseId} token={token} canEdit={canEdit} />}
  </div>;
}
