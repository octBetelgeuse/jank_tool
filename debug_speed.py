"""诊断脚本：精确测量每个步骤的耗时"""
import subprocess
import time
import sys

# 加路径
sys.path.insert(0, ".")
from case_scripts import PACKAGE

print("=" * 60)
print("ADB设备检查...")
r = subprocess.run(["adb", "devices"], capture_output=True, text=True)
print(r.stdout.strip())

# 解析设备ID
lines = r.stdout.strip().split("\n")
device_id = None
for line in lines[1:]:
    parts = line.split()
    if len(parts) >= 2 and parts[1] == "device":
        device_id = parts[0]
        break

if not device_id:
    print("❌ 没有检测到设备！请连接手机并开启USB调试")
    sys.exit(1)

print(f"✅ 检测到设备: {device_id}")

def adb_shell(cmd, timeout=10):
    """执行ADB shell命令并返回耗时"""
    t0 = time.time()
    r = subprocess.run(
        ["adb", "-s", device_id, "shell", cmd],
        capture_output=True, text=True, timeout=timeout
    )
    elapsed = time.time() - t0
    return elapsed, r.stdout.strip(), r.returncode

def adb_cmd(args, timeout=10):
    """执行ADB命令并返回耗时"""
    t0 = time.time()
    r = subprocess.run(
        ["adb", "-s", device_id] + args,
        capture_output=True, text=True, timeout=timeout
    )
    elapsed = time.time() - t0
    return elapsed, r.stdout.strip(), r.returncode

# ========== 测试各步骤耗时 ==========
print("\n" + "=" * 60)
print("🚀 逐步测速")
print("=" * 60)

# 1. force-stop
print("\n[1] am force-stop (停App)...")
t, out, rc = adb_shell(f"am force-stop {PACKAGE}")
print(f"   耗时: {t:.2f}s  输出: {out[:80]}")

time.sleep(1)

# 2. monkey启动
print("\n[2] monkey -p 启动App...")
t, out, rc = adb_shell(f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1")
print(f"   耗时: {t:.2f}s  输出: {out[:80]}")

time.sleep(2)

# 3. 检查App是否在前台
print("\n[3] dumpsys activity top (检查前台Activity)...")
t, out, rc = adb_shell("dumpsys activity top | head -20")
print(f"   耗时: {t:.2f}s")
# 看相机是否在前台
if PACKAGE in out:
    print(f"   ✅ 相机已在前台")
else:
    print(f"   ⚠️ 相机可能还没完全启动")

# 4. 用uiautomator2测试exists()速度
print("\n[4] uiautomator2 exists() 测试...")
try:
    import uiautomator2 as u2
    t0 = time.time()
    d = u2.connect(device_id)
    t_conn = time.time() - t0
    print(f"   连接耗时: {t_conn:.2f}s")
    
    # 测试exists
    t0 = time.time()
    result = d.exists(text="拍照")
    t1 = time.time() - t0
    print(f"   exists('拍照'): {result}, 耗时: {t1:.2f}s")
    
    t0 = time.time()
    result = d.exists(text="PHOTO")
    t1 = time.time() - t0
    print(f"   exists('PHOTO'): {result}, 耗时: {t1:.2f}s")
    
    t0 = time.time()
    result = d.exists(text="后置")
    t1 = time.time() - t0
    print(f"   exists('后置'): {result}, 耗时: {t1:.2f}s")
    
    # 测试click_element
    t0 = time.time()
    d.click_element(text="拍照")
    t1 = time.time() - t0
    print(f"   click_element('拍照') 耗时: {t1:.2f}s")
    
    # 测试get_elements(批量)
    t0 = time.time()
    elems = d.get_elements(text="*")
    t1 = time.time() - t0
    print(f"   get_elements('*'): {len(elems)}个元素, 耗时: {t1:.2f}s")
    
except ImportError:
    print("   ⚠️ uiautomator2未安装")
except Exception as e:
    print(f"   ❌ uiautomator2错误: {e}")

# 5. 冷启动完整流程测试
print("\n[5] 完整冷启动流程测速...")
print("    (force-stop → monkey → sleep(2) → 检查)...")

t0_start = time.time()

# 停
adb_shell(f"am force-stop {PACKAGE}")
time.sleep(0.5)

# 启
adb_shell(f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1")

# 等2秒
time.sleep(2)

# 查前台
t1 = time.time()
out = adb_shell("dumpsys activity top | grep ACTIVITY")[1]
if PACKAGE in out:
    print(f"    ✅ {t1 - t0_start:.2f}s 后相机在前台")
else:
    # 多等几秒再查
    for extra in [2, 4, 6, 8]:
        time.sleep(2)
        t1 = time.time()
        out = adb_shell("dumpsys activity top | grep ACTIVITY")[1]
        if PACKAGE in out:
            print(f"    ✅ {t1 - t0_start:.2f}s 后相机在前台(多等{extra}s)")
            break
    else:
        print(f"    ⚠️ {t1 - t0_start:.2f}s 后仍未检测到相机在前台")

# 6. ADB命令延迟测试
print("\n[6] ADB基础延迟测试 (5次ping)...")
for i in range(5):
    t, out, rc = adb_shell("echo ok")
    print(f"    ping {i+1}: {t:.3f}s")

print("\n✅ 诊断完成")
