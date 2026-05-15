from __future__ import annotations

from core.doc_engine.parsers.base import ParsedDocument


class TxtParser:
    def parse(self, file_path: str) -> ParsedDocument:
        encodings = ["utf-8", "gbk", "gb18030", "latin-1"]
        text = None
        used_encoding = "utf-8"

        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    text = f.read()
                used_encoding = encoding
                break
            except (UnicodeDecodeError, UnicodeError):
                continue

        if text is None:
            try:
                import chardet
                with open(file_path, "rb") as f:
                    raw = f.read()
                detected = chardet.detect(raw)
                encoding = detected.get("encoding", "utf-8")
                text = raw.decode(encoding, errors="replace")
                used_encoding = encoding
            except Exception:
                text = ""

        return ParsedDocument(
            text=text,
            tables=[],
            images=[],
            metadata={"encoding": used_encoding, "parser": "txt"},
        )
