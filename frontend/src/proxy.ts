import { NextResponse, type NextRequest } from "next/server";
import { literaturePdfLimitMb } from "./lib/literature-config";

export function proxy(request: NextRequest) {
  const declared = request.headers.get("content-length") || "";
  const limit = literaturePdfLimitMb();
  // Reject before sending a large body upstream. Otherwise an early backend
  // 413 can reset the proxy's pending write and be surfaced as a generic 500.
  if (request.method === "POST" && /^\d+$/.test(declared) && Number(declared) > limit * 1024 * 1024) {
    return NextResponse.json({ detail: { code: "file_too_large", message: `PDF 不能超过 ${limit} MB。` } }, { status: 413 });
  }
  return NextResponse.next();
}

export const config = { matcher: "/api/literature/uploads" };
