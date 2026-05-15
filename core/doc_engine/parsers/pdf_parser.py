from __future__ import annotations

from core.doc_engine.parsers.base import ParsedDocument


class PdfParser:
    def parse(self, file_path: str) -> ParsedDocument:
        import pdfplumber

        text_parts = []
        tables = []
        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)
            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                if page_text:
                    text_parts.append(page_text)
                for table in (page.extract_tables() or []):
                    tables.append({
                        "page": page_num + 1,
                        "headers": table[0] if table else [],
                        "rows": table[1:] if len(table) > 1 else [],
                    })

        full_text = "\n\n".join(text_parts)
        is_scanned = len(full_text.strip()) < page_count * 50 if page_count > 0 else False

        return ParsedDocument(
            text=full_text,
            tables=tables,
            images=[],
            metadata={"page_count": page_count, "is_scanned": is_scanned, "parser": "pdfplumber"},
        )
