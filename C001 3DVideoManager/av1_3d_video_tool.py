# -*- coding: utf-8 -*-
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QActionGroup,
)


APP_NAME = "AV1 3D Video Batch Converter"
APP_DIR = Path(__file__).resolve().parent
REPORTS_DIR_NAME = "transfer_reports"
LANGUAGES = {
    "zh": "中文",
    "ja": "日本語",
    "en": "English",
}
TRANSLATIONS = {
    "zh": {
        "menu_language": "语言",
        "lang_zh": "中文",
        "lang_ja": "日本語",
        "lang_en": "English",
        "file_management": "文件管理",
        "add_video": "添加视频",
        "add_folder": "添加文件夹",
        "recursive_scan": "递归扫描",
        "operations": "操作",
        "start_detect": "开始检测",
        "start_convert": "开始转换",
        "stop_convert": "停止转换",
        "clear_list": "清空列表",
        "output_dir": "输出目录",
        "choose_output_dir": "选择输出目录",
        "stats_info": "统计信息",
        "video_list": "视频列表",
        "table_hint": "选中行转换选中视频；未选中则转换全部已检测视频",
        "h_filename": "文件名",
        "h_3d_type": "3D类型",
        "h_codec": "编码",
        "h_resolution": "分辨率",
        "h_fps": "帧率",
        "h_duration": "时长",
        "h_size": "大小",
        "h_status": "状态",
        "log": "日志",
        "video_details": "视频详情",
        "stereo_fix": "3D 类型修正",
        "apply_selected": "应用到选中",
        "av1_settings": "AV1 转码设置",
        "encoder": "编码器",
        "size_mode": "尺寸模式",
        "custom_width": "自定义宽",
        "crf": "CRF",
        "preserve_bitrate": "保留源视频码率",
        "preset": "Preset",
        "audio": "音频",
        "overwrite": "允许覆盖同名输出文件",
        "status_ready": "就绪",
        "status_detecting": "正在检测视频信息...",
        "status_detect_done": "检测完成",
        "status_converting": "正在转换...",
        "status_convert_done": "转换结束",
        "context_remove": "从列表删除",
        "context_delete": "永久删除文件...",
        "detail_select_video": "请选择一个视频查看详细信息。",
        "dlg_ffmpeg_unavailable": "FFmpeg 不可用",
        "dlg_cannot_detect": "无法检测",
        "dlg_ffprobe_missing": "找不到 ffprobe。",
        "dlg_cannot_convert": "无法转换",
        "dlg_ffmpeg_missing": "找不到 ffmpeg 或 ffprobe。",
        "dlg_no_convertible": "没有可转换文件",
        "dlg_no_convertible_msg": "请先检测视频，再开始转换。",
        "dlg_missing_encoder": "缺少编码器",
        "dlg_missing_encoder_msg": "当前 FFmpeg 没有可用 AV1 编码器。",
        "dlg_converting": "正在转换",
        "dlg_converting_msg": "请先停止或等待转换完成。",
        "dlg_task_running": "任务正在运行",
        "dlg_task_remove_msg": "请先等待检测/转换结束，再删除列表项。",
        "dlg_task_delete_msg": "请先等待检测/转换结束，再永久删除文件。",
        "dlg_confirm_delete": "确认永久删除",
        "dlg_confirm_delete_intro": "确定要从磁盘永久删除这些源视频文件吗？",
        "dlg_confirm_delete_count": "数量",
        "dlg_confirm_delete_suffix": "文件会被直接删除，这个操作不会进入本工具的撤销队列。",
        "dlg_partial_delete_failed": "部分文件删除失败",
        "dlg_no_video_selected": "未选择视频",
        "dlg_no_video_selected_msg": "请先选择要修正的已检测视频。",
        "dlg_still_converting": "正在转换",
        "dlg_still_converting_msg": "转换仍在运行，确定要退出吗？",
        "file": "文件",
        "stereo_type": "3D类型",
        "input_video": "输入视频",
        "output_video": "输出视频",
        "codec": "编码",
        "profile": "Profile",
        "resolution": "分辨率",
        "sar_dar": "SAR / DAR",
        "pix_fmt": "像素格式",
        "fps": "帧率",
        "bitrate": "码率",
        "duration": "时长",
        "audio_label": "音频",
        "subtitle_streams": "字幕流",
        "transfer": "报告",
        "error": "错误",
        "stat_total": "视频总数",
        "stat_detected": "已检测",
        "stat_waiting": "等待转换",
        "stat_converting": "转换中",
        "stat_done": "已完成",
        "stat_failed": "失败",
        "status_pending": "待检测",
        "status_detected": "已检测",
        "status_waiting": "等待转换",
        "status_converting_short": "转换中",
        "status_done": "已完成",
        "status_failed": "失败",
        "status_stopped": "已停止",
        "stereo_auto": "自动重新判断",
        "stereo_unknown": "3D 未知",
        "res_keep": "保持原尺寸",
        "res_auto_1080": "自动 1080：2D 转 1080p，SBS 保持宽度",
        "res_height_1080": "高度转 1080（宽度保持）",
        "res_sbs_height_1080": "3D SBS 高度转 1080（宽度保持）",
        "res_2d_1080": "普通 2D 转 1920x1080",
        "res_custom": "自定义宽高",
        "audio_copy": "音频 copy",
        "audio_opus": "转 Opus 160k",
        "audio_aac": "转 AAC 192k",
        "encoder_not_found": "未找到 AV1 编码器",
        "select_video_files": "选择视频文件",
        "select_video_folder": "选择视频文件夹",
        "select_output_folder": "选择输出目录",
        "more_files": "以及另外 {count} 个文件",
        "analysis_section": "编码/质量判断",
        "effective_bitrate": "有效视频码率",
        "bitrate_source": "码率来源",
        "bpppf": "Bits/(Pixel*Frame)",
        "encoder_settings": "编码器设置",
        "encoder_not_recorded": "未在元数据中发现 CRF/QP/Preset",
        "source_quality": "片源质量估计",
        "quality_note": "基于码率、分辨率、帧率、编码效率的启发式估计，不等于真实母版质量。",
        "processing_judgement": "降噪/锐化判断",
        "processing_not_detectable": "未发现可读滤镜痕迹；无法仅凭成品视频可靠判断。",
        "processing_possible": "元数据中发现可能的处理痕迹",
        "quality_very_high": "很高",
        "quality_high": "高",
        "quality_medium": "中等",
        "quality_low": "偏低",
        "quality_very_low": "很低",
        "quality_unknown": "未知",
        "confidence_low": "低可信",
        "confidence_medium": "中等可信",
        "confidence_high": "高可信",
        "source_video_stream": "视频流字段",
        "source_format_estimate": "容器码率估算",
        "source_file_size_estimate": "文件大小/时长估算",
        "source_unknown": "未知",
    },
    "ja": {
        "menu_language": "言語",
        "lang_zh": "中文",
        "lang_ja": "日本語",
        "lang_en": "English",
        "file_management": "ファイル管理",
        "add_video": "動画を追加",
        "add_folder": "フォルダーを追加",
        "recursive_scan": "再帰スキャン",
        "operations": "操作",
        "start_detect": "検出開始",
        "start_convert": "変換開始",
        "stop_convert": "変換停止",
        "clear_list": "リストをクリア",
        "output_dir": "出力先",
        "choose_output_dir": "出力先を選択",
        "stats_info": "統計情報",
        "video_list": "動画リスト",
        "table_hint": "選択行を変換；未選択なら検出済み動画をすべて変換",
        "h_filename": "ファイル名",
        "h_3d_type": "3D種別",
        "h_codec": "コーデック",
        "h_resolution": "解像度",
        "h_fps": "FPS",
        "h_duration": "長さ",
        "h_size": "サイズ",
        "h_status": "状態",
        "log": "ログ",
        "video_details": "動画詳細",
        "stereo_fix": "3D 種別修正",
        "apply_selected": "選択に適用",
        "av1_settings": "AV1 変換設定",
        "encoder": "エンコーダ",
        "size_mode": "サイズ設定",
        "custom_width": "カスタム幅",
        "crf": "CRF",
        "preserve_bitrate": "元動画ビットレートを保持",
        "preset": "Preset",
        "audio": "音声",
        "overwrite": "同名出力ファイルを上書き",
        "status_ready": "準備完了",
        "status_detecting": "動画情報を検出中...",
        "status_detect_done": "検出完了",
        "status_converting": "変換中...",
        "status_convert_done": "変換終了",
        "context_remove": "リストから削除",
        "context_delete": "ファイルを完全に削除...",
        "detail_select_video": "詳細を見る動画を選択してください。",
        "dlg_ffmpeg_unavailable": "FFmpeg が利用できません",
        "dlg_cannot_detect": "検出できません",
        "dlg_ffprobe_missing": "ffprobe が見つかりません。",
        "dlg_cannot_convert": "変換できません",
        "dlg_ffmpeg_missing": "ffmpeg または ffprobe が見つかりません。",
        "dlg_no_convertible": "変換できるファイルがありません",
        "dlg_no_convertible_msg": "先に動画を検出してから変換してください。",
        "dlg_missing_encoder": "エンコーダ不足",
        "dlg_missing_encoder_msg": "現在の FFmpeg には利用可能な AV1 エンコーダがありません。",
        "dlg_converting": "変換中",
        "dlg_converting_msg": "先に変換を停止するか、完了を待ってください。",
        "dlg_task_running": "タスク実行中",
        "dlg_task_remove_msg": "検出/変換が終わってからリスト項目を削除してください。",
        "dlg_task_delete_msg": "検出/変換が終わってからファイルを完全削除してください。",
        "dlg_confirm_delete": "完全削除の確認",
        "dlg_confirm_delete_intro": "これらの元動画ファイルをディスクから完全に削除しますか？",
        "dlg_confirm_delete_count": "数量",
        "dlg_confirm_delete_suffix": "ファイルは直接削除され、このツール内では元に戻せません。",
        "dlg_partial_delete_failed": "一部のファイル削除に失敗しました",
        "dlg_no_video_selected": "動画が選択されていません",
        "dlg_no_video_selected_msg": "修正する検出済み動画を選択してください。",
        "dlg_still_converting": "変換中",
        "dlg_still_converting_msg": "変換がまだ実行中です。終了してもよろしいですか？",
        "file": "ファイル",
        "stereo_type": "3D種別",
        "input_video": "入力動画",
        "output_video": "出力動画",
        "codec": "コーデック",
        "profile": "Profile",
        "resolution": "解像度",
        "sar_dar": "SAR / DAR",
        "pix_fmt": "ピクセル形式",
        "fps": "FPS",
        "bitrate": "ビットレート",
        "duration": "長さ",
        "audio_label": "音声",
        "subtitle_streams": "字幕ストリーム",
        "transfer": "レポート",
        "error": "エラー",
        "stat_total": "動画総数",
        "stat_detected": "検出済み",
        "stat_waiting": "変換待ち",
        "stat_converting": "変換中",
        "stat_done": "完了",
        "stat_failed": "失敗",
        "status_pending": "未検出",
        "status_detected": "検出済み",
        "status_waiting": "変換待ち",
        "status_converting_short": "変換中",
        "status_done": "完了",
        "status_failed": "失敗",
        "status_stopped": "停止済み",
        "stereo_auto": "自動判定",
        "stereo_unknown": "3D 不明",
        "res_keep": "元サイズを保持",
        "res_auto_1080": "自動 1080：2D は 1080p、SBS は幅を保持",
        "res_height_1080": "高さを 1080 に変更（幅保持）",
        "res_sbs_height_1080": "3D SBS 高さを 1080 に変更（幅保持）",
        "res_2d_1080": "通常 2D を 1920x1080 に変換",
        "res_custom": "カスタム幅/高さ",
        "audio_copy": "音声 copy",
        "audio_opus": "Opus 160k に変換",
        "audio_aac": "AAC 192k に変換",
        "encoder_not_found": "AV1 エンコーダが見つかりません",
        "select_video_files": "動画ファイルを選択",
        "select_video_folder": "動画フォルダーを選択",
        "select_output_folder": "出力先を選択",
        "more_files": "ほか {count} 個のファイル",
        "analysis_section": "エンコード/品質判定",
        "effective_bitrate": "有効動画ビットレート",
        "bitrate_source": "ビットレート元",
        "bpppf": "Bits/(Pixel*Frame)",
        "encoder_settings": "エンコーダ設定",
        "encoder_not_recorded": "メタデータに CRF/QP/Preset は見つかりません",
        "source_quality": "ソース品質推定",
        "quality_note": "ビットレート、解像度、フレームレート、コーデック効率に基づく推定で、実際のマスター品質とは限りません。",
        "processing_judgement": "ノイズ除去/シャープ化判定",
        "processing_not_detectable": "読み取れるフィルター痕跡は見つかりません。完成動画だけでは確実に判定できません。",
        "processing_possible": "メタデータに処理痕跡の可能性があります",
        "quality_very_high": "非常に高い",
        "quality_high": "高い",
        "quality_medium": "中程度",
        "quality_low": "低め",
        "quality_very_low": "非常に低い",
        "quality_unknown": "不明",
        "confidence_low": "低信頼",
        "confidence_medium": "中信頼",
        "confidence_high": "高信頼",
        "source_video_stream": "動画ストリーム項目",
        "source_format_estimate": "コンテナビットレート推定",
        "source_file_size_estimate": "ファイルサイズ/長さから推定",
        "source_unknown": "不明",
    },
    "en": {
        "menu_language": "Language",
        "lang_zh": "中文",
        "lang_ja": "日本語",
        "lang_en": "English",
        "file_management": "File Management",
        "add_video": "Add Videos",
        "add_folder": "Add Folder",
        "recursive_scan": "Recursive Scan",
        "operations": "Actions",
        "start_detect": "Scan",
        "start_convert": "Convert",
        "stop_convert": "Stop",
        "clear_list": "Clear List",
        "output_dir": "Output Folder",
        "choose_output_dir": "Choose Output Folder",
        "stats_info": "Stats",
        "video_list": "Video List",
        "table_hint": "Selected rows convert selected videos; no selection converts all scanned videos",
        "h_filename": "File Name",
        "h_3d_type": "3D Type",
        "h_codec": "Codec",
        "h_resolution": "Resolution",
        "h_fps": "FPS",
        "h_duration": "Duration",
        "h_size": "Size",
        "h_status": "Status",
        "log": "Log",
        "video_details": "Video Details",
        "stereo_fix": "3D Type Override",
        "apply_selected": "Apply To Selected",
        "av1_settings": "AV1 Settings",
        "encoder": "Encoder",
        "size_mode": "Size Mode",
        "custom_width": "Custom Width",
        "crf": "CRF",
        "preserve_bitrate": "Preserve source bitrate",
        "preset": "Preset",
        "audio": "Audio",
        "overwrite": "Overwrite existing output files",
        "status_ready": "Ready",
        "status_detecting": "Scanning video info...",
        "status_detect_done": "Scan complete",
        "status_converting": "Converting...",
        "status_convert_done": "Conversion finished",
        "context_remove": "Remove From List",
        "context_delete": "Delete File Permanently...",
        "detail_select_video": "Select a video to view details.",
        "dlg_ffmpeg_unavailable": "FFmpeg Unavailable",
        "dlg_cannot_detect": "Cannot Scan",
        "dlg_ffprobe_missing": "ffprobe was not found.",
        "dlg_cannot_convert": "Cannot Convert",
        "dlg_ffmpeg_missing": "ffmpeg or ffprobe was not found.",
        "dlg_no_convertible": "No Convertible Files",
        "dlg_no_convertible_msg": "Scan videos before starting conversion.",
        "dlg_missing_encoder": "Missing Encoder",
        "dlg_missing_encoder_msg": "This FFmpeg build has no available AV1 encoder.",
        "dlg_converting": "Converting",
        "dlg_converting_msg": "Stop conversion or wait for it to finish first.",
        "dlg_task_running": "Task Running",
        "dlg_task_remove_msg": "Wait for scanning/conversion to finish before removing list items.",
        "dlg_task_delete_msg": "Wait for scanning/conversion to finish before permanently deleting files.",
        "dlg_confirm_delete": "Confirm Permanent Delete",
        "dlg_confirm_delete_intro": "Permanently delete these source video files from disk?",
        "dlg_confirm_delete_count": "Count",
        "dlg_confirm_delete_suffix": "Files will be deleted directly and cannot be undone inside this tool.",
        "dlg_partial_delete_failed": "Some Files Could Not Be Deleted",
        "dlg_no_video_selected": "No Video Selected",
        "dlg_no_video_selected_msg": "Select scanned videos before overriding the 3D type.",
        "dlg_still_converting": "Converting",
        "dlg_still_converting_msg": "Conversion is still running. Exit anyway?",
        "file": "File",
        "stereo_type": "3D Type",
        "input_video": "Input Video",
        "output_video": "Output Video",
        "codec": "Codec",
        "profile": "Profile",
        "resolution": "Resolution",
        "sar_dar": "SAR / DAR",
        "pix_fmt": "Pixel Format",
        "fps": "FPS",
        "bitrate": "Bitrate",
        "duration": "Duration",
        "audio_label": "Audio",
        "subtitle_streams": "Subtitle Streams",
        "transfer": "Report",
        "error": "Error",
        "stat_total": "Total Videos",
        "stat_detected": "Scanned",
        "stat_waiting": "Waiting",
        "stat_converting": "Converting",
        "stat_done": "Done",
        "stat_failed": "Failed",
        "status_pending": "Pending Scan",
        "status_detected": "Scanned",
        "status_waiting": "Waiting",
        "status_converting_short": "Converting",
        "status_done": "Done",
        "status_failed": "Failed",
        "status_stopped": "Stopped",
        "stereo_auto": "Auto Detect Again",
        "stereo_unknown": "3D Unknown",
        "res_keep": "Keep Original Size",
        "res_auto_1080": "Auto 1080: 2D to 1080p, keep SBS width",
        "res_height_1080": "Height to 1080 (keep width)",
        "res_sbs_height_1080": "3D SBS height to 1080 (keep width)",
        "res_2d_1080": "2D to 1920x1080",
        "res_custom": "Custom Width/Height",
        "audio_copy": "Audio copy",
        "audio_opus": "Convert to Opus 160k",
        "audio_aac": "Convert to AAC 192k",
        "encoder_not_found": "No AV1 encoder found",
        "select_video_files": "Select Video Files",
        "select_video_folder": "Select Video Folder",
        "select_output_folder": "Choose Output Folder",
        "more_files": "{count} more files",
        "analysis_section": "Encoding / Quality Judgement",
        "effective_bitrate": "Effective Video Bitrate",
        "bitrate_source": "Bitrate Source",
        "bpppf": "Bits/(Pixel*Frame)",
        "encoder_settings": "Encoder Settings",
        "encoder_not_recorded": "No CRF/QP/Preset found in metadata",
        "source_quality": "Source Quality Estimate",
        "quality_note": "Heuristic estimate from bitrate, resolution, frame rate, and codec efficiency; not proof of master quality.",
        "processing_judgement": "Denoise / Sharpen Judgement",
        "processing_not_detectable": "No readable filter trace found; cannot reliably infer this from the finished video alone.",
        "processing_possible": "Possible processing trace found in metadata",
        "quality_very_high": "Very High",
        "quality_high": "High",
        "quality_medium": "Medium",
        "quality_low": "Low",
        "quality_very_low": "Very Low",
        "quality_unknown": "Unknown",
        "confidence_low": "Low confidence",
        "confidence_medium": "Medium confidence",
        "confidence_high": "High confidence",
        "source_video_stream": "Video stream field",
        "source_format_estimate": "Container bitrate estimate",
        "source_file_size_estimate": "File size / duration estimate",
        "source_unknown": "Unknown",
    },
}
STATUS_KEYS = {
    "待检测": "status_pending",
    "已检测": "status_detected",
    "等待转换": "status_waiting",
    "转换中": "status_converting_short",
    "已完成": "status_done",
    "失败": "status_failed",
    "已停止": "status_stopped",
}
STEREO_TEXT_KEYS = {
    "自动重新判断": "stereo_auto",
    "3D 未知": "stereo_unknown",
}
VIDEO_EXTENSIONS = {
    ".3gp",
    ".avi",
    ".flv",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ts",
    ".webm",
    ".wmv",
}


