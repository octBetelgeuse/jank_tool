from __future__ import annotations

import os
import sys
import time
import importlib.util
from typing import Callable, Optional, Dict, Any, List

# 模块级相机UI配置（可通过 set_camera_ui() 注入）
# 默认值兼容旧版 com.android.camera2
class _DefaultCameraUI:
    package_name = "com.android.camera2"
    shutter_resource_ids = [
        "com.android.camera2:id/shutter_button",
        "com.android.camera:id/shutter_button",
        "shutter_button",
    ]
    record_resource_ids = [
        "com.android.camera2:id/record_button",
        "com.android.camera:id/record_button",
        "record_button",
    ]
    # 前后摄切换按钮的resourceId（全局常量，优先定位）
    switch_camera_resource_ids = [
        "com.android.camera2:id/switch_camera",
        "com.android.camera:id/switch_camera",
        "switch_camera",
    ]
    shutter_text_fallback = "拍照"
    record_text_fallback = "录制"
    button_y_ratio = 0.88
    # 切换按钮兜底坐标比例（找不到resourceId和关键词时用）
    switch_camera_fallback_x_ratio = 0.9
    switch_camera_fallback_y_ratio = 0.08
    switch_camera_keywords = ["后置", "后摄", "切换", "翻转", "rotate", "Flip"]
    front_camera_keywords = ["前置", "前摄", "切换", "翻转", "rotate", "Flip"]
    photo_mode_keywords = ["拍照", "PHOTO", "Photo", "photo", "普通", "标准"]
    video_mode_keywords = ["录像", "视频", "VIDEO", "Video", "video", "录影"]

# 全局引用
_camera_ui = _DefaultCameraUI()


def set_camera_ui(ui_settings):
    """注入相机UI配置（CameraUISettings实例），运行前调用即可"""
    global _camera_ui
    if ui_settings is not None:
        _camera_ui = ui_settings


def _get_package() -> str:
    return _camera_ui.package_name


def _get_shutter_ids() -> list:
    return list(_camera_ui.shutter_resource_ids)


def _get_record_ids() -> list:
    return list(_camera_ui.record_resource_ids)


def _get_switch_ids() -> list:
    """获取前后摄切换按钮的resourceId列表（全局常量 camera_switch_button）"""
    return list(_camera_ui.switch_camera_resource_ids)


def _get_switch_keywords() -> list:
    return list(_camera_ui.switch_camera_keywords)


def _get_front_keywords() -> list:
    return list(_camera_ui.front_camera_keywords)


def _get_photo_keywords() -> list:
    return list(_camera_ui.photo_mode_keywords)


def _get_video_keywords() -> list:
    return list(_camera_ui.video_mode_keywords)


def _get_button_y_ratio() -> float:
    return _camera_ui.button_y_ratio


def _get_switch_fallback_pos() -> tuple:
    """获取切换按钮兜底坐标比例 (x_ratio, y_ratio)"""
    return _camera_ui.switch_camera_fallback_x_ratio, _camera_ui.switch_camera_fallback_y_ratio


# 兼容旧代码的PACKAGE常量
PACKAGE = _get_package()


def case1_camera_photo_preview(u2, logger: Optional[Callable[[str], None]] = None):
    """case1: 相机拍照模式预览（保留向后兼容）"""
    log = logger or print
    package = _get_package()

    log("[case1] 启动相机...")
    try:
        u2.stop_app(package)
        time.sleep(1)
    except Exception:
        pass
    u2.launch_app(package)
    time.sleep(3)

    # 尝试切到拍照模式
    log("[case1] 尝试切换到拍照模式...")
    for keyword in _get_photo_keywords():
        try:
            if u2.exists(text=keyword):
                u2.click_element(text=keyword)
                log(f"[case1] 点击了 '{keyword}' 切换拍照模式")
                time.sleep(1)
                break
        except Exception:
            continue

    log("[case1] 相机已就绪，返回等待录制...")


