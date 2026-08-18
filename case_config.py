from __future__ import annotations

import os
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Callable, Any


DEFAULT_CASES_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.json")


@dataclass
class JankLevelThresholds:
    """卡顿等级阈值（基于帧时长dur，单位ms）- 4级"""
    tiny_min: float = 34.0     # 细微卡顿下限
    tiny_max: float = 67.0     # 细微卡顿上限（不含）
    slight_min: float = 67.0   # 轻微卡顿下限
    slight_max: float = 100.0  # 轻微卡顿上限（不含）
    obvious_min: float = 100.0 # 明显卡顿下限
    obvious_max: float = 167.0 # 明显卡顿上限（不含）
    severe_min: float = 167.0  # 严重卡顿下限
    severe_max: float = float('inf')  # 严重卡顿上限：正无穷

    def to_dict(self) -> Dict[str, float]:
        d = asdict(self)
        # JSON不支持inf，转成极大值99999.0
        for k, v in d.items():
            if v == float('inf'):
                d[k] = 99999.0
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "JankLevelThresholds":
        def _to_float(v):
            f = float(v)
            # 极大值还原为inf
            if f >= 99999.0:
                return float('inf')
            return f
        return cls(**{k: _to_float(v) for k, v in data.items()})


@dataclass
class TestCaseConfig:
    """单个测试用例配置"""
    name: str                       # case名称，如 case1
    description: str                # 描述，如 相机拍照模式预览5s
    duration: int                   # 录制时长(秒)
    package_name: str               # 目标包名
    monitor_processes: str = "all"  # 监控进程，逗号分隔或all
    script_name: str = ""           # 脚本函数名（对应case_scripts中的函数，或自定义脚本）
    script_path: str = ""           # 自定义脚本文件路径（.py），优先级高于script_name
    rounds: int = 5                 # 运行轮数，默认5轮
    enabled: bool = True            # 是否启用

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestCaseConfig":
        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            duration=int(data.get("duration", 30)),
            package_name=str(data.get("package_name", "")),
            monitor_processes=str(data.get("monitor_processes", "all")),
            script_name=str(data.get("script_name", "")),
            script_path=str(data.get("script_path", "")),
            rounds=int(data.get("rounds", 5)),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class CameraUISettings:
    """相机UI控件配置 — 换不同相机APK时改这里或在GUI中改"""
    # 包名（默认相机包名）
    package_name: str = "com.android.camera2"
    # 快门按钮resourceId（按优先级排序，支持多个候选）
    shutter_resource_ids: List[str] = field(default_factory=lambda: [
        "com.android.camera2:id/shutter_button",
        "com.android.camera:id/shutter_button",
        "shutter_button",
    ])
    # 录像按钮resourceId
    record_resource_ids: List[str] = field(default_factory=lambda: [
        "com.android.camera2:id/record_button",
        "com.android.camera:id/record_button",
        "record_button",
    ])
    # 前后置切换按钮resourceId（全局常量，优先用这个定位）
    switch_camera_resource_ids: List[str] = field(default_factory=lambda: [
        "com.android.camera2:id/switch_camera",
        "com.android.camera:id/switch_camera",
        "switch_camera",
    ])
    # 快门/录像按钮文字兜底
    shutter_text_fallback: str = "拍照"
    record_text_fallback: str = "录制"
    # 底部按钮垂直位置比例（0.0~1.0，屏幕百分比）
    button_y_ratio: float = 0.88
    # 前后置切换按钮兜底坐标比例（找不到resourceId和关键词时用）(x%, y%)
    switch_camera_fallback_x_ratio: float = 0.9
    switch_camera_fallback_y_ratio: float = 0.08
    # 前后置切换按钮关键词
    switch_camera_keywords: List[str] = field(default_factory=lambda: [
        "后置", "后摄", "切换", "翻转", "rotate", "Flip",
    ])
    # 前置关键词
    front_camera_keywords: List[str] = field(default_factory=lambda: [
        "前置", "前摄", "切换", "翻转", "rotate", "Flip",
    ])
    # 拍照模式关键词
    photo_mode_keywords: List[str] = field(default_factory=lambda: [
        "拍照", "PHOTO", "Photo", "photo", "普通", "标准",
    ])
    # 录像模式关键词
    video_mode_keywords: List[str] = field(default_factory=lambda: [
        "录像", "视频", "VIDEO", "Video", "video", "录影",
    ])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CameraUISettings":
        _defaults = cls()
        return cls(
            package_name=str(data.get("package_name", "com.android.camera2")),
            shutter_resource_ids=list(data.get("shutter_resource_ids", _defaults.shutter_resource_ids)),
            record_resource_ids=list(data.get("record_resource_ids", _defaults.record_resource_ids)),
            switch_camera_resource_ids=list(data.get("switch_camera_resource_ids", _defaults.switch_camera_resource_ids)),
            shutter_text_fallback=str(data.get("shutter_text_fallback", "拍照")),
            record_text_fallback=str(data.get("record_text_fallback", "录制")),
            button_y_ratio=float(data.get("button_y_ratio", 0.88)),
            switch_camera_fallback_x_ratio=float(data.get("switch_camera_fallback_x_ratio", 0.9)),
            switch_camera_fallback_y_ratio=float(data.get("switch_camera_fallback_y_ratio", 0.08)),
            switch_camera_keywords=list(data.get("switch_camera_keywords", _defaults.switch_camera_keywords)),
            front_camera_keywords=list(data.get("front_camera_keywords", _defaults.front_camera_keywords)),
            photo_mode_keywords=list(data.get("photo_mode_keywords", _defaults.photo_mode_keywords)),
            video_mode_keywords=list(data.get("video_mode_keywords", _defaults.video_mode_keywords)),
        )


