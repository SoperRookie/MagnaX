from __future__ import absolute_import
import multiprocessing
import subprocess
import time
import os
import platform
import re
import webbrowser
import requests
import socket
import sys
import psutil
import atexit
import shlex
from loguru import logger
from threading import Lock
from flask import Flask
from pyfiglet import Figlet
from magnax.view.apis import api
from magnax.view.pages import page
from magnax import __version__

# Global reference to tunneld process
_tunneld_process = None

# 免密 sudo helper:magnax 启动时杀旧+起新 tunneld,关闭时停掉。
# 安装见 /usr/local/bin/magnax-tunneld + /etc/sudoers.d/magnax-tunneld(NOPASSWD)。
# 未安装时自动回退到旧的 sudo 提示流程。
_TUNNELD_HELPER = '/usr/local/bin/magnax-tunneld'
_TUNNELD_PATTERN = 'pymobiledevice3 remote tunneld'

# iOS 27 起,pymobiledevice3 7.x 的 tunneld 配对失败(tunnel_service._verify_proof AssertionError),
# 需要 11.x 才能建隧道。但 11.x 接口全异步,采集代码仍基于 7.x,而 7.x 客户端可以正常使用
# 11.x tunneld 提供的隧道。所以只把 tunneld 放到独立 venv 里用新版跑,采集端不动。
# 可用环境变量 MAGNAX_TUNNELD_PYTHON 指定任意装了新版 pymobiledevice3 的 python。
_TUNNELD_VENV = os.path.join(os.path.expanduser('~'), '.magnax', 'tunneld-venv')
_TUNNELD_NEW_IOS_MAJOR = 27
_TUNNELD_NEW_PMD3_MAJOR = 11

app = Flask(__name__, template_folder='templates', static_folder='static')
app.register_blueprint(api)
app.register_blueprint(page)

# socketio = SocketIO(app, cors_allowed_origins="*")
# thread = True
# thread_lock = Lock()


# @socketio.on('connect', namespace='/logcat')
# def connect():
#     socketio.emit('start connect', {'data': 'Connected'}, namespace='/logcat')
#     logDir = os.path.join(os.getcwd(),'adblog')
#     if not os.path.exists(logDir):
#         os.mkdir(logDir)
#     global thread
#     thread = True
#     with thread_lock:
#         if thread:
#             thread = socketio.start_background_task(target=backgroundThread)


# def backgroundThread():
#     global thread
#     try:
#         current_time = time.strftime("%Y%m%d%H", time.localtime())
#         logPath = os.path.join(os.getcwd(),'adblog',f'{current_time}.log')
#         logcat = subprocess.Popen(f'adb logcat *:E > {logPath}', stdout=subprocess.PIPE,
#                                   shell=True)
#         with open(logPath, "r") as f:
#             while thread:
#                 socketio.sleep(1)
#                 for line in f.readlines():
#                     socketio.emit('message', {'data': line}, namespace='/logcat')
#         if logcat.poll() == 0:
#             thread = False
#     except Exception:
#         pass


# @socketio.on('disconnect_request', namespace='/logcat')
# def disconnect():
#     global thread
#     logger.warning('Logcat client disconnected')
#     thread = False
#     disconnect()

def ip() -> str:
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except:
        logger.info('hostname:{}'.format(socket.gethostname()))
        logger.warning('config [127.0.0.1 hostname] in /etc/hosts file')
        ip = '127.0.0.1'    
    return ip


def listen(port):
    net_connections = psutil.net_connections()
    conn = [c for c in net_connections if c.status == "LISTEN" and c.laddr.port == port]
    if conn:
        pid = conn[0].pid
        logger.warning('Port {} is used by process {}'.format(port, pid))
        logger.info('you can start magnax : python -m magnax --host={ip} --port={port}')
        return False
    return True

def status(host: str, port: int):
    r = requests.get('http://{}:{}'.format(host, port), timeout=2.0)
    flag = (True, False)[r.status_code == 200]
    return flag


def open_url(host: str, port: int):
    flag = True
    while flag:
        logger.info('start magnax service')
        f = Figlet(font="slant", width=300)
        print(f.renderText("MAGNAX {}".format(__version__)))
        flag = status(host, port)
    try:    
        webbrowser.open('http://{}:{}/?platform=Android&lan=en'.format(host, port), new=2)
    except Exception as e:
        logger.exception(e)    
    logger.info('Running on http://{}:{}/?platform=Android&lan=en (Press CTRL+C to quit)'.format(host, port))


def start(host: str, port: int):
    # threaded=True:多线程处理请求,避免某次 adb 采集变慢/卡住时单线程把整个服务堵死、
    # 前端所有监控曲线一起卡死(长时间监控高负载下尤其明显)
    app.run(host=host, port=port, debug=False, threaded=True)


