import { expect, test } from '@playwright/test';

test.use({ channel: 'chromium' });

test('PDF preview retries a broken connection and manual reload starts a new request', async ({ page }) => {
  let fileRequests = 0;
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/literature/papers/P-PREVIEW/file') {
      fileRequests++;
      if (fileRequests <= 2) await route.abort('failed');
      else await route.fulfill({ status: 200, contentType: 'application/pdf', body: '%PDF-1.4\n%%EOF' });
      return;
    }
    const json = path === '/api/eval/login' ? { token: 'mock-session-token', user: { tester_id: 'preview-user', role: 'developer' } }
      : path === '/api/eval/me' ? { tester_id: 'preview-user', role: 'developer' }
      : path === '/api/literature/taxonomy' ? { dimensions: [], tags: [] }
      : path === '/api/literature/users' ? []
      : path === '/api/literature/config' ? { max_pdf_mb: 100 }
      : path === '/api/literature/papers/P-PREVIEW' ? {
        id: 'P-PREVIEW', revision: 1, title: '预览测试', authors: [], tag_ids: [], related_papers: [],
        registration: 'draft', usage: 'normal', filename: 'source.pdf', sha256: 'preview', events: [],
      } : null;
    if (json === null) throw new Error(`Unexpected API request: ${path}`);
    await route.fulfill({ status: 200, json });
  });

  await page.goto('/evaluation/literature/P-PREVIEW');
  await page.getByLabel('账号', { exact: true }).fill('cau_mock');
  await page.getByLabel('密码', { exact: true }).fill('CauMock123');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByText('PDF 预览连接中断，请点击重试。')).toBeVisible();
  expect(fileRequests).toBe(2);
  await page.getByRole('button', { name: '重新加载 PDF' }).click();
  await expect(page.getByTitle('PDF 原文预览')).toHaveAttribute('src', /^blob:/);
  expect(fileRequests).toBe(3);
});
