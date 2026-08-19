from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, List, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from case_config import JankLevelThresholds


@dataclass
class JankEvent:
    timestamp: int
    duration: int
    frame_token: Optional[str] = None
    jank_type: Optional[str] = None
    jank_tag: Optional[str] = None
    present_type: Optional[str] = None
    on_time_finish: Optional[int] = None
    jank_severity_type: Optional[str] = None
    jank_score: Optional[float] = None
    layer_name: Optional[str] = None
    process_name: Optional[str] = None
    exceeded_thresholds: List[str] = field(default_factory=list)  # 超出的阈值列表
    jank_level: Optional[str] = None  # 卡顿等级：slight / obvious / severe
    frame_source: Optional[str] = None  # "app"=全部进程(非SF)帧 "sf"=SurfaceFlinger帧 "other"=其他


@dataclass
class JankLevelBreakdown:
    """按卡顿等级统计数量（4级：细微/轻微/明显/严重）"""
    tiny: int = 0    # 细微卡顿 (34-67ms)
    slight: int = 0  # 轻微卡顿 (67-100ms)
    obvious: int = 0 # 明显卡顿 (100-167ms)
    severe: int = 0  # 严重卡顿 (>=167ms)

    def to_dict(self) -> Dict[str, int]:
        return {"tiny": self.tiny, "slight": self.slight, "obvious": self.obvious, "severe": self.severe}


@dataclass
class JankAnalysisResult:
    total_frames: int
    jank_frames: int
    jank_ratio: float
    avg_frame_time: float
    max_frame_time: float
    min_frame_time: float
    jank_events: List[JankEvent]
    jank_type_breakdown: Dict[str, int] = field(default_factory=dict)
    jank_tag_breakdown: Dict[str, int] = field(default_factory=dict)
    duration_threshold_breakdown: Dict[str, int] = field(default_factory=dict)  # 帧时长阈值统计
    analysis_mode: str = "jank_field"  # jank_field 或 duration

    # ===== 新增指标 =====
    # 平均帧率（两种算法）
    avg_fps_by_duration: float = 0.0   # 总帧数 / 录制时长（秒）
    avg_fps_by_frame_interval: float = 0.0  # 1 / 平均帧间隔(秒)
    # 最大帧间隔
    max_frame_gap_ns: int = 0          # 相邻两帧ts时间戳差值最大值（ns）
    max_frame_gap_ms: float = 0.0      # 上面的值换算成ms
    max_frame_dur_ms: float = 0.0      # 帧时长(dur)最大值，复用 max_frame_time 但单独保留
    # 录制覆盖时长（基于第一帧到最后一帧的ts差）
    trace_coverage_ns: int = 0
    trace_coverage_ms: float = 0.0
    # 卡顿等级分类（基于帧时长）
    jank_level_breakdown: JankLevelBreakdown = field(default_factory=JankLevelBreakdown)
    # 录制参数（由外部填入，方便报告使用）
    record_duration_s: float = 0.0     # 设定的录制时长秒数

    # ===== 按来源(全部进程/SF侧)分类统计 =====
    # 每个来源 = {"app"/"sf"/"other"}
    per_source_total_frames: Dict[str, int] = field(default_factory=dict)
    per_source_jank_frames: Dict[str, int] = field(default_factory=dict)
    per_source_jank_level: Dict[str, JankLevelBreakdown] = field(default_factory=dict)


