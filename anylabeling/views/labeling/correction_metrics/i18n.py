"""Feature strings in the application's standard Qt translation catalog."""

import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP, QTranslator


CONTEXT = "CorrectionCost"
LANGUAGES = ("en_US", "zh_CN", "ja_JP", "ko_KR")

MESSAGES = {
    "title": QT_TRANSLATE_NOOP("CorrectionCost", "Correction Cost Statistics"),
    "need_image": QT_TRANSLATE_NOOP("CorrectionCost", "Open an image first."),
    "save_before_complete": QT_TRANSLATE_NOOP("CorrectionCost", "Save the current version before marking it complete."),
    "incomplete": QT_TRANSLATE_NOOP("CorrectionCost", "Correction cost records are incomplete."),
    "scope": QT_TRANSLATE_NOOP("CorrectionCost", "Scope"),
    "start": QT_TRANSLATE_NOOP("CorrectionCost", "Start recording"),
    "first": QT_TRANSLATE_NOOP("CorrectionCost", "First image"),
    "last": QT_TRANSLATE_NOOP("CorrectionCost", "Last image"),
    "all": QT_TRANSLATE_NOOP("CorrectionCost", "All"),
    "this": QT_TRANSLATE_NOOP("CorrectionCost", "Current image"),
    "image_total": QT_TRANSLATE_NOOP("CorrectionCost", "{count} images"),
    "scope_range": QT_TRANSLATE_NOOP("CorrectionCost", "{count} image(s): {first} … {last}"),
    "cancel": QT_TRANSLATE_NOOP("CorrectionCost", "Cancel"),
    "close": QT_TRANSLATE_NOOP("CorrectionCost", "Close"),
    "details": QT_TRANSLATE_NOOP("CorrectionCost", "Show details"),
    "hide_details": QT_TRANSLATE_NOOP("CorrectionCost", "Hide details"),
    "pause": QT_TRANSLATE_NOOP("CorrectionCost", "Pause timer"),
    "resume": QT_TRANSLATE_NOOP("CorrectionCost", "Resume timer"),
    "stop": QT_TRANSLATE_NOOP("CorrectionCost", "Stop recording"),
    "complete": QT_TRANSLATE_NOOP("CorrectionCost", "Finish round"),
    "continue": QT_TRANSLATE_NOOP("CorrectionCost", "Continue correction"),
    "review": QT_TRANSLATE_NOOP("CorrectionCost", "Start review"),
    "report": QT_TRANSLATE_NOOP("CorrectionCost", "Report"),
    "idle_keep": QT_TRANSLATE_NOOP("CorrectionCost", "Keep as review time"),
    "idle_exclude": QT_TRANSLATE_NOOP("CorrectionCost", "Exclude idle time"),
    "current_image": QT_TRANSLATE_NOOP("CorrectionCost", "Image"),
    "round": QT_TRANSLATE_NOOP("CorrectionCost", "Round"),
    "baseline": QT_TRANSLATE_NOOP("CorrectionCost", "Starting boxes"),
    "saved": QT_TRANSLATE_NOOP("CorrectionCost", "Saved result"),
    "draft": QT_TRANSLATE_NOOP("CorrectionCost", "Current draft"),
    "quality": QT_TRANSLATE_NOOP("CorrectionCost", "Quality assessment"),
    "processing": QT_TRANSLATE_NOOP("CorrectionCost", "Processing status"),
    "time": QT_TRANSLATE_NOOP("CorrectionCost", "In-app processing"),
    "seconds": QT_TRANSLATE_NOOP("CorrectionCost", "{seconds} s"),
    "timing": QT_TRANSLATE_NOOP("CorrectionCost", "Timer"),
    "operations": QT_TRANSLATE_NOOP("CorrectionCost", "Operations / touches / unique objects"),
    "integrity": QT_TRANSLATE_NOOP("CorrectionCost", "Record integrity"),
    "clean": QT_TRANSLATE_NOOP("CorrectionCost", "No recorded gaps"),
    "net": QT_TRANSLATE_NOOP("CorrectionCost", "Added {added} · Deleted {deleted} · Geometry {geometry_changed} · Class {class_changed}"),
    "unfinished": QT_TRANSLATE_NOOP("CorrectionCost", "In progress"),
    "processing-complete": QT_TRANSLATE_NOOP("CorrectionCost", "Completed"),
    "not-assessed": QT_TRANSLATE_NOOP("CorrectionCost", "Not assessed"),
    "unknown-existing": QT_TRANSLATE_NOOP("CorrectionCost", "Existing annotations, unknown source"),
    "replacement": QT_TRANSLATE_NOOP("CorrectionCost", "Replacement prediction"),
    "additive": QT_TRANSLATE_NOOP("CorrectionCost", "Appended prediction"),
    "correction": QT_TRANSLATE_NOOP("CorrectionCost", "Correction"),
    "working": QT_TRANSLATE_NOOP("CorrectionCost", "Processing"),
    "inactive": QT_TRANSLATE_NOOP("CorrectionCost", "Inactive"),
    "blocking_wait": QT_TRANSLATE_NOOP("CorrectionCost", "Waiting"),
    "not_ready": QT_TRANSLATE_NOOP("CorrectionCost", "Loading"),
    "paused": QT_TRANSLATE_NOOP("CorrectionCost", "Paused"),
    "closed": QT_TRANSLATE_NOOP("CorrectionCost", "Stopped"),
    "idle_note": QT_TRANSLATE_NOOP("CorrectionCost", "Pending idle: {seconds} s (included until confirmed)"),
    "report_title": QT_TRANSLATE_NOOP("CorrectionCost", "Correction Cost Report"),
    "refresh": QT_TRANSLATE_NOOP("CorrectionCost", "Refresh snapshot"),
    "snapshot": QT_TRANSLATE_NOOP("CorrectionCost", "Snapshot {stamp}"),
    "images": QT_TRANSLATE_NOOP("CorrectionCost", "Image rounds"),
    "classes": QT_TRANSLATE_NOOP("CorrectionCost", "Class changes"),
    "groups": QT_TRANSLATE_NOOP("CorrectionCost", "By density and model"),
    "current_only": QT_TRANSLATE_NOOP("CorrectionCost", "Current results only"),
    "search": QT_TRANSLATE_NOOP("CorrectionCost", "Search image, class or model"),
    "phase": QT_TRANSLATE_NOOP("CorrectionCost", "Stage"),
    "versions": QT_TRANSLATE_NOOP("CorrectionCost", "Model version"),
    "rounds": QT_TRANSLATE_NOOP("CorrectionCost", "Rounds"),
    "images_count": QT_TRANSLATE_NOOP("CorrectionCost", "Distinct images"),
    "counts": QT_TRANSLATE_NOOP("CorrectionCost", "{images} completed image(s) · {eligible}/{rounds} comparable rounds"),
    "excluded": QT_TRANSLATE_NOOP("CorrectionCost", "Excluded reasons"),
    "group_note": QT_TRANSLATE_NOOP("CorrectionCost", "Comparable saved rounds only. Density uses final rectangles. Sequential runs on the same image are dependent."),
    "prev": QT_TRANSLATE_NOOP("CorrectionCost", "Previous page"),
    "next": QT_TRANSLATE_NOOP("CorrectionCost", "Next page"),
    "page": QT_TRANSLATE_NOOP("CorrectionCost", "Page {page}/{pages} · {count} rows"),
    "selected_finish": QT_TRANSLATE_NOOP("CorrectionCost", "Finish selected rounds…"),
    "selected_confirm": QT_TRANSLATE_NOOP("CorrectionCost", "Mark only the following {count} saved round(s) complete?"),
    "snapshot_changed": QT_TRANSLATE_NOOP("CorrectionCost", "Revalidate revisions before applying. Changed or ineligible rows will be skipped."),
    "select_rows": QT_TRANSLATE_NOOP("CorrectionCost", "Select current saved rows on the Images tab."),
    "no_data": QT_TRANSLATE_NOOP("CorrectionCost", "No recorded image"),
    "export": QT_TRANSLATE_NOOP("CorrectionCost", "Export CSV…"),
    "dictionary": QT_TRANSLATE_NOOP("CorrectionCost", "Metric dictionary"),
    "loading": QT_TRANSLATE_NOOP("CorrectionCost", "Loading report…"),
    "exporting": QT_TRANSLATE_NOOP("CorrectionCost", "Writing CSV…"),
    "exported": QT_TRANSLATE_NOOP("CorrectionCost", "Exported {file}"),
    "error": QT_TRANSLATE_NOOP("CorrectionCost", "Operation failed"),
    "yes": QT_TRANSLATE_NOOP("CorrectionCost", "Yes"),
    "no": QT_TRANSLATE_NOOP("CorrectionCost", "No"),
    "current": QT_TRANSLATE_NOOP("CorrectionCost", "Current"),
    "completed": QT_TRANSLATE_NOOP("CorrectionCost", "Completed"),
    "baseline_count": QT_TRANSLATE_NOOP("CorrectionCost", "Initial boxes"),
    "ai_count": QT_TRANSLATE_NOOP("CorrectionCost", "AI boxes"),
    "final_count": QT_TRANSLATE_NOOP("CorrectionCost", "Saved boxes"),
    "added": QT_TRANSLATE_NOOP("CorrectionCost", "Added"),
    "deleted": QT_TRANSLATE_NOOP("CorrectionCost", "Deleted"),
    "geometry_changed": QT_TRANSLATE_NOOP("CorrectionCost", "Geometry edits"),
    "class_changed": QT_TRANSLATE_NOOP("CorrectionCost", "Class edits"),
    "transactions": QT_TRANSLATE_NOOP("CorrectionCost", "Operations"),
    "working_seconds": QT_TRANSLATE_NOOP("CorrectionCost", "Processing (s)"),
    "median_seconds": QT_TRANSLATE_NOOP("CorrectionCost", "Median seconds/round"),
    "seconds_per_100": QT_TRANSLATE_NOOP("CorrectionCost", "Seconds / 100 boxes"),
    "issues": QT_TRANSLATE_NOOP("CorrectionCost", "Limitations"),
    "image_path": QT_TRANSLATE_NOOP("CorrectionCost", "Image"),
    "model": QT_TRANSLATE_NOOP("CorrectionCost", "Model"),
    "model_version": QT_TRANSLATE_NOOP("CorrectionCost", "Model version"),
    "category_version": QT_TRANSLATE_NOOP("CorrectionCost", "Class vocabulary version"),
    "kind": QT_TRANSLATE_NOOP("CorrectionCost", "Metric"),
    "initial_class": QT_TRANSLATE_NOOP("CorrectionCost", "Initial class"),
    "final_class": QT_TRANSLATE_NOOP("CorrectionCost", "Final class"),
    "count": QT_TRANSLATE_NOOP("CorrectionCost", "Objects"),
    "denominator": QT_TRANSLATE_NOOP("CorrectionCost", "Denominator"),
    "origin": QT_TRANSLATE_NOOP("CorrectionCost", "Baseline source"),
    "modified_original": QT_TRANSLATE_NOOP("CorrectionCost", "Changed original boxes"),
    "modified_rate": QT_TRANSLATE_NOOP("CorrectionCost", "Changed / initial"),
    "density": QT_TRANSLATE_NOOP("CorrectionCost", "Final boxes per image"),
    "initial": QT_TRANSLATE_NOOP("CorrectionCost", "Initial"),
    "final": QT_TRANSLATE_NOOP("CorrectionCost", "Final"),
    "geometry": QT_TRANSLATE_NOOP("CorrectionCost", "Geometry"),
    "unsaved": QT_TRANSLATE_NOOP("CorrectionCost", "Unsaved"),
    "partial_scope": QT_TRANSLATE_NOOP("CorrectionCost", "Partial rectangle scope"),
    "unknown_source": QT_TRANSLATE_NOOP("CorrectionCost", "Unknown source"),
    "interrupted": QT_TRANSLATE_NOOP("CorrectionCost", "Interrupted timing"),
    "history": QT_TRANSLATE_NOOP("CorrectionCost", "Historical"),
    "idle_threshold": QT_TRANSLATE_NOOP("CorrectionCost", "Idle prompt after (s)"),
    # Collapsible current-image panel (design D7).
    "collapse": QT_TRANSLATE_NOOP("CorrectionCost", "Collapse"),
    "expand": QT_TRANSLATE_NOOP("CorrectionCost", "Expand"),
    "phase_review": QT_TRANSLATE_NOOP("CorrectionCost", "Review"),
    "unique_objects": QT_TRANSLATE_NOOP("CorrectionCost", "Unique objects"),
    "touches": QT_TRANSLATE_NOOP("CorrectionCost", "Touches"),
    "comparable": QT_TRANSLATE_NOOP("CorrectionCost", "Comparable"),
    "degraded": QT_TRANSLATE_NOOP("CorrectionCost", "Recording problem"),
    "idle_pending": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Idle time awaiting confirmation"
    ),
    "already_completed": QT_TRANSLATE_NOOP(
        "CorrectionCost", "This round is already complete."
    ),
    # Short record-integrity reasons; an unknown code is shown verbatim.
    "issue_storage_gap": QT_TRANSLATE_NOOP("CorrectionCost", "Statistics write gap"),
    "issue_unknown_origin": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Unknown source (disclosed only)"
    ),
    "issue_class_incomparable": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Class mapping not comparable"
    ),
    "issue_unsaved_result": QT_TRANSLATE_NOOP("CorrectionCost", "Result not saved"),
    "issue_shape_identity_conflict": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Object identity conflict"
    ),
    "issue_invalid_geometry": QT_TRANSLATE_NOOP("CorrectionCost", "Invalid geometry"),
    "issue_unknown_image_version": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Unknown image version"
    ),
    "issue_type_conversion": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Shape type conversion"
    ),
    "issue_interrupted_draft": QT_TRANSLATE_NOOP("CorrectionCost", "Interrupted draft"),
    "issue_external_annotation_change": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Annotations changed externally"
    ),
    "issue_image_content_changed": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Image content changed"
    ),
    "issue_observer_error": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Recording callback failed"
    ),
    "issue_unidentified_geometry": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Unidentified geometry edit"
    ),
    "issue_prediction_gap": QT_TRANSLATE_NOOP("CorrectionCost", "Prediction record gap"),
    # Correction cost report dialog (merged from report_dialog.py).
    "rounds_phases": QT_TRANSLATE_NOOP(
        "CorrectionCost",
        "Rounds {rounds} · correction {correction} · review {review}",
    ),
    "excluded_total": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Excluded rounds: {count}"
    ),
    "excluded_none": QT_TRANSLATE_NOOP("CorrectionCost", "Nothing excluded"),
    "image_count": QT_TRANSLATE_NOOP("CorrectionCost", "Images"),
    "unchanged": QT_TRANSLATE_NOOP("CorrectionCost", "Unchanged boxes"),
    "review_phase": QT_TRANSLATE_NOOP("CorrectionCost", "Review"),
    "export_images": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Image round details CSV…"
    ),
    "export_classes": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Class change details CSV…"
    ),
    "export_dictionary": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Metric dictionary CSV…"
    ),
    "export_cancelled": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Export cancelled; no file was written."
    ),
    "export_failed": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Export failed: {error}"
    ),
    "export_busy": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Wait for the current export to finish."
    ),
    "sort_hint": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Click a column header to sort."
    ),
    "reason_unfinished": QT_TRANSLATE_NOOP("CorrectionCost", "Round unfinished"),
    "reason_incomplete": QT_TRANSLATE_NOOP("CorrectionCost", "Record incomplete"),
    "reason_class_incomparable": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Class vocabulary not comparable"
    ),
    "reason_unsaved_result": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Saved result pending"
    ),
    "reason_unknown_image_version": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Image version unknown"
    ),
    "reason_shape_identity_conflict": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Duplicate object identity"
    ),
    "reason_invalid_geometry": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Invalid geometry"
    ),
    "reason_type_conversion": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Shape type converted"
    ),
    "reason_unobserved_content_change": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Unobserved content change"
    ),
    "reason_unidentified_geometry": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Unidentified geometry edit"
    ),
    "reason_storage_gap": QT_TRANSLATE_NOOP("CorrectionCost", "Storage gap"),
    "reason_reopened_round": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Round reopened"
    ),
    "reason_metrics_observer_error": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Statistics write failed"
    ),
    "reason_pending_checkpoint": QT_TRANSLATE_NOOP(
        "CorrectionCost", "Save checkpoint pending"
    ),
}