@dataclass
class VideoInfo:
    path: Path
    probe: dict[str, Any]
    video: dict[str, Any]
    audio_streams: list[dict[str, Any]]
    subtitle_streams: list[dict[str, Any]]
    detected_3d_type: str
    analysis: dict[str, Any]


@dataclass
class ConvertSettings:
    output_dir: Path
    encoder: str
    preserve_bitrate: bool
    resolution_mode: str
    custom_width: int
    custom_height: int
    crf: int
    preset: int
    audio_mode: str
    overwrite: bool


def _is_windows_system_dir(path: Path) -> bool:
    if os.name != "nt":
        return False
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    normalized = str(path).rstrip("\\/").casefold()
    return normalized in {
        str(system_root).rstrip("\\/").casefold(),
        str(system_root / "System32").rstrip("\\/").casefold(),
    }


def launch_base_dir() -> Path:
    try:
        cwd = Path.cwd()
    except OSError:
        return APP_DIR
    if _is_windows_system_dir(cwd):
        return APP_DIR
    return cwd


def default_output_dir() -> Path:
    return (launch_base_dir() / "converted").resolve()


def format_command_for_log(command: list[str]) -> str:
    parts = [str(part) for part in command]
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def short_log_line(line: str, limit: int = 240) -> str:
    text = line.replace("\r", "\\r").replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def find_executable(name: str) -> str:
    exe = shutil.which(name)
    if not exe:
        raise RuntimeError(f"找不到 {name}，请安装 FFmpeg 并加入 PATH。")
    return exe


