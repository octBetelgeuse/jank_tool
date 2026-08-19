# -*- coding: utf-8 -*-
"""
批量下载负载 APK 脚本
从 mirrorapk.com 下载 LOAD_OPERATIONS 中列出的所有应用，
可选下载完成后自动 adb install 到连接的设备。

用法:
    python download_apks.py                    # 下载全部
    python download_apks.py --region 国内       # 只下载国内应用
    python download_apks.py --region 海外       # 只下载海外应用
    python download_apks.py --region 国内 --install   # 下载后自动 adb install
"""

import os
import sys
import time
import argparse
import urllib.request
import urllib.error
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# ========== 负载应用列表（与 case_scripts.py 中 LOAD_OPERATIONS 保持同步）==========
LOAD_APPS: List[Dict] = [
    # 国内应用
    {"package": "com.huawei.health", "name": "运动健康", "region": "国内"},
    {"package": "tv.danmaku.bili", "name": "哔哩哔哩", "region": "国内"},
    {"package": "com.autonavi.minimap", "name": "高德地图", "region": "国内"},
    {"package": "com.tencent.qqmusic", "name": "QQ音乐", "region": "国内"},
    {"package": "com.baidu.searchbox", "name": "百度", "region": "国内"},
    {"package": "com.dragon.read", "name": "番茄免费小说", "region": "国内"},
    {"package": "com.ss.android.article.news", "name": "今日头条", "region": "国内"},
    {"package": "com.sankuai.meituan", "name": "拼多多", "region": "国内"},
    {"package": "com.eg.android.AlipayGphone", "name": "支付宝", "region": "国内"},
    {"package": "com.miui.gallery", "name": "图库", "region": "国内"},
    {"package": "com.tencent.mm", "name": "微信", "region": "国内"},
    {"package": "com.ss.android.ugc.aweme", "name": "抖音", "region": "国内"},
    # 海外应用
    {"package": "com.vivavideo.imkit", "name": "VivaVideo", "region": "海外"},
    {"package": "com.reddit.frontpage", "name": "reddit", "region": "海外"},
    {"package": "com.shazam.android", "name": "Shazam", "region": "海外"},
    {"package": "com.samsung.android.welt", "name": "Wolt", "region": "海外"},
    {"package": "com.zynga.magictiles3", "name": "MagicTiles3", "region": "海外"},
    {"package": "com.sec.android.app.sheinc", "name": "SHEIN", "region": "海外"},
    {"package": "com.lidl.mobile.scanner", "name": "Lidl", "region": "海外"},
    {"package": "com.ibisinc.ibispaintx", "name": "ibisPaint X", "region": "海外"},
    {"package": "com.zedge.android", "name": "Zedge", "region": "海外"},
    {"package": "com.blgo.superapp", "name": "BLGO LIVE", "region": "海外"},
    {"package": "com.meitu.reface", "name": "Reface", "region": "海外"},
    {"package": "com.kunlun.xrecorder", "name": "xRecorder", "region": "海外"},
    {"package": "com.amazon.mShop.android.shopping", "name": "Amazon Shop", "region": "海外"},
    {"package": "com.android.chrome", "name": "Chrome", "region": "海外"},
    {"package": "com.waze", "name": "Waze", "region": "海外"},
]

# mirrorapk 的下载 URL 模板（不同站点规则不同，这里用最常用的格式）
# 格式1: https://www.mirrorapk.com/{package_name_with_dots_to_dash}/{version}/{apk_filename}
# 但实际上每个包名的文件名不统一，所以先尝试 "latest" 模式
MIRROR_APK_BASE_URL = "https://www.mirrorapk.com"

