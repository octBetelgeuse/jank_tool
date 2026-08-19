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
    camera_text_aliases = ["相机", "Camera", "camera", "摄像头"]

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


def _get_camera_text_aliases() -> list:
    """获取相机桌面图标文字别名列表"""
    return list(_camera_ui.camera_text_aliases)


# 兼容旧代码的PACKAGE常量
PACKAGE = _get_package()


# ============================================================
# 负载操作 - 通用辅助
# ============================================================

# 启动页/欢迎页「跳过」按钮常见关键词（按匹配优先级排序，先文本后描述/资源ID）
_SPLASH_SKIP_KEYWORDS = [
    # 纯中文
    "跳过", "跳过广告", "立即跳过", "跳过此广告", "跳过广告>", "跳过 >", "→跳过",
    "跳过3", "跳过2", "跳过1", "跳过5", "跳过4", "跳过6",
    # 纯英文
    "SKIP", "Skip", "skip", "SKIP AD", "Skip Ad", "Skip ad",
    "SKIP>", "Skip>", "SKIP 5", "SKIP 4", "SKIP 3", "SKIP 2", "SKIP 1",
    "Skip >", "skip >",
    # 变体（关闭/稍后/下一步、同意等常见进入主页前的最后一步）
    "跳过引导", "跳过弹窗", "关闭广告", "取消", "CLOSE", "Close", "close",
    "X", "✕", "✖", "×",  # 右上角叉号常见字符
]
# 包含这些关键字的资源ID、content-desc也视作跳过按钮候选
_SPLASH_SKIP_RES_PATTERNS = [
    "skip", "ad_skip", "btn_skip", "bt_skip", "button_skip",
    "close", "ad_close", "btn_close", "cancel", "dismiss", "jump",
]


