import { expect, test, type Page } from '@playwright/test';

const fixture = { case: { case_id: 'NAV01', version: 1, title: '导航回归用例', category: 'NEW', priority: 'P1', source: 'browser test', preconditions: '隔离验证', expected: ['页面关联正确'], attachment_requirements: [], steps: [{ action: 'query', instruction: '发送问候', input: '你好' }] }, fixtures: [], dataset_id: 'navigation', professional_review: 'pending' };
const execution = { execution_id: 'execution-navigation', case_id: 'NAV01', case_version: 1, tester_id: 'navigation-user', status: 'open', created_at: '2026-10-04T09:00:00Z', task_id: 'task-navigation', needs_reset: false, attachment: null, events: [], review: null };
const task = { task_id: 'task-navigation', title: '导航验收任务', case_versions: [{ case_id: 'NAV01', case_version: 1 }], build_version: 'navigation-test', runtime_config_version: 'navigation-test:config', knowledge_version: 'test', created_by: 'navigation-user', created_at: execution.created_at };

async function mockApi(page: Page, role = 'developer', taskId: string | null = task.task_id) {
  const requests: string[] = [];
  let current: Record<string, unknown> = { ...execution, task_id: taskId };
  await page.route('**/api/eval/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/eval', '');
    requests.push(path);
    let value: unknown = [];
    if (path === '/me') value = { tester_id: 'navigation-user', role };
    else if (path === '/config') value = { build_version: 'navigation-test', runtime_config_version: 'navigation-test:config' };
    else if (path === '/cases') value = [fixture];
    else if (path === '/executions') value = [execution];
    else if (path === `/executions/${execution.execution_id}`) value = current;
    else if (path === `/executions/${execution.execution_id}/reviews`) {
      current = { ...current, status: 'reviewed', review: { ...route.request().postDataJSON(), review_kind: 'development_trial' } };
      value = current;
    }
    else if (path === '/tasks') value = [task];
    else if (path === `/tasks/${task.task_id}/progress`) value = { task, scope: 'all', summary: { total_cases: 1, prepared_cases: 1, started_cases: 0, reviewed_cases: 0, executions: 1 }, cases: [{ case_id: 'NAV01', case_version: 1, executions: [{ ...execution, event_count: 0 }], started: false, reviewed: false }] };
    else if (path.endsWith('/dashboard')) value = { task, summary: { executions: 1, pending: 1, scored_denominator: 0, pass: 0, partial: 0, fail: 0, blocked: 0 }, by_case_version: [], assessment_counts: { ai_assisted: 0, domain_expert: 0 }, issues: { total: 0, unresolved: 0 }, severe_regressions: [] };
    else if (path === '/statistics') value = { executions: 1, pending: 1, reviewed: 0, overall: {}, layers: {}, by_case_version: [] };
    else if (path === '/review-queue') value = [{ execution_id: execution.execution_id, case_id: 'NAV01', case_version: 1, tester_id: 'navigation-user', status: 'pending_development', assignments: [], pending_reviewers: [], expert_assessments: [], development_review: null, resolution: null }];
    await route.fulfill({ json: value });
  });
  return requests;
}
async function login(page: Page) {
  await page.getByLabel('评测访问密钥').fill('isolated-navigation-token');
  await page.getByRole('button', { name: '进入工作台' }).click();
}

