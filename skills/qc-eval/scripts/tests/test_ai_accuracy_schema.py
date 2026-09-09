#!/usr/bin/env python3
"""Regression tests for source-owned dynamic AI accuracy columns."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.ai_accuracy import (
    inspect_ai_accuracy_headers,
    inspect_ai_accuracy_schema,
    validate_ai_accuracy_headers,
)


def headers(model_count: int, ai_positions: list[int] | None = None) -> dict[str, int]:
    result: dict[str, int] = {}
    column = 1
    for position in range(1, model_count + 1):
        result[f"model-{position}反馈质量（作业质量）"] = column
        column += 1
    for position in ai_positions or []:
        result[f"模型{position}质检结论是否准确"] = column
        column += 1
        result[f"模型{position}判断原因"] = column
        column += 1
    return result


class AiAccuracySchemaTests(unittest.TestCase):
    def test_model_counts_are_dynamic(self) -> None:
        for count in (3, 4, 5):
            info = inspect_ai_accuracy_headers(headers(count, list(range(1, count + 1))))
            self.assertTrue(info["enabled"])
            self.assertEqual(info["model_count"], count)
            self.assertEqual(len(info["headers"]), count * 2)
            self.assertEqual(info["errors"], [])

    def test_no_ai_fields_disables_without_inventing_columns(self) -> None:
        info = inspect_ai_accuracy_headers(headers(4))
        self.assertFalse(info["enabled"])
        self.assertEqual(info["errors"], [])
        schema = inspect_ai_accuracy_schema(
            headers(4),
            headers(4, [1, 2, 3, 4]),
        )
        self.assertFalse(schema["errors"])

    def test_partial_fields_are_an_error(self) -> None:
        info = inspect_ai_accuracy_headers(headers(4, [1, 2, 3]))
        self.assertTrue(info["errors"])
        with self.assertRaises(RuntimeError):
            validate_ai_accuracy_headers(headers(4, [1, 2, 3]))

    def test_non_contiguous_or_extra_positions_are_an_error(self) -> None:
        non_contiguous = inspect_ai_accuracy_headers(headers(4, [1, 2, 4]))
        self.assertTrue(any("模型3" in error for error in non_contiguous["errors"]))
        extra = inspect_ai_accuracy_headers(headers(4, [1, 2, 3, 4, 5]))
        self.assertTrue(any("模型5" in error for error in extra["errors"]))

    def test_target_must_match_source_schema(self) -> None:
        source = headers(5, [1, 2, 3, 4, 5])
        target = headers(4, [1, 2, 3, 4])
        schema = inspect_ai_accuracy_schema(source, target)
        self.assertTrue(schema["errors"])
        self.assertTrue(any("目标表" in error for error in schema["errors"]))

    def test_target_without_fields_is_an_error_when_source_is_enabled(self) -> None:
        schema = inspect_ai_accuracy_schema(headers(3, [1, 2, 3]), headers(3))
        self.assertTrue(schema["errors"])
        self.assertTrue(any("目标表缺少" in error for error in schema["errors"]))


if __name__ == "__main__":
    unittest.main()
