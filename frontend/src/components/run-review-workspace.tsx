"use client";

import { EvaluationRuns } from "./evaluation-runs";
import { useEvaluationSession } from "./evaluation-shell";

export function RunReviewWorkspace({ detail, query }: { detail: string; query: string }) {
  const { token, user } = useEvaluationSession();
  return <EvaluationRuns token={token} detail={detail} query={query} actor={user.tester_id} canHandoff={user.role === "developer"} canEdit={user.role !== 'tester'} />;
}
