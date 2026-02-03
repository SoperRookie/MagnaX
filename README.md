<p align="center">
  <a>English</a> | <a href="./README.zh.md">中文</a> | <a href="./FAQ.md">FAQ</a> | <a href="https://mp.weixin.qq.com/s?__biz=MzkxMzYyNDM2NA==&mid=2247484506&idx=1&sn=b7eb6de68f84bed03001375d08e08ce9&chksm=c17b9819f60c110fd14e652c104237821b95a13da04618e98d2cf27afa798cb45e53cf50f5bd&token=1402046775&lang=zh_CN&poc_token=HKmRi2WjP7gf9CVwvLWQ2cRhrUR3wmbB9-fNZdD4" target="__blank">使用文档</a>
</p>

<p align="center">
<a href="#">
<img src="https://cdn.nlark.com/yuque/0/2024/png/153412/1715927541315-fb4f7662-d8bb-4d3e-a712-13a3c3073ac8.png?x-oss-process=image%2Fformat%2Cwebp" alt="MagnaX" width="100">
</a>
<br>
</p>
<p align="center">
<a href="https://pypi.org/project/magnax/" target="__blank"><img src="https://img.shields.io/pypi/v/magnax" alt="magnax preview"></a>
<a href="https://pepy.tech/project/magnax" target="__blank"><img src="https://static.pepy.tech/personalized-badge/magnax?period=total&units=international_system&left_color=grey&right_color=orange&left_text=downloads"></a>

<br>
</p>

## 🔎Preview

MagnaX - Real-time collection tool for Android/iOS performance data.

Quickly locate and analyze performance issues to improve application performance and quality. No need for ROOT/jailbreak, plug and play.