def try_skip_splash_screen(u2, log: Callable[[str], None], timeout_s: float = 4.5) -> bool:
    """
    负载App启动后，尝试点击欢迎页/广告页的「跳过/SKIP」按钮，快速进入主界面。
    匹配策略（优先级从高到低，避免误点）：
      1) 精确匹配 text 关键词（跳过 / SKIP 等 _SPLASH_SKIP_KEYWORDS）
      2) 模糊匹配 textContains（包含关键字的更长文本，如 "3秒后跳过"）
      3) 按 resourceId 模式（skip/ad_skip/btn_skip/close 等）
      4) content-desc 关键字匹配
    命中后点击坐标（避免 uiautomator2 click() 内部等待），最长轮询 timeout_s 秒。
    """
    import re as _re
    end_at = time.time() + timeout_s
    poll_interval = 0.4
    clicked = False

    def _try_click_element(el) -> bool:
        """拿到 bounds 后坐标点击，失败回退到 click(timeout)"""
        nonlocal clicked
        try:
            info = el.info
            bounds = info.get("bounds") or {}
            if bounds:
                cx = (bounds.get("left", 0) + bounds.get("right", 0)) // 2
                cy = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2
                # 按钮一般在屏幕上半部，跳过按钮通常<200px高；极端防误点
                if 10 <= cx and 10 <= cy and cx <= 20000 and cy <= 20000:
                    u2.d.click(cx, cy)
                    clicked = True
                    return True
            # 兜底：走 element click
            el.click(timeout=0.8)
            clicked = True
            return True
        except Exception:
            return False

    def _hit_text(t: str) -> bool:
        if not t:
            return False
        tt = t.strip()
        if not tt:
            return False
        for kw in _SPLASH_SKIP_KEYWORDS:
            if tt == kw:
                return True
        # 模糊命中：形如 "3 秒后跳过" / "3s Skip Ad"
        low = tt.lower()
        fuzzy_needles = ["跳过", "skip", "关闭广告", "close ad"]
        for nd in fuzzy_needles:
            if nd in low:
                # 长度不要太离谱（避免把普通文案命中），最长<=20字符
                if len(tt) <= 24:
                    return True
        return False

    while time.time() < end_at:
        # 1. 精确 text 匹配（遍历关键词，快路径）
        found_exact = False
        for kw in _SPLASH_SKIP_KEYWORDS:
            try:
                el = u2.d(text=kw)
                if el.exists(timeout=0.08):
                    info = el.info or {}
                    # 粗略的"点击区域过滤"：跳过按钮一般在屏幕上半/右上角
                    bounds = info.get("bounds") or {}
                    cy = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2 if bounds else 0
                    if bounds and cy > 0:
                        w, h = 2000, 2000  # placeholder
                        try:
                            ws = u2.get_window_size()
                            w, h = ws[0], ws[1]
                        except Exception:
                            pass
                        # 跳过按钮基本不会在屏幕下半段的中间（那里是"同意"或"开始使用"）
                        # 但右上角、屏幕顶部1/3、右下角时间标旁边都可能有 -> 放宽
                        # 仅过滤纯键盘行底部按钮：bottom > 90% 且 width<屏幕宽 60%
                        bottom = bounds.get("bottom", 0)
                        left = bounds.get("left", 0)
                        right = bounds.get("right", 0)
                        bw = right - left
                        if bottom >= int(h * 0.93) and bw < int(w * 0.6):
                            # 很可能是"同意/开始"类按钮，跳过
                            continue
                    log(f"    [跳过页] 命中text='{kw}'，点击")
                    if _try_click_element(el):
                        found_exact = True
                        break
            except Exception:
                continue
        if found_exact:
            # 再等一下给页面跳转，尝试第二轮点（有时有两个广告连续）
            time.sleep(0.6)
            continue

        # 2. 资源ID模式匹配（idMatches 正则）
        try:
            pattern = ".*(" + "|".join(_SPLASH_SKIP_RES_PATTERNS) + ").*"
            el = u2.d(resourceIdMatches=pattern)
            if el.exists(timeout=0.08):
                # 取最靠上、且面积较小的（避免匹配到整个父布局）
                cands = []
                try:
                    for e in el:
                        try:
                            info = e.info or {}
                            b = info.get("bounds") or {}
                            if not b:
                                continue
                            w_e = b.get("right", 0) - b.get("left", 0)
                            h_e = b.get("bottom", 0) - b.get("top", 0)
                            if w_e <= 0 or h_e <= 0:
                                continue
                            # 跳过按钮一般较小；极端尺寸直接跳过
                            if w_e > 600 or h_e > 200:
                                continue
                            cands.append((b.get("top", 0), b.get("left", 0), e, info))
                        except Exception:
                            continue
                except Exception:
                    pass
                if cands:
                    cands.sort(key=lambda x: (x[0], x[1]))  # 顶部优先
                    top_e = cands[0][2]
                    # 再校验 text/desc，避免把"分享"、"搜索"等 close/btn_id 当作跳过
                    try:
                        txt = (cands[0][3].get("text") or "").strip()
                        desc = (cands[0][3].get("contentDescription") or "").strip()
                    except Exception:
                        txt, desc = "", ""
                    if _hit_text(txt) or _hit_text(desc):
                        log(f"    [跳过页] 命中resId，点击 ({txt or desc or 'no-text'})")
                        _try_click_element(top_e)
                        time.sleep(0.6)
                        continue
                    # resID 强特征（btn_skip/ad_skip 等）且 text 为空（不少App跳过按钮是图片）也接受
                    if not txt and not desc:
                        log(f"    [跳过页] 命中resId(图片按钮)，点击")
                        _try_click_element(top_e)
                        time.sleep(0.6)
                        continue
        except Exception:
            pass

        # 3. contentDescription 模糊匹配
        try:
            # 拿顶层 dump 的 text+desc 太慢，退化为用 textContains 的几个强模糊词
            for kw in ["跳过", "skip", "SKIP"]:
                try:
                    el = u2.d(textContains=kw)
                    if el.exists(timeout=0.08):
                        # 限制长度 < 16，防止把标题长文本点错
                        try:
                            txt = (el.info.get("text") or "").strip()
                        except Exception:
                            txt = ""
                        if 0 < len(txt) <= 18 and ("跳过" in txt.lower() or "skip" in txt.lower()):
                            log(f"    [跳过页] textContains命中='{txt}'，点击")
                            _try_click_element(el)
                            time.sleep(0.6)
                            break
                except Exception:
                    continue
        except Exception:
            pass

        # 等一下再下一轮
        time.sleep(poll_interval)

    if clicked:
        log("    [跳过页] 已尝试点击跳过欢迎页/广告页")
    return clicked


# ============================================================
# 负载操作（每轮测试前执行，制造系统负载）
# ============================================================