# 请求头（模拟浏览器）
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 每个 App 的下载 URL 映射（手动填写，避免自动抓取页面解析的复杂性）
# key = package_name, value = download_url
DOWNLOAD_URLS: Dict[str, str] = {
    # === 国内应用 ===
    "com.huawei.health":           f"{MIRROR_APK_BASE_URL}/com.huawei.health",
    "tv.danmaku.bili":            f"{MIRROR_APK_BASE_URL}/tv.danmaku.bili",
    "com.autonavi.minimap":       f"{MIRROR_APK_BASE_URL}/com.autonavi.minimap",
    "com.tencent.qqmusic":        f"{MIRROR_APK_BASE_URL}/com.tencent.qqmusic",
    "com.baidu.searchbox":        f"{MIRROR_APK_BASE_URL}/com.baidu.searchbox",
    "com.dragon.read":            f"{MIRROR_APK_BASE_URL}/com.dragon.read",
    "com.ss.android.article.news": f"{MIRROR_APK_BASE_URL}/com.ss.android.article.news",
    "com.sankuai.meituan":        f"{MIRROR_APK_BASE_URL}/com.sankuai.meituan",
    "com.eg.android.AlipayGphone": f"{MIRROR_APK_BASE_URL}/com.eg.android.AlipayGphone",
    "com.miui.gallery":           f"{MIRROR_APK_BASE_URL}/com.miui.gallery",
    "com.tencent.mm":             f"{MIRROR_APK_BASE_URL}/com.tencent.mm",
    "com.ss.android.ugc.aweme":  f"{MIRROR_APK_BASE_URL}/com.ss.android.ugc.aweme",
    # === 海外应用 ===
    "com.vivavideo.imkit":        f"{MIRROR_APK_BASE_URL}/com.vivavideo.imkit",
    "com.reddit.frontpage":       f"{MIRROR_APK_BASE_URL}/com.reddit.frontpage",
    "com.shazam.android":         f"{MIRROR_APK_BASE_URL}/com.shazam.android",
    "com.samsung.android.welt":  f"{MIRROR_APK_BASE_URL}/com.samsung.android.welt",
    "com.zynga.magictiles3":     f"{MIRROR_APK_BASE_URL}/com.zynga.magictiles3",
    "com.sec.android.app.sheinc": f"{MIRROR_APK_BASE_URL}/com.sec.android.app.sheinc",
    "com.lidl.mobile.scanner":   f"{MIRROR_APK_BASE_URL}/com.lidl.mobile.scanner",
    "com.ibisinc.ibispaintx":    f"{MIRROR_APK_BASE_URL}/com.ibisinc.ibispaintx",
    "com.zedge.android":         f"{MIRROR_APK_BASE_URL}/com.zedge.android",
    "com.blgo.superapp":          f"{MIRROR_APK_BASE_URL}/com.blgo.superapp",
    "com.meitu.reface":          f"{MIRROR_APK_BASE_URL}/com.meitu.reface",
    "com.kunlun.xrecorder":      f"{MIRROR_APK_BASE_URL}/com.kunlun.xrecorder",
    "com.amazon.mShop.android.shopping": f"{MIRROR_APK_BASE_URL}/com.amazon.mShop.android.shopping",
    "com.android.chrome":         f"{MIRROR_APK_BASE_URL}/com.android.chrome",
    "com.waze":                   f"{MIRROR_APK_BASE_URL}/com.waze",
}


def get_download_url(package: str) -> Optional[str]:
    """获取 APK 下载 URL"""
    return DOWNLOAD_URLS.get(package)


def try_download_direct(base_url: str, dest_path: str) -> Tuple[bool, str]:
    """尝试直接下载 APK（如果 URL 是直链）"""
    try:
        req = urllib.request.Request(base_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "html" in content_type.lower():
                # 返回了 HTML，说明不是直链
                return False, "不是直链（返回HTML页面）"
            # 检查 Content-Length
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 8192
            last_progress = -1
            with open(dest_path, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = int(downloaded * 100 / total)
                        if pct != last_progress:
                            last_progress = pct
                            size_str = format_size(downloaded)
                            total_str = format_size(total)
                            print(f"\r  下载进度: {pct:3d}%  ({size_str}/{total_str})", end="", flush=True)
                    else:
                        size_str = format_size(downloaded)
                        print(f"\r  已下载: {size_str}", end="", flush=True)
            print()  # 换行
            if total > 0 and downloaded < total:
                return False, f"下载不完整 {downloaded}/{total}"
            # 检查文件是否是有效的 APK（ZIP 格式）
            if downloaded < 100:
                os.remove(dest_path)
                return False, "文件太小，可能是错误页面"
            with open(dest_path, "rb") as f:
                header = f.read(4)
                if header[:2] != b"PK":
                    os.remove(dest_path)
                    return False, f"文件格式无效（非 ZIP/APK），头部={header[:4]}"
            return True, f"下载成功 {format_size(downloaded)}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, f"网络错误: {e.reason}"
    except Exception as e:
        return False, f"异常: {e}"


def format_size(size: int) -> str:
    """格式化文件大小"""
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size/1024:.1f}KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size/1024/1024:.1f}MB"
    else:
        return f"{size/1024/1024/1024:.2f}GB"


def download_apk(app: Dict, output_dir: str) -> Tuple[bool, str]:
    """下载单个 APK
    
    Returns:
        (success, message)
    """
    package = app["package"]
    name = app["name"]
    
    # APK 文件名：把 . 替换为 _ 方便 Windows 文件名
    safe_name = package.replace(".", "_")
    dest_path = os.path.join(output_dir, f"{safe_name}.apk")
    
    # 如果已下载且有效，跳过
    if os.path.exists(dest_path):
        if os.path.getsize(dest_path) > 100000:  # > 100KB
            with open(dest_path, "rb") as f:
                header = f.read(4)
                if header[:2] == b"PK":
                    size = os.path.getsize(dest_path)
                    return True, f"已存在，跳过 ({format_size(size)})"
        # 文件无效，删除重新下载
        os.remove(dest_path)
    
    # 获取下载 URL
    url = get_download_url(package)
    if not url:
        # 没有配置直链，生成搜索页面 URL
        search_url = f"{MIRROR_APK_BASE_URL}/?s={package}"
        return False, f"无直链，请手动下载: {search_url}"
    
    print(f"  下载: {name} ({package})")
    print(f"  URL: {url}")
    
    success, msg = try_download_direct(url, dest_path)
    if success:
        return True, msg
    
    # 直链失败，生成手动下载链接
    search_url = f"{MIRROR_APK_BASE_URL}/?s={package}"
    alt_url = f"https://m.apkpure.com/search?q={package}"
    return False, f"{msg} | 手动: {search_url} 或 {alt_url}"


