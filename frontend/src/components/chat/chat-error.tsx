import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api";

interface Props {
  error: ApiError;
  onRetry?: () => void;
}

export function ChatError({ error, onRetry }: Props) {
  return (
    <div className="border-destructive/40 bg-destructive/10 text-destructive rounded-md border p-3 text-sm">
      <p>{error.userMessage}</p>
      <p className="mt-1 text-xs opacity-70">
        错误码：<code>{error.code}</code>
        {error.httpStatus !== null && <> · HTTP {error.httpStatus}</>}
      </p>
      {onRetry && (
        <div className="mt-2">
          <Button variant="outline" size="sm" onClick={onRetry}>
            重试
          </Button>
        </div>
      )}
    </div>
  );
}
