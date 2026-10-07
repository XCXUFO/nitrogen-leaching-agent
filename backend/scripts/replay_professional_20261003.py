"""Replay the frozen professional questions without assigning a review score."""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/raw/whcns/received-2026-09-26/package/模型/Nbal_out.xls"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://127.0.0.1:8002")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    opener = build_opener(ProxyHandler({}))

    def post(path: str, data: bytes, content_type: str) -> dict:
        request = Request(args.api_base + path, data=data, method="POST",
                          headers={"Content-Type": content_type})
        try:
            with opener.open(request, timeout=150) as response:
                return json.load(response)
        except HTTPError as exc:
            return {"http_status": exc.code, "detail": json.loads(exc.read())}

    receipt = post("/api/files?filename=" + quote(SOURCE.name), SOURCE.read_bytes(), "application/octet-stream")
    if "file_id" not in receipt:
        raise RuntimeError(f"upload failed: {receipt}")
    session_id = str(uuid.uuid4())
    history: list[dict[str, str]] = []
    rounds = []
    for query in (
        "接下来只讨论玉米农田。氮素淋失主要受哪些因素影响？",
        "硝态氮最大值是多少，为什么可能这么高？",
        "那最小值呢？",
    ):
        body = {"query": query, "session_id": session_id, "file_id": receipt["file_id"], "history": history[-12:]}
        response = post("/api/chat", json.dumps(body, ensure_ascii=False).encode(), "application/json")
        rounds.append({"question": query, "response": response})
        if "answer" not in response:
            break
        history.extend([{"role": "user", "content": query},
                        {"role": "assistant", "content": response["answer"][:4000]}])
    result = {"replayed_at": datetime.now(timezone.utc).isoformat(),
              "source": str(SOURCE.relative_to(ROOT)), "session_id": session_id,
              "upload_status": receipt["status"], "rounds": rounds,
              "review_status": "unreviewed; no professional pass assigned"}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([{"question": round_["question"], "run_id": round_["response"].get("run_id"),
                       "route": round_["response"].get("agent_route"), "outcome": round_["response"].get("outcome"),
                       "error": round_["response"].get("detail")}
                      for round_ in rounds], ensure_ascii=False))


if __name__ == "__main__":
    main()