# 负载操作配置：每个条目 {包名, 显示名, 操作类型, 参数, region}
# 操作类型: "launch" 只启动, "swipe" 启动后滑动N次, "navigate" 启动后导航到指定目的地
# region: "国内" 或 "海外"
# text_aliases: 桌面图标文字别名（按顺序尝试匹配点击）
LOAD_OPERATIONS = [
    # 国内应用
    {"package": "com.hihonor.health", "name": "运动健康", "action": "launch", "region": "国内",
     "text_aliases": ["运动健康", "Honor Health"]},
    {"package": "com.bilibili.app.in", "name": "哔哩哔哩", "action": "swipe", "count": 5, "region": "国内",
     "text_aliases": ["哔哩哔哩", "bilibili"]},
    {"package": "com.autonavi.minimap", "name": "高德地图", "action": "navigate", "keyword": "大雁塔", "region": "国内",
     "text_aliases": ["高德地图", "Amap"]},
    {"package": "com.tencent.qqmusic", "name": "QQ音乐", "action": "launch", "region": "国内",
     "text_aliases": ["QQ音乐"]},
    {"package": "com.baidu.searchbox", "name": "百度", "action": "swipe", "count": 5, "region": "国内",
     "text_aliases": ["百度", "Baidu"]},
    {"package": "com.dragon.read", "name": "番茄免费小说", "action": "swipe", "count": 5, "region": "国内",
     "text_aliases": ["番茄免费小说", "番茄小说"]},
    {"package": "com.ss.android.article.news", "name": "今日头条", "action": "swipe", "count": 5, "region": "国内",
     "text_aliases": ["今日头条", "Toutiao"]},
    {"package": "com.xunmeng.pinduoduo", "name": "拼多多", "action": "swipe", "count": 5, "region": "国内",
     "text_aliases": ["拼多多", "Pinduoduo"]},
    {"package": "com.eg.android.AlipayGphone", "name": "支付宝", "action": "launch", "region": "国内",
     "text_aliases": ["支付宝", "Alipay"]},
    {"package": "com.google.android.apps.photos", "name": "图库", "action": "swipe", "count": 5, "region": "国内",
     "text_aliases": ["图库", "Photos"]},
    {"package": "com.tencent.mm", "name": "微信", "action": "swipe", "count": 5, "region": "国内",
     "text_aliases": ["微信", "WeChat"]},
    {"package": "com.ss.android.ugc.aweme", "name": "抖音", "action": "swipe", "count": 5, "region": "国内",
     "text_aliases": ["抖音", "Douyin"]},
    # 海外应用
    {"package": "com.vivavideo.imkit", "name": "VivaVideo", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["VivaVideo"]},
    {"package": "com.reddit.frontpage", "name": "reddit", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["reddit", "Reddit"]},
    {"package": "com.shazam.android", "name": "Shazam", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["Shazam"]},
    {"package": "com.samsung.android.welt", "name": "Wolt", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["Wolt"]},
    {"package": "com.zynga.magictiles3", "name": "MagicTiles3", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["MagicTiles3"]},
    {"package": "com.sec.android.app.sheinc", "name": "SHEIN", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["SHEIN"]},
    {"package": "com.lidl.mobile.scanner", "name": "Lidl", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["Lidl"]},
    {"package": "com.ibisinc.ibispaintx", "name": "ibisPaint X", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["ibisPaint X", "ibisPaint"]},
    {"package": "com.zedge.android", "name": "Zedge", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["Zedge"]},
    {"package": "com.blgo.superapp", "name": "BLGO LIVE", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["BLGO LIVE", "BLGO"]},
    {"package": "com.meitu.reface", "name": "Reface", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["Reface"]},
    {"package": "com.kunlun.xrecorder", "name": "xRecorder", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["xRecorder"]},
    {"package": "com.amazon.mShop.android.shopping", "name": "Amazon Shop", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["Amazon Shop", "Amazon"]},
    {"package": "com.android.chrome", "name": "Chrome", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["Chrome"]},
    {"package": "com.waze", "name": "Waze", "action": "swipe", "count": 5, "region": "海外",
     "text_aliases": ["Waze"]},
]