@dataclass
class AppConfig:
    """全局配置"""
    package_name: str = "com.android.camera2"
    monitor_processes: str = "all"
    thresholds: JankLevelThresholds = field(default_factory=JankLevelThresholds)
    camera_ui: CameraUISettings = field(default_factory=CameraUISettings)
    cases: List[TestCaseConfig] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "package_name": self.package_name,
            "monitor_processes": self.monitor_processes,
            "thresholds": self.thresholds.to_dict(),
            "camera_ui": self.camera_ui.to_dict(),
            "cases": [c.to_dict() for c in self.cases],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        thresholds = JankLevelThresholds.from_dict(data.get("thresholds", {})) if data.get("thresholds") else JankLevelThresholds()
        camera_ui = CameraUISettings.from_dict(data.get("camera_ui", {})) if data.get("camera_ui") else CameraUISettings()
        cases = [TestCaseConfig.from_dict(c) for c in data.get("cases", [])]
        return cls(
            package_name=str(data.get("package_name", "com.android.camera2")),
            monitor_processes=str(data.get("monitor_processes", "all")),
            thresholds=thresholds,
            camera_ui=camera_ui,
            cases=cases,
        )


def default_config() -> AppConfig:
    """生成默认配置，包含6个相机Case（4拍照+2录像，对应需求Excel）"""
    cfg = AppConfig(
        package_name="com.android.camera2",
        monitor_processes="com.android.camera2",
        thresholds=JankLevelThresholds(
            tiny_min=34.0, tiny_max=67.0,
            slight_min=67.0, slight_max=100.0,
            obvious_min=100.0, obvious_max=167.0,
            severe_min=167.0, severe_max=float('inf'),
        ),
        cases=[
            # ---- 拍照：后置拍照模式 x2（启动后 / 拍照后，时长5s）----
            TestCaseConfig(
                name="camera_photo_preview_001_003_启动后",
                description="【后置拍照模式】启动后预览丢帧_高亮【风景】【AI默认】",
                duration=5,
                package_name="com.android.camera2",
                monitor_processes="com.android.camera2",
                script_name="photo_rear_003_launch",
                enabled=True,
            ),
            TestCaseConfig(
                name="camera_photo_preview_001_003_拍照后",
                description="【后置拍照模式】拍照后预览丢帧_高亮【风景】【AI默认】",
                duration=5,
                package_name="com.android.camera2",
                monitor_processes="com.android.camera2",
                script_name="photo_rear_003_capture",
                enabled=True,
            ),
            # ---- 拍照：前置人像模式 x2（启动后 / 拍照后，时长5s）----
            TestCaseConfig(
                name="camera_photo_preview_001_011_启动后",
                description="【前置人像模式】启动后预览丢帧_高亮高动态【人像】【开美颜】",
                duration=5,
                package_name="com.android.camera2",
                monitor_processes="com.android.camera2",
                script_name="photo_front_011_launch",
                enabled=True,
            ),
            TestCaseConfig(
                name="camera_photo_preview_001_011_拍照后",
                description="【前置人像模式】拍照后预览丢帧_高亮高动态【人像】【开美颜】",
                duration=5,
                package_name="com.android.camera2",
                monitor_processes="com.android.camera2",
                script_name="photo_front_011_capture",
                enabled=True,
            ),
            # ---- 录像模式 x2（后置/前置，时长20s，真实点击录制按钮）----
            TestCaseConfig(
                name="Record_video_后置_003",
                description="【Record_video】录制视频卡顿丢帧-后置【1080P+30fps+美肤】高亮+人像",
                duration=20,
                package_name="com.android.camera2",
                monitor_processes="com.android.camera2",
                script_name="video_rear_003",
                enabled=True,
            ),
            TestCaseConfig(
                name="Record_video_前置_006",
                description="【Record_video】录制视频卡顿丢帧-前置【1080P+30fps+美肤】高亮+人像",
                duration=20,
                package_name="com.android.camera2",
                monitor_processes="com.android.camera2",
                script_name="video_front_006",
                enabled=True,
            ),
        ],
    )
    return cfg


def load_config(path: str = DEFAULT_CASES_JSON) -> AppConfig:
    """加载配置文件，不存在则生成默认并保存"""
    if not os.path.exists(path):
        cfg = default_config()
        save_config(cfg, path)
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AppConfig.from_dict(data)
    except Exception as e:
        print(f"加载配置失败，使用默认配置: {e}")
        return default_config()


def save_config(cfg: AppConfig, path: str = DEFAULT_CASES_JSON) -> None:
    """保存配置到JSON文件"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg.to_dict(), f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise RuntimeError(f"保存配置失败: {e}")
