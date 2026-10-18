"""Conversation cohorts with complete turn histories and execution diagnostics."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def metric(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else None}


def step_metrics(events):
    groups = defaultdict(list)
    for event in events:
        if event.get("step_id") and event.get("kind") in {"tool", "skill", "service", "container"}:
            groups[(event["kind"], event.get("run_id", ""), event["step_id"])].append(event)
    output = {}
    for kind in ("tool", "skill", "service"):
        success = eligible = failed_attempts = ended_attempts = empty = retrievals = 0
        excluded = Counter()
        for (step_kind, _, _), values in groups.items():
            if step_kind != kind: continue
            attempts = defaultdict(list)
            for event in values: attempts[event.get("attempt_no", 1)].append(event)
            for attempt in attempts.values():
                started = any(event.get("type") == "step_started" for event in attempt)
                end = next((event for event in reversed(attempt) if event.get("type") == "step_finished"), None)
                if started and end and end.get("status") in {"succeeded", "failed"} and end.get("outcome") != "not_executed":
                    ended_attempts += 1
                    failed_attempts += end["status"] == "failed"
            latest = attempts[max(attempts)]
            started = any(event.get("type") == "step_started" for event in latest)
            final = next((event for event in reversed(latest) if event.get("type") == "step_finished"), {})
            status = final.get("status", "unknown")
            if started and status in {"succeeded", "failed"} and final.get("outcome") != "not_executed":
                eligible += 1
                success += status == "succeeded"
                if status == "succeeded" and final.get("operation") == "retrieval":
                    retrievals += 1
                    empty += final.get("outcome") == "no_result"
            else: excluded[status] += 1
        output[kind] = {"success": metric(success, eligible), "attempt_failure": metric(failed_attempts, ended_attempts),
                        "retrieval_no_result": metric(empty, retrievals), "excluded": dict(excluded), "observed_steps": sum(key[0] == kind for key in groups)}
    return output


class OnlineMetrics:
    def __init__(self, connection, lock):
        self.db, self.lock = connection, lock

    def population(self):
        with self.lock:
            cursor = self.db.execute("""SELECT s.*,r.payload,r.session_id AS trace_session_id
                FROM chat_submissions s LEFT JOIN agent_runs r ON r.run_id=s.run_id
                ORDER BY s.accepted_at,s.run_id""")
            keys = [column[0] for column in cursor.description]
            rows = [dict(zip(keys, row)) for row in cursor]
            # Synchronous evaluation and older conversations may have traces only.
            # Never infer turn/rerun associations from question text.
            traces = self.db.execute("""SELECT r.payload,r.session_id FROM agent_runs r
                WHERE NOT EXISTS (SELECT 1 FROM chat_submissions s WHERE s.run_id=r.run_id)
                ORDER BY r.started_at,r.rowid""").fetchall()
        for raw, session_id in traces:
            trace = json.loads(raw)
            rows.append({"run_id": trace["run_id"], "owner": None, "session_id": session_id,
                         "primary_run_id": trace.get("primary_run_id") or trace["run_id"],
                         "accepted_at": trace["started_at"], "source": trace.get("source", "legacy"),
                         "mode": trace.get("mode"), "config_version": trace.get("config_version"),
                         "status": {"ok": "succeeded", "error": "failed"}.get(trace["status"], trace["status"]),
                         "payload": raw})
        for row in rows:
            trace = json.loads(row["payload"]) if row["payload"] else {}
            row["session_id"] = row.get("trace_session_id") or row["session_id"]
            row.update({"trace": trace, "skills": list(dict.fromkeys(call["skill"] for call in trace.get("tool_calls", [])))})
        return rows

    @staticmethod
    def session_key(row):
        # Keep owners and trusted run sources isolated, even for reused IDs.
        return row["owner"], row["session_id"], row["source"]

    @staticmethod
    def session_status(rows):
        states = {row["status"] for row in rows}
        if states & {"failed", "cancelled", "interrupted"}: return "abnormal"
        if states & {"accepted", "running"}: return "running"
        if states != {"succeeded"}: return "unknown"
        return "normal"

    @staticmethod
    def matches_turn(row, filters):
        if any(filters.get(key) and row.get(key) != filters[key] for key in ("mode", "config_version")): return False
        if filters.get("skill") and filters["skill"] not in row["skills"]: return False
        return not filters.get("task_type") or filters["task_type"] in row["trace"].get("understanding", {}).get("intents", ["uncollected"])

    def summary(self, filters, *, include_sessions=False):
        population = self.population()
        grouped = defaultdict(list)
        for row in population:
            if row["run_id"] == row["primary_run_id"]:
                grouped[self.session_key(row)].append(row)
        sessions = {}
        for key, turns in grouped.items():
            turns.sort(key=lambda row: (row["accepted_at"], row["run_id"]))
            created_at = turns[0]["accepted_at"]
            if filters.get("source") and key[2] != filters["source"]: continue
            if filters.get("from") and created_at < filters["from"]: continue
            if filters.get("to") and created_at > filters["to"]: continue
            if filters.get("status") and self.session_status(turns) != filters["status"]: continue
            # Select conversations, then keep ALL their turns for context analysis.
            if not any(self.matches_turn(turn, filters) for turn in turns): continue
            sessions[key] = turns
        rows = [row for turns in sessions.values() for row in turns]
        selected_primary = {row["run_id"]: row for row in rows}
        reruns = [row for row in population if row["primary_run_id"] in selected_primary and row["run_id"] != row["primary_run_id"]]
        steps = [{"run_id": row["run_id"], **event} for row in rows for event in row["trace"].get("execution_steps", [])]
        missing = sum(not row["trace"] for row in rows)
        trends = defaultdict(Counter)
        skill_counts = defaultdict(lambda: {"calls": 0, "failures": 0, "latencies": [], "runs": set(), "sessions": set()})
        task_counts = Counter()
        for key, turns in sessions.items():
            day = datetime.fromisoformat(turns[0]["accepted_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
            trends[day]["sessions"] += 1
            trends[day]["abnormal_sessions"] += self.session_status(turns) == "abnormal"
            trends[day]["turns"] += len(turns)
            tasks = set()
            for row in turns:
                tasks.update(row["trace"].get("understanding", {}).get("intents", ["uncollected"]))
                for call in row["trace"].get("tool_calls", []):
                    count = skill_counts[call["skill"]]
                    count["calls"] += 1
                    count["failures"] += call["status"] == "error"
                    count["latencies"].append(call["latency_ms"])
                    count["runs"].add(row["run_id"])
                    count["sessions"].add(key)
            task_counts.update(tasks)
        recent = []
        if include_sessions:
            for turns in sorted(sessions.values(), key=lambda turns: (turns[0]["accepted_at"], turns[0]["run_id"]), reverse=True)[:20]:
                first = turns[0]
                recent.append({"session_id": first["session_id"], "run_id": next((row["run_id"] for row in turns if row["trace"]), None),
                               "topic": " ".join(first["trace"].get("input", "运行明细未采集").split())[:40],
                               "created_at": first["accepted_at"], "turns": len(turns), "status": self.session_status(turns),
                               "trace_missing": sum(not row["trace"] for row in turns)})
        return {"metric_version": "session-primary-v1", "unit": "session", "updated_at": datetime.now(timezone.utc).isoformat(), "filters": filters,
                "sessions": len(sessions), "session_states": dict(Counter(self.session_status(turns) for turns in sessions.values())),
                "multi_turn": metric(sum(len(turns) > 1 for turns in sessions.values()), len(sessions)),
                "mean_turns": round(len(rows) / len(sessions), 2) if sessions else None,
                "turn_distribution": [{"turns": turns, "sessions": count} for turns, count in sorted(Counter(map(len, sessions.values())).items())],
                "recent_sessions": recent,
                "questions": len(rows), "population_run_ids": [row["run_id"] for row in rows], "states": dict(Counter(row["status"] for row in rows)),
                "reruns": {"attempts": len(reruns), "succeeded": sum(row["status"] == "succeeded" for row in reruns),
                           "sessions": len({self.session_key(selected_primary[row["primary_run_id"]]) for row in reruns}),
                           "recovered_failed_primary": len({row["primary_run_id"] for row in reruns if row["status"] == "succeeded" and selected_primary[row["primary_run_id"]]["status"] in {"failed", "interrupted", "unknown", "cancelled"}})},
                "steps": step_metrics(steps), "trace_missing": missing,
                "by_task": dict(task_counts),
                "by_skill": [{"skill": name, "calls": value["calls"], "failures": value["failures"], "runs": len(value["runs"]), "sessions": len(value["sessions"]),
                              "mean_latency_ms": round(sum(value["latencies"])/len(value["latencies"]))} for name, value in sorted(skill_counts.items())],
                "daily": [{"date": day, **counts} for day, counts in sorted(trends.items())]}