def adb_install(apk_path: str) -> Tuple[bool, str]:
    """通过 adb install APK"""
    try:
        # 检查 adb 是否可用
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True, text=True, timeout=10
        )
        lines = [l for l in result.stdout.strip().split("\n") if l and "List" not in l]
        devices = [l for l in lines if "device" in l and "unauthorized" not in l]
        if not devices:
            return False, "无可用设备（请连接手机并打开 USB 调试）"
        
        result = subprocess.run(
            ["adb", "install", "-r", apk_path],
            capture_output=True, text=True, timeout=120
        )
        if "Success" in result.stdout:
            return True, "安装成功"
        else:
            return False, result.stdout.strip() or result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "安装超时（超过120秒）"
    except FileNotFoundError:
        return False, "未找到 adb 命令，请确保 platform-tools 在 PATH 中"
    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="Batch download load APKs")
    parser.add_argument("--region", choices=["CN", "OS", "ALL", "国内", "海外", "全部"], default="ALL",
                        help="Region: CN=China, OS=Oversea, ALL=all")
    parser.add_argument("--install", action="store_true",
                        help="Auto adb install after download")
    parser.add_argument("--output", default=None,
                        help="Output directory")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="Skip already downloaded files")
    args = parser.parse_args()
    
    # Normalize region
    region_map = {"CN": "国内", "OS": "海外", "ALL": "全部"}
    region = region_map.get(args.region, args.region)
    
    if region == "全部":
        apps = LOAD_APPS
    else:
        apps = [a for a in LOAD_APPS if a["region"] == region]
    
    # 输出目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = args.output or os.path.join(script_dir, "apks_downloaded")
    os.makedirs(output_dir, exist_ok=True)
    
    print("=" * 55)
    print(f"区域: {region}  |  共 {len(apps)} 个应用")
    print(f"输出目录: {output_dir}")
    print(f"自动安装: {'是' if args.install else '否'}")
    print("=" * 55)
    print()
    
    results = []  # (package, name, success, message)
    
    for i, app in enumerate(apps, 1):
        print(f"\n[{i}/{len(apps)}] ", end="")
        package = app["package"]
        name = app["name"]
        
        # 下载
        success, msg = download_apk(app, output_dir)
        print(f"  结果: {'✓ ' if success else '✗ '}{msg}")
        
        # 如果有 APK 文件且需要安装
        apk_path = os.path.join(output_dir, package.replace(".", "_") + ".apk")
        installed_msg = ""
        if success and args.install and os.path.exists(apk_path):
            print(f"  adb install... ", end="", flush=True)
            inst_ok, inst_msg = adb_install(apk_path)
            installed_msg = f" | 安装: {'✓ ' if inst_ok else '✗ '}{inst_msg}"
            print(f"{'✓ ' if inst_ok else '✗ '}{inst_msg}")
        
        results.append((package, name, success, msg, installed_msg))
    
    # 汇总
    print("\n" + "=" * 55)
    print(f"下载汇总 (区域={region}):")
    print("-" * 55)
    ok_count = sum(1 for r in results if r[2])
    fail_count = len(results) - ok_count
    
    for pkg, name, ok, msg, inst in results:
        status = "✓" if ok else "✗"
        line = f"  [{status}] {name:<12s} {pkg}"
        if inst:
            line += inst
        print(line)
    
    print(f"\n总计: {ok_count} 成功, {fail_count} 失败")
    
    if fail_count > 0:
        print(f"\n失败的应用（可手动下载）:")
        for pkg, name, ok, msg, _ in results:
            if not ok:
                search_url = f"{MIRROR_APK_BASE_URL}/?s={pkg}"
                print(f"  - {name} ({pkg}): {search_url}")
    
    print()
    
    # 如果有安装失败的，也输出
    if args.install:
        inst_fail = [r for r in results if r[4] and r[4].startswith(" | 安装: ✗")]
        if inst_fail:
            print(f"安装失败的应用 ({len(inst_fail)} 个):")
            for pkg, name, _, _, inst in inst_fail:
                print(f"  - {name} ({pkg}): {inst.strip(' |')}")
    
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
