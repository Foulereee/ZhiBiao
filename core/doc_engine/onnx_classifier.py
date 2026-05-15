from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

LABEL_MAP = {
    0: "title",
    1: "abstract",
    2: "body",
    3: "reference",
    4: "table_caption",
    5: "figure_caption",
    6: "heading",
    7: "list_item",
    8: "footer",
    9: "other",
}

MAX_LENGTH = 128
VOCAB_SIZE = 5000
UNK_IDX = 1
PAD_IDX = 0


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            tokens.append(char)
        elif char.isalnum():
            tokens.append(char.lower())
        elif char.isspace():
            continue
        else:
            tokens.append(char)
    return tokens


def _build_vocab() -> dict[str, int]:
    vocab: dict[str, int] = {f"<PAD>": PAD_IDX, f"<UNK>": UNK_IDX}
    idx = 2
    for cp in range(0x4E00, 0x9FFF + 1):
        vocab[chr(cp)] = idx
        idx += 1
        if idx >= VOCAB_SIZE:
            break
    for c in "abcdefghijklmnopqrstuvwxyz0123456789":
        vocab[c] = idx
        idx += 1
        if idx >= VOCAB_SIZE:
            break
    return vocab


_VOCAB = _build_vocab()


def _encode(text: str) -> list[int]:
    tokens = _tokenize(text)
    ids = [_VOCAB.get(t, UNK_IDX) for t in tokens]
    if len(ids) > MAX_LENGTH:
        ids = ids[:MAX_LENGTH]
    else:
        ids = ids + [PAD_IDX] * (MAX_LENGTH - len(ids))
    return ids


class OnnxClassifier:
    def __init__(self, model_path: str = "", device: str = "auto"):
        self._available = False
        self._session = None

        if not model_path:
            base = Path(__file__).resolve().parent.parent.parent
            model_path = str(base / "models" / "doc_classifier.onnx")

        if device == "auto":
            device = self._detect_device()

        providers = self._resolve_providers(device)

        try:
            import onnxruntime as ort
        except ImportError:
            logger.warning("onnxruntime 未安装，文档分类器不可用，将使用降级策略")
            return

        if not os.path.isfile(model_path):
            logger.warning("ONNX 模型文件未找到: %s，文档分类器不可用", model_path)
            return

        try:
            self._session = ort.InferenceSession(model_path, providers=providers)
            self._available = True
            logger.info("ONNX 文档分类器已加载: %s (provider=%s)", model_path, self._session.get_providers())
        except Exception as exc:
            logger.warning("ONNX 模型加载失败: %s，将使用降级策略", exc)

    @staticmethod
    def _detect_device() -> str:
        try:
            import onnxruntime as ort
            available = ort.get_available_providers()
            if "CUDAExecutionProvider" in available:
                return "cuda"
            if "DmlExecutionProvider" in available:
                return "dml"
        except ImportError:
            pass
        return "cpu"

    @staticmethod
    def _resolve_providers(device: str) -> list[str]:
        mapping = {
            "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
            "dml": ["DmlExecutionProvider", "CPUExecutionProvider"],
            "cpu": ["CPUExecutionProvider"],
        }
        return mapping.get(device, ["CPUExecutionProvider"])

    def is_available(self) -> bool:
        return self._available

    def classify(self, paragraphs: list[str], batch_size: int = 32) -> list[str]:
        if not paragraphs:
            return []

        if not self._available:
            return ["body"] * len(paragraphs)

        all_ids = np.array([_encode(p) for p in paragraphs], dtype=np.int64)

        input_name = self._session.get_inputs()[0].name
        predictions: list[str] = []

        for start in range(0, len(all_ids), batch_size):
            batch = all_ids[start : start + batch_size]
            outputs = self._session.run(None, {input_name: batch})
            logits = outputs[0]
            if logits.ndim == 1:
                logits = logits.reshape(1, -1)
            pred_indices = np.argmax(logits, axis=-1)
            for idx in pred_indices:
                predictions.append(LABEL_MAP.get(int(idx), "other"))

        return predictions
