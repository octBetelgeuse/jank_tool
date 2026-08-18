from __future__ import annotations

import subprocess
import os
import time
from typing import Optional


class AdbManager:
    def __init__(self, adb_path: str = "adb", device_id: str = None):
        self.adb_path = adb_path
        self.device_id = device_id
        self._check_adb()

    def _check_adb(self):
        try:
            result = subprocess.run(
                [self.adb_path, "version"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"ADB not found or not working: {result.stderr}")
        except FileNotFoundError:
            raise RuntimeError(
                "ADB not found in PATH. "
                "Please install Android SDK and add ADB to PATH."
            )

    def run_command(self, command: str, device_id: Optional[str] = None) -> str:
        cmd = [self.adb_path]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(command.split())
        
        print(f"执行命令: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            error_msg = f"ADB命令失败 (返回码: {result.returncode})"
            if result.stderr:
                error_msg += f": {result.stderr.strip()}"
            elif result.stdout:
                error_msg += f"，stdout: {result.stdout.strip()}"
            else:
                error_msg += "，没有更多错误信息"
            raise RuntimeError(error_msg)
        
        if result.stderr:
            print(f"命令警告: {result.stderr.strip()}")
        
        return result.stdout.strip()

    def shell_command(self, command: str, device_id: Optional[str] = None) -> str:
        full_command = f"shell {command}"
        # 如果没有传入device_id，使用实例变量
        actual_device_id = device_id if device_id is not None else self.device_id
        return self.run_command(full_command, actual_device_id)

    def start_perfetto_trace(self, output_path: str = "/data/misc/perfetto-traces/trace.perfetto-trace", 
                             duration: Optional[int] = 60, buffer_size: str = "100",
                             categories: str = None,
                             monitor_processes: str = "all"):
        """
        在Android设备上启动Perfetto trace录制。
        使用 --background 方式后台运行，支持长时间录制。
        
        参数:
            monitor_processes: 监控的进程名，逗号分隔，"all" 表示全部
        """
        buffer_kb = int(buffer_size) * 1024
        
        # 首先启用 Perfetto traced 服务
        self.shell_command("setprop persist.traced.enable 1", self.device_id)
        time.sleep(1)
        
        # 创建配置文件内容（Protocol Buffer 文本格式）
        # 使用专业配置，包含完整的帧时间线和系统信息
        duration_ms = duration * 1000 if duration and duration > 0 else 0
        
        # 处理 atrace_apps
        if monitor_processes and monitor_processes.strip() and monitor_processes.strip() != "all":
            apps_list = [f'      atrace_apps: "{app.strip()}"' for app in monitor_processes.split(",") if app.strip()]
            atrace_apps_config = "\n".join(apps_list)
        else:
            atrace_apps_config = '      atrace_apps: "*"'
        
        config_content = f"""buffers: {{
  size_kb: {buffer_kb}
  fill_policy: RING_BUFFER
}}

buffers: {{
  size_kb: 4096
  fill_policy: RING_BUFFER
}}

data_sources: {{
  config {{
    name: "android.gpu.memory"
  }}
}}

data_sources: {{
  config {{
    name: "linux.process_stats"
    target_buffer: 1
    process_stats_config {{
      scan_all_processes_on_start: true
    }}
  }}
}}

data_sources: {{
  config {{
    name: "android.surfaceflinger.frametimeline"
  }}
}}

data_sources: {{
  config {{
    name: "android.log"
    android_log_config {{
      log_ids: LID_DEFAULT
      log_ids: LID_RADIO
      log_ids: LID_SYSTEM
    }}
  }}
}}

data_sources: {{
  config {{
    name: "linux.sys_stats"
    sys_stats_config {{
      stat_period_ms: 250
      stat_counters: STAT_CPU_TIMES
      stat_counters: STAT_FORK_COUNT
    }}
  }}
}}

data_sources: {{
  config {{
    name: "linux.ftrace"
    ftrace_config {{
      ftrace_events: "sched/sched_switch"
      ftrace_events: "power/suspend_resume"
      ftrace_events: "sched/sched_wakeup"
      ftrace_events: "sched/sched_wakeup_new"
      ftrace_events: "sched/sched_waking"
      ftrace_events: "power/cpu_frequency"
      ftrace_events: "power/cpu_idle"
      ftrace_events: "power/gpu_frequency"
      ftrace_events: "gpu_mem/gpu_mem_total"
      ftrace_events: "sched/sched_process_exit"
      ftrace_events: "sched/sched_process_free"
      ftrace_events: "task/task_newtask"
      ftrace_events: "task/task_rename"
      ftrace_events: "sched/sched_blocked_reason"
      ftrace_events: "ftrace/print"
      atrace_categories: "am"
      atrace_categories: "adb"
      atrace_categories: "aidl"
      atrace_categories: "dalvik"
      atrace_categories: "audio"
      atrace_categories: "binder_lock"
      atrace_categories: "binder_driver"
      atrace_categories: "bionic"
      atrace_categories: "camera"
      atrace_categories: "disk"
      atrace_categories: "database"
      atrace_categories: "gfx"
      atrace_categories: "hal"
      atrace_categories: "input"
      atrace_categories: "network"
      atrace_categories: "nnapi"
      atrace_categories: "pagecache"
      atrace_categories: "pm"
      atrace_categories: "power"
      atrace_categories: "rs"
      atrace_categories: "res"
      atrace_categories: "rro"
      atrace_categories: "sm"
      atrace_categories: "ss"
      atrace_categories: "vibrator"
      atrace_categories: "video"
      atrace_categories: "view"
      atrace_categories: "webview"
      atrace_categories: "wm"
{atrace_apps_config}
    }}
  }}
}}

duration_ms: {duration_ms}
write_into_file: true
file_write_period_ms: 2500
max_file_size_bytes: 10000000000
flush_period_ms: 30000
incremental_state_config {{
  clear_period_ms: 5000
}}
"""
        
        # 将配置写入到设备临时目录
        config_path = "/data/local/tmp/perfetto_config"
        
        # 先清理旧配置
        self.shell_command(f"rm -f {config_path}", self.device_id)
        
        # 使用base64编码一次性传输配置文件（避免换行和特殊字符问题）
        import base64
        encoded_config = base64.b64encode(config_content.encode('utf-8')).decode('ascii')
        base64_command = f'echo "{encoded_config}" | base64 -d > {config_path}'
        self.shell_command(base64_command, self.device_id)
        
        # 确保输出目录存在
        output_dir = "/".join(output_path.split("/")[:-1]) if "/" in output_path else "/data/misc/perfetto-traces"
        self.shell_command(f"mkdir -p {output_dir}", self.device_id)
        
        # 使用 --detach 模式（和用户手动抓trace的方式一致）
        # 需要先清理旧的trace文件
        self.shell_command(f"rm -f {output_path}", self.device_id)
        
        # 生成唯一的detach name（用时间戳），避免多次使用时冲突
        import time as _time
        detach_name = f"perfetto_test_{int(_time.time())}"
        
        # 启动Perfetto（detach模式：Perfetto立即退出，trace在后台录制直到duration_ms到期或手动停止）
        cmd = f"cat {config_path} | perfetto --txt -c - -o {output_path} --detach={detach_name}"
        
        # 执行命令
        result = self.shell_command(cmd, self.device_id)
        
        # 等待一下让服务启动
        time.sleep(2)
        
        return f"Perfetto started successfully (detach={detach_name}): {result}"

    def stop_perfetto_trace(self):
        """停止Perfetto trace录制"""
        # 使用 detach模式下的 --stop 命令（停止所有正在录制的session）
        try:
            self.shell_command("perfetto --stop 2>/dev/null || true", self.device_id)
            time.sleep(1)
        except Exception:
            pass
        # 兜底：用killall强制停止
        self.shell_command("killall perfetto 2>/dev/null || true", self.device_id)
        time.sleep(1)
        return "Trace stopped"

    def pull_trace_file(self, remote_path: str = "/data/misc/perfetto-traces/trace.perfetto-trace", 
                       local_path: str = "./trace.perfetto-trace"):
        # 先检查远程文件是否存在
        check_cmd = f"ls -la {remote_path} 2>/dev/null || echo 'file not found'"
        check_result = self.shell_command(check_cmd, self.device_id)
        
        if "file not found" in check_result:
            raise RuntimeError(f"远程文件不存在: {remote_path}\n检查结果: {check_result}")
        
        # 检查文件大小
        size_cmd = f"stat -c %s {remote_path} 2>/dev/null || ls -la {remote_path}"
        size_result = self.shell_command(size_cmd, self.device_id)
        print(f"Trace文件信息: {size_result}")
        
        # 执行 pull
        command = f"pull {remote_path} {local_path}"
        result = self.run_command(command, self.device_id)
        return result

    def get_device_list(self) -> list:
        result = self.run_command("devices")
        lines = result.strip().split('\n')[1:]
        devices = []
        for line in lines:
            if line.strip():
                parts = line.split()
                devices.append(parts[0])
        return devices

    def get_current_activity(self, device_id: Optional[str] = None) -> str:
        try:
            result = self.shell_command(
                "dumpsys activity activities | grep mResumedActivity",
                device_id
            )
            return result.strip()
        except:
            return ""

    def launch_app(self, package_name: str, activity_name: Optional[str] = None, 
                   device_id: Optional[str] = None):
        if activity_name:
            cmd = f"am start -n {package_name}/{activity_name}"
        else:
            cmd = f"monkey -p {package_name} -c android.intent.category.LAUNCHER 1"
        return self.shell_command(cmd, device_id)

    def force_stop_app(self, package_name: str, device_id: Optional[str] = None):
        return self.shell_command(f"am force-stop {package_name}", device_id)

    def clear_app_data(self, package_name: str, device_id: Optional[str] = None):
        return self.shell_command(f"pm clear {package_name}", device_id)

    def get_package_version(self, package_name: str, device_id: Optional[str] = None) -> str:
        result = self.shell_command(f"dumpsys package {package_name} | grep versionName", device_id)
        if result:
            return result.split('=')[-1].strip()
        return ""

    def take_screenshot(self, output_path: str = "/sdcard/screenshot.png", 
                       device_id: Optional[str] = None):
        return self.shell_command(f"screencap {output_path}", device_id)

    def record_screen(self, output_path: str = "/sdcard/screenrecord.mp4", 
                     duration: int = 60, device_id: Optional[str] = None):
        return self.shell_command(f"screenrecord --time-limit {duration} {output_path}", device_id)

    def get_cpu_info(self, device_id: Optional[str] = None) -> str:
        return self.shell_command("cat /proc/cpuinfo", device_id)

    def get_memory_info(self, device_id: Optional[str] = None) -> str:
        return self.shell_command("cat /proc/meminfo", device_id)

    def get_battery_level(self, device_id: Optional[str] = None) -> int:
        result = self.shell_command("dumpsys battery | grep level", device_id)
        if result:
            return int(result.split(':')[-1].strip())
        return -1

    def set_battery_level(self, level: int, device_id: Optional[str] = None):
        return self.shell_command(f"adb shell dumpsys battery set level {level}", device_id)

    def enable_wifi(self, device_id: Optional[str] = None):
        return self.shell_command("svc wifi enable", device_id)

    def disable_wifi(self, device_id: Optional[str] = None):
        return self.shell_command("svc wifi disable", device_id)

    def toggle_airplane_mode(self, device_id: Optional[str] = None):
        return self.shell_command("settings put global airplane_mode_on 1", device_id)

    def wait_for_device(self, timeout: int = 60):
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                self.run_command("get-state")
                return True
            except:
                time.sleep(1)
        return False

    def install_apk(self, apk_path: str, device_id: Optional[str] = None):
        command = f"install -r {apk_path}"
        return self.run_command(command, device_id)

    def uninstall_app(self, package_name: str, device_id: Optional[str] = None):
        return self.run_command(f"uninstall {package_name}", device_id)

    def reboot_device(self, device_id: Optional[str] = None):
        return self.shell_command("reboot", device_id)

    def get_logcat(self, filter_spec: str = "", device_id: Optional[str] = None) -> str:
        cmd = "logcat"
        if filter_spec:
            cmd += f" {filter_spec}"
        return self.shell_command(cmd, device_id)

    def clear_logcat(self, device_id: Optional[str] = None):
        return self.shell_command("logcat -c", device_id)