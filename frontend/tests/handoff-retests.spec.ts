import { expect, test } from '@playwright/test';

test('offline target history, isolated candidate and pending human review', async ({ page }) => {
  let attempt: Record<string, unknown> | null = null;
  const prompt = { prompt_id: 'candidate-1', version: 'prompt-hash', label: '候选规则', text: '先解释再引导' };
  const source = { local_id: 'local-FIX-05', evaluation_mode: 'fixed_history_target_turn',
    seed_history: [{ role: 'user', content: '第一问' }, { role: 'assistant', content: '原先回答' }],
    source: { id: 'FIX-05', conversation_title: '新手模型用途', target_turn: 2,
      source_review_status: 'needs_changes', source_session_id: 'original-session',
      original_review: { note: '请先介绍用途' }, user_turns: ['你这个模型有什么用途？'], acceptance_draft: ['保留历史'] },
    baseline: { turns: [{ turn: 2, user: '你这个模型有什么用途？', assistant_visible_text: '请补充模型名称', is_evaluation_target: true, source_run_id: 'original-run' }] },
    missing_fields: ['historical_prompt_versions'] };
  let submitted: unknown;
  const task = { prompt_id: 'task-original', scope: 'concept_explanation', label: '默认概念', text: '先解释再引导', version: 'task-v1', examples: [] };
  const active = { concept_explanation: task, knowledge_search: { ...task, scope: 'knowledge_search' }, case_assistant: { ...task, scope: 'case_assistant' } };
  const versions = [task];

  await page.route('**/api/eval/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/eval', '');
    if (path === '/me') return route.fulfill({ json: { tester_id: 'dev', role: 'developer' } });
    if (path === '/login') return route.fulfill({ json: { token: 'mock-session-token', user: { tester_id: 'dev', role: 'developer' } } });
    if (path === '/task-prompts') {
      if (route.request().method() === 'POST') {
        const payload = route.request().postDataJSON();
        expect(payload.scope).toBe('concept_explanation');
        const saved = { ...task, ...payload, prompt_id: 'task-candidate', version: 'task-v2' };
        versions.unshift(saved);
        return route.fulfill({ status: 201, json: saved });
      }
      return route.fulfill({ json: { active, versions } });
    }
    if (path === '/prompt-versions') return route.fulfill({ json: [prompt] });
    if (path.endsWith('/retests')) {
      submitted = route.request().postDataJSON();
      attempt = { attempt_id: 'attempt-1', status: 'completed', quality: 'pending', requested_prompt_id: prompt.prompt_id,
        steps: [{ run_id: 'new-run', query: '你这个模型有什么用途？', status: 'completed', history: source.seed_history, actual_prompt: prompt, response: { answer: '本助手可以帮助解读农业资料。' } }] };
      return route.fulfill({ status: 202, json: attempt });
    }
    if (path === '/handoff-sources/local-FIX-05') return route.fulfill({ json: { ...source, attempts: attempt ? [attempt] : [] } });
    return route.fulfill({ json: [] });
  });
  await page.goto('/evaluation/runs/local-FIX-05?source=handoff');
  await page.getByLabel('账号', { exact: true }).fill('mock');
  await page.getByLabel('密码', { exact: true }).fill('mock-password');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByText('第 2 轮，携带 2 条固定历史', { exact: false })).toBeVisible();
  await page.getByText('编辑并另存任务候选', { exact: true }).click();
  await page.getByLabel('任务候选名称', { exact: true }).fill('概念候选');
  await page.getByLabel('任务规则', { exact: true }).fill('先说明模型用途，再引导用户');
  await page.getByRole('button', { name: '保存任务候选', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('尚未启用');
  await page.getByRole('button', { name: '用候选复测', exact: true }).click();
  await expect(page.getByText('技术完成 · 待复核 · 尚未关联上线')).toBeVisible();
  expect(submitted).toMatchObject({ prompt_id: 'candidate-1', task_prompt_ids: { concept_explanation: 'task-candidate' } });
  await expect(page.getByText('请补充模型名称', { exact: true }).last()).toBeVisible();
  await expect(page.getByText('本助手可以帮助解读农业资料。', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '符合', exact: true })).toBeDisabled();
});