def case2_camera_video_preview(u2, logger: Optional[Callable[[str], None]] = None):
    """case2: 相机录像模式预览（保留向后兼容）"""
    log = logger or print
    package = _get_package()

    log("[case2] 启动相机...")
    try:
        u2.stop_app(package)
        time.sleep(1)
    except Exception:
        pass
    u2.launch_app(package)
    time.sleep(3)

    # 尝试切到录像模式
    log("[case2] 尝试切换到录像模式...")
    for keyword in _get_video_keywords():
        try:
            if u2.exists(text=keyword):
                u2.click_element(text=keyword)
                log(f"[case2] 点击了 '{keyword}' 切换录像模式")
                time.sleep(1.5)
                break
        except Exception:
            continue

    log("[case2] 相机已就绪，返回等待录制...")


# ============================================================
# 新6个Case脚本（对应需求Excel）：4拍照+2录像
# ============================================================

def _launch_camera(u2, log):
    """通用：冷启动相机（am start优先，monkey备选，launch_app兜底）"""
    import subprocess
    _pkg = _get_package()

    # Step 0: force-stop
    log("  → am force-stop...")
    try:
        subprocess.run(
            ["adb", "shell", "am", "force-stop", _pkg],
            capture_output=True, text=True, timeout=5
        )
        time.sleep(0.3)
    except Exception as e:
        log(f"  → force-stop异常: {e}")

    # Step 1: am start 直接用intent启动
    log("  → am start (intent方式)...")
    _started = False
    try:
        result = subprocess.run(
            ["adb", "shell", "am", "start",
             "-a", "android.intent.action.MAIN",
             "-c", "android.intent.category.LAUNCHER",
             _pkg],
            capture_output=True, text=True, timeout=5
        )
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            _started = True
            log(f"  → ✓ 相机已启动 (am start)")
            if output.strip():
                log(f"    {output.strip()[:100]}")
        else:
            log(f"  → am start返回非0: {result.returncode}")
    except subprocess.TimeoutExpired:
        log(f"  → am start超时")
    except Exception as e:
        log(f"  → am start异常: {e}")

    # Step 2: monkey备选
    if not _started:
        log("  → am start未成功，尝试monkey(3s超时)...")
        try:
            result = subprocess.run(
                ["adb", "shell", "monkey", "-p", _pkg,
                 "-c", "android.intent.category.LAUNCHER", "1"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and "Events injected" in (result.stdout or ""):
                _started = True
                log(f"  → ✓ 相机已启动 (monkey)")
        except subprocess.TimeoutExpired:
            log(f"  → monkey超时")
        except Exception as e:
            log(f"  → monkey异常: {e}")

    # Step 3: launch_app兜底
    if not _started:
        log("  → 前面均失败，使用launch_app兜底(可能较慢)...")
        try:
            u2.launch_app(_pkg)
        except Exception as e:
            log(f"  → launch_app异常: {e}")


def _click_if_exists(u2, keywords, log, desc, wait_after=0.3):
    """在keywords列表中依次查找并点击第一个存在的控件；全部不存在返回False。
    优化策略：先尝试dump_hierarchy一次性获取UI树，本地解析文本匹配，避免多次ADB调用。"""
    # 策略1: 尝试dump_hierarchy一次性获取所有文本（最快，1次ADB）
    all_texts = set()
    try:
        hierarchy_xml = u2.d.dump_hierarchy()
        import re
        texts = re.findall(r'text="([^"]*)"', hierarchy_xml)
        all_texts = set(t for t in texts if t)
    except Exception:
        pass

    if all_texts:
        for kw in keywords:
            if kw in all_texts:
                u2.click_element(text=kw)
                log(f"  → 点击[{desc}]: '{kw}'")
                time.sleep(wait_after)
                return True

    # 策略2: 降级 - 逐个exists检查
    for kw in keywords:
        try:
            if u2.exists(text=kw):
                u2.click_element(text=kw)
                log(f"  → 点击[{desc}]: '{kw}'")
                time.sleep(wait_after)
                return True
        except Exception:
            continue

    log(f"  → 未找到[{desc}]")
    return False


def _switch_to_rear_camera(u2, log):
    """切换到后置摄像头：优先用resourceId → 再用关键词 → 最后才是坐标兜底"""
    # Step 1: 优先用 resourceId (全局常量 camera_switch_button)
    for rid in _get_switch_ids():
        try:
            if u2.exists(resourceId=rid):
                u2.click_element(resourceId=rid)
                log(f"  → 点击切换摄像头(resourceId={rid})")
                time.sleep(0.8)
                return
        except Exception:
            continue

    # Step 2: 关键词匹配
    if _click_if_exists(u2, _get_switch_keywords(), log, "后置/翻转"):
        time.sleep(0.8)
        return

    # Step 3: 坐标兜底（比例可配置）
    try:
        w, h = u2.get_window_size()
        xr, yr = _get_switch_fallback_pos()
        u2.click(int(w * xr), int(h * yr))
        log(f"  → [兜底]点击切换摄像头坐标({xr*100:.0f}%, {yr*100:.0f}%)")
        time.sleep(0.8)
    except Exception as e:
        log(f"  → 切换后置失败(可忽略): {e}")


def _switch_to_front_camera(u2, log):
    """切换到前置摄像头：优先用resourceId → 再用关键词 → 最后才是坐标兜底"""
    # Step 1: 优先用 resourceId (全局常量 camera_switch_button)
    for rid in _get_switch_ids():
        try:
            if u2.exists(resourceId=rid):
                u2.click_element(resourceId=rid)
                log(f"  → 点击切换摄像头(resourceId={rid})")
                time.sleep(0.8)
                return
        except Exception:
            continue

    # Step 2: 关键词匹配
    if _click_if_exists(u2, _get_front_keywords(), log, "前置/翻转"):
        time.sleep(0.8)
        return

    # Step 3: 坐标兜底（比例可配置）
    try:
        w, h = u2.get_window_size()
        xr, yr = _get_switch_fallback_pos()
        u2.click(int(w * xr), int(h * yr))
        log(f"  → [兜底]点击切换摄像头坐标({xr*100:.0f}%, {yr*100:.0f}%)")
        time.sleep(0.8)
    except Exception as e:
        log(f"  → 切换前置失败(可忽略): {e}")


def _take_photo(u2, log):
    """触发一次拍照（优先resourceId → 文字兜底 → 坐标兜底）"""
    shutter_ids = _get_shutter_ids()
    for rid in shutter_ids:
        try:
            if u2.exists(resourceId=rid):
                u2.click_element(resourceId=rid)
                log(f"  → 点击快门拍照(resourceId={rid})")
                time.sleep(1.5)
                return
        except Exception:
            continue
    # 文字兜底
    try:
        txt = _camera_ui.shutter_text_fallback
        if u2.exists(text=txt):
            u2.click_element(text=txt)
            log(f"  → 点击[{txt}]文字按钮")
            time.sleep(1.5)
            return
    except Exception:
        pass
    # 坐标兜底
    try:
        w, h = u2.get_window_size()
        ratio = _get_button_y_ratio()
        u2.click(w // 2, int(h * ratio))
        log(f"  → [兜底]点击底部{ratio*100:.0f}%位置拍照")
        time.sleep(1.5)
    except Exception as e:
        log(f"  → 拍照失败(可忽略): {e}")


# ============================================================
# 拍照Case 1：后置拍照模式 → 启动后预览
# （场景/滤镜/AI等选择操作已注释，手动在相机上设好后再运行）
# ============================================================
def photo_rear_003_launch(u2, logger: Optional[Callable[[str], None]] = None):
    """【后置拍照模式】启动后预览丢帧
    时长：5s（录制由引擎控制）
    """
    log = logger or print
    log("[后置-启动后预览] 冷启动相机...")
    _launch_camera(u2, log)
    log("[后置-启动后预览] 相机启动完毕")

    # 1. 切到拍照模式
    log("[后置-启动后预览] 切到拍照模式...")
    _click_if_exists(u2, _get_photo_keywords(), log, "拍照模式")

    # 2. 切到后置
    log("[后置-启动后预览] 切后置...")
    _switch_to_rear_camera(u2, log)

    # --- 以下UI选择操作已注释（手动在相机上设好：风景/高亮/AI默认） ---
    # # 设置场景[风景]
    # log("[后置-启动后预览] 设置场景[风景]...")
    # if not _click_if_exists(u2, ["风景", "Scenery", "SCENERY", "Landscape"], log, "风景模式"):
    #     log("  → [风景]控件未找到，跳过（保持默认场景）")
    #
    # # 设置效果[高亮]
    # log("[后置-启动后预览] 设置效果[高亮]...")
    # if not _click_if_exists(u2, ["高亮", "鲜艳", "HDR", "亮丽"], log, "高亮/HDR效果"):
    #     log("  → [高亮]控件未找到，跳过")
    #
    # # AI默认
    # log("[后置-启动后预览] 确保AI默认...")
    # _click_if_exists(u2, ["AI默认", "AI 开", "AI开", "智能", "自动"], log, "AI开启/默认")

    log("[后置-启动后预览] 等待1.5s稳定...")
    time.sleep(1.5)
    log("[后置-启动后预览] 就绪")


# ============================================================
# 拍照Case 2：后置拍照模式 → 拍照后预览
# （场景/滤镜/AI等选择操作已注释，手动在相机上设好后再运行）
# 执行时序（由引擎控制）：
#   1. 本函数：启动相机 → 切拍照/后置 → 返回回调
#   2. 引擎等待3s稳定 → 启动trace
#   3. trace启动约1s后：执行回调 → 拍一张照 → 随后trace覆盖"拍照后预览"的剩余时间
# 时长：5s
# ============================================================
def photo_rear_003_capture(u2, logger: Optional[Callable[[str], None]] = None):
    log = logger or print
    log("[后置-拍照后预览] 冷启动相机...")
    _launch_camera(u2, log)
    log("[后置-拍照后预览] 相机启动完毕")

    log("[后置-拍照后预览] 切拍照模式...")
    _click_if_exists(u2, _get_photo_keywords(), log, "拍照模式")

    log("[后置-拍照后预览] 切后置...")
    _switch_to_rear_camera(u2, log)

    # --- 以下UI选择操作已注释（手动在相机上设好：风景/高亮/AI默认） ---
    # log("[后置-拍照后预览] 场景=风景...")
    # _click_if_exists(u2, ["风景", "Scenery", "SCENERY", "Landscape"], log, "风景模式")
    #
    # log("[后置-拍照后预览] 效果=高亮...")
    # _click_if_exists(u2, ["高亮", "鲜艳", "HDR", "亮丽"], log, "高亮/HDR效果")
    #
    # log("[后置-拍照后预览] AI设置...")
    # _click_if_exists(u2, ["AI默认", "AI 开", "AI开", "智能", "自动"], log, "AI开启/默认")

    time.sleep(1)
    log("[后置-拍照后预览] 准备就绪，等待trace启动（拍照会在trace中约1s处触发）...")

    # ===== 返回回调：由引擎在trace启动1s后执行拍照动作 =====
    def _capture_action():
        log("[后置-拍照后预览] ===== trace期间：执行拍照动作 =====")
        _take_photo(u2, log)
        time.sleep(1.5)
        log("[后置-拍照后预览] ===== 拍照完成，进入后预览 =====")
    return _capture_action


# ============================================================
# 拍照Case 3：前置人像模式 → 启动后预览
# （美颜/高亮等选择操作已注释，手动在相机上设好后再运行）
# ============================================================
def photo_front_011_launch(u2, logger: Optional[Callable[[str], None]] = None):
    """【前置人像模式】启动后预览丢帧
    时长：5s
    """
    log = logger or print
    log("[前置人像-启动后预览] 冷启动相机...")
    _launch_camera(u2, log)
    log("[前置人像-启动后预览] 相机启动完毕")

    # 1. 切到前置
    log("[前置人像-启动后预览] 切前置...")
    _switch_to_front_camera(u2, log)

    # 2. 切人像模式（核心模式切换，保留）
    log("[前置人像-启动后预览] 切人像模式...")
    _click_if_exists(u2, ["人像", "PORTRAIT", "Portrait", "portrait", "美颜相机"], log, "人像模式")

    # --- 以下UI选择操作已注释（手动在相机上设好：美颜/高亮高动态） ---
    # # 开美颜
    # log("[前置人像-启动后预览] 开美颜...")
    # if not _click_if_exists(u2, ["美颜", "Beauty", "BEAUTY", "美肤"], log, "美颜开启"):
    #     log("  → [美颜]控件没找到，尝试其他路径...")
    #
    # # 效果：高亮高动态
    # log("[前置人像-启动后预览] 设置效果=高亮高动态...")
    # if not _click_if_exists(u2, ["高亮", "高动态", "HDR", "鲜艳", "亮丽"], log, "高亮/HDR"):
    #     log("  → [高亮高动态]控件未找到，跳过")

    time.sleep(1.5)
    log("[前置人像-启动后预览] 就绪，等待trace录制...")


# ============================================================
# 拍照Case 4：前置人像模式 → 拍照后预览
# （美颜/高亮等选择操作已注释，手动在相机上设好后再运行）
# 执行时序（由引擎控制）：
#   1. 本函数：启动相机 → 切前置 → 返回回调
#   2. 引擎等待3s稳定 → 启动trace
#   3. trace启动约1s后：执行回调 → 拍一张照 → 随后trace覆盖"拍照后预览"剩余时间
# 时长：5s
# ============================================================
def photo_front_011_capture(u2, logger: Optional[Callable[[str], None]] = None):
    log = logger or print
    log("[前置人像-拍照后预览] 冷启动相机...")
    _launch_camera(u2, log)
    log("[前置人像-拍照后预览] 相机启动完毕")

    log("[前置人像-拍照后预览] 切前置...")
    _switch_to_front_camera(u2, log)

    # 切人像模式（核心模式切换，保留）
    log("[前置人像-拍照后预览] 切人像模式...")
    _click_if_exists(u2, ["人像", "PORTRAIT", "Portrait", "portrait", "美颜相机"], log, "人像模式")

    # --- 以下UI选择操作已注释（手动在相机上设好：美颜/高亮高动态） ---
    # log("[前置人像-拍照后预览] 开美颜...")
    # _click_if_exists(u2, ["美颜", "Beauty", "BEAUTY", "美肤"], log, "美颜开启")
    #
    # log("[前置人像-拍照后预览] 设置效果=高亮高动态...")
    # _click_if_exists(u2, ["高亮", "高动态", "HDR", "鲜艳", "亮丽"], log, "高亮/HDR")

    time.sleep(1)
    log("[前置人像-拍照后预览] 准备就绪，等待trace启动（拍照会在trace中约1s处触发）...")

    # ===== 返回回调：由引擎在trace启动1s后执行拍照动作 =====
    def _capture_action():
        log("[前置人像-拍照后预览] ===== trace期间：执行拍照动作 =====")
        _take_photo(u2, log)
        time.sleep(1.5)
        log("[前置人像-拍照后预览] ===== 拍照完成，进入后预览 =====")
    return _capture_action


# ============================================================
# 录像Case 5：录像模式 → 后置 Record_video
# （分辨率/帧率/美肤/效果等选择操作已注释，手动在相机上设好后再运行）
# 关键：切好模式后 → 点击录制按钮 → 真实录制20s
# ============================================================
def _start_video_recording(u2, log):
    """通用：点击录像按钮开始录制（优先resourceId → 文字兜底 → 坐标兜底）"""
    rec_ids = _get_record_ids()
    for rid in rec_ids:
        try:
            if u2.exists(resourceId=rid):
                u2.click_element(resourceId=rid)
                log(f"  → 点击录像按钮(resourceId={rid})")
                time.sleep(1)
                return True
        except Exception:
            continue
    # 文字兜底
    try:
        txt = _camera_ui.record_text_fallback
        if u2.exists(text=txt):
            u2.click_element(text=txt)
            log(f"  → 点击[{txt}]文字按钮")
            time.sleep(1)
            return True
    except Exception:
        pass
    # 坐标兜底
    try:
        w, h = u2.get_window_size()
        ratio = _get_button_y_ratio()
        u2.click(w // 2, int(h * ratio))
        log(f"  → [兜底]点击底部{ratio*100:.0f}%位置开始录像")
        time.sleep(1)
        return True
    except Exception as e:
        log(f"  → 点击录像按钮失败(可忽略): {e}")
        return False


def video_rear_003(u2, logger: Optional[Callable[[str], None]] = None):
    """Record_video 录制视频卡顿丢帧 - 后置
    【录像模式-后置】
    时长：20s（脚本会点击录像按钮开始真实录制）
    """
    log = logger or print
    log("[录像-后置] 冷启动相机...")
    _launch_camera(u2, log)
    log("[录像-后置] 相机启动完毕")

    # 1. 切录像模式
    log("[录像-后置] 切录像模式...")
    _click_if_exists(u2, _get_video_keywords(), log, "录像模式")
    time.sleep(1.5)

    # 2. 切后置
    log("[录像-后置] 切后置...")
    _switch_to_rear_camera(u2, log)

    # --- 以下UI选择操作已注释（手动在相机上设好：1080P/30fps/美肤/效果） ---
    # # 3. 分辨率：1080P
    # log("[录像-后置] 尝试设置分辨率=1080P...")
    # if not _click_if_exists(u2, ["1080P", "1080p", "FHD", "1920×1080", "1920x1080"], log, "1080P分辨率"):
    #     log("  → 未找到分辨率控件，使用默认")
    #
    # # 4. 帧率：30fps
    # log("[录像-后置] 尝试设置帧率=30fps...")
    # if not _click_if_exists(u2, ["30fps", "30FPS", "30 fps"], log, "30fps帧率"):
    #     log("  → 未找到帧率控件，使用默认")
    #
    # # 5. 美肤
    # log("[录像-后置] 开美肤/美颜...")
    # _click_if_exists(u2, ["美肤", "美颜", "Beauty", "BEAUTY"], log, "美肤开启")
    #
    # # 6. 效果：高亮 + 人像
    # log("[录像-后置] 效果=高亮,人像...")
    # _click_if_exists(u2, ["高亮", "鲜艳", "亮丽", "HDR"], log, "高亮效果")
    # _click_if_exists(u2, ["人像", "人像视频", "背景虚化", "Portrait", "人像虚化"], log, "人像/虚化模式")

    time.sleep(1)

    # ======== 关键：点击录制按钮开始真实录制 ========
    log("[录像-后置] ======== 点击录制按钮开始录像 ========")
    _start_video_recording(u2, log)
    log("[录像-后置] 录像已开始，等待trace录制20s...")


# ============================================================
# 录像Case 6：录像模式 → 前置 Record_video
# （分辨率/帧率/美肤/效果等选择操作已注释，手动在相机上设好后再运行）
# ============================================================
def video_front_006(u2, logger: Optional[Callable[[str], None]] = None):
    """Record_video 录制视频卡顿丢帧 - 前置
    【录像模式-前置】
    时长：20s（脚本会点击录像按钮开始真实录制）
    """
    log = logger or print
    log("[录像-前置] 冷启动相机...")
    _launch_camera(u2, log)
    log("[录像-前置] 相机启动完毕")

    log("[录像-前置] 切录像模式...")
    _click_if_exists(u2, _get_video_keywords(), log, "录像模式")
    time.sleep(1.5)

    log("[录像-前置] 切前置...")
    _switch_to_front_camera(u2, log)

    # --- 以下UI选择操作已注释（手动在相机上设好：1080P/30fps/美肤/效果） ---
    # log("[录像-前置] 尝试设置分辨率=1080P...")
    # _click_if_exists(u2, ["1080P", "1080p", "FHD", "1920×1080", "1920x1080"], log, "1080P分辨率")
    #
    # log("[录像-前置] 尝试设置帧率=30fps...")
    # _click_if_exists(u2, ["30fps", "30FPS", "30 fps"], log, "30fps帧率")
    #
    # log("[录像-前置] 开美肤/美颜...")
    # _click_if_exists(u2, ["美肤", "美颜", "Beauty", "BEAUTY"], log, "美肤开启")
    #
    # log("[录像-前置] 效果=高亮,人像...")
    # _click_if_exists(u2, ["高亮", "鲜艳", "亮丽", "HDR"], log, "高亮效果")
    # _click_if_exists(u2, ["人像", "人像视频", "背景虚化", "Portrait", "人像虚化"], log, "人像/虚化模式")

    time.sleep(1)

    # ======== 关键：点击录制按钮开始真实录制 ========
    log("[录像-前置] ======== 点击录制按钮开始录像 ========")
    _start_video_recording(u2, log)
    log("[录像-前置] 录像已开始，等待trace录制20s...")


_BUILTIN_SCRIPTS: Dict[str, Callable] = {
    "case1_camera_photo_preview": case1_camera_photo_preview,
    "case2_camera_video_preview": case2_camera_video_preview,
    # 新6个Case脚本
    "photo_rear_003_launch": photo_rear_003_launch,
    "photo_rear_003_capture": photo_rear_003_capture,
    "photo_front_011_launch": photo_front_011_launch,
    "photo_front_011_capture": photo_front_011_capture,
    "video_rear_003": video_rear_003,
    "video_front_006": video_front_006,
}


def list_builtin_scripts():
    """列出所有内置脚本名"""
    return list(_BUILTIN_SCRIPTS.keys())


def _load_script_from_file(script_path: str) -> Dict[str, Callable]:
    """从 .py 文件加载脚本函数，返回 {函数名: 函数对象}"""
    if not script_path or not os.path.exists(script_path):
        return {}
    try:
        mod_name = f"custom_case_script_{os.path.splitext(os.path.basename(script_path))[0]}"
        spec = importlib.util.spec_from_file_location(mod_name, script_path)
        if spec is None or spec.loader is None:
            return {}
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        funcs = {}
        for name, obj in vars(mod).items():
            if name.startswith("_"):
                continue
            if callable(obj):
                funcs[name] = obj
        return funcs
    except Exception as e:
        print(f"加载自定义脚本失败 {script_path}: {e}")
        return {}


def resolve_script(script_name: str = "", script_path: str = "") -> Optional[Callable]:
    """根据 script_name 和 script_path 解析出要执行的脚本函数
    优先级：script_path 中的同名函数 > 内置 script_name 函数 > 内置 script_path 任意第一个函数 > None
    返回 None 表示不执行任何脚本（纯等待/手动操作模式）
    """
    # 先加载自定义脚本文件
    custom_funcs = _load_script_from_file(script_path) if script_path else {}

    # 如果指定了函数名，优先找自定义脚本，再找内置
    if script_name:
        if script_name in custom_funcs:
            return custom_funcs[script_name]
        if script_name in _BUILTIN_SCRIPTS:
            return _BUILTIN_SCRIPTS[script_name]

    # 没指定函数名，但有自定义脚本文件：取第一个函数（按文件定义顺序的第一个callable非内建）
    if custom_funcs:
        return next(iter(custom_funcs.values()))

    return None
