"""Bounded rich text: keep table cells/spans, accept no executable markup."""
from html import escape
from html.parser import HTMLParser
from typing import Literal

BodyFormat = Literal["plain", "html"]


class CaseHTML(HTMLParser):
    tags = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "em", "s", "u", "code", "pre", "blockquote", "br", "hr", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "colgroup", "col"}
    void = {"br", "hr", "col"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.text: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.tags or len(self.stack) >= 64:
            raise ValueError("正文包含不支持的格式，请使用段落、列表或基本表格。")
        parent = self.stack[-1] if self.stack else None
        parents = {"thead": {"table"}, "tbody": {"table"}, "tfoot": {"table"},
                   "tr": {"table", "thead", "tbody", "tfoot"}, "td": {"tr"}, "th": {"tr"},
                   "colgroup": {"table"}, "col": {"colgroup"}}
        children = {"table": {"thead", "tbody", "tfoot", "tr", "colgroup"},
                    "thead": {"tr"}, "tbody": {"tr"}, "tfoot": {"tr"},
                    "tr": {"td", "th"}, "colgroup": {"col"}}
        if (tag in parents and parent not in parents[tag]) or (parent in children and tag not in children[parent]):
            raise ValueError("表格行列结构无效，请在编辑器中检查后重试。")
        kept = []
        for key, value in attrs:
            if (tag in {"td", "th"} and key in {"colspan", "rowspan"}) or (tag == "ol" and key == "start"):
                if value is None or not value.isdecimal() or not 1 <= int(value) <= (10000 if tag == "ol" else 100):
                    raise ValueError("表格跨度或列表起始序号无效。")
                kept.append(f' {key}="{int(value)}"')
        self.parts.append(f"<{tag}{''.join(kept)}>")
        if tag not in self.void:
            self.stack.append(tag)
        elif tag in {"br", "hr"}:
            self.text.append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in self.void:
            return
        if not self.stack or self.stack.pop() != tag:
            raise ValueError("正文格式不完整，请在编辑器中检查后重试。")
        self.parts.append(f"</{tag}>")
        if tag in {"td", "th"}:
            self.text.append("\t")
        elif tag in {"p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"}:
            self.text.append("\n")

    def handle_data(self, data):
        if self.stack and self.stack[-1] in {"table", "thead", "tbody", "tfoot", "tr", "colgroup"} and data.strip():
            raise ValueError("表格文字必须保留在对应单元格中。")
        self.parts.append(escape(data, quote=False))
        self.text.append(data)


def parse_html(body: str) -> CaseHTML:
    parser = CaseHTML()
    parser.feed(body)
    parser.close()
    if parser.stack:
        raise ValueError("正文格式不完整，请在编辑器中检查后重试。")
    return parser


def normalize_body(body: str, body_format: BodyFormat) -> str:
    if body_format == "plain":
        return body
    parser = parse_html(body)
    if not "".join(parser.text).strip():
        raise ValueError("请先填写案例与措施正文，空白表格不能单独保存。")
    normalized = "".join(parser.parts)
    if len(normalized) > 50000:
        raise ValueError("正文超过 50000 字符容量，请缩短后重试。")
    return normalized


def body_summary(body: str, body_format: BodyFormat) -> str:
    return (" ".join("".join(parse_html(body).text).split()) if body_format == "html" else body)[:180]
