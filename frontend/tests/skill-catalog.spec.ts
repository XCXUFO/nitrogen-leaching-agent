import { expect, test, type Page } from "@playwright/test";
import type { SkillDetail, SkillSummary } from "../src/lib/skill-catalog";

const summaries: SkillSummary[] = [
  ["case_reference", "案例与措施参考", "llm"], ["case_explanation", "案例与措施解释", "llm"],
  ["knowledge_search", "文献检索问答", "llm"], ["file_inspector", "附件检查", "local"],
  ["whcns_analyzer", "WHCNS 结果分析", "local"], ["clarification", "澄清追问", "program"],
  ["capability_guidance", "能力引导", "program"],
].map(([name, title, generation]) => ({
  name, title, generation: generation as SkillSummary["generation"], registered: true,
  description: `${title}的业务说明。`, availability: generation === "llm" ? "unknown" : "available",
  availability_note: "具体输入仍需校验。", configuration: "read_only",
}));

function detail(name: string, unavailable = false): SkillDetail | null {
  const summary = summaries.find((item) => item.name === name);
  return summary ? { ...summary, availability: unavailable ? "unavailable" : summary.availability,
    registry_description: "实际注册描述", scenarios: ["解释指定内容"], examples: ["请解释这段材料。"],
    inputs: ["问题和可用材料"], outputs: ["解释和来源"], limitations: ["不补造空缺数字，不执行 WHCNS 仿真。"],
    dependencies: [{ name: "语言模型服务", status: unavailable ? "unavailable" : "unknown", required: true,
      message: unavailable ? "模型客户端未初始化。" : "客户端已初始化，未执行在线连通性检查。" }],
    input_schema: { type: "object", properties: { query: { type: "string" } } },
    output_schema: { type: "object", properties: { answer: { type: "string" } } },
    harness_version: "0.2.0", runtime_config_version: "catalog-browser:config", code_sha256: "a".repeat(64),
    skill_version: null, checked_at: "2026-10-17T08:00:00+00:00",
  } : null;
}

async function mockApi(page: Page, role = "tester") {
  const calls: string[] = [];
  const state = { unavailable: false, failList: false };
  await page.route("**/api/eval/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/eval", "");
    calls.push(`${route.request().method()} ${path}`);
    if (path === "/login") return route.fulfill({ json: { token: "skill-browser-session-token", user: { tester_id: "catalog-user", role } } });
    if (path === "/me") return route.fulfill({ json: { tester_id: "catalog-user", role } });
    if (path === "/skills") {
      if (state.failList) {
        return route.fulfill({ status: 503, json: { detail: { message: "能力目录暂时不可用，请重试。" } } });
      }
      return route.fulfill({ json: summaries });
    }
    if (path.startsWith("/skills/")) {
      const value = detail(path.split("/").at(-1)!, state.unavailable);
      return value ? route.fulfill({ json: value }) : route.fulfill({ status: 404, json: { detail: { message: "未找到该能力，请返回能力列表。" } } });
    }
    return route.fulfill({ json: [] });
  });
  return { calls, state };
}

async function login(page: Page) {
  await page.getByLabel("账号", { exact: true }).fill("catalog-user");
  await page.getByLabel("密码", { exact: true }).fill("CatalogTest123");
  await page.getByRole("button", { name: "进入工作台" }).click();
}

test("tester can search seven skills, inspect real input/output and refresh dependency state", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (problem) => errors.push(problem.message));
  const { calls, state } = await mockApi(page);
  await page.goto("/evaluation/skills");
  await login(page);
  await expect(page.getByRole("status")).toHaveText("已注册 7 项能力");
  await expect(page.getByRole("navigation", { name: "工作台导航" }).first().getByRole("link", { name: "Skill 能力", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /^查看.+详情$/ })).toHaveCount(7);
  await page.getByLabel("查找能力").fill("WHCNS");
  await expect(page.getByRole("link", { name: /^查看.+详情$/ })).toHaveCount(1);
  await page.getByLabel("查找能力").fill("不存在");
  await expect(page.getByText("没有找到匹配的能力。")).toBeVisible();
  await page.getByRole("button", { name: "清除搜索" }).click();
  await page.getByLabel("查找能力").fill("案例与措施解释");
  await page.getByRole("link", { name: "查看案例与措施解释详情" }).click();
  await expect(page).toHaveURL(/\/evaluation\/skills\/case_explanation$/);
  await expect(page.getByRole("heading", { name: "案例与措施解释", exact: true })).toBeVisible();
  await expect(page.getByText("客户端已初始化，未执行在线连通性检查。")).toBeVisible();
  await expect(page.getByText("case_explanation", { exact: true })).not.toBeVisible();
  await page.getByText("技术信息与输入输出", { exact: true }).click();
  await expect(page.getByText("case_explanation", { exact: true })).toBeVisible();
  await page.getByText("输入 Schema", { exact: true }).click();
  await expect(page.locator("pre").filter({ hasText: "query" })).toBeVisible();
  await expect(page.getByRole("button", { name: /保存|编辑|恢复默认/ })).toHaveCount(0);
  state.unavailable = true;
  await page.getByRole("button", { name: "刷新状态" }).click();
  await expect(page.getByText("模型客户端未初始化。")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "案例与措施解释", exact: true })).toBeVisible();
  expect(calls.filter((call) => call.includes("/skills")).every((call) => call.startsWith("GET "))).toBe(true);
  expect(errors).toEqual([]);
});