#: Raw record-integrity code -> short message key shown by the panel.
ISSUE_KEYS = {
    "partial-scope": "partial_scope",
    "unknown-origin": "issue_unknown_origin",
    "class-incomparable": "issue_class_incomparable",
    "unsaved-result": "issue_unsaved_result",
    "storage-gap": "issue_storage_gap",
    "shape-identity-conflict": "issue_shape_identity_conflict",
    "invalid-geometry": "issue_invalid_geometry",
    "unknown-image-version": "issue_unknown_image_version",
    "type-conversion": "issue_type_conversion",
    "interrupted-draft": "issue_interrupted_draft",
    "interrupted-time": "interrupted",
    "external-annotation-change": "issue_external_annotation_change",
    "image-content-changed": "issue_image_content_changed",
    "metrics-observer-error": "issue_observer_error",
    "unidentified-geometry": "issue_unidentified_geometry",
    "prediction-gap": "issue_prediction_gap",
}

#: Copy added after the catalogues were last compiled.  Every entry is also a
#: normal ``MESSAGES`` source for the lupdate/lrelease cycle; this table keeps
#: it translated in the meantime so a new panel never falls back to English.
#: An entry can be deleted once its .qm translation has been generated.
TRANSLATIONS = {
    "collapse": {
        "en_US": "Collapse",
        "zh_CN": "收起",
        "ja_JP": "折りたたむ",
        "ko_KR": "접기",
    },
    "expand": {
        "en_US": "Expand",
        "zh_CN": "展开",
        "ja_JP": "展開",
        "ko_KR": "펼치기",
    },
    "phase_review": {
        "en_US": "Review",
        "zh_CN": "复核",
        "ja_JP": "レビュー",
        "ko_KR": "검토",
    },
    "unique_objects": {
        "en_US": "Unique objects",
        "zh_CN": "去重对象",
        "ja_JP": "重複なしオブジェクト",
        "ko_KR": "중복 제거 개체",
    },
    "touches": {
        "en_US": "Touches",
        "zh_CN": "触达次数",
        "ja_JP": "接触回数",
        "ko_KR": "접촉 횟수",
    },
    "comparable": {
        "en_US": "Comparable",
        "zh_CN": "可完整比较",
        "ja_JP": "完全比較可",
        "ko_KR": "전체 비교 가능",
    },
    "degraded": {
        "en_US": "Recording problem",
        "zh_CN": "记录异常",
        "ja_JP": "記録エラー",
        "ko_KR": "기록 오류",
    },
    "idle_pending": {
        "en_US": "Idle time awaiting confirmation",
        "zh_CN": "空闲时间待确认",
        "ja_JP": "待機時間の確認待ち",
        "ko_KR": "대기 시간 확인 대기",
    },
    "already_completed": {
        "en_US": "This round is already complete.",
        "zh_CN": "本轮已完成。",
        "ja_JP": "このラウンドは既に完了しています。",
        "ko_KR": "이 라운드는 이미 완료되었습니다.",
    },
    "issue_storage_gap": {
        "en_US": "Statistics write gap",
        "zh_CN": "统计写入缺口",
        "ja_JP": "統計書き込み欠損",
        "ko_KR": "통계 쓰기 누락",
    },
    "issue_unknown_origin": {
        "en_US": "Unknown source (disclosed only)",
        "zh_CN": "来源未知（仅披露）",
        "ja_JP": "出所不明（開示のみ）",
        "ko_KR": "출처 불명(공개만)",
    },
    "issue_class_incomparable": {
        "en_US": "Class mapping not comparable",
        "zh_CN": "类别映射不可比",
        "ja_JP": "分類対応が比較不可",
        "ko_KR": "분류 매핑 비교 불가",
    },
    "issue_unsaved_result": {
        "en_US": "Result not saved",
        "zh_CN": "结果未保存",
        "ja_JP": "結果が未保存",
        "ko_KR": "결과 미저장",
    },
    "issue_shape_identity_conflict": {
        "en_US": "Object identity conflict",
        "zh_CN": "对象标识冲突",
        "ja_JP": "オブジェクトID競合",
        "ko_KR": "개체 식별자 충돌",
    },
    "issue_invalid_geometry": {
        "en_US": "Invalid geometry",
        "zh_CN": "几何数据非法",
        "ja_JP": "ジオメトリ不正",
        "ko_KR": "기하 데이터 오류",
    },
    "issue_unknown_image_version": {
        "en_US": "Unknown image version",
        "zh_CN": "图片版本未知",
        "ja_JP": "画像バージョン不明",
        "ko_KR": "이미지 버전 불명",
    },
    "issue_type_conversion": {
        "en_US": "Shape type conversion",
        "zh_CN": "形状类型转换",
        "ja_JP": "形状タイプ変換",
        "ko_KR": "도형 유형 변환",
    },
    "issue_interrupted_draft": {
        "en_US": "Interrupted draft",
        "zh_CN": "草稿中断",
        "ja_JP": "下書き中断",
        "ko_KR": "초안 중단",
    },
    "issue_external_annotation_change": {
        "en_US": "Annotations changed externally",
        "zh_CN": "标注被外部修改",
        "ja_JP": "外部で注釈が変更",
        "ko_KR": "외부에서 주석 변경됨",
    },
    "issue_image_content_changed": {
        "en_US": "Image content changed",
        "zh_CN": "图片内容已变化",
        "ja_JP": "画像内容が変更済み",
        "ko_KR": "이미지 내용 변경됨",
    },
    "issue_observer_error": {
        "en_US": "Recording callback failed",
        "zh_CN": "记录回调异常",
        "ja_JP": "記録コールバック異常",
        "ko_KR": "기록 콜백 오류",
    },
    "issue_unidentified_geometry": {
        "en_US": "Unidentified geometry edit",
        "zh_CN": "无法识别几何修改",
        "ja_JP": "ジオメトリ変更を特定できず",
        "ko_KR": "기하 수정 식별 불가",
    },
    "issue_prediction_gap": {
        "en_US": "Prediction record gap",
        "zh_CN": "预测记录缺口",
        "ja_JP": "予測記録の欠損",
        "ko_KR": "예측 기록 누락",
    },
    "rounds_phases": {
        "en_US": "Rounds {rounds} · correction {correction} · review {review}",
        "zh_CN": "轮次 {rounds} · 修正 {correction} · 复核 {review}",
        "ja_JP": "ラウンド {rounds} · 修正 {correction} · レビュー {review}",
        "ko_KR": "라운드 {rounds} · 수정 {correction} · 검토 {review}",
    },
    "excluded_total": {
        "en_US": "Excluded rounds: {count}",
        "zh_CN": "已排除轮次：{count}",
        "ja_JP": "除外ラウンド：{count}",
        "ko_KR": "제외된 라운드: {count}",
    },
    "excluded_none": {
        "en_US": "Nothing excluded",
        "zh_CN": "没有排除项",
        "ja_JP": "除外はありません",
        "ko_KR": "제외 항목 없음",
    },
    "image_count": {
        "en_US": "Images",
        "zh_CN": "图片数",
        "ja_JP": "画像数",
        "ko_KR": "이미지 수",
    },
    "unchanged": {
        "en_US": "Unchanged boxes",
        "zh_CN": "未变框数",
        "ja_JP": "未変更ボックス",
        "ko_KR": "변경 없는 박스",
    },
    "review_phase": {
        "en_US": "Review",
        "zh_CN": "复核",
        "ja_JP": "レビュー",
        "ko_KR": "검토",
    },
    "export_images": {
        "en_US": "Image round details CSV…",
        "zh_CN": "图片轮次明细 CSV…",
        "ja_JP": "画像ラウンド明細 CSV…",
        "ko_KR": "이미지 라운드 상세 CSV…",
    },
    "export_classes": {
        "en_US": "Class change details CSV…",
        "zh_CN": "类别变化明细 CSV…",
        "ja_JP": "クラス変更明細 CSV…",
        "ko_KR": "클래스 변경 상세 CSV…",
    },
    "export_dictionary": {
        "en_US": "Metric dictionary CSV…",
        "zh_CN": "指标字典 CSV…",
        "ja_JP": "指標辞書 CSV…",
        "ko_KR": "지표 사전 CSV…",
    },
    "export_cancelled": {
        "en_US": "Export cancelled; no file was written.",
        "zh_CN": "导出已取消，未写入文件。",
        "ja_JP": "エクスポートを中止しました。ファイルは書き込まれていません。",
        "ko_KR": "내보내기를 취소했습니다. 파일을 쓰지 않았습니다.",
    },
    "export_failed": {
        "en_US": "Export failed: {error}",
        "zh_CN": "导出失败：{error}",
        "ja_JP": "エクスポートに失敗しました：{error}",
        "ko_KR": "내보내기 실패: {error}",
    },
    "export_busy": {
        "en_US": "Wait for the current export to finish.",
        "zh_CN": "请等待当前导出完成。",
        "ja_JP": "現在のエクスポート完了をお待ちください。",
        "ko_KR": "현재 내보내기가 끝날 때까지 기다리세요.",
    },
    "sort_hint": {
        "en_US": "Click a column header to sort.",
        "zh_CN": "点击列标题排序。",
        "ja_JP": "列ヘッダーをクリックして並べ替えます。",
        "ko_KR": "열 머리글을 클릭해 정렬합니다.",
    },
    "reason_unfinished": {
        "en_US": "Round unfinished",
        "zh_CN": "轮次未完成",
        "ja_JP": "ラウンド未完了",
        "ko_KR": "라운드 미완료",
    },
    "reason_incomplete": {
        "en_US": "Record incomplete",
        "zh_CN": "记录不完整",
        "ja_JP": "記録が不完全",
        "ko_KR": "기록 불완전",
    },
    "reason_class_incomparable": {
        "en_US": "Class vocabulary not comparable",
        "zh_CN": "类别体系不可比",
        "ja_JP": "クラス体系が比較不可",
        "ko_KR": "클래스 체계 비교 불가",
    },
    "reason_unsaved_result": {
        "en_US": "Saved result pending",
        "zh_CN": "保存结果待确认",
        "ja_JP": "保存結果の確定待ち",
        "ko_KR": "저장 결과 대기 중",
    },
    "reason_unknown_image_version": {
        "en_US": "Image version unknown",
        "zh_CN": "图片版本未知",
        "ja_JP": "画像バージョン不明",
        "ko_KR": "이미지 버전 알 수 없음",
    },
    "reason_shape_identity_conflict": {
        "en_US": "Duplicate object identity",
        "zh_CN": "对象标识重复",
        "ja_JP": "オブジェクト識別子の重複",
        "ko_KR": "객체 식별자 중복",
    },
    "reason_invalid_geometry": {
        "en_US": "Invalid geometry",
        "zh_CN": "几何数据无效",
        "ja_JP": "無効なジオメトリ",
        "ko_KR": "잘못된 기하 정보",
    },
    "reason_type_conversion": {
        "en_US": "Shape type converted",
        "zh_CN": "形状类型已转换",
        "ja_JP": "図形タイプ変換",
        "ko_KR": "도형 유형 변환",
    },
    "reason_unobserved_content_change": {
        "en_US": "Unobserved content change",
        "zh_CN": "未观测到的内容变化",
        "ja_JP": "未観測の内容変更",
        "ko_KR": "관측되지 않은 내용 변경",
    },
    "reason_unidentified_geometry": {
        "en_US": "Unidentified geometry edit",
        "zh_CN": "无法识别的几何编辑",
        "ja_JP": "特定不能なジオメトリ編集",
        "ko_KR": "식별되지 않은 기하 편집",
    },
    "reason_storage_gap": {
        "en_US": "Storage gap",
        "zh_CN": "存储缺口",
        "ja_JP": "保存の欠落",
        "ko_KR": "저장 공백",
    },
    "reason_reopened_round": {
        "en_US": "Round reopened",
        "zh_CN": "轮次已重新打开",
        "ja_JP": "ラウンド再開",
        "ko_KR": "라운드 다시 열림",
    },
    "reason_metrics_observer_error": {
        "en_US": "Statistics write failed",
        "zh_CN": "统计写入失败",
        "ja_JP": "統計の書き込み失敗",
        "ko_KR": "통계 쓰기 실패",
    },
    "reason_pending_checkpoint": {
        "en_US": "Save checkpoint pending",
        "zh_CN": "保存检查点待确认",
        "ja_JP": "保存チェックポイント待ち",
        "ko_KR": "저장 체크포인트 대기",
    },
}