![10 161 9 178_50003__platform=Android lan=en (1)](https://github.com/smart-test-ti/MagnaX/assets/24454096/61a0b801-23b4-4711-8215-51cd7bc9dc04)

## 📦Requirements

- Install Python 3.10 + (supports up to Python 3.14) [**Download**](https://www.python.org/downloads/)
- Install adb and configure environment variables (MagnaX's  adb may not necessarily fit your computer) [**Download**](https://developer.android.com/studio/releases/platform-tools)

💡 If Windows users need to test iOS, install and start iTunes. [**Documentation**](https://github.com/alibaba/taobao-iphone-device)

💡 For iOS 17+ devices, you need to start the pymobiledevice3 tunnel service first:

```shell
# macOS/Linux (requires sudo)
sudo python3 -m pymobiledevice3 remote start-tunnel

# Or run as a background daemon
sudo python3 -m pymobiledevice3 remote tunneld
```

## 📥Installation

### default

```shell
pip install -U magnax    (pip install magnax==version)
```

### mirrors

```shell
pip install -i  https://mirrors.ustc.edu.cn/pypi/web/simple -U magnax
```

💡 If your network is unable to download through [pip install -U magnax], please try using mirrors to download, but the download of MagnaX may not be the latest version.

## 🚀Quickstart

### default

```shell
python -m magnax
```

### customize

```shell
python -m magnax --host=ip --port=port
```

## 🏴󠁣󠁩󠁣󠁭󠁿Python API

```python
# magnax version : >= 2.8.5
from magnax.public.apm import AppPerformanceMonitor
from magnax.public.common import Devices

d = Devices()
processList = d.getPid(deviceId='ca6bd5a5', pkgName='com.bilibili.app.in') # for android
print(processList) # ['{pid}:{packagename}',...]

apm = AppPerformanceMonitor(pkgName='com.bilibili.app.in',platform='Android', deviceId='ca6bd5a5', surfaceview=True, 
                            noLog=False, pid=None, record=False, collect_all=False, duration=0)
# apm = AppPerformanceMonitor(pkgName='com.bilibili.app.in', platform='iOS') only supports one device
# surfaceview： False = gfxinfo (Developer - GPU rendering mode - adb shell dumpsys gfxinfo)
# noLog : False (Save test data to log file)

# ************* Collect a performance parameter ************* #
cpu = apm.collectCpu() # %
memory = apm.collectMemory() # MB
memory_detail = apm.collectMemoryDetail() # MB
network = apm.collectNetwork(wifi=True) # KB
fps = apm.collectFps() # HZ
battery = apm.collectBattery() # level:% temperature:°C current:mA voltage:mV power:w
gpu = apm.collectGpu() # %
disk = apm.collectDisk()
thermal = apm.collectThermal()
# ************* Collect all performance parameter ************* #
 
if __name__ == '__main__':
  apm = AppPerformanceMonitor(pkgName='com.bilibili.app.in',platform='Android', deviceId='ca6bd5a5', surfaceview=True, 
                              noLog=False, pid=None, record=False, collect_all=True, duration=0)
  # apm = AppPerformanceMonitor(pkgName='com.bilibili.app.in', platform='iOS',  deviceId='xxxx', noLog=False, record=False, collect_all=True, duration=0)
  #duration: running time (second)
  #record: record android screen
  apm.collectAll(report_path=None) # report_path='/test/report.html'

# in other python file
from magnax.public.apm import initPerformanceService  

initPerformanceService.stop() # stop magnax
```

## 🏴󠁣󠁩󠁣󠁭󠁿Service API

### Start the service in the background

```
# magnax version >= 2.1.5

macOS/Linux: nohup python3 -m magnax &
Windows: start /min python3 -m magnax &
```

### Request performance data from api

```shell
Android: http://{ip}:{port}/apm/collect?platform=Android&deviceid=ca6bd5a5&pkgname=com.bilibili.app.in&target=cpu
iOS: http://{ip}:{port}/apm/collect?platform=iOS&pkgname=com.bilibili.app.in&target=cpu

target in ['cpu','memory','memory_detail','network','fps','battery','gpu']
```

## 🔥Features

* **No ROOT/Jailbreak:** No need of Root for Android devices, Jailbreak for iOS devices. Efficiently solving the test and analysis challenges in Android & iOS performance.
* **Data Integrality:** We provide the data about CPU, GPU, Memory, Battery, Network,FPS, Jank, etc., which you may easy to get.
* **Beautiful Report:** A beautiful and detailed report analysis, where to store, visualize, edit, manage, and download all the test cases collected with MagnaX no matter where you are or when is it.
* **Useful Monitoring Settings:** Support setting alarm values, collecting duration, and accessing mobile devices on other PC machines during the monitoring process.
* **PK Model:** Supports simultaneous comparative testing of two mobile devices.

  - 🌱2-devices: test the same app on two different phones.
  - 🌱2-apps: test two different apps on two phones with the same configuration.
* **Collect In Python/API:** Support Python and API to collect performance data, helping users easily integrate into automated testing processes.

## Develop

* https://github.com/pallets/flask
* https://github.com/tabler/tabler

### Dependencies

| Package | Purpose |
|---|---|
| flask >= 3.1.0 | Web framework |
| loguru | Logging |
| openpyxl >= 3.1.0 | Excel report export (.xlsx) |
| pymobiledevice3 >= 2.0.0 | iOS device control |
| py-ios-device >= 2.0.0 | iOS performance data collection |
| fire | CLI argument parsing |
| psutil | System process utilities |
| opencv-python | Screen recording |

### Debug

* Remove `magnax.` prefix in import paths

```python
# example
from magnax.view.apis import api
# change to
from view.apis import api
```

* Run debug server

```shell
cd magnax
python debug.py
```

## Browser

<img src="https://cdn.nlark.com/yuque/0/2023/png/153412/1677553244198-96ce5709-f33f-4038-888f-f330d1f74450.png" alt="Chrome" width="50px" height="50px" />

## Terminal

- windows: PowerShell
- macOS：iTerm2 (https://iterm2.com/)

## 💕Thanks

- https://github.com/doronz88/pymobiledevice3
- https://github.com/YueChen-C/py-ios-device
- https://github.com/Genymobile/scrcpy