test("reviewer detail remains readable on mobile and missing skills have a recoverable error", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page, "reviewer");
  await page.goto("/evaluation/skills/case_explanation");
  await login(page);
  await expect(page.getByRole("heading", { name: "案例与措施解释", exact: true })).toBeVisible();
  await page.getByText("技术信息与输入输出", { exact: true }).click();
  await page.getByText("输入 Schema", { exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "打开导航" }).click();
  await expect(page.getByRole("dialog", { name: "移动端导航" }).getByRole("link", { name: "Skill 能力", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "关闭导航" }).click();
  await page.goto("/evaluation/skills/no-such-skill");
  await expect(page.getByLabel("Skill 能力详情", { exact: true }).getByRole("alert")).toContainText("未找到该能力");
  await page.getByRole("link", { name: "返回Skill 能力", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("已注册 7 项能力");
});

test("a failed catalog load can be retried without losing the login session", async ({ page }) => {
  const { state } = await mockApi(page, "developer");
  state.failList = true;
  await page.goto("/evaluation/skills");
  await login(page);
  await expect(page.getByLabel("Skill 能力列表", { exact: true }).getByRole("alert")).toContainText("能力目录暂时不可用");
  state.failList = false;
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("已注册 7 项能力");
  await expect(page.getByRole("button", { name: "退出登录" })).toBeVisible();
});


test("limited expression settings persist, detect conflicts and reset with history", async ({ page }) => {
  await mockApi(page);
  const defaults = { style: "plain", detail: "medium", organization: "answer_first" };
  let current = { revision: 0, version: "expression:0", values: { ...defaults }, actor: "builtin", changed_at: "", action: "default" };
  const history: typeof current[] = [];
  let fail = false;
  await page.route("**/api/eval/skills/case_explanation", route => route.fulfill({ json: { ...detail("case_explanation"), configuration: "limited" } }));
  await page.route("**/api/eval/skills/case_explanation/configuration**", route => {
    if (route.request().method() === "GET") return route.fulfill({ json: { current, history } });
    const body = route.request().postDataJSON();
    if (fail) return route.fulfill({ status: 503, json: { detail: { message: "保存失败，输入已保留。" } } });
    if (body.expected_revision !== current.revision) return route.fulfill({ status: 409, json: { detail: { message: "配置已被其他人修改。输入已保留，请读取最新版本。" } } });
    const reset = route.request().url().endsWith("/reset");
    current = { revision: current.revision + 1, version: `expression:${current.revision + 1}`, values: reset ? { ...defaults } : body.values, actor: "tester", changed_at: "2026-10-17", action: reset ? "reset" : "save" };
    history.unshift(current);
    return route.fulfill({ json: current });
  });
  await page.goto("/evaluation/skills/case_explanation"); await login(page);
  await page.getByLabel("默认详细程度").selectOption("detailed");
  fail = true;
  await page.getByRole("button", { name: "保存并启用", exact: true }).click();
  await expect(page.getByLabel("表达配置").getByRole("alert")).toContainText("输入已保留");
  await expect(page.getByLabel("默认详细程度")).toHaveValue("detailed");
  fail = false; current = { ...current, revision: 1, version: "expression:1" };
  await page.getByRole("button", { name: "保存并启用", exact: true }).click();
  await expect(page.getByLabel("表达配置").getByRole("alert")).toContainText("其他人修改");
  await expect(page.getByLabel("默认详细程度")).toHaveValue("detailed");
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "读取最新配置" }).click();
  await expect(page.getByLabel("默认详细程度")).toHaveValue("medium");
  await page.getByLabel("默认详细程度").selectOption("detailed");
  await page.getByRole("button", { name: "保存并启用", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("已保存并启用");
  await page.reload();
  await expect(page.getByLabel("默认详细程度")).toHaveValue("detailed");
  await page.getByRole("button", { name: "恢复默认", exact: true }).click();
  await expect(page.getByLabel("默认详细程度")).toHaveValue("medium");
  await page.getByText("变更记录", { exact: true }).click();
  await expect(page.getByLabel("表达配置")).toContainText("expression:3 · 恢复默认");
});

test("unified case capability appears once and old detail links to the canonical entry", async ({ page }) => {
  await mockApi(page);
  const canonical = { ...detail('case_explanation')!, name: 'case_assistant', title: '案例与措施助手', configuration: 'limited' };
  const current = [canonical, ...summaries.filter(s => !['case_reference', 'case_explanation'].includes(s.name)), { ...summaries[0], name: 'concept_explanation', title: '概念解释' }];
  await page.route('**/api/eval/skills', route => route.fulfill({ json: current }));
  await page.route('**/api/eval/skills/case_reference', route => route.fulfill({ json: { ...detail('case_reference'), alias_of: 'case_assistant' } }));
  await page.route('**/api/eval/skills/case_assistant', route => route.fulfill({ json: canonical }));
  await page.route('**/api/eval/skills/case_assistant/configuration', route => route.fulfill({ json: { current: { revision: 0, version: 'case-v1', values: { style: 'plain', detail: 'medium', organization: 'answer_first' }, actor: 'builtin', changed_at: null, action: 'default' }, history: [] } }));
  await page.goto('/evaluation/skills');
  await login(page);
  await expect(page.getByRole('link', { name: '查看案例与措施助手详情' })).toHaveCount(1);
  await expect(page.getByRole('link', { name: '查看案例与措施参考详情' })).toHaveCount(0);
  await page.goto('/evaluation/skills/case_reference');
  await page.getByRole('link', { name: '查看统一案例能力' }).click();
  await expect(page.getByRole('heading', { name: '案例与措施助手', exact: true })).toBeVisible();
  await expect(page.getByLabel('表达配置', { exact: true })).toBeVisible();
});
