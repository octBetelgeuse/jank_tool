# -*- coding: utf-8 -*-
"""
Batch install load APKs to device.
Handles .apk and .apkm (APKMirror) formats.
Auto-detects package names from various filename formats.

Usage:
    python install_apks.py                            # install all
    python install_apks.py --region CN                 # China only
    python install_apks.py --apk-dir D:/apkfiles      # custom dir
"""

import os
import sys
import re
import zipfile
import shutil
import argparse
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional, Dict

# ========== Package name -> (display_name, region) mapping ==========
# Multiple known package name aliases for the same app
# Keys are lowercased for case-insensitive matching
PACKAGE_ALIASES: Dict[str, Tuple[str, str]] = {
    # --- 国内应用 ---
    "com.huawei.health": ("运动健康", "国内"),
    "com.hihonor.health": ("运动健康(荣耀)", "国内"),
    "tv.danmaku.bili": ("哔哩哔哩", "国内"),
    "com.bilibili.app.in": ("哔哩哔哩(国际版)", "国内"),
    "com.autonavi.minimap": ("高德地图", "国内"),
    "com.tencent.qqmusic": ("QQ音乐", "国内"),
    "com.baidu.searchbox": ("百度", "国内"),
    "com.dragon.read": ("番茄免费小说", "国内"),
    "com.ss.android.article.news": ("今日头条", "国内"),
    "com.sankuai.meituan": ("拼多多", "国内"),
    "com.xunmeng.pinduoduo": ("拼多多", "国内"),
    "com.eg.android.alipaygphone": ("支付宝", "国内"),  # lowercased
    "com.miui.gallery": ("图库", "国内"),
    "com.tencent.mm": ("微信", "国内"),
    "com.ss.android.ugc.aweme": ("抖音", "国内"),
    "com.quvideo.xiaoying": ("抖音(火山版)", "国内"),
    # --- 海外应用 ---
    "com.vivavideo.imkit": ("VivaVideo", "海外"),
    "com.reddit.frontpage": ("reddit", "海外"),
    "com.shazam.android": ("Shazam", "海外"),
    "com.samsung.android.welt": ("Wolt", "海外"),
    "com.zynga.magictiles3": ("MagicTiles3", "海外"),
    "com.youmusic.magictiles": ("MagicTiles3", "海外"),
    "com.sec.android.app.sheinc": ("SHEIN", "海外"),
    "com.lidl.mobile.scanner": ("Lidl", "海外"),
    "com.lidl.eci.lidlplus": ("Lidl", "海外"),
    "com.ibisinc.ibispaintx": ("ibisPaint X", "海外"),
    "net.zedge.android": ("Zedge", "海外"),
    "com.zedge.android": ("Zedge", "海外"),
    "com.blgo.superapp": ("BLGO LIVE", "海外"),
    "sg.bigo.live": ("BIGO LIVE", "海外"),
    "com.zzkko": ("BLGO LIVE", "海外"),
    "com.meitu.reface": ("Reface", "海外"),
    "video.reface.app": ("Reface", "海外"),
    "com.kunlun.xrecorder": ("xRecorder", "海外"),
    "videoeditor.videorecorder.screenrecorder": ("xRecorder", "海外"),
    "com.amazon.mshop.android.shopping": ("Amazon Shop", "海外"),  # lowercased
    "com.android.chrome": ("Chrome", "海外"),
    "com.waze": ("Waze", "海外"),
    # --- Chinese name mappings ---
    "今日头条": ("今日头条", "国内"),
    "百度": ("百度", "国内"),
    "哔哩哔哩": ("哔哩哔哩", "国内"),
    "微信": ("微信", "国内"),
    "抖音": ("抖音", "国内"),
    "支付宝": ("支付宝", "国内"),
    "拼多多": ("拼多多", "国内"),
    "高德地图": ("高德地图", "国内"),
    "qq音乐": ("QQ音乐", "国内"),
}


