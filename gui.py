from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os
import threading
import subprocess
import json
import time
import copy
from typing import Optional, List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from jank_test_tool import JankAnalysisResult
    from case_config import TestCaseConfig

from trace_analyzer import PerfettoTraceAnalyzer
from adb_utils import AdbManager
from case_config import (
    AppConfig, TestCaseConfig, JankLevelThresholds,
    load_config, save_config, default_config, DEFAULT_CASES_JSON,
)
from jank_test_tool import JankTestTool
from report_exporter import (
    SUMMARY_HEADERS, CaseSummaryRow, build_summary_row,
    export_full_report, export_summary_excel, export_summary_csv,
)
from case_scripts import list_builtin_scripts


class JankTestGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Android Jank Test Tool - Case化版本")
        self.root.geometry("1180x780")
        self.root.resizable(True, True)

        # 加载配置
        self.app_cfg: AppConfig = load_config()

        # 通用变量
        self.device_list = []
        self.selected_device = tk.StringVar()
        self.output_dir = tk.StringVar(value="./results")

        # 阈值配置 - 4级：细微/轻微/明显/严重
        self.th_tiny_min = tk.DoubleVar(value=self.app_cfg.thresholds.tiny_min)
        self.th_tiny_max = tk.DoubleVar(value=self.app_cfg.thresholds.tiny_max)
        self.th_slight_min = tk.DoubleVar(value=self.app_cfg.thresholds.slight_min)
        self.th_slight_max = tk.DoubleVar(value=self.app_cfg.thresholds.slight_max)
        self.th_obvious_min = tk.DoubleVar(value=self.app_cfg.thresholds.obvious_min)
        self.th_obvious_max = tk.DoubleVar(value=self.app_cfg.thresholds.obvious_max)
        self.th_severe_min = tk.DoubleVar(value=self.app_cfg.thresholds.severe_min)
        self.th_severe_max = tk.DoubleVar(value=99999.0)  # 仅占位，实际始终用inf

        # 分析配置
        self.analysis_mode = tk.StringVar(value="duration")
        self.frame_threshold = tk.DoubleVar(value=16.67)

        # Case表格用的内存list（直接引用app_cfg.cases但便于GUI编辑）
        self.cases: list = self.app_cfg.cases

        # Trace分析tab变量
        self.trace_file_path = tk.StringVar()
        self.analyze_mode = tk.StringVar(value="duration")
        self.analyze_threshold = tk.DoubleVar(value=16.67)
        self.analyze_process_filter = tk.StringVar(value="")
        self.last_analysis_result = None
        self.last_summary_rows = []  # 保存Case运行汇总行列表

        # 运行状态
        self._running = False
        self._stop_flag = False

        self.log_text = None
        self.setup_ui()
        self.refresh_devices()

    # ============== UI Setup ==============
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="8")
        main_frame.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        case_tab = ttk.Frame(notebook, padding="6")
        legacy_tab = ttk.Frame(notebook, padding="6")
        analyze_tab = ttk.Frame(notebook, padding="6")
        notebook.add(case_tab, text="Case运行(新)")
        notebook.add(legacy_tab, text="运行测试(旧)")
        notebook.add(analyze_tab, text="分析Trace")

        self.setup_case_tab(case_tab)
        self.setup_legacy_tab(legacy_tab)
        self.setup_analyze_tab(analyze_tab)

    # ---------- Case运行Tab ----------
    def setup_case_tab(self, parent):
        # ---------- 顶部：设备 & 输出目录 ----------
        top_frame = ttk.LabelFrame(parent, text="通用配置", padding="6")
        top_frame.pack(fill=tk.X, pady=2)

        ttk.Label(top_frame, text="设备:").grid(row=0, column=0, sticky=tk.W)
        self.device_combobox = ttk.Combobox(top_frame, textvariable=self.selected_device, state="readonly", width=22)
        self.device_combobox.grid(row=0, column=1, sticky=tk.W, padx=4)
        ttk.Button(top_frame, text="刷新设备", command=self.refresh_devices).grid(row=0, column=2, padx=4)

        ttk.Label(top_frame, text="输出目录:").grid(row=0, column=3, sticky=tk.W, padx=(16, 0))
        ttk.Entry(top_frame, textvariable=self.output_dir, width=40).grid(row=0, column=4, sticky=tk.W, padx=4)
        ttk.Button(top_frame, text="浏览", command=self.browse_output_dir).grid(row=0, column=5)

        # ---------- 卡顿等级阈值 ----------
        th_frame = ttk.LabelFrame(parent, text="卡顿等级阈值 (ms)", padding="6")
        th_frame.pack(fill=tk.X, pady=2)

        # 4列3行布局：列=细微/轻微/明显/严重，行=标题(行0)/Min(行1)/Max(行2)
        level_defs = [
            ("细微", self.th_tiny_min,   self.th_tiny_max,   False),
            ("轻微", self.th_slight_min, self.th_slight_max, False),
            ("明显", self.th_obvious_min, self.th_obvious_max, False),
            ("严重", self.th_severe_min, self.th_severe_max, True),   # 严重Max为∞，不可编辑
        ]
        for col, (name, var_min, var_max, is_severe_max) in enumerate(level_defs):
            base_col = col * 3
            # 列标题
            ttk.Label(th_frame, text=f"【{name}】").grid(
                row=0, column=base_col,
                padx=(0 if col == 0 else 16, 0), pady=(0, 2),
            )
            # Min 行
            ttk.Label(th_frame, text="Min:").grid(
                row=1, column=base_col, sticky=tk.E,
                padx=(0 if col == 0 else 16, 2),
            )
            ttk.Spinbox(th_frame, from_=0.1, to=1000.0, increment=0.5,
                        textvariable=var_min, width=7).grid(
                row=1, column=base_col + 1, sticky=tk.W,
            )
            # Max 行
            ttk.Label(th_frame, text="Max:").grid(
                row=2, column=base_col, sticky=tk.E,
                padx=(0 if col == 0 else 16, 2), pady=(4, 0),
            )
            if is_severe_max:
                # 严重Max显示∞，只读Label
                ttk.Label(th_frame, text="∞", foreground="#888",
                          width=7).grid(
                    row=2, column=base_col + 1, sticky=tk.W, pady=(4, 0),
                )
            else:
                ttk.Spinbox(th_frame, from_=0.1, to=1000.0, increment=0.5,
                            textvariable=var_max, width=7).grid(
                    row=2, column=base_col + 1, sticky=tk.W, pady=(4, 0),
                )

        ttk.Button(th_frame, text="保存阈值到配置",
                   command=self.on_save_thresholds).grid(row=0, column=12, rowspan=3, padx=(16, 0))

        # ---------- 相机UI配置（换相机APK时修改这里） ----------
        cam_frame = ttk.LabelFrame(parent, text="相机UI配置（换相机APK时修改）", padding="6")
        cam_frame.pack(fill=tk.X, pady=2)

        # 包名
        ttk.Label(cam_frame, text="包名:").grid(row=0, column=0, sticky=tk.W)
        self.cam_package_var = tk.StringVar(value=self.app_cfg.camera_ui.package_name)
        ttk.Entry(cam_frame, textvariable=self.cam_package_var, width=30).grid(row=0, column=1, sticky=tk.W, padx=(4, 12))

        # 快门按钮resourceId
        ttk.Label(cam_frame, text="快门按钮IDs\n(逗号分隔，按优先级):").grid(row=0, column=2, sticky=tk.W)
        self.cam_shutter_ids_var = tk.StringVar(
            value=", ".join(self.app_cfg.camera_ui.shutter_resource_ids))
        ttk.Entry(cam_frame, textvariable=self.cam_shutter_ids_var, width=55).grid(row=0, column=3, sticky=tk.W, padx=(4, 12))

        # 录像按钮resourceId
        ttk.Label(cam_frame, text="录像按钮IDs\n(逗号分隔):").grid(row=0, column=4, sticky=tk.W)
        self.cam_record_ids_var = tk.StringVar(
            value=", ".join(self.app_cfg.camera_ui.record_resource_ids))
        ttk.Entry(cam_frame, textvariable=self.cam_record_ids_var, width=45).grid(row=0, column=5, sticky=tk.W, padx=(4, 12))

        # 文字兜底 & 坐标兜底
        ttk.Label(cam_frame, text="快门文字兜底:").grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        self.cam_shutter_text_var = tk.StringVar(value=self.app_cfg.camera_ui.shutter_text_fallback)
        ttk.Entry(cam_frame, textvariable=self.cam_shutter_text_var, width=10).grid(row=1, column=1, sticky=tk.W, padx=(4, 12), pady=(4, 0))

        ttk.Label(cam_frame, text="录像文字兜底:").grid(row=1, column=2, sticky=tk.W, pady=(4, 0))
        self.cam_record_text_var = tk.StringVar(value=self.app_cfg.camera_ui.record_text_fallback)
        ttk.Entry(cam_frame, textvariable=self.cam_record_text_var, width=10).grid(row=1, column=3, sticky=tk.W, padx=(4, 12), pady=(4, 0))

        ttk.Label(cam_frame, text="底部按钮位置(%):").grid(row=1, column=4, sticky=tk.W, pady=(4, 0))
        self.cam_button_y_var = tk.DoubleVar(value=self.app_cfg.camera_ui.button_y_ratio * 100)
        ttk.Spinbox(cam_frame, from_=10, to=95, increment=2,
                    textvariable=self.cam_button_y_var, width=6).grid(row=1, column=5, sticky=tk.W, padx=(4, 12), pady=(4, 0))

        # 前后摄切换按钮resourceId（全局常量 camera_switch_button）
        ttk.Label(cam_frame, text="切换按钮IDs(逗号分隔，优先定位):").grid(row=2, column=0, sticky=tk.W, pady=(4, 0))
        self.cam_switch_ids_var = tk.StringVar(
            value=", ".join(self.app_cfg.camera_ui.switch_camera_resource_ids))
        ttk.Entry(cam_frame, textvariable=self.cam_switch_ids_var, width=55).grid(row=2, column=1, columnspan=3, sticky=tk.W, padx=(4, 12), pady=(4, 0))

        ttk.Label(cam_frame, text="切换兜底坐标(%):").grid(row=2, column=4, sticky=tk.W, pady=(4, 0))
        sw_frame = ttk.Frame(cam_frame)
        sw_frame.grid(row=2, column=5, sticky=tk.W, padx=(4, 12), pady=(4, 0))
        self.cam_switch_x_var = tk.DoubleVar(value=self.app_cfg.camera_ui.switch_camera_fallback_x_ratio * 100)
        self.cam_switch_y_var = tk.DoubleVar(value=self.app_cfg.camera_ui.switch_camera_fallback_y_ratio * 100)
        ttk.Label(sw_frame, text="X:").grid(row=0, column=0)
        ttk.Spinbox(sw_frame, from_=5, to=95, increment=5,
                    textvariable=self.cam_switch_x_var, width=5).grid(row=0, column=1)
        ttk.Label(sw_frame, text=" Y:").grid(row=0, column=2, padx=(8, 0))
        ttk.Spinbox(sw_frame, from_=5, to=95, increment=5,
                    textvariable=self.cam_switch_y_var, width=5).grid(row=0, column=3)

        # 模式切换关键词
        ttk.Label(cam_frame, text="拍照模式关键词(逗号分隔):").grid(row=3, column=0, sticky=tk.W, pady=(4, 0))
        self.cam_photo_kw_var = tk.StringVar(
            value=", ".join(self.app_cfg.camera_ui.photo_mode_keywords))
        ttk.Entry(cam_frame, textvariable=self.cam_photo_kw_var, width=30).grid(row=3, column=1, columnspan=2, sticky=tk.W, padx=(4, 12), pady=(4, 0))

        ttk.Label(cam_frame, text="录像模式关键词(逗号分隔):").grid(row=3, column=3, sticky=tk.W, pady=(4, 0))
        self.cam_video_kw_var = tk.StringVar(
            value=", ".join(self.app_cfg.camera_ui.video_mode_keywords))
        ttk.Entry(cam_frame, textvariable=self.cam_video_kw_var, width=30).grid(row=3, column=4, columnspan=2, sticky=tk.W, padx=(4, 12), pady=(4, 0))

        ttk.Button(cam_frame, text="应用相机UI配置到脚本",
                   command=self._apply_camera_ui).grid(row=4, column=0, columnspan=6, pady=(8, 0))

        # ---------- Case列表区 ----------
        list_frame = ttk.LabelFrame(parent, text="Case列表 (双击编辑)", padding="6")
        list_frame.pack(fill=tk.X, pady=2)

        cols = ("enabled", "name", "description", "rounds", "duration", "monitor_processes", "script_name")
        self.case_tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=7)
        headings = [("enabled", "启用", 55), ("name", "Case名", 150), ("description", "描述", 280),
                    ("rounds", "轮数", 50),
                    ("duration", "时长s", 60),
                    ("monitor_processes", "监控进程", 180), ("script_name", "脚本函数", 180)]
        for key, txt, w in headings:
            self.case_tree.heading(key, text=txt)
            self.case_tree.column(key, width=w, anchor=tk.W)
        self.case_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # 双击编辑（排除第一列enable和第四列rounds）
        self.case_tree.bind("<Double-1>", self._on_double_click_case_tree)
        # 单击第一列切换启用状态，单击轮数列编辑轮数
        self.case_tree.bind("<ButtonRelease-1>", self._on_click_case_tree)

        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.case_tree.yview)
        vsb.pack(side=tk.LEFT, fill=tk.Y)
        self.case_tree.configure(yscrollcommand=vsb.set)

        btn_frame = ttk.Frame(list_frame)
        btn_frame.pack(side=tk.LEFT, fill=tk.Y, padx=4)
        ttk.Button(btn_frame, text="新增Case", command=self.on_add_case).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="编辑Case", command=self.on_edit_case).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="删除Case", command=self.on_delete_case).pack(fill=tk.X, pady=2)
        ttk.Separator(btn_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)
        ttk.Button(btn_frame, text="上移", command=lambda: self._move_case(-1)).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="下移", command=lambda: self._move_case(1)).pack(fill=tk.X, pady=2)
        ttk.Separator(btn_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)
        ttk.Button(btn_frame, text="保存Cases配置", command=self.on_save_cases).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="打开内置脚本列表", command=self._show_builtin_scripts).pack(fill=tk.X, pady=2)

        self._refresh_case_tree()

        # ---------- 控制按钮 ----------
        ctrl = ttk.Frame(parent)
        ctrl.pack(fill=tk.X, pady=6)
        self.start_batch_btn = ttk.Button(ctrl, text="▶ 开始批量执行Cases", command=self.start_batch_run)
        self.start_batch_btn.pack(side=tk.LEFT, padx=2)
        self.stop_batch_btn = ttk.Button(ctrl, text="■ 停止", command=self.stop_batch_run, state=tk.DISABLED)
        self.stop_batch_btn.pack(side=tk.LEFT, padx=2)
        self.progress_bar = ttk.Progressbar(ctrl, mode='indeterminate')
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self.progress_label = ttk.Label(ctrl, text="")
        self.progress_label.pack(side=tk.RIGHT)

        # ---------- 汇总结果表格 ----------
        result_frame = ttk.LabelFrame(parent, text="执行结果汇总 (实时更新)", padding="6")
        result_frame.pack(fill=tk.BOTH, expand=True, pady=2)

        self.summary_tree = ttk.Treeview(result_frame, columns=SUMMARY_HEADERS, show="headings")
        for i, h in enumerate(SUMMARY_HEADERS):
            # 26列:
            # 0名称 1描述 2时长 3性能帧数(SF) 4App帧 5SF帧
            # 6总帧率 7间隔帧率 8预览FPS 9成片FPS 10帧间隔 11帧时长
            # 12-15 SF卡顿4级(细/轻/明/严)  16-19App侧4级  20-23SF侧4级  24卡顿率 25错误
            widths = [
                140, 240, 70,   # 0-2
                100, 70, 70,    # 3-5 (性能帧数SF, App帧, SF帧)
                130, 130,       # 6-7
                130, 130,       # 8-9
                110, 110,       # 10-11
                85, 85, 85, 85,  # 12-15 (SF卡顿4级)
                70, 70, 70, 70,  # 16-19
                70, 70, 70, 70,  # 20-23
                70, 200,         # 24-25
            ]
            w = widths[i] if i < len(widths) else 100
            self.summary_tree.heading(h, text=h)
            self.summary_tree.column(h, width=w,
                                     anchor=tk.CENTER if i > 1 else tk.W)
        self.summary_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sy = ttk.Scrollbar(result_frame, orient="vertical", command=self.summary_tree.yview)
        sy.pack(side=tk.LEFT, fill=tk.Y)
        self.summary_tree.configure(yscrollcommand=sy.set)
        sx = ttk.Scrollbar(result_frame, orient="horizontal", command=self.summary_tree.xview)
        sx.pack(side=tk.BOTTOM, fill=tk.X)
        self.summary_tree.configure(xscrollcommand=sx.set)

        # 导出按钮
        export_f = ttk.Frame(parent)
        export_f.pack(fill=tk.X, pady=4)
        ttk.Button(export_f, text="导出当前汇总 (Excel/CSV/JSON)", command=self.on_export_summary).pack(side=tk.RIGHT)
        ttk.Label(export_f, text="提示: 批量执行完成后会自动导出到输出目录").pack(side=tk.LEFT)

        # ---------- 日志输出 ----------
        log_frame = ttk.LabelFrame(parent, text="日志输出", padding="6")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=2)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=8)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)

    # ---------- 运行测试(旧)Tab ----------
    def setup_legacy_tab(self, parent):
        device_frame = ttk.LabelFrame(parent, text="设备选择", padding="6")
        device_frame.pack(fill=tk.X, pady=2)

        ttk.Label(device_frame, text="设备:").grid(row=0, column=0, sticky=tk.W)
        ttk.Combobox(device_frame, textvariable=self.selected_device, state="readonly", width=22).grid(row=0, column=1, sticky=tk.W, padx=4)
        ttk.Button(device_frame, text="刷新", command=self.refresh_devices).grid(row=0, column=2, padx=4)

        app_frame = ttk.LabelFrame(parent, text="应用配置", padding="6")
        app_frame.pack(fill=tk.X, pady=2)

        self.selected_package = tk.StringVar(value=self.app_cfg.package_name)
        self.monitor_processes = tk.StringVar(value="all")

        ttk.Label(app_frame, text="包名:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(app_frame, textvariable=self.selected_package, width=40).grid(row=0, column=1, sticky=tk.EW, padx=4)

        ttk.Label(app_frame, text="监控进程:").grid(row=1, column=0, sticky=tk.W)
        ttk.Entry(app_frame, textvariable=self.monitor_processes, width=40).grid(row=1, column=1, sticky=tk.EW, padx=4)
        ttk.Label(app_frame, text="(逗号分隔，all=全部)").grid(row=1, column=2, sticky=tk.W)

        test_frame = ttk.LabelFrame(parent, text="测试配置", padding="6")
        test_frame.pack(fill=tk.X, pady=2)
        self.test_type = tk.StringVar(value="manual")
        self.event_count = tk.IntVar(value=1000)
        self.throttle = tk.IntVar(value=100)
        self.duration = tk.IntVar(value=30)
        self.legacy_analysis_mode = tk.StringVar(value="jank_field")
        self.legacy_threshold = tk.DoubleVar(value=16.67)

        ttk.Radiobutton(test_frame, text="手动测试", variable=self.test_type, value="manual").grid(row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(test_frame, text="Monkey测试", variable=self.test_type, value="monkey").grid(row=0, column=1, sticky=tk.W)
        ttk.Label(test_frame, text="事件数:").grid(row=1, column=0, sticky=tk.W)
        ttk.Spinbox(test_frame, from_=100, to=5000, textvariable=self.event_count, width=8).grid(row=1, column=1)
        ttk.Label(test_frame, text="间隔ms:").grid(row=1, column=2, sticky=tk.W)
        ttk.Spinbox(test_frame, from_=10, to=1000, textvariable=self.throttle, width=8).grid(row=1, column=3)
        ttk.Label(test_frame, text="录制时长s:").grid(row=2, column=0, sticky=tk.W)
        ttk.Spinbox(test_frame, from_=5, to=600, textvariable=self.duration, width=8).grid(row=2, column=1)
        ttk.Label(test_frame, text="输出目录:").grid(row=3, column=0, sticky=tk.W)
        ttk.Entry(test_frame, textvariable=self.output_dir, width=30).grid(row=3, column=1, sticky=tk.EW, columnspan=3)
        ttk.Button(test_frame, text="浏览", command=self.browse_output_dir).grid(row=3, column=4, padx=4)

        ctrl = ttk.Frame(parent)
        ctrl.pack(fill=tk.X, pady=6)
        self.legacy_start_btn = ttk.Button(ctrl, text="开始测试", command=self.start_legacy_test)
        self.legacy_start_btn.pack(side=tk.LEFT, padx=4)
        self.legacy_stop_btn = ttk.Button(ctrl, text="停止测试", command=self.stop_legacy_test, state=tk.DISABLED)
        self.legacy_stop_btn.pack(side=tk.LEFT, padx=4)

        log_frame = ttk.LabelFrame(parent, text="日志输出", padding="6")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=2)
        self.legacy_log = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=20)
        self.legacy_log.pack(fill=tk.BOTH, expand=True)
        self.legacy_log.config(state=tk.DISABLED)

    # ---------- 分析Trace Tab ----------
    def setup_analyze_tab(self, parent):
        file_frame = ttk.LabelFrame(parent, text="Trace文件", padding="6")
        file_frame.pack(fill=tk.X, pady=2)

        ttk.Entry(file_frame, textvariable=self.trace_file_path, width=60).grid(row=0, column=0, sticky=tk.EW)
        ttk.Button(file_frame, text="浏览", command=self.browse_trace_file).grid(row=0, column=1, padx=4)
        ttk.Button(file_frame, text="分析", command=self.analyze_trace).grid(row=0, column=2, padx=4)

        cfg_frame = ttk.LabelFrame(parent, text="分析配置 & 卡顿等级阈值", padding="6")
        cfg_frame.pack(fill=tk.X, pady=2)

        ttk.Label(cfg_frame, text="进程过滤:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(cfg_frame, textvariable=self.analyze_process_filter, width=28).grid(row=0, column=1, sticky=tk.EW)
        ttk.Label(cfg_frame, text="(逗号分隔，空=全部)").grid(row=0, column=2, sticky=tk.W, padx=4)

        # 4列3行布局：列=细微/轻微/明显/严重，行=标题(行1)/Min(行2)/Max(行3)
        level_defs = [
            ("细微", self.th_tiny_min,   self.th_tiny_max,   False),
            ("轻微", self.th_slight_min, self.th_slight_max, False),
            ("明显", self.th_obvious_min, self.th_obvious_max, False),
            ("严重", self.th_severe_min, self.th_severe_max, True),   # 严重Max为∞，不可编辑
        ]
        for col, (name, var_min, var_max, is_severe_max) in enumerate(level_defs):
            base_col = col * 2
            ttk.Label(cfg_frame, text=f"【{name}】").grid(
                row=1, column=base_col,
                padx=(0 if col == 0 else 20, 0), pady=(8, 2),
            )
            ttk.Label(cfg_frame, text="Min:").grid(
                row=2, column=base_col, sticky=tk.E,
                padx=(0 if col == 0 else 20, 2),
            )
            ttk.Spinbox(cfg_frame, from_=0.1, to=1000.0, increment=0.5,
                        textvariable=var_min, width=7).grid(
                row=2, column=base_col + 1, sticky=tk.W,
            )
            ttk.Label(cfg_frame, text="Max:").grid(
                row=3, column=base_col, sticky=tk.E,
                padx=(0 if col == 0 else 20, 2), pady=(4, 0),
            )
            if is_severe_max:
                # 严重Max显示∞，只读Label
                ttk.Label(cfg_frame, text="∞", foreground="#888",
                          width=7).grid(
                    row=3, column=base_col + 1, sticky=tk.W, pady=(4, 0),
                )
            else:
                ttk.Spinbox(cfg_frame, from_=0.1, to=1000.0, increment=0.5,
                            textvariable=var_max, width=7).grid(
                    row=3, column=base_col + 1, sticky=tk.W, pady=(4, 0),
                )

        result_frame = ttk.LabelFrame(parent, text="分析结果", padding="6")
        result_frame.pack(fill=tk.BOTH, expand=True, pady=2)

        self.result_text = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD, height=20)
        self.result_text.pack(fill=tk.BOTH, expand=True)
        self.result_text.config(state=tk.DISABLED)

        export = ttk.Frame(parent)
        export.pack(fill=tk.X, pady=4)
        ttk.Button(export, text="导出JSON报告", command=self.export_report).pack(side=tk.RIGHT)

    # ============== Helpers ==============
    def _current_thresholds(self) -> JankLevelThresholds:
        return JankLevelThresholds(
            tiny_min=float(self.th_tiny_min.get()),
            tiny_max=float(self.th_tiny_max.get()),
            slight_min=float(self.th_slight_min.get()),
            slight_max=float(self.th_slight_max.get()),
            obvious_min=float(self.th_obvious_min.get()),
            obvious_max=float(self.th_obvious_max.get()),
            severe_min=float(self.th_severe_min.get()),
            severe_max=float('inf'),  # 严重Max始终为∞
        )

    def _current_camera_ui(self):
        """从GUI读取当前相机UI配置"""
        from case_config import CameraUISettings
        return CameraUISettings(
            package_name=self.cam_package_var.get().strip(),
            shutter_resource_ids=[x.strip() for x in self.cam_shutter_ids_var.get().split(",") if x.strip()],
            record_resource_ids=[x.strip() for x in self.cam_record_ids_var.get().split(",") if x.strip()],
            switch_camera_resource_ids=[x.strip() for x in self.cam_switch_ids_var.get().split(",") if x.strip()],
            shutter_text_fallback=self.cam_shutter_text_var.get().strip(),
            record_text_fallback=self.cam_record_text_var.get().strip(),
            button_y_ratio=float(self.cam_button_y_var.get()) / 100.0,
            switch_camera_fallback_x_ratio=float(self.cam_switch_x_var.get()) / 100.0,
            switch_camera_fallback_y_ratio=float(self.cam_switch_y_var.get()) / 100.0,
            photo_mode_keywords=[x.strip() for x in self.cam_photo_kw_var.get().split(",") if x.strip()],
            video_mode_keywords=[x.strip() for x in self.cam_video_kw_var.get().split(",") if x.strip()],
        )

    def _apply_camera_ui(self):
        """将GUI中的相机UI配置应用到case_scripts模块（立即生效）"""
        try:
            ui = self._current_camera_ui()
            import case_scripts
            case_scripts.set_camera_ui(ui)
            # 同步到app_cfg
            self.app_cfg.camera_ui = ui
            self.app_cfg.package_name = ui.package_name
            self.log(f"[相机UI] 配置已应用: 包名={ui.package_name}, "
                     f"快门IDs={ui.shutter_resource_ids}, "
                     f"录像IDs={ui.record_resource_ids}")
            messagebox.showinfo("成功", "相机UI配置已应用到脚本！")
        except Exception as e:
            messagebox.showerror("错误", f"应用失败: {e}")

    def log(self, message: str, widget=None):
        text_w = widget or self.log_text
        if text_w is None:
            return
        text_w.config(state=tk.NORMAL)
        text_w.insert(tk.END, message + "\n")
        text_w.see(tk.END)
        text_w.config(state=tk.DISABLED)
        # 兼容日志也打印到cmd
        print(message)

    def browse_output_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.output_dir.set(d)

    def browse_trace_file(self):
        f = filedialog.askopenfilename(filetypes=[("Perfetto Trace", "*.perfetto-trace")])
        if f:
            self.trace_file_path.set(f)

    def refresh_devices(self):
        try:
            r = subprocess.run(["adb", "devices"], capture_output=True, text=True)
            lines = r.stdout.strip().split('\n')[1:]
            devices = [p[0] for p in (line.split() for line in lines if line.strip()) if p]
            self.device_list = devices
            try:
                self.device_combobox['values'] = devices
            except Exception:
                pass
            if devices:
                self.selected_device.set(devices[0])
            else:
                self.selected_device.set("")
        except Exception as e:
            self.log(f"获取设备列表失败: {e}")

    # ============== Case List ==============
    def _refresh_case_tree(self):
        for iid in self.case_tree.get_children():
            self.case_tree.delete(iid)
        for idx, case in enumerate(self.cases):
            self.case_tree.insert(
                "", tk.END, iid=str(idx),
                values=(
                    "✓" if case.enabled else "",
                    case.name, case.description,
                    case.rounds,
                    case.duration,
                    case.monitor_processes,
                    case.script_name,
                )
            )

    def _on_click_case_tree(self, event):
        """点击第一列切换启用状态；点击第四列(#4)轮数弹出输入框修改"""
        region = self.case_tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        column = self.case_tree.identify_column(event.x)
        row_id = self.case_tree.identify_row(event.y)
        if not row_id:
            return
        try:
            idx = int(row_id)
            if not (0 <= idx < len(self.cases)):
                return
        except (ValueError, IndexError):
            return

        if column == "#1":  # 第一列(enabled)
            self.cases[idx].enabled = not self.cases[idx].enabled
            self._refresh_case_tree()
            self.case_tree.selection_set(row_id)
            return

        if column == "#4":  # 第四列(rounds)  列序: 1启用 2Case名 3描述 4轮数 5时长...
            cur = self.cases[idx].rounds
            import tkinter.simpledialog as sd
            new_val = sd.askinteger(
                f"设置轮数", f"Case {self.cases[idx].name} 运行轮数:",
                initialvalue=cur, minvalue=1, maxvalue=100, parent=self.root
            )
            if new_val is not None and new_val > 0:
                self.cases[idx].rounds = new_val
                self._refresh_case_tree()
                self.case_tree.selection_set(row_id)
            return

    def _on_double_click_case_tree(self, event):
        """双击编辑，但第一列(启用)和第四列(轮数)不触发编辑对话框（已专用处理）"""
        region = self.case_tree.identify_region(event.x, event.y)
        if region == "cell":
            column = self.case_tree.identify_column(event.x)
            if column in ("#1", "#4"):
                return
        self.on_edit_case()

    def _selected_case_index(self) -> "Optional[int]":
        sel = self.case_tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except Exception:
            return None

    def on_add_case(self):
        new_case = TestCaseConfig(
            name=f"case{len(self.cases)+1}",
            description="新Case",
            duration=10,
            package_name=self.app_cfg.package_name,
            monitor_processes=self.app_cfg.monitor_processes,
            script_name="", script_path="", enabled=True,
        )
        ok = self._open_case_dialog(new_case, title="新增Case")
        if ok:
            self.cases.append(new_case)
            self._refresh_case_tree()

    def on_edit_case(self):
        idx = self._selected_case_index()
        if idx is None or idx >= len(self.cases):
            messagebox.showwarning("提示", "请先选择一个Case")
            return
        case = self.cases[idx]
        temp = copy.deepcopy(case)
        if self._open_case_dialog(temp, title=f"编辑 {case.name}"):
            self.cases[idx] = temp
            self._refresh_case_tree()

    def on_delete_case(self):
        idx = self._selected_case_index()
        if idx is None:
            messagebox.showwarning("提示", "请先选择一个Case")
            return
        if messagebox.askyesno("确认", f"删除Case {self.cases[idx].name}?"):
            self.cases.pop(idx)
            self._refresh_case_tree()

    def _move_case(self, delta: int):
        idx = self._selected_case_index()
        if idx is None:
            return
        n_idx = idx + delta
        if 0 <= n_idx < len(self.cases):
            self.cases[idx], self.cases[n_idx] = self.cases[n_idx], self.cases[idx]
            self._refresh_case_tree()
            self.case_tree.selection_set(str(n_idx))

    def on_save_thresholds(self):
        self.app_cfg.thresholds = self._current_thresholds()
        try:
            save_config(self.app_cfg)
            messagebox.showinfo("成功", f"阈值已保存到: {DEFAULT_CASES_JSON}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")

    def on_save_cases(self):
        self.app_cfg.cases = list(self.cases)
        self.app_cfg.thresholds = self._current_thresholds()
        self.app_cfg.camera_ui = self._current_camera_ui()
        self.app_cfg.package_name = self.app_cfg.camera_ui.package_name
        try:
            save_config(self.app_cfg)
            messagebox.showinfo("成功", f"配置已保存到: {DEFAULT_CASES_JSON}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")

    def _show_builtin_scripts(self):
        scripts = list_builtin_scripts()
        msg = "内置Case脚本函数:\n\n" + "\n".join("  - " + s for s in scripts) + \
              "\n\n使用方法: 在Case的'脚本函数'字段里填入函数名即可。"
        messagebox.showinfo("内置脚本", msg)

    def _open_case_dialog(self, case: TestCaseConfig, title: str = "Case") -> bool:
        """返回True表示用户点击了保存"""
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.geometry("560x420")
        dlg.transient(self.root)
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        name_var = tk.StringVar(value=case.name)
        desc_var = tk.StringVar(value=case.description)
        dur_var = tk.IntVar(value=case.duration)
        rnd_var = tk.IntVar(value=case.rounds)
        mon_var = tk.StringVar(value=case.monitor_processes)
        scr_var = tk.StringVar(value=case.script_name)
        enabled_var = tk.BooleanVar(value=case.enabled)

        def row(r, label, widget):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky=tk.W, pady=4, padx=2)
            widget.grid(row=r, column=1, sticky=tk.EW, pady=4, padx=2)

        frm.columnconfigure(1, weight=1)
        row(0, "Case名称:", ttk.Entry(frm, textvariable=name_var))
        row(1, "描述:", ttk.Entry(frm, textvariable=desc_var))
        row(2, "录制时长(秒):", ttk.Spinbox(frm, from_=1, to=600, textvariable=dur_var, width=10))
        row(3, "运行轮数:", ttk.Spinbox(frm, from_=1, to=100, textvariable=rnd_var, width=10))
        row(4, "监控进程 (all/逗号分隔):", ttk.Entry(frm, textvariable=mon_var))
        row(5, "脚本函数 (内置或自定义文件中):", ttk.Entry(frm, textvariable=scr_var))
        ttk.Checkbutton(frm, text="启用本Case", variable=enabled_var).grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=6)

        saved = {"ok": False}

        def on_ok():
            if not name_var.get().strip():
                messagebox.showwarning("提示", "Case名称不能为空", parent=dlg)
                return
            case.name = name_var.get().strip()
            case.description = desc_var.get()
            case.duration = int(dur_var.get() or 10)
            case.rounds = int(rnd_var.get() or 1)
            if case.rounds < 1:
                case.rounds = 1
            case.monitor_processes = mon_var.get() or "all"
            case.script_name = scr_var.get()
            case.script_path = ""  # 不再使用脚本文件
            case.enabled = enabled_var.get()
            saved["ok"] = True
            dlg.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=7, column=0, columnspan=3, sticky=tk.EW, pady=10)
        ttk.Button(btns, text="保存", command=on_ok).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side=tk.RIGHT)
        dlg.wait_window()
        return saved["ok"]

    # ============== Case批量执行 ==============
    def start_batch_run(self):
        if self._running:
            return
        if not self.selected_device.get():
            messagebox.showwarning("提示", "请选择设备")
            return
        enabled = [c for c in self.cases if c.enabled]
        if not enabled:
            messagebox.showwarning("提示", "没有启用的Case，请先在Case列表中勾选启用并保存")
            return
        output = self.output_dir.get().strip() or "./results"
        os.makedirs(output, exist_ok=True)

        self._running = True
        self._stop_flag = False
        self.start_batch_btn.config(state=tk.DISABLED)
        self.stop_batch_btn.config(state=tk.NORMAL)
        self.progress_bar.start()
        self.progress_label.config(text="批量执行中...")
        self.last_summary_rows = []
        for iid in self.summary_tree.get_children():
            self.summary_tree.delete(iid)

        threading.Thread(target=self._batch_run_thread, daemon=True).start()

    def stop_batch_run(self):
        self._stop_flag = True
        self.progress_label.config(text="停止中...")
        try:
            subprocess.run(["adb", "-s", self.selected_device.get(), "shell", "killall", "-SIGINT", "perfetto"], capture_output=True)
            self.log("已发送停止Perfetto信号")
        except Exception:
            pass

    def _batch_run_thread(self):
        try:
            device = self.selected_device.get()
            base_output = self.output_dir.get().strip() or "./results"

            # 生成两级目录: {base_output}/{yyyymmddHHMM}/{device_SN}/
            import datetime as _dt
            time_stamp = _dt.datetime.now().strftime("%Y%m%d%H%M")
            device_sn = device  # adb devices 列出的ID就是设备SN
            output_dir = os.path.join(base_output, time_stamp, device_sn)
            os.makedirs(output_dir, exist_ok=True)
            self.log(f"[初始化] 结果输出目录: {output_dir}")

            # 自动注入相机UI配置到case_scripts
            try:
                ui = self._current_camera_ui()
                import case_scripts
                case_scripts.set_camera_ui(ui)
                self.app_cfg.camera_ui = ui
                self.log(f"[初始化] 相机UI配置已加载: 包名={ui.package_name}")
            except Exception as e:
                self.log(f"[初始化] 相机UI配置加载失败(使用默认): {e}")

            tool = JankTestTool(device_id=device)
            tool.connect_device(device)
            enabled_cases = [c for c in self.cases if c.enabled]
            total_tasks = sum(max(c.rounds, 1) for c in enabled_cases)
            self.log(f"[批量] 已连接设备 {device}，共 {len(enabled_cases)} 个启用Case，{total_tasks} 轮")

            # 用可变容器让回调能实时访问已生成的rows
            live_rows: list = []

            def _on_done(c, r, e, ri=1, rn=1, dt=0, tt=1):
                # engine已把每轮的row加入live_rows（通过闭包引用）
                self.last_summary_rows = list(live_rows)
                self.root.after(0, self._on_case_done_ui, c, r, e, ri, rn, dt, tt)

            rows, details = tool.run_case_batch(
                cases=list(self.cases),
                output_dir=output_dir,
                analysis_mode=self.analysis_mode.get(),
                frame_threshold_ms=float(self.frame_threshold.get()),
                jank_level_thresholds=self._current_thresholds(),
                logger=lambda m: self.log(m),
                should_stop=lambda: self._stop_flag,
                on_case_done=_on_done,
                live_rows=live_rows,  # 传入可变列表
            )
            self.last_summary_rows = rows
            self.root.after(0, self._refresh_summary_tree, rows)
            self.log(f"[批量] 全部完成，共 {len(rows)} 行数据（每轮+AVG），报告已输出到 {output_dir}")
        except Exception as e:
            self.log(f"[批量] 执行异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.root.after(0, self._end_batch_ui)

    def _on_case_done_ui(self, case, result, err,
                        round_i=1, rounds=1, done=0, total=1):
        """每轮完成回调：更新进度条+实时刷新汇总表格"""
        # 进度展示
        if total > 0:
            self.progress_label.config(
                text=f"{case.name} 轮{round_i}/{rounds}  总体 {done}/{total}"
            )
        # 实时刷新汇总表格（engine已把每轮行加入summary_rows）
        rows = self.last_summary_rows
        if rows:
            self._refresh_summary_tree(rows)

    def _refresh_summary_tree(self, rows):
        for iid in self.summary_tree.get_children():
            self.summary_tree.delete(iid)
        for r in rows:
            self.summary_tree.insert("", tk.END, values=r.to_row())

    def _end_batch_ui(self):
        self._running = False
        self._stop_flag = False
        self.start_batch_btn.config(state=tk.NORMAL)
        self.stop_batch_btn.config(state=tk.DISABLED)
        self.progress_bar.stop()
        self.progress_label.config(text="完成" if not self._stop_flag else "已停止")

    # ============== 导出汇总 ==============
    def on_export_summary(self):
        if not self.last_summary_rows:
            messagebox.showwarning("提示", "暂无结果可导出，请先执行Case批量测试")
            return
        out_dir = self.output_dir.get().strip() or "./results"
        os.makedirs(out_dir, exist_ok=True)
        filename = filedialog.asksaveasfilename(
            initialdir=out_dir,
            initialfile="jank_cases_summary.xlsx",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv"), ("JSON", "*.json")],
        )
        if not filename:
            return
        base, ext = os.path.splitext(filename)
        try:
            if ext.lower() == ".csv":
                export_summary_csv(self.last_summary_rows, filename)
            elif ext.lower() == ".json":
                data = {"headers": SUMMARY_HEADERS,
                        "rows": [dict(zip(SUMMARY_HEADERS, r.to_row())) for r in self.last_summary_rows]}
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            else:
                export_summary_excel(self.last_summary_rows, filename)
            messagebox.showinfo("成功", f"已导出到:\n{filename}")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {e}")

    # ============== 旧模式运行 ==============
    def start_legacy_test(self):
        if self._running:
            return
        if not self.selected_device.get():
            messagebox.showwarning("警告", "请选择设备")
            return
        self._running = True
        self.legacy_start_btn.config(state=tk.DISABLED)
        self.legacy_stop_btn.config(state=tk.NORMAL)
        threading.Thread(target=self._legacy_thread, daemon=True).start()

    def stop_legacy_test(self):
        self._stop_flag = True
        try:
            subprocess.run(["adb", "-s", self.selected_device.get(), "shell", "killall", "-SIGINT", "perfetto"], capture_output=True)
        except Exception:
            pass

    def _legacy_thread(self):
        def _log(m):
            self.root.after(0, lambda: self.log(m, self.legacy_log))
        try:
            device = self.selected_device.get()
            package = self.selected_package.get()
            base_output = self.output_dir.get().strip() or "./results"

            # 生成两级目录: {base_output}/{yyyymmddHHMM}/{device_SN}/
            import datetime as _dt
            time_stamp = _dt.datetime.now().strftime("%Y%m%d%H%M")
            device_sn = device
            output = os.path.join(base_output, time_stamp, device_sn)
            os.makedirs(output, exist_ok=True)
            _log(f"[初始化] 结果输出目录: {output}")

            adb = AdbManager(device_id=device)
            monitor = self.monitor_processes.get()
            _log("启动Perfetto trace录制...")
            adb.start_perfetto_trace(
                duration=int(self.duration.get()), buffer_size="100",
                monitor_processes=monitor,
            )
            _log("Trace录制已启动")
            time.sleep(2)

            if self.test_type.get() == "monkey":
                _log(f"启动Monkey: {self.event_count.get()} 事件, 间隔{self.throttle.get()}ms")
                adb.shell_command(
                    f"monkey -p {package} -v {self.event_count.get()} --throttle {self.throttle.get()}",
                    device_id=device,
                )
                _log("Monkey测试完成")
            else:
                _log("手动模式，请操作设备...")
                total = int(self.duration.get())
                for i in range(total):
                    if self._stop_flag:
                        break
                    time.sleep(1)
                _log("手动模式结束")

            _log("停止trace录制...")
            adb.stop_perfetto_trace()
            time.sleep(3)

            trace_file = os.path.join(output, f"legacy_{package}.perfetto-trace")
            report_file = os.path.join(output, f"legacy_{package}_report.json")
            _log("拉取trace文件...")
            adb.pull_trace_file(local_path=trace_file)

            _log("分析trace文件...")
            analyzer = PerfettoTraceAnalyzer()
            mode = self.legacy_analysis_mode.get()
            th = float(self.legacy_threshold.get())
            proc_list = None if (monitor.strip() == "all" or monitor.strip() == "") else [p.strip() for p in monitor.split(",") if p.strip()]
            result = analyzer.analyze_jank(trace_file, frame_threshold_ms=th, analysis_mode=mode,
                                           process_filter=proc_list,
                                           jank_level_thresholds=self._current_thresholds(),
                                           record_duration_s=float(self.duration.get()))
            report = analyzer.export_jank_report(trace_file, report_file,
                                                 frame_threshold_ms=th, analysis_mode=mode,
                                                 process_filter=proc_list,
                                                 jank_level_thresholds=self._current_thresholds(),
                                                 record_duration_s=float(self.duration.get()))
            jl = result.jank_level_breakdown
            _log(f"\n=== 分析结果 ===")
            _log(f"总帧数: {result.total_frames}, 卡顿帧数: {result.jank_frames}, 卡顿率: {result.jank_ratio * 100:.2f}%")
            _log(f"平均帧率(时长/帧间隔): {result.avg_fps_by_duration:.2f} / {result.avg_fps_by_frame_interval:.2f} FPS")
            _log(f"最大帧间隔(ts差): {result.max_frame_gap_ms:.2f} ms, 最大帧时长(dur): {result.max_frame_dur_ms:.2f} ms")
            _log(f"轻微卡顿: {jl.slight}, 明显卡顿: {jl.obvious}, 严重卡顿: {jl.severe}")
            # 按来源分类打印
            src_map = {"app": "App侧", "sf": "SF侧(SurfaceFlinger)", "other": "其他进程", "all": "全部进程"}
            src_keys = sorted(set(list(result.per_source_total_frames.keys()) + list(result.per_source_jank_frames.keys())))
            for sk in src_keys:
                label = src_map.get(sk, sk)
                st = result.per_source_total_frames.get(sk, 0)
                sj = result.per_source_jank_frames.get(sk, 0)
                sb = result.per_source_jank_level.get(sk)
                if sb is None:
                    sb_s, sb_o, sb_se = 0, 0, 0
                else:
                    sb_s, sb_o, sb_se = sb.slight, sb.obvious, sb.severe
                _log(f"[{label}] 总帧={st}, 卡顿帧={sj}, 轻微={sb_s}, 明显={sb_o}, 严重={sb_se}")
            _log(f"报告已保存到: {report_file}")
        except Exception as e:
            _log(f"测试失败: {e}")
            import traceback
            traceback.print_exc()
        finally:
            def _end():
                self._running = False
                self._stop_flag = False
                self.legacy_start_btn.config(state=tk.NORMAL)
                self.legacy_stop_btn.config(state=tk.DISABLED)
            self.root.after(0, _end)

    # ============== Trace分析 ==============
    def analyze_trace(self):
        trace_file = self.trace_file_path.get()
        if not trace_file or not os.path.exists(trace_file):
            messagebox.showwarning("警告", "请选择有效的trace文件")
            return
        try:
            analyzer = PerfettoTraceAnalyzer()
            mode = self.analyze_mode.get()
            th = float(self.analyze_threshold.get())
            pf_str = self.analyze_process_filter.get()
            pf = None if not pf_str.strip() else [p.strip() for p in pf_str.split(",") if p.strip()]
            thresholds = self._current_thresholds()

            result = analyzer.analyze_jank(trace_file, frame_threshold_ms=th, analysis_mode=mode,
                                           process_filter=pf, jank_level_thresholds=thresholds)

            output_dir = self.output_dir.get().strip() or "./results"
            os.makedirs(output_dir, exist_ok=True)
            report_file = os.path.join(output_dir, "analysis_report.json")
            report = analyzer.export_jank_report(trace_file, report_file,
                                                 frame_threshold_ms=th, analysis_mode=mode,
                                                 process_filter=pf, jank_level_thresholds=thresholds)

            self.last_analysis_result = report
            self.result_text.config(state=tk.NORMAL)
            self.result_text.delete(1.0, tk.END)

            a = report["analysis"]
            s = (
                f"=== Trace分析报告 ===\n"
                f"文件: {os.path.basename(trace_file)}\n"
                f"分析模式: {report['analysis_mode']}\n\n"
                f"总帧数: {a['total_frames']}\n"
                f"卡顿帧数: {a['jank_frames']}  卡顿率: {a['jank_ratio_percent']:.2f}%\n"
                f"平均帧率(按时长): {a['avg_fps_by_duration']:.2f} FPS\n"
                f"平均帧率(按帧间隔): {a['avg_fps_by_frame_interval']:.2f} FPS\n"
                f"最大帧间隔(ts差): {a['max_frame_gap_ms']:.2f} ms\n"
                f"最大帧时长(dur): {a['max_frame_dur_ms']:.2f} ms\n"
                f"平均帧时长: {a['avg_frame_time_ms']:.2f} ms\n\n"
            )
            jl = report.get("jank_level_breakdown", {})
            s += f"--- 卡顿等级分类(阈值: {self.th_slight_min.get()}-{self.th_slight_max.get()}ms 轻微; " \
                 f"{self.th_obvious_min.get()}-{self.th_obvious_max.get()}ms 明显; " \
                 f">={self.th_severe_min.get()}ms 严重) ---\n"
            s += f"  轻微: {jl.get('slight', 0)}, 明显: {jl.get('obvious', 0)}, 严重: {jl.get('severe', 0)}\n\n"

            # 按来源分类展示
            per_src = report.get("per_source_breakdown") or {}
            if per_src:
                s += "--- 按帧来源分类 (方案A: 用户进程 + 自动附加SF) ---\n"
                src_label_map = {"app": "App侧(用户指定进程)", "sf": "SF侧(SurfaceFlinger)", "other": "其他进程", "all": "全部进程"}
                for src_key in sorted(per_src.keys()):
                    info = per_src[src_key]
                    label = info.get("label") or src_label_map.get(src_key, src_key)
                    bd = info.get("jank_level_breakdown", {}) or {}
                    s += (f"  [{label}] 总帧={info.get('total_frames', 0)}, "
                          f"卡顿帧={info.get('jank_frames', 0)} ({info.get('jank_ratio_percent', 0):.2f}%), "
                          f"轻微={bd.get('slight', 0)}, 明显={bd.get('obvious', 0)}, 严重={bd.get('severe', 0)}\n")
                s += "\n"

            if report.get("jank_type_breakdown"):
                s += "--- Jank类型分布 ---\n"
                for k, v in sorted(report["jank_type_breakdown"].items(), key=lambda x: -x[1]):
                    s += f"  {k}: {v}\n"
                s += "\n"
            if report.get("duration_threshold_breakdown"):
                s += "--- 超出帧时长阈值统计 ---\n"
                for k, v in report["duration_threshold_breakdown"].items():
                    s += f"  {k}: {v}\n"
                s += "\n"
            if report["jank_events"]:
                s += "--- 卡顿事件(前10条) ---\n"
                source_short = {"app": "APP", "sf": "SF", "other": "OTH", "all": "ALL"}
                for i, ev in enumerate(report["jank_events"][:10]):
                    s += f"\n[{i+1}] ts={ev['timestamp_ns']}ns, dur={ev['duration_ms']}ms"
                    src = ev.get("frame_source")
                    if src:
                        s += f", src={source_short.get(src, src)}"
                    if ev.get("jank_level"):
                        s += f", level={ev['jank_level']}"
                    if ev.get("jank_type"):
                        s += f", jank_type={ev['jank_type']}"
                    if ev.get("process_name"):
                        s += f", proc={ev['process_name']}"
                    if ev.get("exceeded_thresholds"):
                        s += f", exceeded={ev['exceeded_thresholds']}"
            self.result_text.insert(tk.END, s)
            self.result_text.config(state=tk.DISABLED)
            messagebox.showinfo("成功", f"分析完成，报告已保存: {report_file}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("错误", f"分析失败: {e}")

    def export_report(self):
        if not self.last_analysis_result:
            messagebox.showwarning("警告", "请先分析trace文件")
            return
        f = filedialog.asksaveasfilename(defaultextension=".json",
                                          filetypes=[("JSON", "*.json"), ("所有文件", "*.*")])
        if not f:
            return
        try:
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(self.last_analysis_result, fh, indent=2, ensure_ascii=False)
            messagebox.showinfo("成功", f"已导出: {f}")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = JankTestGUI(root)
    root.mainloop()
