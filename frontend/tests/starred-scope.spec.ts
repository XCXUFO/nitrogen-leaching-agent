import { test, expect } from '@playwright/test';

test('starred scope and sources remain visible and editing preserves the import profile', async ({ page }) => {
  let record = { question_id: 'business-id', source_sq_id: 'SQ-024', question: '为什么区分农田和区域尺度？', answer: '已有材料仅解释区分尺度的理由。', revision: 1,
    created_at: '2026-11-11', updated_at: '2026-11-11', reuse: { reuse_status: 'reference', coverage_scope: '区分尺度的原因', excluded_scope: '模型的具体构建方法',
      source_refs: ['课题四反馈问题.docx · T4'], variants: ['本项目为什么区分田块模型和区域模型？'], profile: 'scale_models', professional_review: 'unknown' } };
  const writes: Record<string, unknown>[] = [];
  await page.route('**/api/eval/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/me')) return route.fulfill({ json: { tester_id: 'dev', role: 'developer' } });
    if (path.endsWith('/login')) return route.fulfill({ json: { token: 'mock', user: { tester_id: 'dev', role: 'developer' } } });
    if (path.endsWith('/starred-questions')) return route.fulfill({ json: [record] });
    if (path.endsWith('/starred-questions/business-id')) {
      const body = route.request().postDataJSON(); writes.push(body);
      record = { ...record, ...body, revision: 2 };
      return route.fulfill({ json: record });
    }
    throw new Error(`Unexpected ${path}`);
  });
  await page.goto('/evaluation/starred-questions');
  await page.getByLabel('账号', { exact: true }).fill('reviewer');
  await page.getByLabel('密码', { exact: true }).fill('mock-password');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByText('来源 SQ-024', { exact: false })).toBeVisible();
  await page.getByText('查看适用范围与资料来源').click();
  await expect(page.getByText('未覆盖：模型的具体构建方法')).toBeVisible();
  await expect(page.getByText('来源：课题四反馈问题.docx · T4')).toBeVisible();
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  const form = page.getByRole('form', { name: '编辑问题' });
  await form.getByLabel('对应答案（选填）').fill('更新后的有限范围参考答复。');
  await form.getByLabel('答复状态').selectOption('partial');
  await form.getByRole('button', { name: '保存', exact: true }).click();
  await expect(form).toHaveCount(0);
  await expect(page.getByText('更新后的有限范围参考答复。')).toBeVisible();
  expect(writes[0].expected_revision).toBe(1);
  expect(writes[0].reuse).toMatchObject({ reuse_status: 'partial', profile: 'scale_models', excluded_scope: '模型的具体构建方法', source_refs: ['课题四反馈问题.docx · T4'] });
});
