from core.doc_engine.parsers.base import ParsedDocument, DocumentParser, get_parser, PARSER_REGISTRY
from core.doc_engine.parsers.pdf_parser import PdfParser
from core.doc_engine.parsers.docx_parser import DocxParser
from core.doc_engine.parsers.txt_parser import TxtParser
from core.doc_engine.section_detector import SectionDetector

PARSER_REGISTRY["pdf_parser"] = PdfParser
PARSER_REGISTRY["docx_parser"] = DocxParser
PARSER_REGISTRY["txt_parser"] = TxtParser

__all__ = ["ParsedDocument", "DocumentParser", "get_parser", "SectionDetector"]