def _max_ios_major():
    """已连接 iOS 设备中最高的系统主版本号,没有设备或读不到返回 0。"""
    major = 0
    try:
        from pymobiledevice3.usbmux import list_devices
        from pymobiledevice3.lockdown import create_using_usbmux

        for device in list_devices():
            try:
                version = create_using_usbmux(serial=device.serial).product_version
                if version:
                    major = max(major, int(version.split('.')[0]))
            except Exception:
                pass
    except Exception:
        pass
    return major


def check_ios17_device():
    """Check if there are iOS 17+ devices connected."""
    return _max_ios_major() >= 17


def _pmd3_major(python_exe=None):
    """指定 python 环境里 pymobiledevice3 的主版本号,取不到返回 0。默认查当前环境。"""
    try:
        if python_exe is None or python_exe == sys.executable:
            from importlib.metadata import version
            ver = version('pymobiledevice3')
        else:
            ver = subprocess.run(
                [python_exe, '-c',
                 "from importlib.metadata import version;print(version('pymobiledevice3'))"],
                capture_output=True, text=True, timeout=30).stdout.strip()
        return int(ver.split('.')[0])
    except Exception:
        return 0


def _ensure_tunneld_venv():
    """确保独立 venv 里有新版 pymobiledevice3,返回其 python 路径;失败返回 None。"""
    py = os.path.join(_TUNNELD_VENV, 'bin', 'python')
    if os.path.exists(py) and _pmd3_major(py) >= _TUNNELD_NEW_PMD3_MAJOR:
        return py
    logger.info(f'[iOS] 检测到 iOS {_TUNNELD_NEW_IOS_MAJOR}+,首次需要安装新版 pymobiledevice3 '
                f'到 {_TUNNELD_VENV}(需联网,约 1 分钟)...')
    try:
        os.makedirs(os.path.dirname(_TUNNELD_VENV), exist_ok=True)
        if not os.path.exists(py):
            subprocess.run([sys.executable, '-m', 'venv', _TUNNELD_VENV], check=True, timeout=300,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        subprocess.run([py, '-m', 'pip', 'install', '-q', '-U', 'pymobiledevice3'], check=True,
                       timeout=900, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if _pmd3_major(py) >= _TUNNELD_NEW_PMD3_MAJOR:
            logger.info('[iOS] 新版 pymobiledevice3 安装完成')
            return py
        logger.warning('[iOS] 安装后的 pymobiledevice3 版本仍低于 11')
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b'').decode(errors='ignore').strip()[-300:]
        logger.warning(f'[iOS] 安装新版 pymobiledevice3 失败: {err or e}')
    except Exception as e:
        logger.warning(f'[iOS] 安装新版 pymobiledevice3 失败: {e}')
    return None


def _tunneld_python(ios_major):
    """决定用哪个 python 起 tunneld:iOS 27+ 且当前环境 pymobiledevice3 < 11 时用独立 venv。"""
    override = os.environ.get('MAGNAX_TUNNELD_PYTHON')
    if override:
        return override
    if ios_major < _TUNNELD_NEW_IOS_MAJOR or _pmd3_major() >= _TUNNELD_NEW_PMD3_MAJOR:
        return sys.executable
    py = _ensure_tunneld_venv()
    if py is None:
        logger.warning(f'[iOS] 回退到当前环境的 tunneld,iOS {_TUNNELD_NEW_IOS_MAJOR}+ 很可能建不了隧道。'
                       f'可手动执行: {sys.executable} -m venv {_TUNNELD_VENV} && '
                       f'{_TUNNELD_VENV}/bin/pip install -U pymobiledevice3')
        return sys.executable
    return py


def _remote_pair(python_exe):
    """借已信任的 USB lockdown 会话写 RemotePairing 配对记录(无弹窗),失败不影响后续。"""
    try:
        subprocess.run([python_exe, '-m', 'pymobiledevice3', 'lockdown', 'remotepairing', '--pair'],
                       timeout=30, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        logger.debug(f'[iOS] remotepairing --pair failed: {e}')


def _helper_python():
    """免密 helper 脚本里写死的 python 路径(PYEXE=...),读不到返回 None。"""
    try:
        with open(_TUNNELD_HELPER) as fh:
            m = re.search(r'^PYEXE=["\']?([^"\'\n]+)', fh.read(), re.M)
        return m.group(1).strip() if m else None
    except Exception:
        return None


def _same_python(a, b):
    # 不能用 realpath:venv 的 bin/python 是指向基础解释器的软链接,解析后会和当前环境"相同"
    try:
        return os.path.abspath(a) == os.path.abspath(b)
    except Exception:
        return False


def is_tunneld_running():
    """Check if tunneld is already running."""
    try:
        from pymobiledevice3.tunneld.api import get_tunneld_devices
        devices = get_tunneld_devices()
        return len(devices) > 0
    except:
        return False


def _run_with_sudo_macos(cmd_args, kill_old=False):
    """Run command with sudo using macOS GUI password prompt.
    kill_old=True 时先杀掉残留的旧 tunneld(占着 49151 端口,新的起不来)。"""
    try:
        # Use osascript to get admin privileges with GUI prompt
        cmd_str = ' '.join(shlex.quote(a) for a in cmd_args)
        if kill_old:
            cmd_str = f"/usr/bin/pkill -9 -f '{_TUNNELD_PATTERN}'; /bin/sleep 1; {cmd_str}"
        apple_script = f'''
        do shell script "{cmd_str} > /dev/null 2>&1 &" with administrator privileges
        '''
        result = subprocess.run(
            ['osascript', '-e', apple_script],
            capture_output=True,
            timeout=60  # Give user time to enter password
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning('[iOS] Password prompt timed out')
        return False
    except Exception as e:
        logger.debug(f'[iOS] osascript failed: {e}')
        return False


def _run_with_sudo_linux(cmd_args):
    """Run command with sudo using Linux GUI password prompt (if available)."""
    try:
        # Try pkexec (PolicyKit) for GUI prompt
        result = subprocess.run(
            ['which', 'pkexec'],
            capture_output=True
        )
        if result.returncode == 0:
            subprocess.Popen(
                ['pkexec'] + cmd_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            return True
    except:
        pass

    # Try zenity/kdialog for password input
    try:
        # Try zenity (GNOME)
        result = subprocess.run(
            ['zenity', '--password', '--title=MagnaX - iOS tunneld'],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0 and result.stdout:
            password = result.stdout.strip()
            proc = subprocess.Popen(
                ['sudo', '-S'] + cmd_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            proc.stdin.write(f'{password}\n'.encode())
            proc.stdin.close()
            return True
    except:
        pass

    return False


def start_tunneld():
    """启动 magnax 时创建全新 tunneld:优先用免密 helper 杀旧+起新,保证每次都是新的
    (旧 tunneld 可能状态陈旧、抓不到当前设备,如 WiFi->USB 切换后)。未装 helper 则回退旧流程。"""
    if platform.system() == 'Windows':
        logger.warning('[iOS] tunneld is not supported on Windows')
        return False
    ios_major = _max_ios_major()
    if ios_major < 17:
        logger.debug('[iOS] No iOS 17+ device found, skipping tunneld')
        return True

    tunneld_py = _tunneld_python(ios_major)
    external = not _same_python(tunneld_py, sys.executable)
    if external:
        logger.info(f'[iOS] iOS {ios_major} 设备,tunneld 使用独立环境: {tunneld_py}')
        _remote_pair(tunneld_py)

    helper_ok = os.path.exists(_TUNNELD_HELPER)
    if helper_ok and external and not _same_python(_helper_python() or '', tunneld_py):
        # helper 里写死的是旧环境的 python,起出来的 tunneld 连不上 iOS 27。
        # 只用它把旧 tunneld 停掉,再走下面的 sudo 提示流程用新环境起。
        helper_ok = False
        subprocess.run(['sudo', '-n', _TUNNELD_HELPER, 'stop'],
                       timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.warning('[iOS] 免密 helper 指向的环境不支持当前 iOS 版本,本次改用密码提示启动。'
                       '想恢复免密,执行一次: '
                       f"sudo sed -i '' 's|^PYEXE=.*|PYEXE=\"{tunneld_py}\"|' {_TUNNELD_HELPER}")

    if helper_ok:
        try:
            subprocess.run(['sudo', '-n', _TUNNELD_HELPER, 'restart'],
                           timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(15):
                time.sleep(1)
                if is_tunneld_running():
                    logger.info('[iOS] tunneld 已重建(全新)')
                    return True
            logger.warning('[iOS] 已调用 tunneld helper 但隧道未就绪(设备是否连好并已信任?)')
            return False
        except Exception as e:
            logger.warning(f'[iOS] tunneld helper 调用失败: {e},回退到旧方式')

    return _start_tunneld_legacy(tunneld_py)


def _start_tunneld_legacy(python_exe=None):
    """回退流程:未装免密 helper 时,用 sudo GUI 提示启动 tunneld。
    python_exe 不是当前环境时(iOS 27+ 的独立 venv),macOS 下会顺带杀掉残留的旧 tunneld。"""
    global _tunneld_process
    python_exe = python_exe or sys.executable
    external = not _same_python(python_exe, sys.executable)

    # Only run on macOS/Linux
    if platform.system() == 'Windows':
        logger.warning('[iOS] tunneld is not supported on Windows')
        return False

    # Check if already running
    if is_tunneld_running():
        logger.info('[iOS] tunneld is already running')
        return True

    # Check if iOS 17+ device exists
    if not check_ios17_device():
        logger.debug('[iOS] No iOS 17+ device found, skipping tunneld')
        return True

    logger.info('[iOS] iOS 17+ device detected, starting tunneld...')

    tunneld_cmd = [python_exe, '-m', 'pymobiledevice3', 'remote', 'tunneld']

    # Try to start tunneld
    try:
        # First try without sudo (might work if user has permissions)
        _tunneld_process = subprocess.Popen(
            tunneld_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        # Wait a moment and check if it's working
        time.sleep(2)
        if is_tunneld_running():
            logger.info('[iOS] tunneld started successfully')
            return True

        # If not working, kill it and try with sudo
        if _tunneld_process:
            try:
                _tunneld_process.terminate()
            except:
                pass
            _tunneld_process = None

        # Try with GUI sudo prompt based on platform
        logger.info('[iOS] Requesting administrator privileges for tunneld...')

        if platform.system() == 'Darwin':
            # macOS: Use osascript for GUI password prompt
            if _run_with_sudo_macos(tunneld_cmd, kill_old=external):
                # Wait for tunneld to start
                for _ in range(10):
                    time.sleep(1)
                    if is_tunneld_running():
                        logger.info('[iOS] tunneld started successfully')
                        return True
        else:
            # Linux: Try GUI methods
            if _run_with_sudo_linux(tunneld_cmd):
                for _ in range(10):
                    time.sleep(1)
                    if is_tunneld_running():
                        logger.info('[iOS] tunneld started successfully')
                        return True

        # Last resort: try terminal sudo (will prompt in terminal)
        logger.info('[iOS] Trying terminal sudo (enter password if prompted)...')
        subprocess.Popen(
            ['sudo'] + tunneld_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        for _ in range(15):
            time.sleep(1)
            if is_tunneld_running():
                logger.info('[iOS] tunneld started successfully')
                return True

        logger.warning('[iOS] Could not start tunneld automatically')
        logger.warning(f'[iOS] Please run manually: sudo {python_exe} -m pymobiledevice3 remote tunneld')
        return False

    except Exception as e:
        logger.warning(f'[iOS] Failed to start tunneld: {e}')
        logger.warning(f'[iOS] Please run manually: sudo {python_exe} -m pymobiledevice3 remote tunneld')
        return False


def stop_tunneld():
    """关闭 magnax 时停掉 tunneld。仅主进程执行 —— multiprocessing worker(open_url 等)
    退出时若也跑这里会把服务还在用的 tunneld 误杀。"""
    if multiprocessing.current_process().name != 'MainProcess':
        return

    # 优先用免密 helper 停(能停掉 sudo/root 起的 tunneld,自己 Popen 的那个 terminate 不到)
    if os.path.exists(_TUNNELD_HELPER):
        try:
            subprocess.run(['sudo', '-n', _TUNNELD_HELPER, 'stop'],
                           timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info('[iOS] tunneld 已随 magnax 关闭')
        except Exception as e:
            logger.debug(f'[iOS] stop tunneld failed: {e}')

    # 兜底:杀掉自己 Popen 出来的那个(未装 helper 的回退场景)
    global _tunneld_process
    if _tunneld_process:
        try:
            _tunneld_process.terminate()
            _tunneld_process.wait(timeout=5)
        except Exception:
            try:
                _tunneld_process.kill()
            except Exception:
                pass
        _tunneld_process = None


# Register cleanup on exit
atexit.register(stop_tunneld)


def main(host=None, port=50003):
    # 默认值在导入时即求值,故 ip() 不能作为默认参数(会产生导入期 DNS 解析副作用)
    if host is None:
        host = ip()

    # kill(SIGTERM)关闭时也干净停掉 tunneld —— atexit/KeyboardInterrupt 只覆盖 Ctrl+C。
    # SIGKILL(-9)无法捕获,但"下次启动杀旧建新"仍保证不残留。
    import signal
    def _graceful(signum, frame):
        logger.info('stop magnax (signal {})'.format(signum))
        stop_tunneld()
        sys.exit(0)
    try:
        signal.signal(signal.SIGTERM, _graceful)
    except Exception:
        pass

    # Start tunneld for iOS 17+ devices if needed(启动时杀旧建新)
    start_tunneld()

    try:
        pool = multiprocessing.Pool(processes=2)
        pool.apply_async(start, (host, port))
        pool.apply_async(open_url, (host, port))
        pool.close()
        pool.join()
    except KeyboardInterrupt:
        logger.info('stop magnax success')
        stop_tunneld()
        sys.exit()
    except Exception as e:
        logger.exception(e)
