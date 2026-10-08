"""HTML to plain text using only the standard library."""

from html.parser import HTMLParser

SKIP_TAGS = {"script", "style", "noscript", "head", "nav", "footer"}
BLOCK_TAGS = {
    "p", "div", "section", "article", "li", "tr", "br",
    "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
        elif tag in BLOCK_TAGS and self._skip_depth == 0:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in BLOCK_TAGS and self._skip_depth == 0:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._parts.append(data)

    def text(self) -> str:
        joined = "".join(self._parts)
        lines = [ln.strip() for ln in joined.splitlines()]
        out, prev_blank = [], False
        for ln in lines:
            if not ln:
                if not prev_blank:
                    out.append("")
                prev_blank = True
            else:
                out.append(ln)
                prev_blank = False
        return "\n".join(out).strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()