def run_load_operations(u2, logger: Optional[Callable[[str], None]] = None, region: str = "国内"):
    """执行负载操作：启动多个App并执行滑动等操作，制造系统负载
    
    Args:
        u2: UiAutomatorManager 实例
        logger: 日志输出函数
        region: 负载区域筛选 - "国内" / "海外" / "全部"
    """
    log = logger or print
    
    # 根据 region 过滤负载操作
    if region == "全部":
        ops = LOAD_OPERATIONS
    else:
        ops = [op for op in LOAD_OPERATIONS if op.get("region") == region]
    
    log("=" * 50)
    log(f"[负载操作] 开始执行 (区域={region})...")
    log(f"[负载操作] 共 {len(ops)} 个App需要处理")
    log("=" * 50)

    import subprocess
    success_count = 0
    fail_count = 0

    for idx, op in enumerate(ops, 1):
        pkg = op["package"]
        name = op["name"]
        action = op["action"]
        aliases = op.get("text_aliases", [name])

        log(f"[{idx}/{len(ops)}] {name}({pkg}) - {action}...")
        _T0 = time.time()

        try:
            # 1. 回桌面（确保在 Launcher 界面）
            _T1 = time.time()
            try:
                u2.press_home()
                time.sleep(0.5)
            except Exception:
                pass
            _T_home = time.time() - _T1
            log(f"  [打点] 回桌面完成 ({_T_home:.2f}s)，开始找图标...")

            # 2. 通过文字找图标并点击启动
            _T2 = time.time()
            launched = False
            _click_pos = None  # 记录坐标点击位置
            for text in aliases:
                try:
                    el = u2.d(text=text)
                    if el.exists(timeout=1):
                        # 获取图标坐标，用坐标点击（避免 click() 内部等待）
                        info = el.info
                        bounds = info.get("bounds", {})
                        if bounds:
                            cx = (bounds.get("left", 0) + bounds.get("right", 0)) // 2
                            cy = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2
                            _click_pos = (cx, cy)
                            u2.d.click(cx, cy)
                            log(f"  [打点] 坐标点击({cx},{cy}) 图标: '{text}'")
                        else:
                            el.click(timeout=1.5)
                            log(f"  [打点] 元素点击图标: '{text}'")
                        launched = True
                        break
                except Exception as _e:
                    log(f"  [打点] 别名'{text}'查找失败: {_e}")
                    continue

            # 如果没找到，尝试 resource-id
            if not launched:
                try:
                    el = u2.d(resourceId="com.android.launcher3:id/icon")
                    if el.exists(timeout=1):
                        for child in el:
                            try:
                                txt = child.get_text()
                                if txt and txt in aliases:
                                    child.click(timeout=1.5)
                                    launched = True
                                    log(f"  [打点] 点击了资源ID图标: '{txt}'")
                                    break
                            except Exception:
                                continue
                except Exception as _e:
                    log(f"  [打点] resource-id遍历失败: {_e}")

            # 最后 fallback 用 am start
            if not launched:
                log(f"  [打点] 桌面未找到图标，用 am start 兜底")
                try:
                    subprocess.run(
                        ["adb", "-s", u2.device_id, "shell", "am", "start",
                         "-a", "android.intent.action.MAIN",
                         "-c", "android.intent.category.LAUNCHER",
                         pkg],
                        capture_output=True, timeout=3
                    )
                    launched = True
                except Exception as _e:
                    log(f"  [打点] am start兜底异常: {_e}")

            # 等待 App 启动完成：先让欢迎页/广告页出现 (1.5s)，再尝试点跳过，最后补齐总等待
            WAIT_TOTAL_S = 5.0
            SPLASH_APPEAR_S = 1.5
            SKIP_TIMEOUT_S = 3.0
            log(f"  [打点] 等待启动(欢迎页出现{SPLASH_APPEAR_S}s + 跳过{SKIP_TIMEOUT_S}s + 补齐 共{WAIT_TOTAL_S}s)...")
            _t_wait_start = time.time()
            time.sleep(SPLASH_APPEAR_S)
            try:
                try_skip_splash_screen(u2, log, timeout_s=SKIP_TIMEOUT_S)
            except Exception as _se:
                log(f"  [跳过页] 异常: {_se}")
            # 补齐到 WAIT_TOTAL_S（如果点击跳过逻辑很快结束就补齐等待；若超时则不额外加）
            _elapsed = time.time() - _t_wait_start
            _remain = WAIT_TOTAL_S - _elapsed
            if _remain > 0:
                time.sleep(_remain)
            _T_launch = time.time() - _T2
            log(f"  [打点] 启动阶段总耗时 {_T_launch:.2f}s")

            if not launched:
                log(f"  ❌ {name} 未能启动")
                fail_count += 1
                continue

            # 3. 执行操作
            _T3 = time.time()
            if action == "launch":
                log(f"  [打点] action=launch，无额外操作")

            elif action == "swipe":
                count = op.get("count", 5)
                w, h = u2.get_window_size()
                for i in range(count):
                    try:
                        u2.d.swipe(w * 0.5, h * 0.7, w * 0.5, h * 0.3, duration=0.3)
                        time.sleep(0.3)
                    except Exception as _e:
                        log(f"  [打点] swipe第{i+1}次异常: {_e}")
                        break
                log(f"  [打点] swipe {count}次完成")

            elif action == "navigate":
                keyword = op.get("keyword", "")
                if keyword:
                    try:
                        subprocess.run(
                            ["adb", "-s", u2.device_id, "shell", "am", "start",
                             "-a", "android.intent.action.VIEW",
                             "-d", f"geo:0,0?q={keyword}"],
                            capture_output=True, text=True, timeout=5
                        )
                        time.sleep(1)
                    except Exception as _e:
                        log(f"  [打点] 导航Intent异常: {_e}")
                    w, h = u2.get_window_size()
                    for i in range(3):
                        try:
                            u2.d.swipe(w * 0.5, h * 0.7, w * 0.5, h * 0.3, duration=0.3)
                            time.sleep(0.3)
                        except Exception as _e:
                            log(f"  [打点] navigate swipe第{i+1}次异常: {_e}")
                            break
                    log(f"  [打点] navigate + swipe 3次完成")
            _T_action = time.time() - _T3
            log(f"  [打点] 操作阶段耗时 {_T_action:.2f}s")

            _T_total = time.time() - _T0
            log(f"[{idx}/{len(ops)}] {name} ✅ 完成 | 总耗时{_T_total:.2f}s "
                f"(回桌面{_T_home:.2f}s + 启动{_T_launch:.2f}s + 操作{_T_action:.2f}s)")

            success_count += 1

        except Exception as e:
            import traceback
            fail_count += 1
            log(f"[{idx}/{len(ops)}] {name} ❌ 失败: {e}")
            log(f"  堆栈: {traceback.format_exc().strip()[-300:]}")

    # 负载操作完成后：停止所有负载App + 回桌面，防止后台继续占用资源
    import subprocess
    log("[负载操作] 清理后台：停止所有负载App...")
    kill_count = 0
    for op in ops:
        try:
            subprocess.run(
                ["adb", "-s", u2.device_id, "shell", "am", "force-stop", op["package"]],
                capture_output=True, timeout=3
            )
            kill_count += 1
        except Exception:
            pass
    log(f"[负载操作] 已停止 {kill_count} 个后台App")

    try:
        u2.press_home()
        time.sleep(0.5)
    except Exception:
        pass

    log("=" * 50)
    log(f"[负载操作] 完成！成功{success_count}, 失败{fail_count}")
    log("=" * 50)


