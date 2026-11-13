import { expect, test, type Page } from "@playwright/test";

const started = "2026-11-11T08:00:00Z";
const hit = (paper: string, title: string, rank: number) => ({ chunk_id: `${paper}:chunk`, paper_id: paper, title, rank, score: 1 / rank });
const a = hit("paper-a", "玉米滴灌研究", 1), b = hit("paper-b", "氮肥减量研究", 2), c = hit("paper-c", "土壤水分研究", 3);

function richTurn() {
  return { run_id: "readable", input: "比较玉米滴灌措施并结合文件说明原因", answer: "文件计算结果与文献说明。", started_at: started,
    status: "ok", outcome: "complete", latency_ms: 500, error_code: null,
    decision: { route: "COMPOSED", skills: ["whcns_analyzer", "knowledge_search"] },
    understanding: { keywords: ["玉米", "滴灌", "氧化亚氮", "陕西"], subtasks: [{ subtask_id: "t1", query: "比较玉米滴灌措施" }] },
    tag_mapping: { status: "collected", taxonomy_fingerprint: "original-fingerprint-kept", mappings: [
      { term: "玉米", canonical: "玉米", status: "matched", method: "exact_name", usage: "semantic_condition", candidates: [{ id: "maize", path: "作物 / 玉米" }] },
      { term: "滴灌", canonical: "滴灌", status: "matched", method: "exact_name", usage: "ranking_signal", candidates: [{ id: "drip", path: "措施 / 滴灌" }] },
      { term: "陕西", canonical: "陕西", status: "ambiguous", method: "exact_name", usage: "ranking_signal", candidates: [{ id: "region-1", path: "地区 / 陕西" }, { id: "region-2", path: "案例地区 / 陕西" }] },
    ] },
    retrieval: [
      { source_type: "literature", retrieval_id: "search-1", skill: "knowledge_search", subtask_ids: ["t1"], query: "玉米滴灌措施",
        candidates: [{ ...a, selected: true, recall_paths: [{ route: "tag", rank: 1 }, { route: "semantic:full_text", rank: 2 }] }, { ...b, selected: true, recall_paths: ["full_text"] }, { ...c, selected: false, reason: "condition_unconfirmed" }],
        ranked_candidates: [{ ...b, rank: 1 }, { ...a, rank: 2 }],
        semantic: { rounds: [{ query: "玉米滴灌措施", rerank_status: "applied", recall: [a, b, c], reranked: [{ ...b, rank: 1 }, { ...a, rank: 2 }, c], returned: [{ ...b, rank: 1 }, { ...a, rank: 2 }] }] } },
      { source_type: "literature", retrieval_id: "search-1", stage: "model_context", adopted_chunk_ids: [b.chunk_id, a.chunk_id], supplied_candidates: [{ ...b, rank: 1 }, { ...a, rank: 2 }] },
    ],
    tool_calls: [
      { skill: "file_inspector", status: "ok", latency_ms: 10 }, { skill: "whcns_analyzer", status: "ok", latency_ms: 30 },
      { skill: "knowledge_search", status: "ok", latency_ms: 300, step_id: "skill-1" },
    ],
    execution_steps: [
      { type: "step_started", kind: "skill", step_id: "skill-1", skill: "knowledge_search", name: "文献检索", status: "running", time: started },
      { type: "step_started", kind: "tool", step_id: "tool-1", parent_step_id: "skill-1", name: "检索文献正文", status: "running", time: started },
      { type: "step_finished", kind: "tool", step_id: "tool-1", parent_step_id: "skill-1", name: "检索文献正文", status: "succeeded", time: "2026-11-11T08:00:00.100Z" },
      { type: "step_finished", kind: "skill", step_id: "skill-1", skill: "knowledge_search", status: "succeeded", time: "2026-11-11T08:00:00.300Z" },
    ],
    evidence: [{ source_type: "literature", source_id: a.chunk_id, provenance: { paper_id: "paper-a", title: "玉米滴灌研究" } },
      { source_type: "file", source_id: "file-hash", provenance: { filename: "Nbal_out.xlsx" } }],
    sections: [{ kind: "file_observation", content: "文件中的计算结果。" }, { kind: "literature_inference", content: "文献中的机理。" }],
    answer_assembly: { mode: "file_plus_literature" }, warnings: [],
  };
}