test('sidebar routes preserve login, open linked records and restore a deep link after refresh', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mockApi(page);
  await page.goto('/evaluation'); await login(page);
  const nav = page.getByRole('navigation', { name: '工作台导航' }).first();
  await expect(page.getByRole('heading', { name: '开始工作' })).toBeVisible();
  await nav.getByRole('link', { name: '任务管理', exact: true }).click();
  await expect(page).toHaveURL(/\/evaluation\/tasks$/);
  await expect(nav.getByRole('link', { name: '任务管理', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('heading', { name: '独立审核队列' })).toHaveCount(0);
  await page.getByRole('button', { name: '查看任务' }).click();
  await expect(page).toHaveURL(/\/tasks\/task-navigation$/);
  await page.getByRole('button', { name: /打开执行 execution-navigation/ }).click();
  await expect(page).toHaveURL(/\/executions\/execution-navigation$/);
  await expect(page.getByLabel('执行问题')).toBeVisible();
  await page.getByRole('link', { name: '查看用例版本' }).click();
  await expect(page).toHaveURL(/\/cases\/NAV01%401$/);
  await expect(page.getByRole('heading', { name: /NAV01 v1/ })).toBeVisible();
  await page.getByRole('link', { name: '使用此版本新建执行' }).click();
  await expect(page.getByLabel('用例版本')).toHaveValue('NAV01@1');
  await page.goBack();
  await page.goBack();
  await expect(page.getByLabel('执行问题')).toBeVisible();
  await page.reload(); await login(page);
  await expect(page).toHaveURL(/\/executions\/execution-navigation$/);
  await expect(page.getByLabel('执行问题')).toBeVisible();
  await page.getByRole('button', { name: '收起侧边栏' }).click();
  await expect(page.getByRole('button', { name: '展开侧边栏' })).toBeVisible();
  await page.screenshot({ path: '/tmp/nitrogen-workbench-desktop.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('tester navigation and direct URLs respect module permissions', async ({ page }) => {
  const requests = await mockApi(page, 'tester');
  await page.goto('/evaluation/issues'); await login(page);
  await expect(page.getByRole('main').getByRole('alert')).toContainText('无权访问');
  const nav = page.getByRole('navigation', { name: '工作台导航' }).first();
  await expect(nav.getByRole('link', { name: '问题管理', exact: true })).toHaveCount(0);
  await expect(nav.getByRole('link', { name: '运行记录', exact: true })).toHaveCount(0);
  expect(requests).not.toContain('/issues');
  await nav.getByRole('link', { name: '用例库', exact: true }).click();
  await expect(page.getByRole('button', { name: '查看用例' })).toBeVisible();
  await expect(page.getByRole('link', { name: '管理草稿' })).toHaveCount(0);
  expect(requests).not.toContain('/assets');
  expect(requests).not.toContain('/case-drafts');
});

test('mobile drawer supports navigation and Escape without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page, 'reviewer');
  await page.goto('/evaluation/reviews'); await login(page);
  await expect(page.getByRole('heading', { name: '独立审核队列' })).toBeVisible();
  await page.getByRole('button', { name: '打开导航' }).click();
  const dialog = page.getByRole('dialog', { name: '移动端导航' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('link', { name: '资产目录', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page).toHaveURL(/\/evaluation\/assets$/);
  await expect(page.getByRole('heading', { name: '核实输入输出配对' })).toBeVisible();
  await page.getByRole('button', { name: '打开导航' }).click();
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/nitrogen-workbench-mobile.png', fullPage: true });
});

test('task execution returns to its task after scoring, including refresh and mobile', async ({ page }) => {
  await mockApi(page, 'tester');
  await page.goto('/evaluation/tasks/task-navigation'); await login(page);
  await page.getByRole('button', { name: /打开执行 execution-navigation/ }).click();
  await expect(page.getByRole('link', { name: '返回所属任务', exact: true })).toHaveAttribute('href', '/evaluation/tasks/task-navigation');
  await page.getByLabel('总体结论').selectOption('blocked');
  for (const label of ['路由是否正确', '工具使用是否正确', '证据是否支持', '答案是否正确']) {
    await page.getByRole('combobox', { name: label, exact: true }).selectOption('n.a.');
  }
  await page.getByLabel('评分说明').fill('隔离浏览器验证返回流程');
  await page.getByRole('button', { name: '提交并冻结评分' }).click();
  await expect(page.getByText('此评分已冻结；专业审核结论单独记录。')).toBeVisible();
  await page.reload(); await login(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('link', { name: '返回所属任务', exact: true }).click();
  await expect(page).toHaveURL(/\/evaluation\/tasks\/task-navigation$/);
  await expect(page.getByLabel('任务详情')).toBeVisible();
  await expect(page.getByRole('link', { name: '返回所属任务', exact: true })).toHaveCount(0);
});

test('independent execution returns to the execution list', async ({ page }) => {
  await mockApi(page, 'tester', null);
  await page.goto('/evaluation/executions/execution-navigation'); await login(page);
  await expect(page.getByLabel('执行问题')).toBeVisible();
  await expect(page.getByRole('link', { name: '返回所属任务', exact: true })).toHaveCount(0);
  await page.getByRole('link', { name: '返回执行记录', exact: true }).click();
  await expect(page).toHaveURL(/\/evaluation\/executions$/);
});
