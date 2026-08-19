from __future__ import annotations

import os
import sys
import time
import json
from typing import Optional, Callable, Dict, Any, List, Tuple
from trace_analyzer import PerfettoTraceAnalyzer, JankAnalysisResult
from adb_utils import AdbManager
from uiautomator_manager import UiAutomatorManager
from case_config import (
    AppConfig, TestCaseConfig, JankLevelThresholds,
    load_config, save_config, default_config,
)
from case_scripts import resolve_script, run_load_operations
from report_exporter import (
    CaseSummaryRow, build_summary_row, export_full_report,
)


class JankTestTool:
    def __init__(self, adb_path: str = "adb", device_id: Optional[str] = None):
        self.adb_manager = AdbManager(adb_path, device_id=device_id)
        self.trace_analyzer = PerfettoTraceAnalyzer()
        self.uiautomator: Optional[UiAutomatorManager] = None
        self.device_id = device_id

    def connect_device(self, device_id: Optional[str] = None):
        _T0 = time.time()
        self.device_id = device_id if device_id else self.device_id
        if self.device_id is None:
            _t_list = time.time()
            devices = self.adb_manager.get_device_list()
            print(f"[测速] adb获取设备列表耗时: {time.time()-_t_list:.2f}s")
            if not devices:
                raise RuntimeError("未检测到设备")
            self.device_id = devices[0]
        print(f"[测速] 准备连接设备: {self.device_id}")
        # 更新adb_manager里的device_id，确保后续命令正确
        self.adb_manager.device_id = self.device_id
        _t_u2 = time.time()
        self.uiautomator = UiAutomatorManager(self.device_id)
        print(f"[测速] UiAutomatorManager创建耗时: {time.time()-_t_u2:.2f}s")
        print(f"[测速] connect_device总耗时: {time.time()-_T0:.2f}s")

    # ========== 核心：执行单个 Case ==========
    def run_single_case(self,
                        case: TestCaseConfig,
                        output_dir: str = "./results",
                        analysis_mode: str = "duration",
                        frame_threshold_ms: float = 16.67,
                        jank_level_thresholds: Optional[JankLevelThresholds] = None,
                        logger: Optional[Callable[[str], None]] = None,
                        should_stop: Optional[Callable[[], bool]] = None,
                        load_region: str = "国内",
                        skip_load: bool = False,
                        ) -> Tuple[Optional[JankAnalysisResult], Optional[Dict[str, Any]], str]:
        """
        执行单个Case：先执行脚本→启动trace→录制→拉取→分析
        返回: (分析结果, JSON报告dict, 错误信息str)
        """
        log = logger or print
        err_msg = ""
        if jank_level_thresholds is None:
            jank_level_thresholds = default_config().thresholds

        os.makedirs(output_dir, exist_ok=True)
        trace_file = os.path.join(output_dir, f"{case.name}.perfetto-trace")
        report_file = os.path.join(output_dir, f"{case.name}_report.json")

        # 1. 解析脚本
        script_func = resolve_script(case.script_name, case.script_path)

        # 2. 执行负载操作（每轮测试前都执行，制造系统负载）
        if not skip_load:
            log(f"[{case.name}] 执行负载操作...")
            _T_load_start = time.time()
            try:
                run_load_operations(self.uiautomator, logger=log, region=load_region)
                log(f"[{case.name}] 负载操作完成 (耗时{time.time()-_T_load_start:.2f}s)")
            except Exception as e:
                log(f"[{case.name}] 负载操作异常(可忽略, 录制继续): {e}")
        else:
            log(f"[{case.name}] ⏭️ 跳过负载操作")

        # 3. 执行自动化脚本（启动App、切换模式等）
        during_trace_cb = None  # 可选的"trace期间回调"
        script_error = None
        _T_case_start = time.time()
        if script_func is not None:
            log(f"[{case.name}] 执行自动化脚本: {case.script_name or case.script_path or '(自定义)'}")
            try:
                _T_script = time.time()
                ret = script_func(self.uiautomator, logger=log)
                log(f"[{case.name}] 脚本执行完毕 (耗时{time.time()-_T_script:.2f}s)")
                # 脚本可选返回一个 callable 回调，会在 trace 启动1秒后被调用
                if callable(ret):
                    during_trace_cb = ret
                    log(f"[{case.name}] 脚本返回了during_trace回调，trace开始后1s触发拍照动作")
                # 等App稳定
                log(f"[{case.name}] 等待App稳定 (3s)...")
                time.sleep(3)
            except Exception as e:
                script_error = f"脚本执行异常(可忽略, 录制继续): {e}"
                log(f"[{case.name}] {script_error}")
                time.sleep(2)
        else:
            log(f"[{case.name}] 未配置脚本，直接开始录制...")

        log(f"[{case.name}] === 脚本阶段总耗时: {time.time()-_T_case_start:.2f}s ===")

        # 4. 启动 trace（此时App已在前台，录制的是预览/操作阶段）
        log(f"[{case.name}] 启动Perfetto trace录制 (时长={case.duration}s, 进程={case.monitor_processes})...")
        _T_trace_start = time.time()
        try:
            self.adb_manager.start_perfetto_trace(
                duration=case.duration,
                buffer_size="100",
                monitor_processes=case.monitor_processes,
            )
            log(f"[{case.name}] [测速] 启动trace耗时: {time.time()-_T_trace_start:.2f}s")
        except Exception as e:
            err_msg = f"启动trace失败: {e}"
            log(f"[{case.name}] {err_msg}")
            return None, None, err_msg

        # 5. 等待录制时长结束
        log(f"[{case.name}] 录制中 ({case.duration}s)...")
        _T_record_start = time.time()
        record_start = _T_record_start
        remaining = float(case.duration)
        check_interval = 0.5
        cb_fired = False
        while remaining > 0:
            if should_stop and should_stop():
                log(f"[{case.name}] 用户请求停止...")
                break
            elapsed = time.time() - record_start
            # trace 启动后约1s触发回调（拍照动作等）
            if (during_trace_cb is not None
                    and not cb_fired
                    and elapsed >= 1.0):
                cb_fired = True
                try:
                    log(f"[{case.name}] 触发during_trace回调(拍照动作)...")
                    during_trace_cb()
                except Exception as cb_e:
                    log(f"[{case.name}] during_trace回调异常(继续录制): {cb_e}")
            time.sleep(min(check_interval, remaining))
            remaining -= check_interval
        waited = time.time() - record_start
        if waited < case.duration:
            time.sleep(max(0, case.duration - waited))

        log(f"[{case.name}] 停止trace录制...")
        try:
            self.adb_manager.stop_perfetto_trace()
        except Exception as e:
            log(f"[{case.name}] 停止trace提示(非致命): {e}")
        time.sleep(2)

        # 6. 拉取 trace
        log(f"[{case.name}] 拉取trace文件...")
        try:
            self.adb_manager.pull_trace_file(local_path=trace_file)
        except Exception as e:
            err_msg = f"拉取trace失败: {e}"
            log(f"[{case.name}] {err_msg}")
            return None, None, err_msg

        # 7. 分析 trace
        process_list = (
            None if (not case.monitor_processes or case.monitor_processes.strip() == "all" or case.monitor_processes.strip() == "")
            else [p.strip() for p in case.monitor_processes.split(",") if p.strip()]
        )
        log(f"[{case.name}] 分析trace文件 (模式={analysis_mode}, 阈值={frame_threshold_ms}ms)...")
        try:
            result: JankAnalysisResult = self.trace_analyzer.analyze_jank(
                trace_file,
                frame_threshold_ms=frame_threshold_ms,
                analysis_mode=analysis_mode,
                duration_thresholds=[67, 100, 167],
                process_filter=process_list,
                jank_level_thresholds=jank_level_thresholds,
                record_duration_s=float(case.duration),
                logger=log,
            )
            report = self.trace_analyzer.export_jank_report(
                trace_file, report_file,
                frame_threshold_ms=frame_threshold_ms,
                analysis_mode=analysis_mode,
                duration_thresholds=[67, 100, 167],
                process_filter=process_list,
                jank_level_thresholds=jank_level_thresholds,
                record_duration_s=float(case.duration),
            )
        except Exception as e:
            err_msg = f"分析trace失败: {e}"
            log(f"[{case.name}] {err_msg}")
            return None, None, err_msg

        log(f"[{case.name}] 完成：SF帧数={result.total_frames}，"
            f"卡顿等级(细/轻/明/严)={result.jank_level_breakdown.tiny}"
            f"/{result.jank_level_breakdown.slight}"
            f"/{result.jank_level_breakdown.obvious}"
            f"/{result.jank_level_breakdown.severe}")
        log(f"[{case.name}] FPS(按时长)={result.avg_fps_by_duration:.2f}, "
            f"FPS(按间隔)={result.avg_fps_by_frame_interval:.2f}, "
            f"最大帧间隔={result.max_frame_gap_ms:.2f}ms")
        final_err = (err_msg + (f"; {script_error}" if script_error else "")).strip("; ")
        return result, report, final_err

    # ========== 批量执行 Case ==========
    def run_case_batch(self,
                       cases: List[TestCaseConfig],
                       output_dir: str = "./results",
                       analysis_mode: str = "duration",
                       frame_threshold_ms: float = 16.67,
                       jank_level_thresholds: Optional[JankLevelThresholds] = None,
                       logger: Optional[Callable[[str], None]] = None,
                       should_stop: Optional[Callable[[], bool]] = None,
                       on_case_done: Optional[Callable[[TestCaseConfig, Optional[JankAnalysisResult], str], None]] = None,
                       live_rows: Optional[list] = None,
                       load_region: str = "国内",
                       skip_load: bool = False,
                       ) -> Tuple[List[CaseSummaryRow], Dict[str, Dict[str, Any]]]:
        """
        批量执行多个Case，每个Case按 rounds 运行N轮，最后按Case汇总（数值取平均/计数取累加）
        """
        log = logger or print
        summary_rows: List[CaseSummaryRow] = []
        detail_reports: Dict[str, Dict[str, Any]] = {}

        enabled_cases = [c for c in cases if c.enabled]
        # 先计算总任务数(Case×轮数)，方便进度展示
        total_tasks = sum(max(c.rounds, 1) for c in enabled_cases)
        done_tasks = 0

        for case_idx, case in enumerate(enabled_cases, start=1):
            rounds = max(case.rounds, 1)
            # 收集N轮的分析结果
            per_round_results: List[JankAnalysisResult] = []
            per_round_errors: List[str] = []
            last_report: Optional[Dict[str, Any]] = None

            log(f"\n{'=' * 60}")
            log(f"===== [{case_idx}/{len(enabled_cases)}] {case.name}  共{rounds}轮 =====")
            log(f"{'=' * 60}")

            for round_i in range(1, rounds + 1):
                if should_stop and should_stop():
                    log(f"收到停止信号，剩余 {rounds - round_i + 1} 轮取消")
                    break

                # 生成"CaseName_round_N"的子名用于报告命名
                round_subname = f"{case.name}_R{round_i}"
                log(f"\n--- 第 {round_i}/{rounds} 轮 ({case.name}) ---")
                # 构造临时case副本（不修改原case），用于trace输出命名
                import copy as _cp
                tmp_case = _cp.deepcopy(case)
                tmp_case.name = round_subname

                try:
                    result, report, err = self.run_single_case(
                        case=tmp_case,
                        output_dir=output_dir,
                        analysis_mode=analysis_mode,
                        frame_threshold_ms=frame_threshold_ms,
                        jank_level_thresholds=jank_level_thresholds,
                        logger=log,
                        should_stop=should_stop,
                        load_region=load_region,
                        skip_load=skip_load,
                    )
                except Exception as e:
                    result, report, err = None, None, f"执行异常: {e}"
                    log(f"[警告] {case.name} 第{round_i}轮失败: {err}")

                done_tasks += 1
                if result is not None:
                    per_round_results.append(result)
                    # ===== 每轮生成一行汇总数据 =====
                    round_row = build_summary_row(tmp_case, result, error=err or "")
                    round_row.case_name = f"{case.name}_R{round_i}"
                    summary_rows.append(round_row)
                    if live_rows is not None:
                        live_rows.append(round_row)
                if err:
                    per_round_errors.append(f"R{round_i}:{err}")
                if report is not None:
                    last_report = report

                # 每轮完成都回调（按原始Case返回，方便UI记录）
                if on_case_done:
                    try:
                        on_case_done(case, result, err or "", round_i, rounds, done_tasks, total_tasks)
                    except TypeError:
                        # 兼容老回调无rounds信息
                        try:
                            on_case_done(case, result, err or "")
                        except Exception as e:
                            log(f"on_case_done 回调异常: {e}")
                    except Exception as e:
                        log(f"on_case_done 回调异常: {e}")

            # ===== N轮跑完后，生成Case级AVG汇总行 =====
            merged_row = self._merge_rounds_into_row(
                case=case,
                round_results=per_round_results,
                errors=per_round_errors,
                jank_level_thresholds=jank_level_thresholds,
            )
            merged_row.case_name = f"{case.name}_AVG"
            summary_rows.append(merged_row)
            if live_rows is not None:
                live_rows.append(merged_row)
            # 详情报告保留最后一轮有效JSON
            if last_report is not None:
                detail_reports[case.name] = last_report
            # 日志展示最终数值
            log(f"\n[{case.name}] 汇总AVG（共{len(per_round_results)}有效轮）：")
            log(f"  平均SF帧数={merged_row.total_frames:.0f}, "
                f"平均FPS={merged_row.avg_fps_by_duration:.2f}/{merged_row.avg_fps_by_frame_interval:.2f}")
            log(f"  卡顿总计(细/轻/明/严)={merged_row.tiny_jank}/{merged_row.slight_jank}/"
                f"{merged_row.obvious_jank}/{merged_row.severe_jank}")
            if merged_row.error:
                log(f"  有异常: {merged_row.error[:80]}")

            if should_stop and should_stop():
                log(f"收到停止信号，剩余 {len(enabled_cases) - case_idx} 个Case取消")
                break

        # 最后导出汇总报告
        log("\n===== 导出汇总报告 =====")
        try:
            outputs = export_full_report(
                summary_rows, output_dir,
                filename_prefix="jank_cases_summary",
                detail_reports=detail_reports,
            )
            for fmt, path in outputs.items():
                log(f"  {fmt.upper()}: {path}")
        except Exception as e:
            log(f"导出汇总报告失败: {e}")
        return summary_rows, detail_reports

    def _merge_rounds_into_row(
        self,
        case: TestCaseConfig,
        round_results: list,
        errors: List[str],
        jank_level_thresholds=None,
    ) -> CaseSummaryRow:
        """
        把N轮分析结果按Case汇总：
        - 计数型 (帧数、卡顿数量、App/SF帧等)：取平均(round)
        - 最大值型 (max_frame_gap, max_frame_dur)：取N轮中的最大值
        - FPS：取每轮FPS的平均
        - 卡顿率：总卡顿帧数/总帧数（加权）
        """
        n = len(round_results)
        if n == 0:
            # 0轮有效 -> 生成0值行，附带错误信息
            from report_exporter import build_summary_row
            return build_summary_row(case, None,
                                     error=(f"全部{max(case.rounds, 1)}轮都失败: "
                                            + " | ".join(errors) if errors else "无有效轮"))

        # 计数累加后除以N（向下取整），卡顿率、最大值等特殊处理
        sum_total_frames = sum(r.total_frames for r in round_results)
        avg_total_frames = round(sum_total_frames / n)

        # FPS = 平均帧数 / 单轮时长 (按总帧数/时长的平均方式)
        fps_by_dur = sum(r.avg_fps_by_duration for r in round_results) / n
        fps_by_interval = sum(r.avg_fps_by_frame_interval for r in round_results) / n

        # App / SF 帧数 (平均)
        app_frames_list = [r.per_source_total_frames.get("app", 0) for r in round_results]
        sf_frames_list = [r.per_source_total_frames.get("sf", 0) for r in round_results]
        app_frames_avg = round(sum(app_frames_list) / n)
        sf_frames_avg = round(sum(sf_frames_list) / n)

        # App / SF 独立 FPS（帧数/时长）
        dur_s = float(case.duration) if case.duration > 0 else 0.0
        app_avg_fps = (sum(app_frames_list) / n / dur_s) if dur_s > 0 else 0.0
        sf_avg_fps = (sum(sf_frames_list) / n / dur_s) if dur_s > 0 else 0.0

        # 卡顿等级（4级）：累加N轮，再取加权平均或直接累加取决于需求；
        # 这里采用"累加后取平均并四舍五入"的直观方式
        def _avg_bd(bd_attr: str) -> int:
            return round(sum(getattr(r.jank_level_breakdown, bd_attr, 0)
                             for r in round_results) / n)

        tiny_avg   = _avg_bd("tiny")
        slight_avg = _avg_bd("slight")
        obvious_avg= _avg_bd("obvious")
        severe_avg = _avg_bd("severe")

        # App / SF 卡顿等级 4级 平均
        def _avg_per_source(bd_attr: str, src: str) -> int:
            total = 0
            for r in round_results:
                bd = r.per_source_jank_level.get(src)
                if bd is not None:
                    total += getattr(bd, bd_attr, 0)
            return round(total / n)

        app_t, app_s, app_o, app_vv = (_avg_per_source(x, "app") for x in ("tiny","slight","obvious","severe"))
        sf_t,  sf_s,  sf_o,  sf_vv  = (_avg_per_source(x, "sf")  for x in ("tiny","slight","obvious","severe"))

        # 最大帧间隔 / 最大帧时长：取N轮最大值
        max_gap = max((r.max_frame_gap_ms for r in round_results), default=0.0)
        max_dur = max((r.max_frame_dur_ms for r in round_results), default=0.0)

        # 加权卡顿率 = 全部卡顿帧数 / 全部总帧数
        total_jank_count = sum(r.jank_frames for r in round_results)
        jank_ratio = (total_jank_count / sum_total_frames) if sum_total_frames > 0 else 0.0

        err_msg = "；".join(errors) if errors else ""

        return CaseSummaryRow(
            case_name=case.name,
            description=case.description,
            duration_s=case.duration,
            total_frames=avg_total_frames,
            avg_fps_by_duration=fps_by_dur,
            avg_fps_by_frame_interval=fps_by_interval,
            max_frame_gap_ms=max_gap,
            max_frame_dur_ms=max_dur,
            tiny_jank=tiny_avg,
            slight_jank=slight_avg,
            obvious_jank=obvious_avg,
            severe_jank=severe_avg,
            jank_ratio_percent=jank_ratio * 100,
            app_total_frames=app_frames_avg,
            sf_total_frames=sf_frames_avg,
            app_avg_fps=app_avg_fps,
            sf_avg_fps=sf_avg_fps,
            app_tiny=app_t, app_slight=app_s, app_obvious=app_o, app_severe=app_vv,
            sf_tiny=sf_t, sf_slight=sf_s, sf_obvious=sf_o, sf_severe=sf_vv,
            error=err_msg,
        )

    # ========== 以下为旧接口兼容保留 ==========
    def run_test_with_trace(self,
                            test_script: Callable[[UiAutomatorManager], None],
                            package_name: str,
                            trace_duration: Optional[int] = None,
                            frame_threshold_ms: float = 16.67,
                            output_dir: str = "./results",
                            test_name: str = "jank_test",
                            monitor_processes: str = "all",
                            analysis_mode: str = "jank_field") -> Dict[str, Any]:
        case = TestCaseConfig(
            name=test_name,
            description=f"legacy test for {package_name}",
            duration=trace_duration or 30,
            package_name=package_name,
            monitor_processes=monitor_processes,
            script_name="",
            enabled=True,
        )
        # 包装用户给的老格式脚本函数
        def legacy_script(u2, logger=None):
            return test_script(u2)

        import case_scripts as _cs
        old_reg = _cs._BUILTIN_SCRIPTS
        tmp_name = f"__legacy_{test_name}"
        old_reg[tmp_name] = legacy_script
        case.script_name = tmp_name
        try:
            result, report, err = self.run_single_case(
                case, output_dir, analysis_mode, frame_threshold_ms, logger=print,
            )
            return report or {"error": err or "unknown"}
        finally:
            old_reg.pop(tmp_name, None)

    def analyze_trace_file(self, trace_file: str, output_file: str) -> Dict[str, Any]:
        from case_config import JankLevelThresholds
        print(f"Analyzing {trace_file} ...")
        try:
            result = self.trace_analyzer.analyze_jank(trace_file,
                jank_level_thresholds=JankLevelThresholds())
            report = self.trace_analyzer.export_jank_report(trace_file, output_file,
                jank_level_thresholds=JankLevelThresholds())
            self._print_report(result)
            return report
        except Exception as e:
            print(f"Failed to analyze trace: {e}")
            return {"error": str(e)}

    def _print_report(self, result: JankAnalysisResult):
        print("\n=== Jank Analysis Report (SF-only) ===")
        print(f"SF Total Frames: {result.total_frames}")
        print(f"SF Jank Frames: {result.jank_frames}, Jank Ratio: {result.jank_ratio * 100:.2f}%")
        print(f"FPS(duration): {result.avg_fps_by_duration:.2f}, FPS(interval): {result.avg_fps_by_frame_interval:.2f}")
        print(f"Max Gap(ts): {result.max_frame_gap_ms:.2f} ms, Max Dur: {result.max_frame_dur_ms:.2f} ms")
        jl = result.jank_level_breakdown
        print(f"细微(Tiny): {jl.tiny}, 轻微(Slight): {jl.slight}, 明显(Obvious): {jl.obvious}, 严重(Severe): {jl.severe}")

    def get_device_info(self) -> Dict[str, Any]:
        info = {}
        try:
            info["devices"] = self.adb_manager.get_device_list()
            info["battery_level"] = self.adb_manager.get_battery_level(self.device_id)
        except Exception as e:
            info["error"] = str(e)
        return info


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Android Jank Test Tool (Case化)")
    parser.add_argument("--adb", default="adb", help="ADB路径")
    parser.add_argument("--device", help="Device ID")
    parser.add_argument("--config", default="", help="case配置文件(cases.json)")
    parser.add_argument("--output", default="./results", help="输出目录")
    parser.add_argument("--mode", default="duration", choices=["duration", "jank_field"], help="分析模式")
    parser.add_argument("--threshold", type=float, default=16.67, help="帧时长模式卡顿阈值ms")
    parser.add_argument("--list-cases", action="store_true", help="只打印配置的case列表")
    parser.add_argument("--trace-file", help="直接分析已有trace文件")
    args = parser.parse_args()

    cfg = load_config(args.config) if args.config else default_config()

    if args.list_cases:
        print("Case列表:")
        for c in cfg.cases:
            print(f"  [{c.name}] enabled={c.enabled} duration={c.duration}s desc={c.description}")
        sys.exit(0)

    if args.trace_file:
        tool = JankTestTool(adb_path=args.adb)
        os.makedirs(args.output, exist_ok=True)
        out = os.path.join(args.output, "trace_analysis_report.json")
        tool.analyze_trace_file(args.trace_file, out)
        sys.exit(0)

    tool = JankTestTool(adb_path=args.adb, device_id=args.device)
    try:
        tool.connect_device(args.device)
        print(f"已连接设备: {tool.device_id}")
        rows, details = tool.run_case_batch(
            cfg.cases, output_dir=args.output,
            analysis_mode=args.mode,
            frame_threshold_ms=args.threshold,
            jank_level_thresholds=cfg.thresholds,
            logger=print,
        )
        print("\n=== 汇总 ===")
        for r in rows:
            print(f"  {r.case_name}: 总帧={r.total_frames}, "
                  f"FPS={r.avg_fps_by_duration:.2f}/{r.avg_fps_by_frame_interval:.2f}, "
                  f"卡顿(细/轻/明/严)={r.tiny_jank}/{r.slight_jank}/{r.obvious_jank}/{r.severe_jank}"
                  f"{' ERR: ' + r.error if r.error else ''}")
    except Exception as e:
        print(f"错误: {e}")
