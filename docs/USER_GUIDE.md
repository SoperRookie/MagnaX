# MagnaX 使用文档

> MagnaX v2.10.0 - Android/iOS 实时性能监控工具

## 目录

- [简介](#简介)
- [安装](#安装)
- [快速开始](#快速开始)
- [CLI 命令行使用](#cli-命令行使用)
- [Web UI 使用](#web-ui-使用)
- [Python API 使用](#python-api-使用)
- [REST API 使用](#rest-api-使用)
- [Android 测试指南](#android-测试指南)
- [iOS 测试指南](#ios-测试指南)
- [性能指标说明](#性能指标说明)
- [报告与分析](#报告与分析)
- [常见问题](#常见问题)

---

## 简介

MagnaX 是一款功能强大的移动应用性能监控工具，支持 Android 和 iOS 平台。**无需 ROOT 或越狱**，即可实时采集以下性能指标：

- **CPU** - 应用/系统 CPU 占用率，支持多核监控
- **内存** - 总内存、Swap、详细内存分布（Java/Native/Code/Stack/Graphics）
- **网络** - 上行/下行流量
- **FPS** - 帧率和卡顿（Jank）检测
- **电池** - 电量、温度、电流、电压、功耗
- **GPU** - GPU 占用率
- **磁盘** - 使用量和剩余空间
- **温度** - 设备热区温度监控

### 三种使用方式

| 方式 | 适用场景 |
|------|----------|
| Web UI | 可视化监控，实时图表展示 |
| Python API | 集成到自动化测试框架 |
| REST API | 与第三方系统对接 |

---

## 安装

### 环境要求

- Python 3.10+
- ADB（Android 调试桥）已配置到系统 PATH
- Windows 测试 iOS 需安装 iTunes

### 通过 pip 安装

```bash
# 标准安装
pip install -U magnax

# 指定版本
pip install magnax==2.10.0

# 国内镜像源
pip install -i https://mirrors.ustc.edu.cn/pypi/web/simple -U magnax
```

### 从源码安装

```bash
git clone https://github.com/smart-test-ti/MagnaX.git
cd MagnaX
pip install -e .
```

### 验证安装

```bash
magnax --help
```

---

## 快速开始

### 1. 启动 iOS tunnel 服务（iOS 用户必须）

如果需要监控 iOS 设备，必须先启动 pymobiledevice3 tunnel 服务：

```bash
# macOS/Linux（需要 sudo 权限）
sudo python3 -m pymobiledevice3 remote tunneld
```

> **注意**: tunnel 服务必须在启动 MagnaX 之前运行，并在整个监控过程中保持运行状态。

### 2. 启动 MagnaX 服务

```bash
# 默认地址：localhost:50003
magnax

# 自定义地址和端口
magnax --host=0.0.0.0 --port=8080
```

### 3. 打开浏览器

访问 `http://localhost:50003`

### 4. 选择设备和应用

1. 选择平台（Android/iOS）
2. 选择已连接的设备
3. 选择要监控的应用包名
4. 点击"开始"按钮

### 5. 查看实时数据

监控页面会实时显示各项性能指标的图表。

---

## CLI 命令行使用

### 基本命令

```bash
# 启动服务（默认设置）
magnax

# 或使用 Python 模块方式
python -m magnax

# 指定主机和端口
magnax --host=0.0.0.0 --port=8080
python -m magnax --host=0.0.0.0 --port=8080
```

### 后台运行

```bash
# macOS/Linux
nohup python3 -m magnax &

# 查看日志
tail -f nohup.out

# Windows
start /min python3 -m magnax &
```

### 停止服务

```bash
# 查找进程
ps aux | grep magnax

# 终止进程
kill <PID>
```

---

## Web UI 使用

### 页面说明

| 页面 | URL | 功能 |
|------|-----|------|
| 主页 | `/` | 单设备性能监控 |
| PK模式 | `/pk` | 双设备/双应用对比测试 |
| 报告列表 | `/report` | 查看历史测试报告 |
| 详细分析 | `/analysis` | 单个报告详细分析 |

### 主页监控流程

1. **选择平台**：Android 或 iOS
2. **选择设备**：从下拉列表选择已连接设备
3. **选择应用**：选择要监控的应用包名
4. **配置选项**：
   - FPS 采集方式（Android）：SurfaceView / gfxinfo
   - WiFi/移动数据切换
   - 屏幕录制开关
5. **开始监控**：点击"开始"按钮
6. **停止并生成报告**：点击"停止"按钮

### PK 模式

PK 模式支持三种对比场景：

- **单设备双应用**：同一设备上两个应用的对比
- **双设备单应用**：同一应用在两台设备上的表现对比
- **双设备双应用**：完全独立的对比测试

### 报告功能

- 导出 Excel 报表
- 生成 HTML 报告（含图表）
- 查看录屏回放
- 删除和重命名报告

---

## Python API 使用

### 导入模块

```python
from magnax.public.apm import AppPerformanceMonitor
from magnax.public.common import Devices, Platform
```

### 获取设备信息

```python
d = Devices()

# Android 设备
android_devices = d.getDeviceIds()
print(f"Android 设备: {android_devices}")

# 获取设备上的应用列表
pkgnames = d.getPkgname(android_devices[0])
print(f"应用列表: {pkgnames}")

# 获取应用进程 ID
pid = d.getPid(android_devices[0], 'com.example.app')
print(f"进程 ID: {pid}")

# iOS 设备
ios_devices = d.getDeviceInfoByiOS()
print(f"iOS 设备: {ios_devices}")

# 获取 iOS 应用列表
ios_apps = d.getPkgnameByiOS(ios_devices[0])
print(f"iOS 应用: {ios_apps}")
```

### 单次采集模式

```python
# 初始化监控器（单次采集模式）
apm = AppPerformanceMonitor(
    pkgName='com.example.app',      # 应用包名
    platform=Platform.Android,       # 平台：Android/iOS
    deviceId='your_device_id',       # 设备 ID
    surfaceview=True,                # FPS 采集方式（Android）
    noLog=True,                      # 不保存日志文件
    collect_all=False                # 单次采集模式
)

# 采集 CPU
cpu = apm.collectCpu()
print(f"应用 CPU: {cpu['appCpuRate']}%")
print(f"系统 CPU: {cpu['systemCpuRate']}%")

# 采集内存
mem = apm.collectMemory()
print(f"总内存: {mem['total']} MB")
print(f"Swap: {mem['swap']} MB")

# 采集内存详情（Android）
mem_detail = apm.collectMemoryDetail()
print(f"Java Heap: {mem_detail['java_heap']} MB")
print(f"Native Heap: {mem_detail['native_heap']} MB")

# 采集网络
network = apm.collectNetwork(wifi=True)
print(f"上行: {network['send']} KB")
print(f"下行: {network['recv']} KB")

# 采集 FPS
fps = apm.collectFps()
print(f"FPS: {fps['fps']}")
print(f"Jank: {fps['jank']}")

# 采集 GPU
gpu = apm.collectGpu()
print(f"GPU: {gpu['gpu']}%")

# 采集电池
battery = apm.collectBattery()
print(f"电池信息: {battery}")

# 采集磁盘
disk = apm.collectDisk()
print(f"已用: {disk['used']} KB")
print(f"可用: {disk['free']} KB")

# 采集温度（Android）
thermal = apm.collectThermal()
print(f"温度信息: {thermal}")
```

### 持续采集模式

```python
if __name__ == '__main__':
    apm = AppPerformanceMonitor(
        pkgName='com.example.app',
        platform=Platform.Android,
        deviceId='your_device_id',
        surfaceview=True,
        noLog=False,               # 保存日志文件
        record=True,               # 录制屏幕
        collect_all=True,          # 持续采集模式
        duration=60                # 持续 60 秒
    )

    # 开始采集并生成报告
    apm.collectAll(report_path='/path/to/report.html')
```

### iOS 设备监控

```python
# iOS 监控
apm = AppPerformanceMonitor(
    pkgName='com.example.app',       # Bundle ID
    platform=Platform.iOS,
    deviceId='device_udid',
    noLog=False,
    collect_all=True,
    duration=120
)

apm.collectAll()
```

### 完整示例：自动化测试集成

```python
from magnax.public.apm import AppPerformanceMonitor
from magnax.public.common import Devices, Platform
import time

def performance_test():
    """性能测试示例"""
    d = Devices()
    devices = d.getDeviceIds()

    if not devices:
        print("未检测到 Android 设备")
        return

    device_id = devices[0]
    pkg_name = 'com.example.app'

    # 创建监控器
    apm = AppPerformanceMonitor(
        pkgName=pkg_name,
        platform=Platform.Android,
        deviceId=device_id,
        surfaceview=True,
        noLog=True,
        collect_all=False
    )

    # 采集 10 次数据
    results = []
    for i in range(10):
        cpu = apm.collectCpu()
        mem = apm.collectMemory()
        fps = apm.collectFps()

        results.append({
            'cpu': cpu['appCpuRate'],
            'memory': mem['total'],
            'fps': fps['fps']
        })

        print(f"第 {i+1} 次采集: CPU={cpu['appCpuRate']}%, "
              f"内存={mem['total']}MB, FPS={fps['fps']}")

        time.sleep(1)

    # 计算平均值
    avg_cpu = sum(r['cpu'] for r in results) / len(results)
    avg_mem = sum(r['memory'] for r in results) / len(results)
    avg_fps = sum(r['fps'] for r in results) / len(results)

    print(f"\n平均值: CPU={avg_cpu:.2f}%, 内存={avg_mem:.2f}MB, FPS={avg_fps:.2f}")

    # 性能断言
    assert avg_cpu < 30, f"CPU 占用过高: {avg_cpu}%"
    assert avg_mem < 500, f"内存占用过高: {avg_mem}MB"
    assert avg_fps >= 55, f"帧率过低: {avg_fps}"

    print("性能测试通过!")

if __name__ == '__main__':
    performance_test()
```

---

## REST API 使用

### 基础信息

- **Base URL**: `http://localhost:50003`
- **请求方式**: GET 或 POST
- **响应格式**: JSON

### 设备管理 API

#### 获取设备列表

```bash
GET /device/info?platform=Android
GET /device/info?platform=iOS
```

响应示例：
```json
{
  "android": ["device1", "device2"],
  "ios": ["udid1"]
}
```

#### 获取应用列表

```bash
GET /device/package?platform=Android&device=device_id
GET /device/package?platform=iOS&device=udid
```

#### 获取进程 ID

```bash
GET /package/pids?platform=Android&device=device_id&pkgname=com.example.app
```

#### 获取 CPU 核心数

```bash
GET /device/cpucore
```

### 性能采集 API

#### 采集 CPU

```bash
GET /apm/cpu?platform=Android&pkgname=com.example.app&device=device_id
```

响应：
```json
{
  "appCpuRate": 12.5,
  "systemCpuRate": 35.2
}
```

#### 采集多核 CPU

```bash
GET /apm/corecpu?platform=Android&pkgname=com.example.app&device=device_id&cores=8
```

响应：
```json
{
  "coreCpuRate": [15.2, 20.1, 18.5, 22.3, 10.8, 8.5, 12.1, 9.7]
}
```

#### 采集内存

```bash
GET /apm/mem?platform=Android&pkgname=com.example.app&device=device_id
```

响应：
```json
{
  "totalPass": 256.5,
  "swapPass": 12.3
}
```

#### 采集内存详情

```bash
GET /apm/mem/detail?platform=Android&pkgname=com.example.app&device=device_id
```

响应：
```json
{
  "memory_detail": {
    "java_heap": 45.2,
    "native_heap": 128.5,
    "code_pss": 32.1,
    "stack": 2.5,
    "graphics": 48.3,
    "system": 12.8
  }
}
```

#### 采集网络

```bash
GET /apm/network?platform=Android&pkgname=com.example.app&device=device_id&wifi_switch=true
```

响应：
```json
{
  "upflow": 125.6,
  "downflow": 1024.8
}
```

#### 采集 FPS

```bash
GET /apm/fps?platform=Android&pkgname=com.example.app&device=device_id&surv=true
```

响应：
```json
{
  "fps": 60,
  "jank": 2
}
```

#### 采集电池

```bash
GET /apm/battery?platform=Android&device=device_id
```

Android 响应：
```json
{
  "level": 85,
  "temperature": 32.5
}
```

iOS 响应：
```json
{
  "temperature": 31.2,
  "current": 450,
  "voltage": 4200,
  "power": 1890
}
```

#### 采集 GPU

```bash
GET /apm/gpu?platform=Android&pkgname=com.example.app&device=device_id
```

响应：
```json
{
  "gpu": 45.8
}
```

#### 采集磁盘

```bash
GET /apm/disk?platform=Android&device=device_id
```

响应：
```json
{
  "used": 52428800,
  "free": 10485760
}
```

#### 采集温度

```bash
GET /apm/thermal?platform=Android&device=device_id
```

响应：
```json
[
  {"type": "cpu-0-0", "temp": 42},
  {"type": "cpu-0-1", "temp": 43},
  {"type": "battery", "temp": 32}
]
```

### 统一采集 API

```bash
GET /apm/collect?platform=Android&deviceid=device_id&pkgname=com.example.app&target=cpu
```

支持的 target 值：
- `cpu` - CPU 占用
- `memory` - 内存占用
- `memory_detail` - 内存详情
- `network` - 网络流量
- `fps` - 帧率
- `battery` - 电池
- `gpu` - GPU 占用

### 报告 API

#### 创建报告

```bash
POST /apm/create/report
Content-Type: application/json

{
  "scene": "test_20240101_120000",
  "platform": "Android"
}
```

#### 导出 Excel

```bash
GET /apm/export/report?scene=test_20240101_120000
```

#### 导出 HTML 报告

```bash
GET /apm/export/html/android?scene=test_20240101_120000
GET /apm/export/html/ios?scene=test_20240101_120000
```

#### 删除报告

```bash
POST /apm/remove/report
Content-Type: application/json

{
  "scene": "test_20240101_120000"
}
```

### 屏幕录制 API

```bash
# 开始录制
POST /apm/record/start?device=device_id

# 开始投屏
GET /apm/record/cast?device=device_id

# 播放录像
GET /apm/record/play?scene=test_20240101_120000
```

### 应用安装 API

```bash
# 从文件安装
POST /apm/install/file
Content-Type: multipart/form-data

file: [APK/IPA 文件]
platform: Android/iOS
device: device_id

# 从链接安装
GET /apm/install/link?url=https://example.com/app.apk&platform=Android&device=device_id
```

### cURL 使用示例

```bash
# 获取设备列表
curl "http://localhost:50003/device/info?platform=Android"

# 采集 CPU
curl "http://localhost:50003/apm/cpu?platform=Android&pkgname=com.example.app&device=device_id"

# 持续采集（配合脚本）
while true; do
  curl -s "http://localhost:50003/apm/cpu?platform=Android&pkgname=com.example.app&device=device_id"
  sleep 1
done
```

---

## Android 测试指南

### 准备工作

1. **启用开发者选项**
   - 设置 → 关于手机 → 连续点击"版本号" 7 次

2. **启用 USB 调试**
   - 设置 → 开发者选项 → 启用"USB 调试"

3. **连接设备**
   ```bash
   # 检查设备连接
   adb devices
   ```

4. **（可选）启用 GPU 呈现模式**
   - 设置 → 开发者选项 → GPU 呈现模式分析 → 选择"在 adb shell dumpsys gfxinfo 中"
   - 使用 gfxinfo 方式采集 FPS 时需要

### FPS 采集方式选择

| 方式 | 参数 | 说明 |
|------|------|------|
| SurfaceView | `surfaceview=True` | 默认方式，通过帧时间戳计算 |
| gfxinfo | `surfaceview=False` | 需要启用 GPU 呈现模式 |

### 网络模式选择

| 模式 | 参数 | 网络接口 |
|------|------|----------|
| WiFi | `wifi=True` | wlan0 |
| 移动数据 | `wifi=False` | rmnet_ipa0 |

### 常见问题排查

```bash
# 检查 ADB 连接
adb devices

# 重启 ADB 服务
adb kill-server
adb start-server

# 检查应用是否运行
adb shell ps | grep com.example.app

# 获取应用包名
adb shell pm list packages | grep example
```

---

## iOS 测试指南

### iOS 17 以下版本

直接通过 USB 连接即可使用。

### iOS 17+ 版本

iOS 17 及以上版本需要先启动 tunnel 服务：

```bash
# 启动 tunnel 服务（需要 sudo 权限）
sudo python3 -m pymobiledevice3 remote start-tunnel

# 或以守护进程方式运行
sudo python3 -m pymobiledevice3 remote tunneld
```

> **重要**: tunnel 服务必须保持运行状态，否则无法采集 iOS 17+ 设备的性能数据。

### 信任开发者证书

首次连接时：
1. 在 iOS 设备上点击"信任此电脑"
2. 设置 → 通用 → 设备管理 → 信任开发者

### Windows 环境

Windows 系统测试 iOS 需要安装 iTunes（用于驱动支持）。

### iOS 支持的指标

| 指标 | iOS 17+ | iOS < 17 |
|------|---------|----------|
| CPU | ✅ | ✅ |
| 内存 | ✅ | ✅ |
| FPS | ✅ | ✅ |
| GPU | ✅ | ✅ |
| 网络 | ✅ | ✅ |
| 电池温度 | ✅ | ✅ |
| 电池电流/电压/功耗 | ✅ | ✅ |
| 磁盘 | ✅ | ✅ |

### 查看 iOS 设备信息

```bash
# 列出连接的 iOS 设备
python3 -m pymobiledevice3 usbmux list

# 查看设备详情
python3 -m pymobiledevice3 lockdown info
```

---

## 性能指标说明

### CPU

| 指标 | 说明 | 单位 |
|------|------|------|
| appCpuRate | 应用 CPU 占用率 | % |
| systemCpuRate | 系统总 CPU 占用率 | % |
| coreCpuRate | 各核心 CPU 占用率 | % |

### 内存

| 指标 | 说明 | 单位 |
|------|------|------|
| total | 应用总内存占用 | MB |
| swap | Swap 内存占用 | MB |
| java_heap | Java 堆内存 | MB |
| native_heap | Native 堆内存 | MB |
| code_pss | 代码内存 | MB |
| stack | 栈内存 | MB |
| graphics | 图形内存 | MB |
| system | 系统内存 | MB |

### 网络

| 指标 | 说明 | 单位 |
|------|------|------|
| upflow/send | 上行流量 | KB |
| downflow/recv | 下行流量 | KB |

### FPS

| 指标 | 说明 | 单位 |
|------|------|------|
| fps | 帧率 | Hz |
| jank | 卡顿次数（Android） | 次 |

### 电池

| 指标 | 平台 | 说明 | 单位 |
|------|------|------|------|
| level | Android | 电池电量 | % |
| temperature | 全平台 | 电池温度 | °C |
| current | iOS | 电流 | mA |
| voltage | iOS | 电压 | mV |
| power | iOS | 功率 | mW |

### GPU

| 指标 | 说明 | 单位 |
|------|------|------|
| gpu | GPU 占用率 | % |

### 磁盘

| 指标 | 说明 | 单位 |
|------|------|------|
| used | 已用空间 | KB |
| free | 可用空间 | KB |

### 温度（Android）

| 指标 | 说明 | 单位 |
|------|------|------|
| thermal zones | 各热区温度 | °C |

---

## 报告与分析

### 报告文件结构

```
report/
└── {scene_name}/
    ├── cpu_app.log           # 应用 CPU
    ├── cpu_sys.log           # 系统 CPU
    ├── cpu0.log ~ cpuN.log   # 各核心 CPU
    ├── mem_total.log         # 总内存
    ├── mem_swap.log          # Swap 内存
    ├── mem_java_heap.log     # Java 堆
    ├── mem_native_heap.log   # Native 堆
    ├── mem_code_pss.log      # 代码内存
    ├── mem_stack.log         # 栈内存
    ├── mem_graphics.log      # 图形内存
    ├── upflow.log            # 上行流量
    ├── downflow.log          # 下行流量
    ├── fps.log               # 帧率
    ├── jank.log              # 卡顿
    ├── gpu.log               # GPU
    ├── battery_level.log     # 电量
    ├── battery_tem.log       # 电池温度
    ├── disk_used.log         # 磁盘使用
    ├── disk_free.log         # 磁盘可用
    ├── result.json           # 汇总信息
    └── record.mkv            # 屏幕录像（可选）
```

### 导出格式

| 格式 | 说明 |
|------|------|
| HTML | 带图表的可视化报告 |
| Excel | 数据表格，便于进一步分析 |
| JSON | 原始数据，便于程序处理 |

### 性能基准建议

| 指标 | 优秀 | 良好 | 需优化 |
|------|------|------|--------|
| CPU | < 15% | 15-30% | > 30% |
| 内存 | < 200MB | 200-400MB | > 400MB |
| FPS | 60 | 55-60 | < 55 |
| Jank | 0 | 1-3 | > 3 |

---

## 常见问题

### Q: 无法检测到 Android 设备？

A: 请检查：
1. USB 调试是否开启
2. 是否在设备上点击了"允许 USB 调试"
3. 运行 `adb devices` 确认设备状态

```bash
adb kill-server
adb start-server
adb devices
```

### Q: iOS 17+ 无法采集数据？

A: iOS 17+ 需要先启动 tunnel 服务：

```bash
sudo python3 -m pymobiledevice3 remote tunneld
```

### Q: FPS 数据为 0？

A:
- Android：确保应用有界面刷新活动
- 如使用 gfxinfo 方式：确保启用了"GPU 呈现模式分析"
- 尝试切换 `surfaceview` 参数

### Q: 内存数据异常？

A:
- 确保应用正在运行
- 检查应用包名是否正确
- 部分系统应用可能没有完整的内存信息

### Q: GPU 数据为 0 或获取失败？

A:
- 部分设备不支持 GPU 监控
- 需要设备有 `/sys/class/kgsl/kgsl-3d0/gpubusy` 或 `/proc/gpuinfo`
- 可能需要 root 权限

### Q: 网络流量数据不准确？

A:
- 确保选择了正确的网络模式（WiFi/移动数据）
- 流量数据为增量值，首次采集前需要初始化基准值

### Q: 如何同时监控多个设备？

A:
- Web UI：使用 PK 模式
- Python API：创建多个 `AppPerformanceMonitor` 实例
- REST API：在请求中指定不同的 `device` 参数

### Q: 报告路径在哪里？

A: 默认位于 MagnaX 安装目录下的 `report/` 文件夹中。

---

## 技术支持

- **GitHub Issues**: https://github.com/smart-test-ti/MagnaX/issues
- **版本**: 2.10.0
- **Python 要求**: 3.10+

---

*本文档基于 MagnaX v2.10.0 编写*