def run_json(cmd: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return json.loads(result.stdout)


def probe_video(ffprobe: str, path: Path) -> dict[str, Any]:
    return run_json(
        [
            ffprobe,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ]
    )


def first_video_stream(probe: dict[str, Any]) -> dict[str, Any]:
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    raise ValueError("没有找到视频流")


def video_stream_summary(probe: dict[str, Any]) -> dict[str, Any]:
    video = first_video_stream(probe)
    fields = [
        "index",
        "codec_name",
        "codec_long_name",
        "profile",
        "level",
        "width",
        "height",
        "coded_width",
        "coded_height",
        "sample_aspect_ratio",
        "display_aspect_ratio",
        "pix_fmt",
        "field_order",
        "r_frame_rate",
        "avg_frame_rate",
        "time_base",
        "start_time",
        "duration",
        "bit_rate",
        "nb_frames",
        "color_range",
        "color_space",
        "color_transfer",
        "color_primaries",
        "chroma_location",
    ]
    return {field: video.get(field) for field in fields if video.get(field) is not None}


def markdown_escape(value: Any) -> str:
    text = "-" if value in {None, ""} else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def markdown_row(label: str, left: Any, right: Any) -> str:
    return f"| {markdown_escape(label)} | {markdown_escape(left)} | {markdown_escape(right)} |"


def reports_dir_for(output_dir: Path) -> Path:
    return output_dir / REPORTS_DIR_NAME


def report_path_for(output_path: Path) -> Path:
    return reports_dir_for(output_path.parent) / f"{output_path.stem}.transfer.md"


def conversion_setting_label(settings: ConvertSettings) -> str:
    return (
        f"encoder={settings.encoder}, preserve_bitrate={settings.preserve_bitrate}, crf={settings.crf}, preset={settings.preset}, "
        f"resolution_mode={report_resolution_mode(settings.resolution_mode)}, "
        f"audio={report_audio_mode(settings.audio_mode)}"
    )


def write_transfer_markdown(
    input_info: "VideoInfo",
    output_probe: dict[str, Any],
    output_path: Path,
    settings: ConvertSettings,
) -> Path:
    output_video = first_video_stream(output_probe)
    output_audio_streams = [s for s in output_probe.get("streams", []) if s.get("codec_type") == "audio"]
    output_analysis = analyze_video_info(output_path, output_probe, output_video, output_audio_streams)
    input_video = input_info.video
    input_analysis = input_info.analysis
    input_duration = probe_duration_seconds(input_info.probe, input_video)
    output_duration = probe_duration_seconds(output_probe, output_video)
    input_size = file_size(input_info.path)
    output_size = file_size(output_path)
    report_path = report_path_for(output_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    size_delta = None
    size_ratio = None
    if input_size and output_size:
        size_delta = input_size - output_size
        size_ratio = output_size / input_size * 100

    lines = [
        "# AV1 转换报告",
        "",
        "## 文件",
        "",
        "| 项目 | 输入 | 输出 |",
        "|---|---:|---:|",
        markdown_row("文件名", input_info.path.name, output_path.name),
        markdown_row("文件路径", input_info.path, output_path),
        markdown_row("文件大小", format_size(input_size), format_size(output_size)),
        markdown_row("容器", input_info.probe.get("format", {}).get("format_name"), output_probe.get("format", {}).get("format_name")),
        markdown_row("时长", format_duration(input_duration), format_duration(output_duration)),
        "",
        "## 视频参数",
        "",
        "| 项目 | 输入 | 输出 |",
        "|---|---:|---:|",
        markdown_row("编码", codec_label(input_video.get("codec_name")), codec_label(output_video.get("codec_name"))),
        markdown_row("Profile", input_video.get("profile"), output_video.get("profile")),
        markdown_row("分辨率", f"{input_video.get('width', '-')}x{input_video.get('height', '-')}", f"{output_video.get('width', '-')}x{output_video.get('height', '-')}"),
        markdown_row("SAR / DAR", f"{input_video.get('sample_aspect_ratio', '-')} / {input_video.get('display_aspect_ratio', '-')}", f"{output_video.get('sample_aspect_ratio', '-')} / {output_video.get('display_aspect_ratio', '-')}"),
        markdown_row("像素格式", input_video.get("pix_fmt"), output_video.get("pix_fmt")),
        markdown_row("帧率", input_video.get("r_frame_rate"), output_video.get("r_frame_rate")),
        markdown_row("视频码率", format_bitrate(input_analysis.get("bitrate_bps")), format_bitrate(output_analysis.get("bitrate_bps"))),
        markdown_row("Bits/(Pixel*Frame)", format_decimal(input_analysis.get("bits_per_pixel_frame"), 6), format_decimal(output_analysis.get("bits_per_pixel_frame"), 6)),
        markdown_row("码率来源", report_bitrate_source(input_analysis.get("bitrate_source")), report_bitrate_source(output_analysis.get("bitrate_source"))),
        "",
        "## 转换设置",
        "",
        "| 参数 | 值 |",
        "|---|---:|",
        f"| 编码器 | {markdown_escape(settings.encoder)} |",
        f"| 保留源视频码率 | {markdown_escape(settings.preserve_bitrate)} |",
        f"| CRF/QP | {markdown_escape(settings.crf)} |",
        f"| Preset | {markdown_escape(settings.preset)} |",
        f"| 尺寸模式 | {markdown_escape(report_resolution_mode(settings.resolution_mode))} |",
        f"| 自定义宽高 | {settings.custom_width}x{settings.custom_height} |",
        f"| 音频 | {markdown_escape(report_audio_mode(settings.audio_mode))} |",
        f"| 覆盖输出 | {markdown_escape(settings.overwrite)} |",
        "",
        "## 质量判断",
        "",
        "| 项目 | 输入 | 输出 |",
        "|---|---:|---:|",
        markdown_row("片源质量估计", report_quality(input_analysis.get("source_quality", {}).get("level")), report_quality(output_analysis.get("source_quality", {}).get("level"))),
        markdown_row("质量估计可信度", report_confidence(input_analysis.get("source_quality", {}).get("confidence")), report_confidence(output_analysis.get("source_quality", {}).get("confidence"))),
        markdown_row("编码器设置", encoder_settings_summary(input_analysis.get("encoder_settings", {})), encoder_settings_summary(output_analysis.get("encoder_settings", {}))),
        markdown_row("降噪/锐化痕迹", report_processing(input_analysis.get("processing", {})), report_processing(output_analysis.get("processing", {}))),
        "",
        "## 体积变化",
        "",
        "```text",
        f"{format_size(input_size)} -> {format_size(output_size)}",
        f"减少：{format_size(size_delta) if size_delta is not None else '-'}",
        f"输出约为原来的：{size_ratio:.1f}%" if size_ratio is not None else "输出约为原来的：-",
        "```",
        "",
        "说明：质量判断是基于码率、分辨率、帧率、编码效率和元数据的启发式估计，不等同于主观画质确认。",
        "",
        f"原始设置摘要：`{markdown_escape(conversion_setting_label(settings))}`",
        "",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def build_video_info(ffprobe: str, path: Path) -> VideoInfo:
    probe = probe_video(ffprobe, path)
    video = first_video_stream(probe)
    audio_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    subtitle_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "subtitle"]
    return VideoInfo(
        path=path,
        probe=probe,
        video=video,
        audio_streams=audio_streams,
        subtitle_streams=subtitle_streams,
        detected_3d_type=detect_3d_type(path, video),
        analysis=analyze_video_info(path, probe, video, audio_streams),
    )


def collect_video_files(folder: Path, recursive: bool) -> list[Path]:
    iterator = folder.rglob("*") if recursive else folder.iterdir()
    files = []
    for path in iterator:
        try:
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                files.append(path)
        except OSError:
            continue
    return sorted(files, key=lambda p: str(p).casefold())


def fraction_to_float(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    try:
        if "/" in value:
            top, bottom = value.split("/", 1)
            return float(top) / float(bottom)
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def stream_duration_seconds(info: VideoInfo) -> float | None:
    fmt_duration = info.probe.get("format", {}).get("duration")
    if fmt_duration:
        try:
            return float(fmt_duration)
        except ValueError:
            pass
    duration = info.video.get("duration")
    if duration:
        try:
            return float(duration)
        except ValueError:
            pass
    return None


def video_frame_count(info: VideoInfo) -> int | None:
    frames = parse_int(info.video.get("nb_frames"))
    if frames:
        return frames
    duration = stream_duration_seconds(info)
    fps = fraction_to_float(info.video.get("avg_frame_rate") or info.video.get("r_frame_rate"))
    if duration and fps:
        return max(1, int(duration * fps))
    return None


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_size(bytes_value: int | None) -> str:
    if bytes_value is None:
        return "-"
    value = float(bytes_value)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return "-"


def parse_float(value: Any) -> float | None:
    if value in {None, "", "N/A"}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int(value: Any) -> int | None:
    parsed = parse_float(value)
    return int(parsed) if parsed is not None else None


def format_bitrate(bits_per_second: int | float | None) -> str:
    if bits_per_second is None:
        return "-"
    value = float(bits_per_second)
    for unit in ["bps", "Kbps", "Mbps", "Gbps"]:
        if value < 1000 or unit == "Gbps":
            return f"{value:.2f} {unit}" if unit != "bps" else f"{int(value)} bps"
        value /= 1000
    return "-"


def format_decimal(value: int | float | None, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}"


def encoder_settings_summary(settings: dict[str, Any]) -> str:
    parts = []
    if settings.get("encoder"):
        parts.append(f"Encoder={settings['encoder']}")
    for key in ["crf", "qp", "cq", "preset"]:
        if settings.get(key):
            parts.append(f"{key.upper()}={settings[key]}")
    return ", ".join(parts) if parts else "not recorded"


def processing_summary(processing: dict[str, Any]) -> str:
    if processing.get("result") == "possible":
        terms = processing.get("denoise_terms", []) + processing.get("sharpen_terms", [])
        return f"possible: {', '.join(terms)}" if terms else "possible"
    return "not detectable"


def report_bitrate_source(source: str | None) -> str:
    return {
        "video_stream": "视频流字段",
        "format_estimate": "容器码率估算",
        "file_size_estimate": "文件大小/时长估算",
        "unknown": "未知",
    }.get(source or "unknown", "未知")


def report_quality(level: str | None) -> str:
    return {
        "very_high": "很高",
        "high": "高",
        "medium": "中等",
        "low": "偏低",
        "very_low": "很低",
        "unknown": "未知",
    }.get(level or "unknown", "未知")


def report_confidence(confidence: str | None) -> str:
    return {
        "low": "低可信",
        "medium": "中等可信",
        "high": "高可信",
    }.get(confidence or "low", "低可信")


def report_processing(processing: dict[str, Any]) -> str:
    if processing.get("result") == "possible":
        terms = processing.get("denoise_terms", []) + processing.get("sharpen_terms", [])
        return f"发现可能痕迹：{', '.join(terms)}" if terms else "发现可能痕迹"
    return "未发现可读痕迹，无法可靠判断"


def report_resolution_mode(mode: str) -> str:
    return {
        "keep": "保持原尺寸",
        "auto_1080": "自动 1080：2D 转 1080p，SBS 保持宽度",
        "height_1080": "高度转 1080（宽度保持）",
        "sbs_height_1080": "3D SBS 高度转 1080（宽度保持）",
        "2d_1080": "普通 2D 转 1920x1080",
        "custom": "自定义宽高",
    }.get(mode, mode)


def report_audio_mode(mode: str) -> str:
    return {
        "copy": "copy",
        "opus": "转 Opus 160k",
        "aac": "转 AAC 192k",
    }.get(mode, mode)


def probe_duration_seconds(probe: dict[str, Any], video: dict[str, Any]) -> float | None:
    duration = parse_float(probe.get("format", {}).get("duration"))
    if duration is not None:
        return duration
    return parse_float(video.get("duration"))


def estimate_video_bitrate(
    path: Path,
    probe: dict[str, Any],
    video: dict[str, Any],
    audio_streams: list[dict[str, Any]],
) -> tuple[int | None, str]:
    stream_bitrate = parse_int(video.get("bit_rate"))
    if stream_bitrate:
        return stream_bitrate, "video_stream"

    format_bitrate_value = parse_int(probe.get("format", {}).get("bit_rate"))
    if format_bitrate_value:
        known_audio_bitrate = sum(parse_int(stream.get("bit_rate")) or 0 for stream in audio_streams)
        estimated = max(0, format_bitrate_value - known_audio_bitrate)
        return estimated or format_bitrate_value, "format_estimate"

    duration = probe_duration_seconds(probe, video)
    size = file_size(path)
    if duration and size:
        return int(size * 8 / duration), "file_size_estimate"

    return None, "unknown"


def codec_efficiency_multiplier(codec_name: str | None) -> float:
    codec = (codec_name or "").lower()
    if codec == "av1":
        return 1.55
    if codec in {"hevc", "h265", "vp9"}:
        return 1.3
    if codec in {"h264", "avc1"}:
        return 1.0
    if codec in {"mpeg4", "vp8"}:
        return 0.75
    return 1.0


def quality_from_bpppf(adjusted_bpppf: float | None, pix_fmt: str | None) -> tuple[str, str]:
    if adjusted_bpppf is None:
        return "unknown", "low"

    ten_bit_bonus = 0.01 if pix_fmt and ("10" in pix_fmt or pix_fmt in {"p010le", "p010be"}) else 0
    score = adjusted_bpppf + ten_bit_bonus
    if score >= 0.14:
        return "very_high", "medium"
    if score >= 0.08:
        return "high", "medium"
    if score >= 0.045:
        return "medium", "medium"
    if score >= 0.025:
        return "low", "medium"
    return "very_low", "medium"


def flatten_probe_text(probe: dict[str, Any], video: dict[str, Any]) -> str:
    parts = []
    for source in [probe.get("format", {}).get("tags", {}), video.get("tags", {})]:
        if isinstance(source, dict):
            for key, value in source.items():
                parts.append(f"{key}={value}")
    side_data = video.get("side_data_list")
    if side_data:
        parts.append(json.dumps(side_data, ensure_ascii=True))
    return "\n".join(parts)


def detect_encoder_settings(metadata_text: str) -> dict[str, Any]:
    text = metadata_text or ""
    lowered = text.lower()
    encoder_matches = re.findall(r"(?:^|\n)(?:encoder|encoded[_ ]?by)=([^\n]+)", text, re.IGNORECASE)
    settings = {
        "encoder": encoder_matches[-1].strip() if encoder_matches else None,
        "crf": None,
        "qp": None,
        "cq": None,
        "preset": None,
        "raw_hint": None,
    }

    patterns = {
        "crf": r"\bcrf\s*[=: ]\s*([0-9]+(?:\.[0-9]+)?)",
        "qp": r"\bqp\s*[=: ]\s*([0-9]+(?:\.[0-9]+)?)",
        "cq": r"\bcq\s*[=: ]\s*([0-9]+(?:\.[0-9]+)?)",
        "preset": r"\b(?:preset|cpu-used|speed)\s*[=: ]\s*([A-Za-z0-9_.-]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, lowered, re.IGNORECASE)
        if match:
            settings[key] = match.group(1)

    if any(settings[key] for key in ["crf", "qp", "cq", "preset"]):
        settings["raw_hint"] = text[:500]
    return settings


def detect_processing_hints(metadata_text: str) -> dict[str, Any]:
    lowered = (metadata_text or "").lower()
    denoise_terms = ["denoise", "hqdn3d", "nlmeans", "bm3d", "atadenoise", "fft3dfilter", "degrain"]
    sharpen_terms = ["sharpen", "unsharp", "cas", "limitedsharpen", "asharp"]
    denoise_hits = [term for term in denoise_terms if term in lowered]
    sharpen_hits = [term for term in sharpen_terms if term in lowered]
    if denoise_hits or sharpen_hits:
        return {
            "result": "possible",
            "denoise_terms": denoise_hits,
            "sharpen_terms": sharpen_hits,
        }
    return {
        "result": "not_detectable",
        "denoise_terms": [],
        "sharpen_terms": [],
    }


def analyze_video_info(
    path: Path,
    probe: dict[str, Any],
    video: dict[str, Any],
    audio_streams: list[dict[str, Any]],
) -> dict[str, Any]:
    bitrate, bitrate_source = estimate_video_bitrate(path, probe, video, audio_streams)
    width = parse_int(video.get("width"))
    height = parse_int(video.get("height"))
    fps = fraction_to_float(video.get("avg_frame_rate")) or fraction_to_float(video.get("r_frame_rate"))
    bpppf = None
    if bitrate and width and height and fps:
        bpppf = bitrate / (width * height * fps)

    adjusted_bpppf = bpppf * codec_efficiency_multiplier(video.get("codec_name")) if bpppf is not None else None
    quality_level, quality_confidence = quality_from_bpppf(adjusted_bpppf, video.get("pix_fmt"))
    metadata_text = flatten_probe_text(probe, video)

    return {
        "bitrate_bps": bitrate,
        "bitrate_source": bitrate_source,
        "bits_per_pixel_frame": bpppf,
        "adjusted_bits_per_pixel_frame": adjusted_bpppf,
        "encoder_settings": detect_encoder_settings(metadata_text),
        "source_quality": {
            "level": quality_level,
            "confidence": quality_confidence,
        },
        "processing": detect_processing_hints(metadata_text),
    }


def format_fps(value: str | None) -> str:
    fps = fraction_to_float(value)
    if fps is None:
        return "-"
    return f"{fps:.3f}".rstrip("0").rstrip(".")


def file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def codec_label(codec: str | None) -> str:
    mapping = {
        "av1": "AV1",
        "h264": "H.264",
        "hevc": "H.265",
        "vp9": "VP9",
        "mpeg4": "MPEG-4",
        "prores": "ProRes",
    }
    return mapping.get((codec or "").lower(), (codec or "-").upper())


def audio_label(streams: list[dict[str, Any]]) -> str:
    if not streams:
        return "-"
    first = streams[0].get("codec_name", "-")
    suffix = "" if len(streams) == 1 else f" +{len(streams) - 1}"
    return f"{first}{suffix}"


def detect_3d_type(path: Path, video: dict[str, Any]) -> str:
    name = path.name.lower()
    side_data = json.dumps(video.get("side_data_list", []), ensure_ascii=True).lower()
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    ratio = width / height if height else 0

    if "side by side" in side_data or "sbs" in side_data:
        return "SBS"
    if "top and bottom" in side_data or "top-bottom" in side_data:
        return "Top-Bottom"

    if re.search(r"(^|[._\-\s])f(ull)?sbs($|[._\-\s])", name) or "full-sbs" in name:
        return "SBS Full"
    if re.search(r"(^|[._\-\s])h(alf)?sbs($|[._\-\s])", name) or "half-sbs" in name:
        return "SBS Half"
    if "sbs" in name or "side-by-side" in name or "side_by_side" in name:
        if ratio >= 3.0 or width >= 3840:
            return "SBS Full"
        return "SBS Half"

    if re.search(r"(^|[._\-\s])f(ull)?(ou|tab)($|[._\-\s])", name) or "full-ou" in name:
        return "Top-Bottom Full"
    if re.search(r"(^|[._\-\s])h(alf)?(ou|tab)($|[._\-\s])", name) or "half-ou" in name:
        return "Top-Bottom Half"
    if "top-bottom" in name or "top_bottom" in name or "_tb" in name or ".tb" in name:
        return "Top-Bottom"
    if re.search(r"(^|[._\-\s])(ou|tab)($|[._\-\s])", name):
        return "Top-Bottom"

    if "3d" in name:
        if ratio >= 3.0:
            return "SBS Full?"
        if height > width:
            return "Top-Bottom?"
        return "3D 未知"

    return "2D"


def av1_pix_fmt(source_pix_fmt: str | None) -> str:
    pix_fmt = (source_pix_fmt or "").lower()
    if "12" in pix_fmt:
        return "yuv420p12le"
    if "10" in pix_fmt or pix_fmt in {"p010le", "p010be"}:
        return "yuv420p10le"
    return "yuv420p"


def source_video_bitrate(info: VideoInfo) -> int | None:
    bitrate = info.analysis.get("bitrate_bps")
    if isinstance(bitrate, (int, float)) and bitrate > 0:
        return int(bitrate)
    return None


def output_path_for(input_path: Path, output_dir: Path, overwrite: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / f"{input_path.stem}_av1.mkv"
    if overwrite or not base.exists():
        return base
    index = 1
    while True:
        candidate = output_dir / f"{input_path.stem}_av1_{index}.mkv"
        if not candidate.exists():
            return candidate
        index += 1


def scale_filter_for(info: VideoInfo, settings: ConvertSettings) -> str | None:
    source_width = int(info.video.get("width") or 0)
    source_height = int(info.video.get("height") or 0)
    mode = settings.resolution_mode

    if mode == "keep":
        return None
    if mode == "auto_1080":
        detected_type = info.detected_3d_type.lower()
        if "sbs" in detected_type:
            if source_height == 1080:
                return "setsar=1"
            return f"scale={source_width}:1080:flags=lanczos,setsar=1"
        if detected_type == "2d":
            return "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1"
        return None
    if mode == "height_1080":
        if source_height == 1080:
            return "setsar=1"
        return f"scale={source_width}:1080:flags=lanczos,setsar=1"
    if mode == "sbs_height_1080":
        if source_height == 1080:
            return "setsar=1"
        return f"scale={source_width}:1080:flags=lanczos,setsar=1"
    if mode == "2d_1080":
        return "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1"
    if mode == "custom":
        width = max(2, settings.custom_width)
        height = max(2, settings.custom_height)
        return f"scale={width}:{height}:flags=lanczos,setsar=1"
    return None


def build_ffmpeg_command(
    ffmpeg: str,
    info: VideoInfo,
    output_path: Path,
    settings: ConvertSettings,
) -> list[str]:
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-y" if settings.overwrite else "-n",
        "-fflags",
        "+discardcorrupt",
        "-i",
        str(info.path),
        "-map",
        "0",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-c:s",
        "copy",
        "-c:d",
        "copy",
        "-c:t",
        "copy",
    ]

    filter_text = scale_filter_for(info, settings)
    if filter_text:
        cmd.extend(["-filter:v:0", filter_text])

    encoder = settings.encoder
    cmd.extend(["-c:v:0", encoder, "-pix_fmt", av1_pix_fmt(info.video.get("pix_fmt"))])

    target_bitrate = source_video_bitrate(info) if settings.preserve_bitrate else None
    if target_bitrate:
        cmd.extend(["-b:v:0", str(target_bitrate)])
        if encoder == "libsvtav1":
            cmd.extend(["-preset", str(settings.preset)])
        elif encoder == "libaom-av1":
            cpu_used = min(8, max(0, settings.preset))
            cmd.extend(["-cpu-used", str(cpu_used), "-row-mt", "1"])
        elif encoder == "librav1e":
            cmd.extend(["-speed", str(settings.preset)])
    elif encoder == "libsvtav1":
        cmd.extend(["-crf", str(settings.crf), "-preset", str(settings.preset)])
    elif encoder == "libaom-av1":
        cpu_used = min(8, max(0, settings.preset))
        cmd.extend(["-crf", str(settings.crf), "-b:v:0", "0", "-cpu-used", str(cpu_used), "-row-mt", "1"])
    elif encoder == "librav1e":
        cmd.extend(["-qp", str(settings.crf), "-speed", str(settings.preset)])

    if settings.audio_mode == "copy":
        cmd.extend(["-c:a", "copy"])
    elif settings.audio_mode == "opus":
        cmd.extend(["-c:a", "libopus", "-b:a", "160k"])
    elif settings.audio_mode == "aac":
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])

    cmd.extend(["-stats_period", "1", "-progress", "pipe:1", str(output_path)])
    return cmd


def ffmpeg_creation_flags() -> int:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return subprocess.CREATE_NO_WINDOW
    return 0


class ProbeWorker(QThread):
    item_ready = pyqtSignal(object)
    item_failed = pyqtSignal(str, str)
    log = pyqtSignal(str)
    finished_count = pyqtSignal(int)

    def __init__(self, paths: list[Path], ffprobe: str) -> None:
        super().__init__()
        self.paths = paths
        self.ffprobe = ffprobe

    def run(self) -> None:
        count = 0
        for path in self.paths:
            try:
                self.log.emit(f"[检测] {path.name}")
                info = build_video_info(self.ffprobe, path)
                self.item_ready.emit(info)
                count += 1
            except Exception as exc:
                self.item_failed.emit(str(path), str(exc))
        self.finished_count.emit(count)


class ConvertWorker(QThread):
    item_status = pyqtSignal(str, str)
    item_progress = pyqtSignal(str, float)
    item_done = pyqtSignal(str, str, object)
    item_failed = pyqtSignal(str, str)
    overall_progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished_all = pyqtSignal()

    def __init__(
        self,
        infos: list[VideoInfo],
        settings: ConvertSettings,
        ffmpeg: str,
        ffprobe: str,
    ) -> None:
        super().__init__()
        self.infos = infos
        self.settings = settings
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self._stop_requested = False
        self._process: subprocess.Popen[str] | None = None

    def stop(self) -> None:
        self._stop_requested = True
        if self._process and self._process.poll() is None:
            self._process.terminate()

    def run(self) -> None:
        total = max(1, len(self.infos))
        for index, info in enumerate(self.infos):
            if self._stop_requested:
                break

            key = str(info.path.resolve()).casefold()
            output_path = output_path_for(info.path, self.settings.output_dir, self.settings.overwrite)
            command = build_ffmpeg_command(self.ffmpeg, info, output_path, self.settings)
            duration = stream_duration_seconds(info) or 1
            total_frames = video_frame_count(info)
            self.item_status.emit(key, "转换中")
            self.item_progress.emit(key, 0.0)
            self.log.emit(f"[转换] {info.path.name} -> {output_path.name}")
            self.log.emit(f"[DEBUG] progress baseline: duration={duration:.2f}s, total_frames={total_frames or '-'}")
            self.log.emit(f"[DEBUG] ffmpeg command: {format_command_for_log(command)}")

            try:
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=ffmpeg_creation_flags(),
                )
                last_percent = 0.01
                self.item_progress.emit(key, last_percent)
                self.overall_progress.emit(int(((index + last_percent / 100) / total) * 10000))
                self.log.emit("[DEBUG] ffmpeg process started; initial progress=0.01%")
                debug_progress_logs = 0
                debug_unparsed_logs = 0
                last_debug_log_at = 0.0
                assert self._process.stdout is not None
                for raw_line in self._process.stdout:
                    line = raw_line.strip()
                    if not line:
                        continue
                    parsed = self._parse_progress_line(line, duration, total_frames)
                    if parsed is not None:
                        last_percent = max(last_percent, parsed)
                        self.item_progress.emit(key, last_percent)
                        overall = int(((index + last_percent / 100) / total) * 10000)
                        self.overall_progress.emit(overall)
                        now = time.monotonic()
                        if debug_progress_logs < 8 or now - last_debug_log_at >= 30:
                            self.log.emit(f"[DEBUG] progress parsed: {last_percent:.2f}% <= {short_log_line(line)}")
                            debug_progress_logs += 1
                            last_debug_log_at = now
                    elif "=" in line and debug_unparsed_logs < 12:
                        self.log.emit(f"[DEBUG] progress unparsed: {short_log_line(line)}")
                        debug_unparsed_logs += 1
                    elif line.startswith("[") or "Error" in line or "error" in line:
                        self.log.emit(line)

                return_code = self._process.wait()
                self._process = None
                if self._stop_requested:
                    self.item_status.emit(key, "已停止")
                    break
                if return_code != 0:
                    self.item_failed.emit(key, f"FFmpeg 退出码 {return_code}")
                    continue

                output_probe = probe_video(self.ffprobe, output_path)
                transfer_path = write_transfer_markdown(info, output_probe, output_path, self.settings)
                self.item_progress.emit(key, 100)
                self.item_done.emit(key, str(output_path), {"probe": output_probe, "report_path": str(transfer_path)})
                self.log.emit(f"[完成] {output_path.name}")
                self.log.emit(f"[报告] {transfer_path}")
                self.overall_progress.emit(int(((index + 1) / total) * 10000))
            except Exception as exc:
                self.item_failed.emit(key, str(exc))

        self.finished_all.emit()

    @staticmethod
    def _parse_progress_line(line: str, duration: float, total_frames: int | None) -> float | None:
        if "=" not in line:
            return None
        key, value = line.split("=", 1)
        if key not in {"out_time_ms", "out_time_us", "out_time", "progress"}:
            return ConvertWorker._parse_stats_progress(line, duration, total_frames)
        if key == "progress" and value == "end":
            return 100.0
        if key in {"out_time_ms", "out_time_us"}:
            try:
                seconds = int(value) / 1_000_000
                return ConvertWorker._percent_from_seconds(seconds, duration)
            except ValueError:
                return None
        if key == "out_time":
            return ConvertWorker._percent_from_timestamp(value, duration)
        return ConvertWorker._parse_stats_progress(line, duration, total_frames)

    @staticmethod
    def _percent_from_seconds(seconds: float, duration: float) -> float | None:
        if duration <= 0:
            return None
        percent = seconds / duration * 100
        if seconds > 0 and percent < 0.01:
            return 0.01
        return min(99.99, max(0.0, round(percent, 2)))

    @staticmethod
    def _percent_from_timestamp(value: str, duration: float) -> float | None:
        parts = value.split(":")
        if len(parts) != 3:
            return None
        try:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            return ConvertWorker._percent_from_seconds(seconds, duration)
        except ValueError:
            return None

    @staticmethod
    def _percent_from_frame(frame: int, total_frames: int | None) -> float | None:
        if not total_frames or frame <= 0:
            return None
        percent = frame / total_frames * 100
        if percent < 0.01:
            return 0.01
        return min(99.99, max(0.0, round(percent, 2)))

    @staticmethod
    def _parse_stats_progress(line: str, duration: float, total_frames: int | None) -> float | None:
        time_match = re.search(r"\btime=\s*([0-9]+:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?)", line)
        if time_match:
            parsed = ConvertWorker._percent_from_timestamp(time_match.group(1), duration)
            if parsed and parsed > 0:
                return parsed
        frame_match = re.search(r"\bframe=\s*([0-9]+)", line)
        if not frame_match:
            return None
        return ConvertWorker._percent_from_frame(int(frame_match.group(1)), total_frames)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self.path_to_row: dict[str, int] = {}
        self.probe_worker: ProbeWorker | None = None
        self.convert_worker: ConvertWorker | None = None
        self.ffmpeg = ""
        self.ffprobe = ""
        self.language = "zh"
        self.language_menu = None
        self.language_actions: dict[str, Any] = {}

        self.setWindowTitle(APP_NAME)
        self.resize(1420, 880)
        self._resolve_tools()
        self._build_ui()
        self._populate_encoders()
        self._connect_signals()
        self._update_stats()

    def _resolve_tools(self) -> None:
        try:
            self.ffmpeg = find_executable("ffmpeg")
            self.ffprobe = find_executable("ffprobe")
        except RuntimeError as exc:
            QMessageBox.critical(self, self.text("dlg_ffmpeg_unavailable"), str(exc))

    def text(self, key: str) -> str:
        return TRANSLATIONS.get(self.language, TRANSLATIONS["zh"]).get(
            key,
            TRANSLATIONS["zh"].get(key, key),
        )

    def kv_sep(self) -> str:
        return ": " if self.language == "en" else "："

    def _build_ui(self) -> None:
        self.setStyleSheet(APP_STYLE)
        self._build_menu_bar()
        self.statusBar().showMessage(self.text("status_ready"))

        root = QSplitter(Qt.Horizontal)
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_center())
        root.addWidget(self._build_inspector())
        root.setSizes([240, 840, 360])
        self.setCentralWidget(root)
        self.retranslate_ui()

    def _build_menu_bar(self) -> None:
        self.language_menu = self.menuBar().addMenu("")
        group = QActionGroup(self)
        group.setExclusive(True)
        for code, label_key in [("zh", "lang_zh"), ("ja", "lang_ja"), ("en", "lang_en")]:
            action = self.language_menu.addAction(self.text(label_key))
            action.setCheckable(True)
            action.setData(code)
            action.triggered.connect(lambda checked=False, lang=code: self.set_language(lang))
            group.addAction(action)
            self.language_actions[code] = action
        self.language_actions[self.language].setChecked(True)

    def set_language(self, language: str) -> None:
        if language not in LANGUAGES or language == self.language:
            return
        self.language = language
        self.language_actions[language].setChecked(True)
        self.retranslate_ui()
        self.log(f"[UI] Language: {LANGUAGES[language]}")

    def _build_sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidebar")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.file_management_title = QLabel()
        self.file_management_title.setObjectName("sectionTitle")
        layout.addWidget(self.file_management_title)

        self.add_files_button = QPushButton()
        self.add_files_button.setIcon(self.style().standardIcon(QStyle.SP_FileIcon))
        layout.addWidget(self.add_files_button)

        self.add_folder_button = QPushButton()
        self.add_folder_button.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
        layout.addWidget(self.add_folder_button)

        self.recursive_checkbox = QCheckBox()
        self.recursive_checkbox.setChecked(True)
        layout.addWidget(self.recursive_checkbox)

        layout.addWidget(horizontal_line())

        self.operations_title = QLabel()
        self.operations_title.setObjectName("sectionTitle")
        layout.addWidget(self.operations_title)

        self.detect_button = QPushButton()
        self.detect_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        layout.addWidget(self.detect_button)

        self.convert_button = QPushButton()
        self.convert_button.setObjectName("primaryButton")
        self.convert_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        layout.addWidget(self.convert_button)

        self.stop_button = QPushButton()
        self.stop_button.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)

        self.clear_button = QPushButton()
        self.clear_button.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        layout.addWidget(self.clear_button)

        layout.addWidget(horizontal_line())

        self.output_dir_title = QLabel()
        self.output_dir_title.setObjectName("sectionTitle")
        layout.addWidget(self.output_dir_title)

        self.output_dir_edit = QLineEdit(str(default_output_dir()))
        self.output_dir_edit.setReadOnly(True)
        layout.addWidget(self.output_dir_edit)

        self.output_dir_button = QPushButton()
        self.output_dir_button.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        layout.addWidget(self.output_dir_button)

        layout.addWidget(horizontal_line())

        self.stats_title = QLabel()
        self.stats_title.setObjectName("sectionTitle")
        layout.addWidget(self.stats_title)

        self.stats_label = QLabel()
        self.stats_label.setObjectName("statsLabel")
        layout.addWidget(self.stats_label)
        layout.addStretch(1)

        return panel

    def _build_center(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.video_list_title = QLabel()
        self.video_list_title.setObjectName("pageTitle")
        header.addWidget(self.video_list_title)
        header.addStretch(1)
        self.table_hint = QLabel()
        self.table_hint.setObjectName("muted")
        header.addWidget(self.table_hint)
        layout.addLayout(header)

        self.table = QTableWidget(0, 8)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 100)
        self.table.setColumnWidth(7, 130)
        layout.addWidget(self.table, 1)

        self.log_group = QGroupBox()
        log_layout = QVBoxLayout(self.log_group)
        log_layout.setContentsMargins(10, 8, 10, 10)
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 10000)
        self.overall_progress.setValue(0)
        self.overall_progress.setFormat("0.00%")
        log_layout.addWidget(self.overall_progress)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumHeight(150)
        log_layout.addWidget(self.log_edit)
        layout.addWidget(self.log_group)

        return panel

    def _build_inspector(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("inspector")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.detail_title = QLabel()
        self.detail_title.setObjectName("pageTitle")
        layout.addWidget(self.detail_title)

        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMinimumHeight(240)
        layout.addWidget(self.details_text)

        self.stereo_group = QGroupBox()
        stereo_layout = QHBoxLayout(self.stereo_group)
        self.manual_3d_combo = QComboBox()
        self.manual_3d_combo.addItem("", "auto")
        self.manual_3d_combo.addItem("", "2D")
        self.manual_3d_combo.addItem("", "SBS Full")
        self.manual_3d_combo.addItem("", "SBS Half")
        self.manual_3d_combo.addItem("", "Top-Bottom Full")
        self.manual_3d_combo.addItem("", "Top-Bottom Half")
        self.manual_3d_combo.addItem("", "3D 未知")
        self.apply_3d_button = QPushButton()
        stereo_layout.addWidget(self.manual_3d_combo, 1)
        stereo_layout.addWidget(self.apply_3d_button)
        layout.addWidget(self.stereo_group)

        self.settings_group = QGroupBox()
        grid = QGridLayout(self.settings_group)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self.encoder_combo = QComboBox()
        self.encoder_label = QLabel()
        grid.addWidget(self.encoder_label, 0, 0)
        grid.addWidget(self.encoder_combo, 0, 1, 1, 2)

        self.resolution_combo = QComboBox()
        self.resolution_combo.addItem("", "keep")
        self.resolution_combo.addItem("", "auto_1080")
        self.resolution_combo.addItem("", "height_1080")
        self.resolution_combo.addItem("", "sbs_height_1080")
        self.resolution_combo.addItem("", "2d_1080")
        self.resolution_combo.addItem("", "custom")
        self.resolution_combo.setCurrentIndex(0)
        self.resolution_label = QLabel()
        grid.addWidget(self.resolution_label, 1, 0)
        grid.addWidget(self.resolution_combo, 1, 1, 1, 2)

        self.custom_width_spin = QSpinBox()
        self.custom_width_spin.setRange(2, 16384)
        self.custom_width_spin.setValue(3840)
        self.custom_height_spin = QSpinBox()
        self.custom_height_spin.setRange(2, 16384)
        self.custom_height_spin.setValue(2160)
        self.custom_width_label = QLabel()
        grid.addWidget(self.custom_width_label, 2, 0)
        grid.addWidget(self.custom_width_spin, 2, 1)
        grid.addWidget(self.custom_height_spin, 2, 2)

        self.preserve_bitrate_checkbox = QCheckBox()
        self.preserve_bitrate_checkbox.setChecked(True)
        grid.addWidget(self.preserve_bitrate_checkbox, 3, 0, 1, 3)

        self.crf_slider = QSlider(Qt.Horizontal)
        self.crf_slider.setRange(0, 63)
        self.crf_slider.setValue(20)
        self.crf_spin = QSpinBox()
        self.crf_spin.setRange(0, 63)
        self.crf_spin.setValue(20)
        self.crf_label = QLabel()
        grid.addWidget(self.crf_label, 4, 0)
        grid.addWidget(self.crf_slider, 4, 1)
        grid.addWidget(self.crf_spin, 4, 2)

        self.preset_slider = QSlider(Qt.Horizontal)
        self.preset_slider.setRange(0, 13)
        self.preset_slider.setValue(5)
        self.preset_spin = QSpinBox()
        self.preset_spin.setRange(0, 13)
        self.preset_spin.setValue(5)
        self.preset_label = QLabel()
        grid.addWidget(self.preset_label, 5, 0)
        grid.addWidget(self.preset_slider, 5, 1)
        grid.addWidget(self.preset_spin, 5, 2)

        self.audio_combo = QComboBox()
        self.audio_combo.addItem("", "copy")
        self.audio_combo.addItem("", "opus")
        self.audio_combo.addItem("", "aac")
        self.audio_label_widget = QLabel()
        grid.addWidget(self.audio_label_widget, 6, 0)
        grid.addWidget(self.audio_combo, 6, 1, 1, 2)

        self.overwrite_checkbox = QCheckBox()
        self.overwrite_checkbox.setChecked(False)
        grid.addWidget(self.overwrite_checkbox, 7, 0, 1, 3)

        layout.addWidget(self.settings_group)
        layout.addStretch(1)
        return panel

    def _connect_signals(self) -> None:
        self.add_files_button.clicked.connect(self.add_files)
        self.add_folder_button.clicked.connect(self.add_folder)
        self.detect_button.clicked.connect(self.start_detect)
        self.convert_button.clicked.connect(self.start_convert)
        self.stop_button.clicked.connect(self.stop_convert)
        self.clear_button.clicked.connect(self.clear_list)
        self.output_dir_button.clicked.connect(self.choose_output_dir)
        self.apply_3d_button.clicked.connect(self.apply_manual_3d_type)
        self.table.itemSelectionChanged.connect(self.update_details_from_selection)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)
        self.crf_slider.valueChanged.connect(self.crf_spin.setValue)
        self.crf_spin.valueChanged.connect(self.crf_slider.setValue)
        self.preset_slider.valueChanged.connect(self.preset_spin.setValue)
        self.preset_spin.valueChanged.connect(self.preset_slider.setValue)
        self.resolution_combo.currentIndexChanged.connect(self.update_custom_size_enabled)
        self.preserve_bitrate_checkbox.toggled.connect(self.update_bitrate_mode_enabled)
        self.update_custom_size_enabled()
        self.update_bitrate_mode_enabled()

    def update_bitrate_mode_enabled(self) -> None:
        use_crf = not self.preserve_bitrate_checkbox.isChecked()
        self.crf_label.setEnabled(use_crf)
        self.crf_slider.setEnabled(use_crf)
        self.crf_spin.setEnabled(use_crf)

    def _populate_encoders(self) -> None:
        self.encoder_combo.clear()
        encoders = available_av1_encoders(self.ffmpeg) if self.ffmpeg else []
        for encoder in encoders:
            self.encoder_combo.addItem(encoder, encoder)
        if not encoders:
            self.encoder_combo.addItem(self.text("encoder_not_found"), "")
            self.convert_button.setEnabled(False)
            self.log("[警告] FFmpeg 未找到 libsvtav1/libaom-av1/librav1e。")
        else:
            preferred = self.encoder_combo.findData("libsvtav1")
            if preferred >= 0:
                self.encoder_combo.setCurrentIndex(preferred)

    def retranslate_ui(self) -> None:
        self.setWindowTitle(APP_NAME)
        if self.language_menu:
            self.language_menu.setTitle(self.text("menu_language"))
            for code, action in self.language_actions.items():
                action.setText(self.text(f"lang_{code}"))

        self.file_management_title.setText(self.text("file_management"))
        self.add_files_button.setText(self.text("add_video"))
        self.add_folder_button.setText(self.text("add_folder"))
        self.recursive_checkbox.setText(self.text("recursive_scan"))
        self.operations_title.setText(self.text("operations"))
        self.detect_button.setText(self.text("start_detect"))
        self.convert_button.setText(self.text("start_convert"))
        self.stop_button.setText(self.text("stop_convert"))
        self.clear_button.setText(self.text("clear_list"))
        self.output_dir_title.setText(self.text("output_dir"))
        self.output_dir_button.setText(self.text("choose_output_dir"))
        self.stats_title.setText(self.text("stats_info"))

        self.video_list_title.setText(self.text("video_list"))
        self.table_hint.setText(self.text("table_hint"))
        self.table.setHorizontalHeaderLabels(
            [
                self.text("h_filename"),
                self.text("h_3d_type"),
                self.text("h_codec"),
                self.text("h_resolution"),
                self.text("h_fps"),
                self.text("h_duration"),
                self.text("h_size"),
                self.text("h_status"),
            ]
        )
        self.log_group.setTitle(self.text("log"))

        self.detail_title.setText(self.text("video_details"))
        self.stereo_group.setTitle(self.text("stereo_fix"))
        self.apply_3d_button.setText(self.text("apply_selected"))
        self.settings_group.setTitle(self.text("av1_settings"))
        self.encoder_label.setText(self.text("encoder"))
        self.preserve_bitrate_checkbox.setText(self.text("preserve_bitrate"))
        self.resolution_label.setText(self.text("size_mode"))
        self.custom_width_label.setText(self.text("custom_width"))
        self.crf_label.setText(self.text("crf"))
        self.preset_label.setText(self.text("preset"))
        self.audio_label_widget.setText(self.text("audio"))
        self.overwrite_checkbox.setText(self.text("overwrite"))

        self.set_combo_texts(
            self.manual_3d_combo,
            {
                "auto": self.text("stereo_auto"),
                "2D": "2D",
                "SBS Full": "SBS Full",
                "SBS Half": "SBS Half",
                "Top-Bottom Full": "Top-Bottom Full",
                "Top-Bottom Half": "Top-Bottom Half",
                "3D 未知": self.text("stereo_unknown"),
            },
        )
        self.set_combo_texts(
            self.resolution_combo,
            {
                "keep": self.text("res_keep"),
                "auto_1080": self.text("res_auto_1080"),
                "height_1080": self.text("res_height_1080"),
                "sbs_height_1080": self.text("res_sbs_height_1080"),
                "2d_1080": self.text("res_2d_1080"),
                "custom": self.text("res_custom"),
            },
        )
        self.set_combo_texts(
            self.audio_combo,
            {
                "copy": self.text("audio_copy"),
                "opus": self.text("audio_opus"),
                "aac": self.text("audio_aac"),
            },
        )
        if self.encoder_combo.count() == 1 and not self.encoder_combo.itemData(0):
            self.encoder_combo.setItemText(0, self.text("encoder_not_found"))

        self.refresh_table_language()
        self._update_stats()
        self.update_details_from_selection()

    @staticmethod
    def set_combo_texts(combo: QComboBox, text_by_data: dict[str, str]) -> None:
        current_data = combo.currentData()
        for index in range(combo.count()):
            data = combo.itemData(index)
            if data in text_by_data:
                combo.setItemText(index, text_by_data[data])
        target_index = combo.findData(current_data)
        if target_index >= 0:
            combo.setCurrentIndex(target_index)

    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.text("select_video_files"),
            str(launch_base_dir()),
            "Video Files (*.mkv *.mp4 *.webm *.mov *.avi *.m4v *.ts *.m2ts *.wmv);;All Files (*)",
        )
        self.add_paths([Path(path) for path in paths])

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.text("select_video_folder"), str(launch_base_dir()))
        if not folder:
            return
        paths = collect_video_files(Path(folder), self.recursive_checkbox.isChecked())
        self.add_paths(paths)
        self.log(f"[扫描] 找到 {len(paths)} 个视频文件")

    def add_paths(self, paths: list[Path]) -> None:
        added = 0
        for path in paths:
            if path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            key = str(path.resolve()).casefold()
            if key in self.path_to_row:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.records.append(
                {
                    "path": path,
                    "info": None,
                    "output_path": None,
                    "output_probe": None,
                    "report_path": None,
                    "status": "待检测",
                    "progress": 0,
                    "error": None,
                }
            )
            self.path_to_row[key] = row
            self._set_row_basic(row, path)
            added += 1
        if added:
            self.log(f"[列表] 已添加 {added} 个文件")
        self._update_stats()

    def status_text(self, status: str) -> str:
        return self.text(STATUS_KEYS.get(status, status))

    def stereo_text(self, stereo_type: str) -> str:
        key = STEREO_TEXT_KEYS.get(stereo_type)
        return self.text(key) if key else stereo_type

    def bitrate_source_text(self, source: str) -> str:
        mapping = {
            "video_stream": "source_video_stream",
            "format_estimate": "source_format_estimate",
            "file_size_estimate": "source_file_size_estimate",
            "unknown": "source_unknown",
        }
        return self.text(mapping.get(source, "source_unknown"))

    def quality_text(self, level: str) -> str:
        return self.text(f"quality_{level}") if f"quality_{level}" in TRANSLATIONS["zh"] else level

    def confidence_text(self, confidence: str) -> str:
        return self.text(f"confidence_{confidence}") if f"confidence_{confidence}" in TRANSLATIONS["zh"] else confidence

    def encoder_settings_text(self, settings: dict[str, Any]) -> str:
        parts = []
        if settings.get("encoder"):
            parts.append(f"Encoder={settings['encoder']}")
        for key in ["crf", "qp", "cq", "preset"]:
            if settings.get(key):
                parts.append(f"{key.upper()}={settings[key]}")
        if parts:
            if not any(settings.get(key) for key in ["crf", "qp", "cq", "preset"]):
                parts.append(self.text("encoder_not_recorded"))
            return ", ".join(parts)
        return self.text("encoder_not_recorded")

    def processing_text(self, processing: dict[str, Any]) -> str:
        if processing.get("result") == "possible":
            terms = processing.get("denoise_terms", []) + processing.get("sharpen_terms", [])
            return f"{self.text('processing_possible')}: {', '.join(terms)}"
        return self.text("processing_not_detectable")

    def refresh_table_language(self) -> None:
        for row, record in enumerate(self.records):
            info: VideoInfo | None = record.get("info")
            if info is not None:
                self.table.item(row, 1).setText(self.stereo_text(info.detected_3d_type))

            status = record.get("status", "待检测")
            progress = int(record.get("progress") or 0)
            if status == "转换中":
                status_display = f"{self.status_text(status)} {progress}%"
            else:
                status_display = self.status_text(status)
            item = self.table.item(row, 7)
            if item:
                item.setText(status_display)

    def _set_row_basic(self, row: int, path: Path) -> None:
        values = [path.name, "-", "-", "-", "-", "-", format_size(file_size(path)), self.status_text("待检测")]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            if column in {2, 3, 4, 5, 6, 7}:
                item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, column, item)
        self._paint_status(row, "待检测")

    def start_detect(self) -> None:
        if self.probe_worker and self.probe_worker.isRunning():
            return
        if not self.ffprobe:
            QMessageBox.warning(self, self.text("dlg_cannot_detect"), self.text("dlg_ffprobe_missing"))
            return
        pending = [record["path"] for record in self.records if record["info"] is None]
        if not pending:
            self.log("[检测] 没有待检测文件")
            return
        self.detect_button.setEnabled(False)
        self.statusBar().showMessage(self.text("status_detecting"))
        self.probe_worker = ProbeWorker(pending, self.ffprobe)
        self.probe_worker.item_ready.connect(self.on_probe_item)
        self.probe_worker.item_failed.connect(self.on_probe_failed)
        self.probe_worker.log.connect(self.log)
        self.probe_worker.finished_count.connect(self.on_probe_finished)
        self.probe_worker.start()

    def on_probe_item(self, info: VideoInfo) -> None:
        key = str(info.path.resolve()).casefold()
        row = self.path_to_row.get(key)
        if row is None:
            return
        self.records[row]["info"] = info
        self.records[row]["status"] = "已检测"
        video = info.video
        values = {
            1: self.stereo_text(info.detected_3d_type),
            2: codec_label(video.get("codec_name")),
            3: f"{video.get('width', '-') }x{video.get('height', '-')}",
            4: format_fps(video.get("r_frame_rate") or video.get("avg_frame_rate")),
            5: format_duration(stream_duration_seconds(info)),
            7: self.status_text("已检测"),
        }
        for column, value in values.items():
            self.table.item(row, column).setText(str(value))
        self._paint_status(row, "已检测")
        self._update_stats()
        self.update_details_from_selection()

    def on_probe_failed(self, path: str, message: str) -> None:
        key = str(Path(path).resolve()).casefold()
        row = self.path_to_row.get(key)
        if row is not None:
            self.records[row]["status"] = "失败"
            self.records[row]["error"] = message
            self.table.item(row, 7).setText(self.status_text("失败"))
            self._paint_status(row, "失败")
        self.log(f"[失败] {Path(path).name}: {message}")
        self._update_stats()

    def on_probe_finished(self, count: int) -> None:
        self.detect_button.setEnabled(True)
        self.statusBar().showMessage(self.text("status_detect_done"))
        self.log(f"[检测] 完成 {count} 个文件")
        self._update_stats()

    def start_convert(self) -> None:
        if self.convert_worker and self.convert_worker.isRunning():
            return
        if not self.ffmpeg or not self.ffprobe:
            QMessageBox.warning(self, self.text("dlg_cannot_convert"), self.text("dlg_ffmpeg_missing"))
            return

        selected_rows = sorted({index.row() for index in self.table.selectedIndexes()})
        source_records = [self.records[row] for row in selected_rows] if selected_rows else self.records
        infos = [record["info"] for record in source_records if record["info"] is not None]
        if not infos:
            QMessageBox.information(self, self.text("dlg_no_convertible"), self.text("dlg_no_convertible_msg"))
            return

        settings = self.current_settings()
        if not settings.encoder:
            QMessageBox.warning(self, self.text("dlg_missing_encoder"), self.text("dlg_missing_encoder_msg"))
            return

        for info in infos:
            key = str(info.path.resolve()).casefold()
            row = self.path_to_row.get(key)
            if row is not None:
                self.records[row]["status"] = "等待转换"
                self.records[row]["progress"] = 0
                self.table.item(row, 7).setText(self.status_text("等待转换"))
                self._paint_status(row, "等待转换")

        self.convert_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.detect_button.setEnabled(False)
        self.overall_progress.setValue(0)
        self.overall_progress.setFormat("0.00%")
        self.statusBar().showMessage(self.text("status_converting"))

        self.convert_worker = ConvertWorker(infos, settings, self.ffmpeg, self.ffprobe)
        self.convert_worker.item_status.connect(self.on_convert_status)
        self.convert_worker.item_progress.connect(self.on_convert_progress)
        self.convert_worker.item_done.connect(self.on_convert_done)
        self.convert_worker.item_failed.connect(self.on_convert_failed)
        self.convert_worker.overall_progress.connect(self.on_overall_progress)
        self.convert_worker.log.connect(self.log)
        self.convert_worker.finished_all.connect(self.on_convert_finished)
        self.convert_worker.start()
        self._update_stats()

    def on_overall_progress(self, value: int) -> None:
        value = max(0, min(10000, int(value)))
        self.overall_progress.setValue(value)
        self.overall_progress.setFormat(f"{value / 100:.2f}%")
    def stop_convert(self) -> None:
        if self.convert_worker and self.convert_worker.isRunning():
            self.log("[转换] 请求停止当前任务")
            self.convert_worker.stop()

    def on_convert_status(self, key: str, status: str) -> None:
        row = self.path_to_row.get(key)
        if row is None:
            return
        self.records[row]["status"] = status
        self.table.item(row, 7).setText(self.status_text(status))
        self._paint_status(row, status)
        self._update_stats()

    def on_convert_progress(self, key: str, percent: float) -> None:
        row = self.path_to_row.get(key)
        if row is None:
            return
        self.records[row]["progress"] = percent
        status = self.records[row].get("status", "")
        display = "0%" if percent <= 0 else f"{percent:.2f}%"
        self.table.item(row, 7).setText(f"{self.status_text(status)} {display}")
        self._paint_status(row, status)

    def on_convert_done(self, key: str, output_path: str, output_payload: object) -> None:
        row = self.path_to_row.get(key)
        if row is None:
            return
        output_probe = output_payload.get("probe") if isinstance(output_payload, dict) else output_payload
        report_path = output_payload.get("report_path") if isinstance(output_payload, dict) else None
        self.records[row]["status"] = "已完成"
        self.records[row]["progress"] = 100
        self.records[row]["output_path"] = Path(output_path)
        self.records[row]["output_probe"] = output_probe
        self.records[row]["report_path"] = Path(report_path) if report_path else report_path_for(Path(output_path))
        self.table.item(row, 7).setText(self.status_text("已完成"))
        self._paint_status(row, "已完成")
        self._update_stats()
        self.update_details_from_selection()

    def on_convert_failed(self, key: str, message: str) -> None:
        row = self.path_to_row.get(key)
        if row is not None:
            self.records[row]["status"] = "失败"
            self.records[row]["error"] = message
            self.table.item(row, 7).setText(self.status_text("失败"))
            self._paint_status(row, "失败")
        self.log(f"[失败] {message}")
        self._update_stats()

    def on_convert_finished(self) -> None:
        self.convert_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.detect_button.setEnabled(True)
        self.statusBar().showMessage(self.text("status_convert_done"))
        self.log("[转换] 队列结束")
        self._update_stats()

    def current_settings(self) -> ConvertSettings:
        return ConvertSettings(
            output_dir=Path(self.output_dir_edit.text()),
            encoder=self.encoder_combo.currentData() or "",
            preserve_bitrate=self.preserve_bitrate_checkbox.isChecked(),
            resolution_mode=self.resolution_combo.currentData() or "keep",
            custom_width=self.custom_width_spin.value(),
            custom_height=self.custom_height_spin.value(),
            crf=self.crf_spin.value(),
            preset=self.preset_spin.value(),
            audio_mode=self.audio_combo.currentData() or "copy",
            overwrite=self.overwrite_checkbox.isChecked(),
        )

    def choose_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.text("select_output_folder"), self.output_dir_edit.text())
        if folder:
            self.output_dir_edit.setText(folder)

    def clear_list(self) -> None:
        if self.convert_worker and self.convert_worker.isRunning():
            QMessageBox.information(self, self.text("dlg_converting"), self.text("dlg_converting_msg"))
            return
        self.records.clear()
        self.path_to_row.clear()
        self.table.setRowCount(0)
        self.details_text.clear()
        self.overall_progress.setValue(0)
        self._update_stats()
        self.log("[列表] 已清空")

    def show_table_context_menu(self, position: Any) -> None:
        row = self.table.rowAt(position.y())
        if row < 0:
            return

        selected_rows = self.selected_rows()
        if row not in selected_rows:
            self.table.clearSelection()
            self.table.selectRow(row)
            selected_rows = [row]

        menu = QMenu(self)
        remove_action = menu.addAction(self.text("context_remove"))
        delete_action = menu.addAction(self.text("context_delete"))

        if self.is_row_task_running():
            remove_action.setEnabled(False)
            delete_action.setEnabled(False)

        action = menu.exec_(self.table.viewport().mapToGlobal(position))
        if action == remove_action:
            self.remove_selected_from_list()
        elif action == delete_action:
            self.delete_selected_files_permanently()

    def selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.table.selectedIndexes()})

    def is_row_task_running(self) -> bool:
        return bool(
            (self.probe_worker and self.probe_worker.isRunning())
            or (self.convert_worker and self.convert_worker.isRunning())
        )

    def remove_selected_from_list(self) -> None:
        if self.is_row_task_running():
            QMessageBox.information(self, self.text("dlg_task_running"), self.text("dlg_task_remove_msg"))
            return

        rows = self.selected_rows()
        if not rows:
            return

        count = len(rows)
        self.remove_rows(rows)
        self.log(f"[列表] 已从列表删除 {count} 个视频")

    def delete_selected_files_permanently(self) -> None:
        if self.is_row_task_running():
            QMessageBox.information(self, self.text("dlg_task_running"), self.text("dlg_task_delete_msg"))
            return

        rows = self.selected_rows()
        if not rows:
            return

        paths = [self.records[row]["path"] for row in rows]
        preview = "\n".join(path.name for path in paths[:8])
        if len(paths) > 8:
            preview += f"\n... {self.text('more_files').format(count=len(paths) - 8)}"

        reply = QMessageBox.warning(
            self,
            self.text("dlg_confirm_delete"),
            f"{self.text('dlg_confirm_delete_intro')}\n\n"
            f"{self.text('dlg_confirm_delete_count')}{self.kv_sep()}{len(paths)}\n"
            f"{preview}\n\n"
            + self.text("dlg_confirm_delete_suffix"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        deleted_rows = []
        failures = []
        for row, path in zip(rows, paths):
            try:
                if path.exists():
                    path.unlink()
                deleted_rows.append(row)
            except OSError as exc:
                failures.append(f"{path.name}: {exc}")

        if deleted_rows:
            self.remove_rows(deleted_rows)
            self.log(f"[删除] 已永久删除 {len(deleted_rows)} 个源视频文件")

        if failures:
            QMessageBox.warning(self, self.text("dlg_partial_delete_failed"), "\n".join(failures[:10]))
            for failure in failures:
                self.log(f"[删除失败] {failure}")

    def remove_rows(self, rows: list[int]) -> None:
        for row in sorted(rows, reverse=True):
            if 0 <= row < len(self.records):
                del self.records[row]
                self.table.removeRow(row)

        self.rebuild_path_index()
        self.details_text.clear()
        self._update_stats()

    def rebuild_path_index(self) -> None:
        self.path_to_row = {
            str(record["path"].resolve()).casefold(): row
            for row, record in enumerate(self.records)
        }

    def update_custom_size_enabled(self) -> None:
        enabled = self.resolution_combo.currentData() == "custom"
        self.custom_width_spin.setEnabled(enabled)
        self.custom_height_spin.setEnabled(enabled)

    def update_details_from_selection(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not rows:
            self.details_text.setPlainText(self.text("detail_select_video"))
            return
        record = self.records[rows[0]]
        info: VideoInfo | None = record.get("info")
        if info is None:
            text = (
                f"{self.text('file')}{self.kv_sep()}{record['path']}\n"
                f"{self.text('h_status')}{self.kv_sep()}{self.status_text(record['status'])}"
            )
            if record.get("error"):
                text += f"\n{self.text('error')}{self.kv_sep()}{record['error']}"
            self.details_text.setPlainText(text)
            return

        video = info.video
        analysis = info.analysis
        bpppf = analysis.get("bits_per_pixel_frame")
        quality = analysis.get("source_quality", {})
        lines = [
            f"{self.text('file')}{self.kv_sep()}{info.path}",
            f"{self.text('stereo_type')}{self.kv_sep()}{self.stereo_text(info.detected_3d_type)}",
            "",
            self.text("input_video"),
            f"{self.text('codec')}{self.kv_sep()}{codec_label(video.get('codec_name'))}",
            f"{self.text('profile')}{self.kv_sep()}{video.get('profile', '-')}",
            f"{self.text('resolution')}{self.kv_sep()}{video.get('width', '-')}x{video.get('height', '-')}",
            f"{self.text('sar_dar')}{self.kv_sep()}{video.get('sample_aspect_ratio', '-')} / {video.get('display_aspect_ratio', '-')}",
            f"{self.text('pix_fmt')}{self.kv_sep()}{video.get('pix_fmt', '-')}",
            f"{self.text('fps')}{self.kv_sep()}{video.get('r_frame_rate', '-')}",
            f"{self.text('bitrate')}{self.kv_sep()}{format_bitrate(analysis.get('bitrate_bps'))}",
            f"{self.text('duration')}{self.kv_sep()}{format_duration(stream_duration_seconds(info))}",
            f"{self.text('audio_label')}{self.kv_sep()}{audio_label(info.audio_streams)}",
            f"{self.text('subtitle_streams')}{self.kv_sep()}{len(info.subtitle_streams)}",
            "",
            self.text("analysis_section"),
            f"{self.text('effective_bitrate')}{self.kv_sep()}{format_bitrate(analysis.get('bitrate_bps'))}",
            f"{self.text('bitrate_source')}{self.kv_sep()}{self.bitrate_source_text(analysis.get('bitrate_source', 'unknown'))}",
            f"{self.text('bpppf')}{self.kv_sep()}{bpppf:.6f}" if bpppf is not None else f"{self.text('bpppf')}{self.kv_sep()}-",
            f"{self.text('encoder_settings')}{self.kv_sep()}{self.encoder_settings_text(analysis.get('encoder_settings', {}))}",
            (
                f"{self.text('source_quality')}{self.kv_sep()}"
                f"{self.quality_text(quality.get('level', 'unknown'))} "
                f"({self.confidence_text(quality.get('confidence', 'low'))})"
            ),
            f"{self.text('processing_judgement')}{self.kv_sep()}{self.processing_text(analysis.get('processing', {}))}",
            self.text("quality_note"),
        ]

        output_path = record.get("output_path")
        output_probe = record.get("output_probe")
        report_path = record.get("report_path")
        if output_path and output_probe:
            output_video = first_video_stream(output_probe)
            lines.extend(
                [
                    "",
                    self.text("output_video"),
                    f"{self.text('file')}{self.kv_sep()}{output_path}",
                    f"{self.text('codec')}{self.kv_sep()}{codec_label(output_video.get('codec_name'))}",
                    f"{self.text('resolution')}{self.kv_sep()}{output_video.get('width', '-')}x{output_video.get('height', '-')}",
                    f"{self.text('sar_dar')}{self.kv_sep()}{output_video.get('sample_aspect_ratio', '-')} / {output_video.get('display_aspect_ratio', '-')}",
                    f"{self.text('pix_fmt')}{self.kv_sep()}{output_video.get('pix_fmt', '-')}",
                    f"{self.text('fps')}{self.kv_sep()}{output_video.get('r_frame_rate', '-')}",
                    f"{self.text('transfer')}{self.kv_sep()}{report_path or report_path_for(output_path)}",
                ]
            )
        if record.get("error"):
            lines.extend(["", f"{self.text('error')}{self.kv_sep()}{record['error']}"])
        self.details_text.setPlainText("\n".join(lines))
        combo_index = self.manual_3d_combo.findData(info.detected_3d_type)
        if combo_index >= 0:
            self.manual_3d_combo.setCurrentIndex(combo_index)

    def apply_manual_3d_type(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, self.text("dlg_no_video_selected"), self.text("dlg_no_video_selected_msg"))
            return

        selected_type = self.manual_3d_combo.currentData()
        changed = 0
        for row in rows:
            info: VideoInfo | None = self.records[row].get("info")
            if info is None:
                continue
            if selected_type == "auto":
                info.detected_3d_type = detect_3d_type(info.path, info.video)
            else:
                info.detected_3d_type = selected_type
            self.table.item(row, 1).setText(self.stereo_text(info.detected_3d_type))
            changed += 1

        if changed:
            self.log(f"[3D] 已修正 {changed} 个文件为 {self.manual_3d_combo.currentText()}")
            self.update_details_from_selection()

    def _paint_status(self, row: int, status: str) -> None:
        colors = {
            "待检测": QColor("#64748b"),
            "已检测": QColor("#15803d"),
            "等待转换": QColor("#b45309"),
            "转换中": QColor("#0369a1"),
            "已完成": QColor("#15803d"),
            "失败": QColor("#b91c1c"),
            "已停止": QColor("#6b7280"),
        }
        item = self.table.item(row, 7)
        if item:
            item.setForeground(colors.get(status, QColor("#111827")))

    def _update_stats(self) -> None:
        detected_count = 0
        waiting_count = 0
        converting_count = 0
        done_count = 0
        failed_count = 0
        for record in self.records:
            status = record.get("status")
            if record.get("info") is not None:
                detected_count += 1
            if status == "等待转换":
                waiting_count += 1
            elif status == "转换中" or (isinstance(status, str) and status.startswith("转换中")):
                converting_count += 1
            elif status == "已完成":
                done_count += 1
            elif status == "失败":
                failed_count += 1
        self.stats_label.setText(
            "\n".join(
                [
                    f"{self.text('stat_total')}{self.kv_sep()}{len(self.records)}",
                    f"{self.text('stat_detected')}{self.kv_sep()}{detected_count}",
                    f"{self.text('stat_waiting')}{self.kv_sep()}{waiting_count}",
                    f"{self.text('stat_converting')}{self.kv_sep()}{converting_count}",
                    f"{self.text('stat_done')}{self.kv_sep()}{done_count}",
                    f"{self.text('stat_failed')}{self.kv_sep()}{failed_count}",
                ]
            )
        )

    def log(self, text: str) -> None:
        self.log_edit.append(text)

    def closeEvent(self, event: Any) -> None:
        if self.convert_worker and self.convert_worker.isRunning():
            reply = QMessageBox.question(
                self,
                self.text("dlg_still_converting"),
                self.text("dlg_still_converting_msg"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self.convert_worker.stop()
        event.accept()


def available_av1_encoders(ffmpeg: str) -> list[str]:
    if not ffmpeg:
        return []
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            creationflags=ffmpeg_creation_flags(),
        )
    except Exception:
        return []
    text = result.stdout
    ordered = ["libsvtav1", "libaom-av1", "librav1e"]
    return [encoder for encoder in ordered if encoder in text]


def horizontal_line() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


APP_STYLE = """
QMainWindow, QWidget {
    background: #f5f7fb;
    color: #111827;
    font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
    font-size: 9.5pt;
}
QWidget#sidebar, QWidget#inspector {
    background: #f8fafc;
}
QLabel#pageTitle {
    font-size: 13pt;
    font-weight: 700;
}
QLabel#sectionTitle {
    font-weight: 700;
    color: #0f172a;
}
QLabel#muted {
    color: #64748b;
}
QLabel#statsLabel {
    color: #334155;
    line-height: 1.4;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 8px 10px;
    text-align: left;
}
QPushButton:hover {
    background: #eff6ff;
    border-color: #60a5fa;
}
QPushButton:disabled {
    color: #94a3b8;
    background: #f1f5f9;
}
QPushButton#primaryButton {
    background: #2563eb;
    color: #ffffff;
    border-color: #1d4ed8;
}
QPushButton#primaryButton:hover {
    background: #1d4ed8;
}
QLineEdit, QComboBox, QSpinBox, QTextEdit {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px;
}
QTableWidget {
    background: #ffffff;
    alternate-background-color: #f8fafc;
    border: 1px solid #dbe3ef;
    gridline-color: #e2e8f0;
    selection-background-color: #dbeafe;
    selection-color: #0f172a;
}
QHeaderView::section {
    background: #f1f5f9;
    border: 0;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #cbd5e1;
    padding: 7px;
    font-weight: 700;
}
QGroupBox {
    border: 1px solid #dbe3ef;
    border-radius: 8px;
    margin-top: 10px;
    background: #ffffff;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QProgressBar {
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #ffffff;
    height: 16px;
    text-align: center;
}
QProgressBar::chunk {
    background: #2563eb;
    border-radius: 5px;
}
QSlider::groove:horizontal {
    height: 5px;
    background: #cbd5e1;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #2563eb;
    border: 1px solid #1d4ed8;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
"""


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
