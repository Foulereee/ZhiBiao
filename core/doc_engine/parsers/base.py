from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ParsedDocument:
    text: str
    tables: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class DocumentParser(Protocol):
    def parse(self, file_path: str) -> ParsedDocument: ...


PARSER_REGISTRY: dict[str, type] = {}

EXT_MAP = {
    ".pdf": "pdf_parser",
    ".docx": "docx_parser",
    ".doc": "docx_parser",
    ".wps": "docx_parser",
    ".txt": "txt_parser",
    ".md": "txt_parser",
    ".html": "txt_parser",
    ".rtf": "txt_parser",
    ".xlsx": "txt_parser",
    ".pptx": "txt_parser",
}


def _register_parsers():
    from core.doc_engine.parsers.pdf_parser import PdfParser
    from core.doc_engine.parsers.docx_parser import DocxParser
    from core.doc_engine.parsers.txt_parser import TxtParser

    PARSER_REGISTRY["pdf_parser"] = PdfParser
    PARSER_REGISTRY["docx_parser"] = DocxParser
    PARSER_REGISTRY["txt_parser"] = TxtParser


_register_parsers()


def get_parser(file_ext: str) -> DocumentParser:
    from core.exceptions import UnsupportedFormatError
    parser_name = EXT_MAP.get(file_ext.lower())
    if not parser_name:
        raise UnsupportedFormatError(f"不支持的文件格式: {file_ext}")
    if parser_name not in PARSER_REGISTRY:
        raise UnsupportedFormatError(f"格式 {file_ext} 已映射但解析器 {parser_name} 未注册")
    return PARSER_REGISTRY[parser_name]()