def extract_package_from_filename(filename: str) -> Optional[str]:
    """Try to extract a package name from a filename.
    
    Handles patterns like:
      com.tencent.mm_8.0.76-3141_minAPI24(arm64-v8a)(nodpi)_apkmirror.com.apk
      com.youmusic.magictiles_13.072.103-..._apkmirror.com.apkm
      今日头条_13.9.0_APKPure.apk
      百度_15.57.1.10_APKPure.apk
      Free++ibis+Paint+X+Tips_1.1_APKPure.apk
      Read+free+books+novels+&+stories_7.2.5.32_APKPure.apk
      APKPure_3.20.77_apkpure.com.apk
      com.apkmirror.helper.prod_2.0.3_...apk
    """
    stem = Path(filename).stem
    
    # Pattern 1: starts with com.xxx.xxx or net.xxx.xxx (reverse domain)
    # Extract everything that looks like a Java package name before first _ or space
    m = re.match(r'^([a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+)', stem, re.IGNORECASE)
    if m:
        candidate = m.group(1)
        # Normalize to lowercase for matching
        candidate_lower = candidate.lower()
        if '.' in candidate_lower:
            return candidate_lower
    
    # Pattern 2: Chinese characters
    chinese_match = re.search(r'[\u4e00-\u9fff]+', stem)
    if chinese_match:
        return chinese_match.group(0)
    
    # Pattern 3: Known English names (Free++, Read+free, APKPure, etc.)
    # Skip these - they're helper/tip apps, not our target apps
    return None


def get_display_info(package_key: str) -> Tuple[str, str]:
    """Get (display_name, region) for a package key."""
    if package_key in PACKAGE_ALIASES:
        return PACKAGE_ALIASES[package_key]
    return (package_key, "未知")


def extract_base_apk_from_apkm(apkm_path: str, output_dir: str) -> Optional[str]:
    """Extract base.apk from an APKMirror .apkm file.
    
    .apkm is a ZIP archive containing base.apk + split APKs.
    Returns the path to the extracted base APK, or None on failure.
    """
    try:
        with zipfile.ZipFile(apkm_path, 'r') as zf:
            # Look for base.apk
            base_apk_name = None
            for name in zf.namelist():
                if name == 'base.apk' or name.endswith('/base.apk'):
                    base_apk_name = name
                    break
            
            if not base_apk_name:
                # Try to find any .apk file
                for name in zf.namelist():
                    if name.endswith('.apk') and '/' not in name:
                        base_apk_name = name
                        break
            
            if not base_apk_name:
                # List contents for debugging
                all_files = zf.namelist()
                print(f"    [WARN] No APK found in .apkm file. Contents: {all_files[:10]}")
                return None
            
            # Extract base.apk
            basename = Path(apkm_path).stem
            extract_path = os.path.join(output_dir, f"{basename}_base.apk")
            with zf.open(base_apk_name) as src, open(extract_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            
            size = os.path.getsize(extract_path)
            print(f"    [OK] Extracted base.apk: {format_size(size)}")
            return extract_path
    except zipfile.BadZipFile:
        print(f"    [ERROR] Not a valid ZIP/.apkm file")
        return None
    except Exception as e:
        print(f"    [ERROR] Extraction failed: {e}")
        return None


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size/1024:.1f}KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size/1024/1024:.1f}MB"
    else:
        return f"{size/1024/1024/1024:.2f}GB"


def find_apk_dir(script_dir: str, custom: Optional[str] = None) -> Optional[str]:
    """Find the APK directory."""
    if custom:
        if os.path.isdir(custom):
            return custom
        print(f"[ERROR] Directory not found: {custom}")
        return None
    
    default = os.path.join(script_dir, "apks_downloaded")
    if os.path.isdir(default):
        return default
    
    print(f"[ERROR] APK directory not found: {default}")
    print("   Run download_apks.bat first, or use --apk-dir to specify")
    return None


def get_device() -> Optional[str]:
    """Get connected device serial."""
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True, text=True, timeout=10
        )
        lines = result.stdout.strip().split("\n")
        devices = []
        for line in lines:
            line = line.strip()
            if not line or "List" in line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        if not devices:
            return None
        if len(devices) > 1:
            print(f"[WARN] {len(devices)} devices detected, using first: {devices[0]}")
        return devices[0]
    except FileNotFoundError:
        print("[ERROR] adb not found, add platform-tools to PATH")
        return None
    except Exception as e:
        print(f"[ERROR] adb devices failed: {e}")
        return None