const legacy = { run_id: "legacy", input: "小麦呢", answer: "小麦资料说明。", started_at: started, status: "ok", outcome: "complete", latency_ms: 80, error_code: null,
  decision: { route: "KNOWLEDGE" }, tool_calls: [{ skill: "knowledge_search", status: "ok", latency_ms: 60 }],
  retrieval: [{ source_type: "literature", candidates: [{ chunk_id: "wheat", source: "小麦试验.pdf", selected: true }] }], evidence: [], sections: [] };

async function open(page: Page, turns: unknown[]) {
  await page.route("**/api/eval/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/eval", "");
    const user = { tester_id: "reviewer", role: "reviewer" };
    if (path === "/me") return route.fulfill({ json: user });
    if (path === "/login") return route.fulfill({ json: { token: "overview-token", user } });
    if (path === "/sessions/readable-session") return route.fulfill({ json: { session_id: "readable-session", topic: "可读链路", created_at: started,
      operator_id: "reviewer", status: "正常", latency_ms: 580, turn_count: turns.length, turns } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/evaluation/runs/readable-session");
  await page.getByLabel("账号", { exact: true }).fill("reviewer");
  await page.getByLabel("密码", { exact: true }).fill("Review123456");
  await page.getByRole("button", { name: "进入工作台" }).click();
  await expect(page.getByRole("region", { name: "本轮执行概览" }).first()).toBeVisible();
}

test("each turn shows keywords, materials, actual skills and output above preserved raw JSON", async ({ page }) => {
  await open(page, [richTurn(), legacy]);
  const overview = page.getByRole("region", { name: "本轮执行概览" }).first();
  await expect(overview).toContainText("关键词 4 个 · 已匹配 2 个 · 命中 2 个标签 · 待确认 1 个");
  await expect(overview).toContainText("氧化亚氮→未匹配标签");
  await expect(overview).toContainText("待确认，候选不计入命中数");
  await expect(overview).toContainText("候选 3 份 / 3 片段");
  const table = overview.getByRole("table");
  const rows = table.getByRole("row");
  await expect(rows.nth(1)).toContainText("氮肥减量研究");
  await expect(rows.nth(1)).toContainText("#1");
  await expect(rows.nth(1)).toContainText("未引用");
  await expect(rows.nth(2)).toContainText("玉米滴灌研究");
  await expect(rows.nth(2)).toContainText("#2");
  await expect(rows.nth(2)).toContainText("已引用");
  await expect(rows.nth(2).getByRole("cell").nth(1)).toHaveText("标签（#1）、语义 · 全文（#2）");
  await expect(rows.nth(1).getByRole("cell").nth(1)).toHaveText("全文");
  await expect(rows.nth(3)).toContainText("条件未确认");
  await expect(rows.nth(3)).toContainText("未送入");
  await expect(overview).toContainText("归属：文献知识检索");
  await expect(overview).toContainText("文件计算结果 + 文献机理说明");
  await expect(overview.getByText("组合输出", { exact: true })).toHaveCount(2);
  await expect(overview.locator("pre")).toHaveCount(0);
  const second = page.getByRole("region", { name: "本轮执行概览" }).nth(1);
  await expect(second).toContainText("小麦试验.pdf");
  await expect(second).not.toContainText("玉米滴灌研究");
  await overview.screenshot({ path: "/tmp/nitrogen-run-overview-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await overview.screenshot({ path: "/tmp/nitrogen-run-overview-mobile.png" });
  await page.setViewportSize({ width: 1280, height: 900 });

  await overview.getByText("重排前后对比", { exact: false }).click();
  const comparison = overview.locator("details").filter({ hasText: "重排前后对比" });
  await expect(comparison).toContainText("重排前：#1 玉米滴灌研究");
  await expect(comparison).toContainText("重排后：#1 氮肥减量研究");
  const raw = page.locator("details").filter({ has: page.locator("summary", { hasText: "展开本轮 MQ 明细 · Run readable" }) }).first();
  await expect(raw).not.toHaveAttribute("open");
  await page.getByText("展开本轮 MQ 明细 · Run readable").click();
  await raw.getByText("标签映射与用途", { exact: true }).click();
  await expect(raw.getByText(/original-fingerprint-kept/).first()).toBeVisible();
  await raw.getByText("完整运行记录", { exact: true }).click();
  await expect(raw.locator("pre").last()).toContainText('"answer_assembly"');
});

test("older records and disabled reranking show missing stages explicitly", async ({ page }) => {
  const turn = richTurn();
  turn.retrieval[0].semantic!.rounds[0].rerank_status = "disabled";
  await open(page, [legacy, turn]);
  const old = page.getByRole("region", { name: "本轮执行概览" }).first();
  await expect(old).toContainText("关键词 未记录");
  await expect(old).toContainText("历史记录未保存标签匹配过程");
  await expect(old).toContainText("未单独记录重排阶段");
  await expect(old).toContainText("筛选通过");
  await expect(old).toContainText("输出组成未记录");
  const newer = page.getByRole("region", { name: "本轮执行概览" }).nth(1);
  await newer.getByText("重排前后对比", { exact: false }).click();
  await expect(newer).toContainText("本路未启用重排");
});

test("starred coverage skips retrieval clearly and overview fits a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, [{ ...legacy, run_id: "starred", tool_calls: [], retrieval: [],
    understanding: { raw_query: "观测信息如何走到治理决策", keywords: ["折氮量"], semantic: { status: "applied", model: "semantic-test",
      candidate_recall: "full_library_semantic_review", rewrites: [{ subtask_id: "task", status: "applied",
        intent_description: "询问项目计划的衔接流程", resolved_query: "项目数据模型应用如何衔接", effective_retrieval_query: "氮素淋溶 情景模拟 措施评价 验证推广" }],
      assessments: [{ matches: [{ coverage: "complete", reason: "覆盖计划流程，未声称已有验证效果" }] }] } }, tag_mapping: { status: "skipped", reason: "starred_full_coverage" },
    starred_match: { status: "full", adopted: [{ question_id: "star-1" }] }, answer_assembly: { mode: "starred_only" } }]);
  const overview = page.getByRole("region", { name: "本轮执行概览" });
  await expect(overview).toContainText("星标问答已完整覆盖，本轮跳过标签映射");
  await expect(overview).toContainText("星标答复已覆盖需求，本轮未继续检索");
  await expect(overview).toContainText("复用已有答复，没有继续调用 Skill");
  await expect(overview).toContainText("原问题：观测信息如何走到治理决策");
  await expect(overview).toContainText("需求理解：询问项目计划的衔接流程");
  await expect(overview).toContainText("检索 Query：氮素淋溶 情景模拟 措施评价 验证推广");
  await expect(overview).toContainText("覆盖计划流程，未声称已有验证效果");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("partial starred coverage does not label covered keywords as unmatched tags", async ({ page }) => {
  await open(page, [{ ...legacy, understanding: { keywords: ["折氮量", "小麦"] }, execution_context: { keywords: ["小麦"] },
    tag_mapping: { status: "collected", mappings: [] }, starred_match: { status: "partial", adopted: [{ question_id: "star-1" }], continuation: { outcome: "complete" } },
    answer_assembly: { mode: "starred_plus_continuation" } }]);
  const overview = page.getByRole("region", { name: "本轮执行概览" });
  await expect(overview).toContainText("折氮量→星标已覆盖，未再映射");
  await expect(overview).toContainText("小麦→未匹配标签");
  await expect(overview).toContainText("已有星标答复 + 剩余问题的处理结果");
});

for (const scenario of ["excluded", "explicit", "legacy"] as const) {
  test(`final citations retain their retrieval origin: ${scenario}`, async ({ page }) => {
    const other = { ...a, chunk_id: scenario === "excluded" ? "paper-a:excluded" : a.chunk_id };
    const firstSupplied = scenario === "excluded" ? [] : [other];
    const selection = (id: string, candidate: typeof a, supplied: typeof a[]) => [
      { source_type: "literature", retrieval_id: id, candidates: [{ ...candidate, selected: supplied.length > 0 }], ranked_candidates: supplied },
      { source_type: "literature", retrieval_id: id, stage: "model_context", supplied_candidates: supplied },
    ];
    await open(page, [{ ...legacy, run_id: "two-rounds",
      retrieval: [...selection("first", other, firstSupplied), ...selection("second", a, [a])],
      evidence: [{ source_type: "literature", source_id: a.chunk_id,
        ...(scenario === "explicit" ? { retrieval_ids: ["second"], chunk_ids: [a.chunk_id] } : {}),
        provenance: { paper_id: "paper-a", title: a.title } }],
    }]);
    const first = page.getByLabel("第 1 次资料检索", { exact: true });
    const second = page.getByLabel("第 2 次资料检索", { exact: true });
    const citation = (region: typeof first) => region.getByRole("row").nth(1).getByRole("cell").last();
    await expect(citation(first)).toHaveText(scenario === "legacy" ? "批次未确认" : "未引用");
    await expect(citation(second)).toHaveText(scenario === "legacy" ? "批次未确认" : "已引用");
    if (scenario === "legacy") {
      await expect(first).toContainText("引用 0 份");
      await expect(second).toContainText("引用批次未确认");
    }
  });
}