class PerfettoTraceAnalyzer:
    def __init__(self):
        try:
            from perfetto.trace_processor import TraceProcessor, TraceProcessorConfig
            self.TraceProcessor = TraceProcessor
            self.TraceProcessorConfig = TraceProcessorConfig
        except ImportError:
            raise RuntimeError(
                "perfetto 未安装。请运行: pip install perfetto\n"
                "或者查看: https://perfetto.dev/docs/analysis/trace-processor-python"
            )
        # 查找本地 trace_processor_shell.exe，避免 perfetto 包联网自动下载
        self.tp_bin_path: Optional[str] = self._find_trace_processor_bin()

    @staticmethod
    def _find_trace_processor_bin() -> Optional[str]:
        """
        按优先级查找 trace_processor_shell 可执行文件：
        1) 工程目录 tools/trace_processor_shell.exe  (Windows)
        2) 工程目录 tools/trace_processor_shell      (Linux/Mac)
        3) perfetto 官方缓存目录：
           ~/.local/share/perfetto/prebuilts/<version>/<platform>/trace_processor_shell(.exe)
        返回找到的绝对路径；找不到返回 None（让 perfetto 自行处理，其会尝试下载）
        """
        # 优先用工程内 tools/ 目录 —— 离线部署最稳
        project_root = os.path.dirname(os.path.abspath(__file__))
        tools_dir = os.path.join(project_root, "tools")
        candidates = [
            os.path.join(tools_dir, "trace_processor_shell.exe"),
            os.path.join(tools_dir, "trace_processor_shell"),
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        # 兜底：perfetto 预下载的官方缓存
        perfetto_home = os.path.join(os.path.expanduser("~"), ".local", "share", "perfetto", "prebuilts")
        if os.path.isdir(perfetto_home):
            # 遍历所有版本/平台找 exe
            for root, _, files in os.walk(perfetto_home):
                for fn in files:
                    if fn.startswith("trace_processor_shell"):
                        full = os.path.join(root, fn)
                        if os.access(full, os.X_OK) or fn.endswith(".exe"):
                            return full
        return None

    def _run_query(self, tp, query: str) -> List[Dict]:
        """执行SQL查询并返回字典列表"""
        result = tp.query(query)
        records = []
        
        try:
            for row in result:
                if hasattr(row, '__dict__'):
                    records.append(row.__dict__)
                elif isinstance(row, dict):
                    records.append(row)
                elif hasattr(row, 'items'):
                    records.append({k: v for k, v in row.items()})
                else:
                    col_names = result.columns() if hasattr(result, 'columns') else []
                    if col_names:
                        row_dict = {}
                        for i, col in enumerate(col_names):
                            try:
                                row_dict[col] = row[i]
                            except:
                                pass
                        records.append(row_dict)
            return records
        except Exception as e:
            raise RuntimeError(f"查询失败: {e}")

    def _safe_str(self, value) -> Optional[str]:
        if value is None or (isinstance(value, float) and str(value) == 'nan'):
            return None
        return str(value)

    def _safe_int(self, value) -> Optional[int]:
        if value is None or (isinstance(value, float) and str(value) == 'nan'):
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None

    def _safe_float(self, value) -> Optional[float]:
        if value is None or (isinstance(value, float) and str(value) == 'nan'):
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _classify_jank_level(self, frame_time_ms: float, thresholds: "JankLevelThresholds") -> Optional[str]:
        """根据帧时长判定卡顿等级，返回 tiny/slight/obvious/severe，不满足返回 None"""
        if thresholds.tiny_min <= frame_time_ms < thresholds.tiny_max:
            return "tiny"
        if thresholds.slight_min <= frame_time_ms < thresholds.slight_max:
            return "slight"
        if thresholds.obvious_min <= frame_time_ms < thresholds.obvious_max:
            return "obvious"
        if frame_time_ms >= thresholds.severe_min:
            return "severe"
        return None

    def analyze_jank(self, trace_file: str, frame_threshold_ms: float = 16.67,
                     analysis_mode: str = "jank_field",
                     duration_thresholds: List[float] = None,
                     process_filter: List[str] = None,
                     jank_level_thresholds: Optional["JankLevelThresholds"] = None,
                     record_duration_s: float = 0.0,
                     logger: Optional[Callable[[str], None]] = None) -> JankAnalysisResult:
        """
        分析trace文件中的jank

        参数:
            trace_file: trace文件路径
            frame_threshold_ms: 帧时长阈值（帧时长模式下使用）
            analysis_mode: 分析模式
                - "jank_field": 使用 actual_frame_timeline_slice 的 jank_type 等字段判定
                - "duration": 使用帧时长判定
            duration_thresholds: 帧时长阈值列表（用于统计不同级别的卡顿），如 [67, 100, 167]
            process_filter: 进程过滤列表，None 表示不过滤
            jank_level_thresholds: 卡顿等级阈值，用于分类 slight/obvious/severe
            record_duration_s: 设定的录制时长秒数，用于计算 avg_fps_by_duration
        """
        if not os.path.exists(trace_file):
            raise FileNotFoundError(f"Trace文件不存在: {trace_file}")

        # 日志输出函数（支持回传到GUI）
        _log = logger or print

        # 设置默认阈值
        if duration_thresholds is None:
            duration_thresholds = [67, 100, 167]
        if jank_level_thresholds is None:
            # 延迟导入避免循环依赖
            from case_config import JankLevelThresholds
            jank_level_thresholds = JankLevelThresholds()

        # ============================================================
        # 方案A：当用户指定具体App进程过滤时，自动附加SurfaceFlinger
        #        同时保留"用户原始过滤列表"用于区分 全部进程 vs SF侧
        # ============================================================
        SF_KEYWORDS = ("surfaceflinger", "/system/bin/surfaceflinger")

        def _is_sf_process(name: str) -> bool:
            n = (name or "").lower()
            return any(k in n for k in SF_KEYWORDS)

        # 保存原始用户输入（用于区分 全部进程 侧标签）
        user_filter_raw: List[str] = []
        if process_filter:
            # 清理空值
            user_filter_raw = [p.strip() for p in process_filter if p and p.strip()]

        # 构建实际用于过滤的 process_filter_effective：
        #   如果用户给了非空列表 → 自动补 SF；
        #   如果用户给的是 None 或空 → 表示All，保持不动。
        process_filter_effective: Optional[List[str]] = None
        if user_filter_raw:
            has_sf = any(
                _is_sf_process(p) or any(k in p.lower() for k in SF_KEYWORDS)
                for p in user_filter_raw
            )
            process_filter_effective = list(user_filter_raw)
            if not has_sf:
                # 附加：用通用名 surfaceflinger，匹配真实进程名
                process_filter_effective.append("surfaceflinger")

        # 用户侧App过滤条件：仅包含用户原始输入、且不是SF关键字的条目
        user_app_patterns = [
            p for p in user_filter_raw
            if not any(k in p.lower() for k in SF_KEYWORDS)
        ]

        def _classify_source(process_name: str) -> str:
            """给帧打来源标签：
            - SF进程 -> sf
            - 指定了App过滤列表时：匹配列表 -> app，不匹配 -> other
            - All模式（没指定App过滤）：非SF都归为 app（即"所有用户进程"）
            """
            if _is_sf_process(process_name):
                return "sf"
            # 用户明确指定了App过滤条件
            if user_app_patterns and process_name:
                for pat in user_app_patterns:
                    if pat in process_name:
                        return "app"
                return "other"
            # All 模式：非 SF 进程一律算作 全部进程
            return "app"

        # 构造 TraceProcessor 初始化参数
        if self.tp_bin_path:
            tp_config = self.TraceProcessorConfig(bin_path=self.tp_bin_path)
            _log(f"[TraceProcessor] 使用本地可执行文件: {self.tp_bin_path}")
        else:
            tp_config = self.TraceProcessorConfig()
            _log("[TraceProcessor] 未找到本地 trace_processor_shell，将使用 perfetto 内置下载（需要联网）")
        tp = self.TraceProcessor(trace=trace_file, config=tp_config)

        jank_type_breakdown: Dict[str, int] = {}
        jank_tag_breakdown: Dict[str, int] = {}
        duration_threshold_breakdown: Dict[str, int] = {}
        jank_level_breakdown = JankLevelBreakdown()
        jank_events: List[JankEvent] = []
        all_frame_times: List[float] = []
        all_timestamps: List[int] = []  # 用于计算帧间隔
        # 保存过滤后的有效帧ts/dur（计算覆盖率、帧间隔等用）
        valid_rows_ts: List[int] = []

        # SF专用数据 - 性能指标只用SF计算
        sf_frame_times: List[float] = []
        sf_valid_rows_ts: List[int] = []
        sf_jank_level_breakdown = JankLevelBreakdown()
        sf_jank_frames = 0

        # 初始化 per_source 统计
        per_source_total_frames: Dict[str, int] = {}
        per_source_jank_frames: Dict[str, int] = {}
        per_source_jank_level: Dict[str, JankLevelBreakdown] = {}

        # 使用 actual_frame_timeline_slice 表查询帧数据（包含jank信息）
        # 先尝试关联查询
        query = """
            SELECT
              af.ts,
              af.dur,
              af.surface_frame_token,
              af.jank_type,
              af.jank_tag,
              af.present_type,
              af.on_time_finish,
              af.jank_severity_type,
              af.jank_score,
              af.layer_name,
              af.upid,
              p.name AS process_name
            FROM actual_frame_timeline_slice af
            LEFT JOIN process p ON af.upid = p.upid
            WHERE af.dur > 0
            ORDER BY af.ts
        """

        try:
            rows = self._run_query(tp, query)
            _log(f"找到 {len(rows)} 个 actual_frame_timeline_slice 帧")
        except Exception as e:
            _log(f"关联查询失败: {e}")
            # 尝试不关联其他表
            simple_query = """
                SELECT
                  ts,
                  dur,
                  surface_frame_token,
                  jank_type,
                  jank_tag,
                  present_type,
                  on_time_finish,
                  jank_severity_type,
                  jank_score,
                  layer_name,
                  upid
                FROM actual_frame_timeline_slice
                WHERE dur > 0
                ORDER BY ts
            """
            try:
                rows = self._run_query(tp, simple_query)
                _log(f"找到 {len(rows)} 个 actual_frame_timeline_slice 帧(无JOIN)")
            except Exception as e2:
                _log(f"简单查询也失败: {e2}")
                rows = []

        # 先做进程过滤，得到有效帧总数（过滤后的）
        filtered_rows: List[Dict[str, Any]] = []
        skipped_rows: List[str] = []  # 记录被过滤掉的进程名，用于调试
        for row in rows:
            process_name = self._safe_str(row.get('process_name'))
            # 用"附加了SF之后的有效过滤器"做匹配
            if process_filter_effective and process_name:
                matched = False
                for proc in process_filter_effective:
                    if proc in process_name:
                        matched = True
                        break
                if not matched:
                    skipped_rows.append(process_name)
                    continue
            elif process_filter_effective and not process_name:
                # 有过滤器但进程名为空 → 也跳过
                skipped_rows.append("<无进程名>")
                continue
            # 给每行附加 frame_source 标签，后面循环直接用
            row_dict = dict(row) if not isinstance(row, dict) else row
            row_dict['_frame_source'] = _classify_source(process_name)
            filtered_rows.append(row_dict)

        total_frames = len(filtered_rows)

        # 调试日志：输出过滤详情
        if process_filter_effective:
            # 统计各进程的帧数分布（被过滤的和通过的）
            passed_names: Dict[str, int] = {}
            for r in filtered_rows:
                pn = self._safe_str(r.get('process_name')) or "<无进程名>"
                passed_names[pn] = passed_names.get(pn, 0) + 1
            skipped_names: Dict[str, int] = {}
            for sn in skipped_rows:
                skipped_names[sn] = skipped_names.get(sn, 0) + 1
            _log(f"[调试] 查询总帧={len(rows)}, 过滤后帧={total_frames}, 被过滤帧={len(skipped_rows)}")
            _log(f"[调试] 有效过滤器={process_filter_effective}")
            _log(f"[调试] 通过的进程: {passed_names}")
            _log(f"[调试] 被过滤的进程(前10): {list(skipped_names.items())[:10]}")
            # 显示所有帧的唯一进程名（帮助用户确认trace里有哪些进程）
            all_process_names = set()
            for r in rows:
                pn = self._safe_str(r.get('process_name'))
                if pn:
                    all_process_names.add(pn)
            _log(f"[调试] trace中所有进程名({len(all_process_names)}个): {sorted(all_process_names)}")
        else:
            _log(f"[调试] All模式, 无进程过滤, 总帧={total_frames}")

        # 初始化帧时长阈值统计
        for threshold in duration_thresholds:
            duration_threshold_breakdown[f">{threshold}ms"] = 0

        for row in filtered_rows:
            ts = self._safe_int(row.get('ts'))
            dur = self._safe_int(row.get('dur'))
            frame_token = self._safe_str(row.get('surface_frame_token'))
            jank_type = self._safe_str(row.get('jank_type'))
            jank_tag = self._safe_str(row.get('jank_tag'))
            present_type = self._safe_str(row.get('present_type'))
            on_time_finish = self._safe_int(row.get('on_time_finish'))
            jank_severity_type = self._safe_str(row.get('jank_severity_type'))
            jank_score = self._safe_float(row.get('jank_score'))
            layer_name = self._safe_str(row.get('layer_name'))
            process_name = self._safe_str(row.get('process_name'))
            frame_source = self._safe_str(row.get('_frame_source')) or "all"

            # ====== 按来源累加总帧数 ======
            per_source_total_frames[frame_source] = per_source_total_frames.get(frame_source, 0) + 1
            if frame_source not in per_source_jank_level:
                per_source_jank_level[frame_source] = JankLevelBreakdown()

            # 记录ts用于帧间隔
            if ts and ts > 0:
                valid_rows_ts.append(ts)

            # 计算帧时间
            frame_time_ms = 0.0
            if dur and dur > 0:
                frame_time_ms = dur / 1_000_000.0
                all_frame_times.append(frame_time_ms)

            # ====== SF专用数据收集（在frame_time_ms计算之后）======
            if frame_source == "sf":
                if ts and ts > 0:
                    sf_valid_rows_ts.append(ts)
                if frame_time_ms > 0:
                    sf_frame_times.append(frame_time_ms)

            # 判断是否为jank帧
            is_jank = False

            # 根据分析模式判定
            if analysis_mode == "jank_field":
                # Jank字段模式：使用系统标记的jank信息
                if jank_type and jank_type not in ('None', 'Unspecified', 'Not Jank', 'null'):
                    is_jank = True
                if on_time_finish == 0:
                    is_jank = True
                if present_type and 'Late' in present_type:
                    is_jank = True
                if jank_score and jank_score > 0:
                    is_jank = True
            else:
                # 帧时长模式：使用帧时长判定
                if dur and dur > 0:
                    if frame_time_ms > frame_threshold_ms:
                        is_jank = True

            # 计算超出的阈值列表
            exceeded_thresholds = []
            if dur and dur > 0:
                for threshold in duration_thresholds:
                    if frame_time_ms > threshold:
                        duration_threshold_breakdown[f">{threshold}ms"] += 1
                        exceeded_thresholds.append(f">{threshold}ms")

            # 卡顿等级分类（基于帧时长，不管当前用哪种analysis_mode都统计）
            jank_level = None
            if dur and dur > 0:
                jank_level = self._classify_jank_level(frame_time_ms, jank_level_thresholds)

            if is_jank or jank_level is not None:
                # 全局卡顿等级汇总统计（4级）
                if jank_level == "tiny":
                    jank_level_breakdown.tiny += 1
                elif jank_level == "slight":
                    jank_level_breakdown.slight += 1
                elif jank_level == "obvious":
                    jank_level_breakdown.obvious += 1
                elif jank_level == "severe":
                    jank_level_breakdown.severe += 1
                # 按来源分别累计卡顿等级
                src_breakdown = per_source_jank_level[frame_source]
                if jank_level == "tiny":
                    src_breakdown.tiny += 1
                elif jank_level == "slight":
                    src_breakdown.slight += 1
                elif jank_level == "obvious":
                    src_breakdown.obvious += 1
                elif jank_level == "severe":
                    src_breakdown.severe += 1
                # SF专用卡顿统计（只统计有等级的帧，与等级汇总一致）
                if frame_source == "sf" and jank_level is not None:
                    sf_jank_frames += 1
                    if jank_level == "tiny":
                        sf_jank_level_breakdown.tiny += 1
                    elif jank_level == "slight":
                        sf_jank_level_breakdown.slight += 1
                    elif jank_level == "obvious":
                        sf_jank_level_breakdown.obvious += 1
                    elif jank_level == "severe":
                        sf_jank_level_breakdown.severe += 1

            if is_jank:
                # 按来源累计 jank 帧数
                per_source_jank_frames[frame_source] = per_source_jank_frames.get(frame_source, 0) + 1

                jank_events.append(JankEvent(
                    timestamp=ts if ts else 0,
                    duration=dur if dur else 0,
                    frame_token=frame_token,
                    jank_type=jank_type,
                    jank_tag=jank_tag,
                    present_type=present_type,
                    on_time_finish=on_time_finish,
                    jank_severity_type=jank_severity_type,
                    jank_score=jank_score,
                    layer_name=layer_name,
                    process_name=process_name,
                    exceeded_thresholds=exceeded_thresholds,
                    jank_level=jank_level,
                    frame_source=frame_source,
                ))

                if analysis_mode == "jank_field":
                    if jank_type:
                        jank_type_breakdown[jank_type] = jank_type_breakdown.get(jank_type, 0) + 1
                    if jank_tag:
                        jank_tag_breakdown[jank_tag] = jank_tag_breakdown.get(jank_tag, 0) + 1
                else:
                    # 帧时长模式：记录超过的阈值
                    if dur and dur > 0:
                        # 找到最大的超过的阈值
                        exceeded_threshold = None
                        for threshold in sorted(duration_thresholds):
                            if frame_time_ms > threshold:
                                exceeded_threshold = threshold
                        if exceeded_threshold:
                            jank_type_breakdown[f">{exceeded_threshold}ms"] = jank_type_breakdown.get(f">{exceeded_threshold}ms", 0) + 1

        # ===== SF 专用性能指标计算 =====
        # 总帧数 = SF帧数
        sf_total_frames = len(sf_valid_rows_ts)
        total_frames = sf_total_frames  # 性能指标只用SF

        # SF卡顿统计
        jank_frames = sf_jank_frames
        jank_level_breakdown = sf_jank_level_breakdown

        jank_ratio = jank_frames / total_frames if total_frames > 0 else 0.0

        # SF帧时长统计
        if sf_frame_times:
            avg_frame_time = sum(sf_frame_times) / len(sf_frame_times)
            max_frame_time = max(sf_frame_times)
            min_frame_time = min(sf_frame_times)
        else:
            avg_frame_time = 0.0
            max_frame_time = 0.0
            min_frame_time = 0.0

        # 最大帧时长(dur) - SF
        max_frame_dur_ms = max_frame_time

        # 覆盖率（ts跨度）- SF
        trace_coverage_ns = 0
        if len(sf_valid_rows_ts) >= 2:
            trace_coverage_ns = sf_valid_rows_ts[-1] - sf_valid_rows_ts[0]
        trace_coverage_ms = trace_coverage_ns / 1_000_000.0 if trace_coverage_ns else 0.0

        # 相邻帧间隔最大值 & 平均帧间隔 - SF
        max_frame_gap_ns = 0
        frame_gaps_ns: List[int] = []
        for i in range(1, len(sf_valid_rows_ts)):
            gap = sf_valid_rows_ts[i] - sf_valid_rows_ts[i - 1]
            if gap > 0:
                frame_gaps_ns.append(gap)
                if gap > max_frame_gap_ns:
                    max_frame_gap_ns = gap
        max_frame_gap_ms = max_frame_gap_ns / 1_000_000.0 if max_frame_gap_ns else 0.0

        # 平均帧率1：总帧数 / 设定录制时长（SF）
        avg_fps_by_duration = 0.0
        if record_duration_s and record_duration_s > 0:
            avg_fps_by_duration = total_frames / record_duration_s
        elif trace_coverage_ms and trace_coverage_ms > 0:
            avg_fps_by_duration = total_frames / (trace_coverage_ms / 1000.0)

        # 平均帧率2：1 / 平均帧间隔(秒)（SF）
        avg_fps_by_frame_interval = 0.0
        if frame_gaps_ns:
            avg_gap_ns = sum(frame_gaps_ns) / len(frame_gaps_ns)
            if avg_gap_ns > 0:
                avg_fps_by_frame_interval = 1_000_000_000.0 / avg_gap_ns

        print(f"总帧数(SF): {total_frames}, 卡顿帧数(SF): {jank_frames}, 卡顿率: {jank_ratio * 100:.2f}%")
        print(f"  卡顿等级(SF) - 细微={jank_level_breakdown.tiny}, 轻微={jank_level_breakdown.slight}, 明显={jank_level_breakdown.obvious}, 严重={jank_level_breakdown.severe}")
        print(f"  平均帧率(按设定时长): {avg_fps_by_duration:.2f} FPS, 平均帧率(按帧间隔): {avg_fps_by_frame_interval:.2f} FPS")
        print(f"  最大帧间隔(ts差): {max_frame_gap_ms:.2f} ms, 最大帧时长(dur): {max_frame_dur_ms:.2f} ms")
        # 打印按来源分类
        source_label_map = {"app": "全部进程", "sf": "SF侧(SurfaceFlinger)", "other": "其他进程"}
        for src_key in sorted(set(list(per_source_total_frames.keys()) + list(per_source_jank_frames.keys()))):
            label = source_label_map.get(src_key, src_key)
            src_total = per_source_total_frames.get(src_key, 0)
            src_jank = per_source_jank_frames.get(src_key, 0)
            src_bd = per_source_jank_level.get(src_key, JankLevelBreakdown())
            print(f"  [{label}] 总帧数={src_total}, 卡顿帧数={src_jank}, "
                  f"细微={src_bd.tiny}, 轻微={src_bd.slight}, 明显={src_bd.obvious}, 严重={src_bd.severe}")

        return JankAnalysisResult(
            total_frames=total_frames,
            jank_frames=jank_frames,
            jank_ratio=jank_ratio,
            avg_frame_time=avg_frame_time,
            max_frame_time=max_frame_time,
            min_frame_time=min_frame_time,
            jank_events=jank_events,
            jank_type_breakdown=jank_type_breakdown,
            jank_tag_breakdown=jank_tag_breakdown,
            duration_threshold_breakdown=duration_threshold_breakdown,
            analysis_mode=analysis_mode,
            # 新增指标
            avg_fps_by_duration=avg_fps_by_duration,
            avg_fps_by_frame_interval=avg_fps_by_frame_interval,
            max_frame_gap_ns=max_frame_gap_ns,
            max_frame_gap_ms=max_frame_gap_ms,
            max_frame_dur_ms=max_frame_dur_ms,
            trace_coverage_ns=trace_coverage_ns,
            trace_coverage_ms=trace_coverage_ms,
            jank_level_breakdown=jank_level_breakdown,
            record_duration_s=record_duration_s,
            # 按来源分类
            per_source_total_frames=per_source_total_frames,
            per_source_jank_frames=per_source_jank_frames,
            per_source_jank_level=per_source_jank_level,
        )

    def export_jank_report(self, trace_file: str, output_file: str, frame_threshold_ms: float = 16.67,
                          analysis_mode: str = "jank_field", duration_thresholds: List[float] = None,
                          process_filter: List[str] = None,
                          jank_level_thresholds=None,
                          record_duration_s: float = 0.0):
        """导出jank分析报告为JSON"""
        result = self.analyze_jank(
            trace_file, frame_threshold_ms, analysis_mode, duration_thresholds,
            process_filter, jank_level_thresholds, record_duration_s
        )

        # 按来源分类统计 -> 转为可序列化dict
        per_source_report: Dict[str, Dict[str, Any]] = {}
        source_label_map = {"app": "全部进程", "sf": "SF侧(SurfaceFlinger)", "other": "其他进程"}
        src_keys = sorted(set(
            list(result.per_source_total_frames.keys()) +
            list(result.per_source_jank_frames.keys()) +
            list(result.per_source_jank_level.keys())
        ))
        for src_key in src_keys:
            label = source_label_map.get(src_key, src_key)
            src_total = result.per_source_total_frames.get(src_key, 0)
            src_jank = result.per_source_jank_frames.get(src_key, 0)
            src_bd = result.per_source_jank_level.get(src_key) or JankLevelBreakdown()
            src_ratio = (src_jank / src_total * 100) if src_total > 0 else 0.0
            per_source_report[src_key] = {
                "label": label,
                "total_frames": src_total,
                "jank_frames": src_jank,
                "jank_ratio_percent": round(src_ratio, 2),
                "jank_level_breakdown": src_bd.to_dict(),
            }

        report = {
            "trace_file": os.path.basename(trace_file),
            "analysis_mode": result.analysis_mode,
            "detection_method": "Perfetto actual_frame_timeline_slice table",
            "record_duration_s": result.record_duration_s,
            "analysis": {
                "total_frames": result.total_frames,
                "jank_frames": result.jank_frames,
                "jank_ratio": result.jank_ratio,
                "jank_ratio_percent": round(result.jank_ratio * 100, 2),
                "avg_frame_time_ms": round(result.avg_frame_time, 3),
                "max_frame_time_ms": round(result.max_frame_time, 3),
                "min_frame_time_ms": round(result.min_frame_time, 3),
                # 新增指标
                "avg_fps_by_duration": round(result.avg_fps_by_duration, 2),
                "avg_fps_by_frame_interval": round(result.avg_fps_by_frame_interval, 2),
                "max_frame_gap_ms": round(result.max_frame_gap_ms, 2),
                "max_frame_dur_ms": round(result.max_frame_dur_ms, 2),
                "trace_coverage_ms": round(result.trace_coverage_ms, 2),
            },
            "jank_level_breakdown": result.jank_level_breakdown.to_dict(),
            "per_source_breakdown": per_source_report,
            "jank_type_breakdown": result.jank_type_breakdown,
            "jank_tag_breakdown": result.jank_tag_breakdown,
            "duration_threshold_breakdown": result.duration_threshold_breakdown,
            "jank_events": [
                {
                    "timestamp_ns": event.timestamp,
                    "duration_ns": event.duration,
                    "duration_ms": round(event.duration / 1_000_000.0, 2) if event.duration else None,
                    "frame_token": event.frame_token,
                    "jank_type": event.jank_type,
                    "jank_tag": event.jank_tag,
                    "jank_level": event.jank_level,
                    "present_type": event.present_type,
                    "on_time_finish": event.on_time_finish,
                    "jank_severity_type": event.jank_severity_type,
                    "jank_score": event.jank_score,
                    "layer_name": event.layer_name,
                    "process_name": event.process_name,
                    "frame_source": event.frame_source,
                    "exceeded_thresholds": event.exceeded_thresholds,
                }
                for event in result.jank_events
            ]
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        return report


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python trace_analyzer.py <trace_file>")
        sys.exit(1)
    
    trace_file = sys.argv[1]
    
    analyzer = PerfettoTraceAnalyzer()
    result = analyzer.analyze_jank(trace_file)
    
    print("\n=== Jank Analysis Report ===")
    print(f"Total Frames: {result.total_frames}")
    print(f"Jank Frames: {result.jank_frames}")
    print(f"Jank Ratio: {result.jank_ratio * 100:.2f}%")
    
    if result.jank_type_breakdown:
        print("\n--- Jank Type Breakdown ---")
        for jt, count in result.jank_type_breakdown.items():
            print(f"  {jt}: {count}")
    
    if result.jank_tag_breakdown:
        print("\n--- Jank Tag Breakdown ---")
        for jt, count in result.jank_tag_breakdown.items():
            print(f"  {jt}: {count}")
