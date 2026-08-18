# Android Jank Test Tool - 安装指南

## 安装依赖

```bash
pip install -r requirements.txt
```

依赖包括：
- **perfetto**: Perfetto 官方 Python SDK，用于分析 trace 文件
- **uiautomator2**: Android UI 自动化测试库
- **pandas**: 数据分析库

---

## 快速开始

### GUI 模式（推荐）

```bash
python gui.py
```

### 命令行模式

```bash
# 分析已存在的 trace 文件
python jank_test_tool.py --trace-file ./sample.perfetto-trace

# 运行 Monkey 测试
python jank_test_tool.py --package com.example.app --monkey

# 手动测试
python jank_test_tool.py --package com.example.app --duration 30
```

---

## 常见问题

### Q: 提示 "perfetto 未安装"
**A**: 请运行 `pip install perfetto`

### Q: Perfetto trace 配置无效
**A**: 确保设备上已安装 Perfetto。较新的 Android 版本（Android 10+）通常预装了 Perfetto。

### Q: 分析时没有数据
**A**: 检查 trace 文件是否正确录制。某些设备可能需要 root 权限才能录制完整的 trace。

---

## 输出文件说明

运行测试后，会在指定输出目录生成以下文件：

- `*.perfetto-trace`: 原始 trace 文件
- `*_report.json`: JSON 格式的分析报告

报告包含：
- 总帧数、卡顿帧数、卡顿率
- Jank 类型分布（如 App Deadline Missed、Buffer Stuffing）
- Jank 标签分布（Self Jank、Dependent Jank）
- 卡顿事件详情

---

## 性能指标说明

- **jank_ratio**: 卡顿帧占总帧数的比例，数值越低越好
- **jank_type**: 卡顿类型
  - `App Deadline Missed`: 应用层未按时完成渲染
  - `SurfaceFlinger CPU Deadline Missed`: SurfaceFlinger CPU 处理超时
  - `Buffer Stuffing`: 缓冲区堆积
- **jank_tag**: 卡顿标签
  - `Self Jank`: 自身导致的卡顿
  - `Dependent Jank`: 依赖链导致的卡顿