def install_apk(apk_path: str, device: Optional[str] = None) -> Tuple[bool, str]:
    """Install a single APK via adb.
    
    Returns (success, message).
    """
    try:
        cmd = ["adb"]
        if device:
            cmd.extend(["-s", device])
        cmd.extend(["install", "-r", apk_path])
        
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            encoding='utf-8', errors='replace'
        )
        output = result.stdout.strip()
        error = result.stderr.strip()
        
        if "Success" in output:
            return True, "Installed"
        elif "INSTALL_FAILED" in output:
            return False, output
        elif error:
            return False, error
        else:
            return result.returncode == 0, output or f"exit={result.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Timeout (>300s)"
    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="Batch install load APKs")
    parser.add_argument("--region", choices=["CN", "OS", "ALL", "国内", "海外", "全部"], default="ALL",
                        help="Region: CN=China, OS=Oversea, ALL=all")
    parser.add_argument("--apk-dir", default=None,
                        help="APK directory path")
    parser.add_argument("--device", default=None,
                        help="Device serial (auto-detect if not specified)")
    args = parser.parse_args()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Normalize region
    region_map = {"CN": "国内", "OS": "海外", "ALL": "全部"}
    region = region_map.get(args.region, args.region)
    
    # Find APK directory
    apk_dir = find_apk_dir(script_dir, args.apk_dir)
    if not apk_dir:
        return 1
    
    # Check device
    device = args.device or get_device()
    if not device:
        print("[ERROR] No device connected. Connect phone and enable USB debugging.")
        return 1
    
    print(f"Device: {device}")
    print(f"APK dir: {apk_dir}")
    print(f"Region: {region}")
    
    # Scan for .apk and .apkm files
    all_files = sorted(Path(apk_dir).glob("*"))
    install_files = []      # (file_path, package_key, display_name, detected_region, is_apkm)
    unrecognized = []       # files we couldn't identify
    
    for f in all_files:
        if not f.is_file():
            continue
        suffix = f.suffix.lower()
        if suffix not in ('.apk', '.apkm'):
            continue
        
        # Try to identify the package
        pkg_key = extract_package_from_filename(f.name)
        
        if pkg_key and pkg_key in PACKAGE_ALIASES:
            display_name, app_region = PACKAGE_ALIASES[pkg_key]
            is_apkm = suffix == '.apkm'
            install_files.append((str(f), pkg_key, display_name, app_region, is_apkm))
        elif pkg_key:
            # Package-like string but not in our mapping
            # Check if it looks like a package name (has dots)
            if '.' in pkg_key:
                display_name, app_region = get_display_info(pkg_key)
                is_apkm = suffix == '.apkm'
                install_files.append((str(f), pkg_key, display_name, app_region, is_apkm))
            else:
                unrecognized.append(f)
        else:
            unrecognized.append(f)
    
    # Filter by region
    if region == "全部":
        filtered = install_files
    else:
        filtered = [(p, pkg, name, r, a) for (p, pkg, name, r, a) in install_files if r == region]
    
    # Also include unrecognized files (user might want to install them too)
    if unrecognized:
        print(f"\n[WARN] {len(unrecognized)} unrecognized files:")
        for f in unrecognized:
            print(f"  - {f.name}")
        print("  (These will also be attempted for installation)")
        for f in unrecognized:
            suffix = f.suffix.lower()
            is_apkm = suffix == '.apkm'
            filtered.append((str(f), "(unknown)", f.stem, "未知", is_apkm))
    
    if not filtered:
        print(f"\n[ERROR] No APK files found in {apk_dir}")
        return 1
    
    total = len(filtered)
    print(f"\n{total} files to install")
    print("=" * 55)
    
    results = []
    success_count = 0
    fail_count = 0
    
    # Temp dir for extracting .apkm files
    temp_dir = tempfile.mkdtemp(prefix="apk_install_")
    
    try:
        for i, (filepath, pkg_key, name, app_region, is_apkm) in enumerate(filtered, 1):
            filename = Path(filepath).name
            fsize = os.path.getsize(filepath)
            
            print(f"\n[{i}/{total}] {name} ({app_region})")
            print(f"  File: {filename} ({format_size(fsize)})")
            
            # Handle .apkm files
            if is_apkm:
                print(f"  Format: .apkm (APKMirror), extracting base APK...")
                base_apk = extract_base_apk_from_apkm(filepath, temp_dir)
                if not base_apk:
                    print(f"  ✗ Failed to extract, skipping")
                    results.append((filepath, pkg_key, name, False, "Extract failed"))
                    fail_count += 1
                    continue
                install_path = base_apk
            else:
                install_path = filepath
            
            # Install
            print(f"  Installing... ", end="", flush=True)
            ok, msg = install_apk(install_path, device)
            
            if ok:
                print(f"✓ {msg}")
                success_count += 1
            else:
                print(f"✗ {msg}")
                fail_count += 1
            
            results.append((filepath, pkg_key, name, ok, msg))
    finally:
        # Clean up temp dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    # Summary
    print("\n" + "=" * 55)
    print(f"Install summary: {success_count} succeeded, {fail_count} failed")
    print("-" * 55)
    
    for filepath, pkg_key, name, ok, msg in results:
        status = "✓" if ok else "✗"
        fname = Path(filepath).name
        print(f"  [{status}] {name}")
    
    if fail_count > 0:
        print(f"\nFailed packages:")
        for filepath, pkg_key, name, ok, msg in results:
            if not ok:
                print(f"  - {name}: {msg}")
    
    print()
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
