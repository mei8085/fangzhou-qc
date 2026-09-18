from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.aiqc_supplement import (  # noqa: E402
    SupplementRecord,
    load_supplement_records,
    merge_audit_trajectory,
    merge_task_summary,
    new_audit_cache,
)


HEADERS = [
    "project_id",
    "task_id",
    "run_id",
    "task_title",
    "qc_task_status",
    "qc_task_quality",
    "qc_task_review_quality",
    "qc_task_settlement",
    "qc_task_is_dirty",
    "qc_task_dirty_labels",
    "qc_task_hitl",
    "qc_traj_status",
    "qc_traj_grade",
    "qc_traj_is_dirty",
    "qc_traj_dirty_labels",
    "qc_traj_res_detail",
    "qc_task_res_detail",
]


def supplement_row(run_id: int = 1001) -> list:
    detail = {
        "algorithm_version": "coding-trajectory-test",
        "feedback_quality": {"grade": "合格", "reason": "具体理由"},
        "dirty_labels": [],
        "trace_stats": {"n_tool_calls": 4},
    }
    return [
        387,
        1234,
        run_id,
        "测试任务",
        "success",
        "高",
        "合格",
        "予以结算：高质量",
        False,
        "[]",
        '["人工复审"]',
        "success",
        "合格",
        False,
        "[]",
        json.dumps(detail, ensure_ascii=False),
        json.dumps({"algorithm_version": "coding-task-test"}, ensure_ascii=False),
    ]


class AiqcSupplementTests(unittest.TestCase):
    def test_load_and_merge_missing_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "aiqc.xlsx"
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.append(HEADERS)
            worksheet.append(supplement_row())
            workbook.save(path)

            records = load_supplement_records(path, "1234")
            self.assertEqual(1, len(records))
            self.assertEqual("coding-trajectory-test", records[0].algorithm_version)

            audit = {
                "aiQc": {
                    "trajectoryResult": {
                        "id": 9,
                        "status": "exhausted",
                        "resultJson": {"reason": "provider_job_stuck"},
                    }
                }
            }
            updated, action = merge_audit_trajectory(audit, records[0])
            self.assertEqual("applied", action)
            result = updated["aiQc"]["trajectoryResult"]
            self.assertEqual("success", result["status"])
            self.assertEqual("合格", result["resultJson"]["FeedbackGrade"])
            self.assertEqual(9, result["id"])

    def test_complete_result_is_not_overwritten_by_default(self) -> None:
        record = SupplementRecord.from_row(tuple(supplement_row()), {h: i + 1 for i, h in enumerate(HEADERS)})
        audit = {
            "aiQc": {
                "trajectoryResult": {
                    "status": "success",
                    "resultJson": {"FeedbackGrade": "高质量"},
                }
            }
        }
        updated, action = merge_audit_trajectory(audit, record)
        self.assertEqual("skipped_complete", action)
        self.assertEqual(audit, updated)

    def test_task_summary_uses_task_level_fields(self) -> None:
        record = SupplementRecord.from_row(tuple(supplement_row()), {h: i + 1 for i, h in enumerate(HEADERS)})
        updated, action = merge_task_summary({"aiQc": {"status": "exhausted"}}, [record])
        self.assertEqual("applied", action)
        self.assertEqual("success", updated["aiQc"]["status"])
        self.assertEqual("高", updated["aiQc"]["taskQuality"])
        self.assertEqual("合格", updated["aiQc"]["expertEvaluationQuality"])
        self.assertEqual("manual_review", updated["aiQc"]["reviewRoute"])

    def test_missing_audit_can_be_created_from_supplement(self) -> None:
        record = SupplementRecord.from_row(tuple(supplement_row()), {h: i + 1 for i, h in enumerate(HEADERS)})
        audit = new_audit_cache(
            "1234",
            {"task_model_run_id": 1001, "platform": "urchin"},
            record,
        )
        self.assertEqual(1001, audit["taskModelRunId"])
        self.assertEqual("success", audit["aiQc"]["trajectoryResult"]["status"])
        self.assertEqual("合格", audit["aiQc"]["trajectoryResult"]["resultJson"]["FeedbackGrade"])


if __name__ == "__main__":
    unittest.main()