def case1_camera_photo_preview(u2, logger: Optional[Callable[[str], None]] = None):
    """case1: 相机拍照模式预览（保留向后兼容）"""
    log = logger or print

    log("[case1] 启动相机...")
    _launch_camera(u2, log)

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

    log("[case2] 启动相机...")
    _launch_camera(u2, log)

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


def manual_interaction_test(u2, logger: Optional[Callable[[str], None]] = None):
    """手动交互测试：不执行任何UI自动化，提示用户手动操作手机触发负载，用于测试卡顿检测功能"""
    log = logger or print
    log("=" * 50)
    log("[手动交互测试] 请开始操作手机！")
    log("[手动交互测试] 录制期间请启动高负载功能（如相机/游戏/视频等）")
    log("[手动交互测试] Trace将在30s内持续录制...")
    log("=" * 50)


# ============================================================
# 新6个Case脚本（对应需求Excel）：4拍照+2录像
# ============================================================

def _launch_camera(u2, log):
    """通用：冷启动相机（点击桌面图标启动）"""
    _pkg = _get_package()
    aliases = _get_camera_text_aliases()
    log("  → 回桌面...")

    # 1. 回桌面
    try:
        u2.press_home()
        time.sleep(0.5)
    except Exception:
        pass

    # 2. 按文字找图标并点击
    launched = False
    for text in aliases:
        try:
            el = u2.d(text=text)
            if el.exists(timeout=1):
                el.click()
                launched = True
                log(f"  → 点击了相机图标: '{text}'")
                break
        except Exception:
            continue

    # 找不到则尝试 resource-id 遍历
    if not launched:
        try:
            el = u2.d(resourceId="com.android.launcher3:id/icon")
            if el.exists(timeout=1):
                for child in el:
                    try:
                        txt = child.get_text()
                        if txt and txt in aliases:
                            child.click()
                            launched = True
                            log(f"  → 点击了相机图标: '{txt}'")
                            break
                    except Exception:
                        continue
        except Exception:
            pass

    if not launched:
        log("  ⚠️ 桌面未找到相机图标，用 am start 兜底...")
        import subprocess
        try:
            subprocess.run(
                ["adb", "shell", "am", "start",
                 "-a", "android.intent.action.MAIN",
                 "-c", "android.intent.category.LAUNCHER",
                 _pkg],
                capture_output=True, timeout=5
            )
            launched = True
        except Exception:
            pass

    if not launched:
        log("  ❌ 相机启动失败")
        return

    # 3. 等待相机启动
    log("  → 等待相机启动...")
    time.sleep(4)
    log("  → ✓ 相机已启动")


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
    # 手动交互测试
    "manual_interaction_test": manual_interaction_test,
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
