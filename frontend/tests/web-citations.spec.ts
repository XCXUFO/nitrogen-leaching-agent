import { test, expect } from '@playwright/test';

test('web evidence opens the actual source with quoted text instead of PDF actions', async ({ page }) => {
  await page.route('**/api/chat/session', route => route.fulfill({ status: 404, json: {} }));
  await page.route('**/api/chat', route => route.fulfill({ json: {
    answer: '以下是合成测试说明。[1]', citations: [{ index: 1, chunk_id: 'web:test', source: 'https://university.example/lesson', source_type: 'web',
      score: 0, snippet: '合成测试材料的这段文字用于验证原文引用关联。', title: '合成测试教材', publisher: 'university.example', retrieved_at: '2026-11-09T12:00:00Z',
      fetch_status: 'fetched', evidence_level: 'page_text', document_id: null, document_available: false }],
    usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 }, retrieved_count: 1, model: 'simulated',
    route: 'knowledge', agent_route: 'KNOWLEDGE', outcome: 'complete', file_evidence: [],
    web_retrieval: { status: 'fetched', sources_read: 1 },
  } }));
  await page.goto('/');
  await page.getByLabel('问题输入').fill('请联网解释光合作用');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByText('本次读取 1 个网页来源；实际采用内容见引用依据。')).toHaveCount(0);
  await page.getByRole('button', { name: '查看引用 1', exact: true }).click();
  await expect(page.getByText('[1] 合成测试教材', { exact: true })).toBeVisible();
  await expect(page.getByText('合成测试材料的这段文字用于验证原文引用关联。')).toBeVisible();
  await expect(page.getByRole('link', { name: '打开网页来源' })).toHaveAttribute('href', 'https://university.example/lesson');
  await expect(page.getByRole('button', { name: '预览文献', exact: true })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