def _translations_dir():
    return Path(__file__).resolve().parents[3] / "resources" / "translations"


@lru_cache(maxsize=4)
def _catalog(locale):
    translator = QTranslator()
    resource = f":/languages/translations/{locale}.qm"
    if not translator.load(resource):
        path = Path(__file__).resolve().parents[3] / "resources" / "translations"
        translator.load(str(path / (locale + ".qm")))
    return translator


@lru_cache(maxsize=4)
def _table(language):
    """Return {source: translation} of this feature from one .ts catalogue.

    The compiled .qm is the runtime source of truth; this fallback keeps
    non-ASCII sources working, which PyQt6 cannot pass to the C++ overload.
    """
    try:
        root = ET.parse(_translations_dir() / (language + ".ts")).getroot()
    except (OSError, ET.ParseError):
        return {}
    messages = {}
    for context in root.findall("context"):
        if context.findtext("name") != CONTEXT:
            continue
        for message in context.findall("message"):
            translation = message.find("translation")
            text = translation.text if translation is not None else None
            source = message.findtext("source")
            if source and text:
                messages[source] = text
    return messages


def _catalog_text(language, source):
    try:
        return _catalog(language).translate(CONTEXT, source) or ""
    except UnicodeError:
        # PyQt6 rejects non-ASCII source text in QTranslator.translate().
        return ""


def _localised(key, source, language):
    table = TRANSLATIONS.get(key)
    if table and language:
        text = table.get(language)
        if text:
            return text
    if language in LANGUAGES:
        text = _catalog_text(language, source) or _table(language).get(source)
        if text:
            return text
    return QCoreApplication.translate(CONTEXT, source) or source


def tr(key, language=None, **values):
    source = MESSAGES.get(key, key)
    message = _localised(key, source, language)
    return message.format(**values) if values else message


def tr_issue(code, language=None):
    """Short localised reason for a record-integrity code."""
    key = ISSUE_KEYS.get(code)
    if key is None:
        candidate = "issue_" + str(code).replace("-", "_")
        key = candidate if candidate in MESSAGES else None
    return tr(key, language) if key else str(code)
