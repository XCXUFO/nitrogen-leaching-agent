"use client";

import { useEffect, useRef } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { TableKit } from "@tiptap/extension-table";
import styles from "./case-body-editor.module.css";

export type BodyFormat = "plain" | "html";
export function bodyContent(body: string, format: BodyFormat) {
  // Legacy text is data, never HTML (including literal <, > and &).
  return format === "html" ? body : {
    type: "doc", content: body.split("\n").map((line) => ({
      type: "paragraph", ...(line ? { content: [{ type: "text", text: line }] } : {}),
    })),
  };
}

export function CaseBodyEditor({ body, format, onChange, disabled = false }: {
  body: string; format: BodyFormat; onChange?: (html: string, hasText: boolean) => void; disabled?: boolean;
}) {
  const editable = !!onChange;
  const lastValue = useRef({ body, format });
  const editor = useEditor({
    immediatelyRender: false,
    shouldRerenderOnTransaction: true,
    extensions: [StarterKit.configure({ link: false, heading: { levels: [2, 3] } }), TableKit],
    content: bodyContent(body, format),
    editable: editable && !disabled,
    editorProps: { attributes: {
      ...(editable ? { id: "case-body", role: "textbox", "aria-label": "案例与措施原文 *", "aria-multiline": "true", "aria-required": "true", "aria-describedby": "case-body-help" } : { "aria-label": "案例与措施正文" }),
    } },
    onUpdate: ({ editor }) => {
      const html = editor.getHTML();
      lastValue.current = { body: html, format: "html" };
      onChange?.(html, !!editor.getText().trim());
    },
  });
  useEffect(() => {
    if (!editor) return;
    if (lastValue.current.body !== body || lastValue.current.format !== format) {
      editor.commands.setContent(bodyContent(body, format), { emitUpdate: false });
      lastValue.current = { body, format };
    }
  }, [body, format, editor]);
  useEffect(() => { editor?.setEditable(editable && !disabled); }, [editor, editable, disabled]);

  const actions = editor ? [
    { label: "段落", run: () => editor.chain().focus().setParagraph().run(), active: editor.isActive("paragraph") },
    { label: "小标题", run: () => editor.chain().focus().toggleHeading({ level: 2 }).run(), active: editor.isActive("heading") },
    { label: "加粗", run: () => editor.chain().focus().toggleBold().run(), active: editor.isActive("bold") },
    { label: "编号列表", run: () => editor.chain().focus().toggleOrderedList().run(), active: editor.isActive("orderedList") },
    { label: "项目列表", run: () => editor.chain().focus().toggleBulletList().run(), active: editor.isActive("bulletList") },
    { label: "插入表格", run: () => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(), disabled: editor.isActive("table") },
    { label: "上方插行", run: () => editor.chain().focus().addRowBefore().run(), disabled: !editor.can().addRowBefore() },
    { label: "下方插行", run: () => editor.chain().focus().addRowAfter().run(), disabled: !editor.can().addRowAfter() },
    { label: "左侧插列", run: () => editor.chain().focus().addColumnBefore().run(), disabled: !editor.can().addColumnBefore() },
    { label: "右侧插列", run: () => editor.chain().focus().addColumnAfter().run(), disabled: !editor.can().addColumnAfter() },
    { label: "删除行", run: () => editor.chain().focus().deleteRow().run(), disabled: !editor.can().deleteRow() },
    { label: "删除列", run: () => editor.chain().focus().deleteColumn().run(), disabled: !editor.can().deleteColumn() },
    { label: "删除表格", run: () => editor.chain().focus().deleteTable().run(), disabled: !editor.can().deleteTable() },
    { label: "撤销", run: () => editor.chain().focus().undo().run(), disabled: !editor.can().undo() },
    { label: "重做", run: () => editor.chain().focus().redo().run(), disabled: !editor.can().redo() },
  ] : [];
  return <div className={`${styles.root} ${editable ? styles.editable : ""}`}>
    {editable && <div role="toolbar" aria-label="正文格式和表格操作" className="flex flex-wrap gap-1 border-b bg-slate-50 p-2">
      {actions.map((action) => <button key={action.label} type="button" disabled={disabled || action.disabled} aria-pressed={action.active}
        className={`rounded px-2 py-1 text-xs disabled:opacity-40 ${action.active ? "bg-emerald-100 text-emerald-900" : "hover:bg-slate-200"}`}
        onMouseDown={(event) => event.preventDefault()} onClick={action.run}>{action.label}</button>)}
    </div>}
    <EditorContent editor={editor} />
    {!editor && <p className="p-3 text-sm text-slate-500">正在加载正文…</p>}
  </div>;
}
