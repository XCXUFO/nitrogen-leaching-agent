interface Props {
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
  slowHint?: boolean;
}

export function ChatMessage({ role, content, pending, slowHint }: Props) {
  const isUser = role === "user";
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={`max-w-[85%] rounded-lg px-4 py-3 text-sm ${
          isUser ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"
        }`}
      >
        <div className="font-sans whitespace-pre-wrap break-words">
          {content}
        </div>
        {pending && slowHint && (
          <p className="mt-2 text-xs opacity-70">
            首次响应较慢（约 10 秒），后端可能正在加载嵌入模型…
          </p>
        )}
      </div>
    </div>
  );
}
