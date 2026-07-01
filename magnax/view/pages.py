import json
import os
from flask import Blueprint
from flask import render_template
from flask import request
from loguru import logger
from magnax.public.common import Devices, File, Method

page = Blueprint("page", __name__)
d = Devices()
m = Method()
f = File()

@page.app_errorhandler(404)
def page_404(e):
    settings = m._settings(request)
    return render_template('404.html', **locals()), 404

@page.app_errorhandler(500)
def page_500(e):
    settings = m._settings(request)
    return render_template('500.html', **locals()), 500

@page.route('/')
def index():
    platform = request.args.get('platform')
    lan = request.args.get('lan')
    settings = m._settings(request)
    return render_template('index.html', **locals())

@page.route('/h5')
def h5():
    lan = request.args.get('lan')
    platform = 'Android'
    settings = m._settings(request)
    return render_template('h5.html', **locals())

def _list_h5_scenes(exclude=None):
    """列出所有 H5 报告场景(用于对比下拉),按时间倒序"""
    scenes = []
    report_dir = f.report_dir
    if os.path.isdir(report_dir):
        for dirn in sorted(os.listdir(report_dir), reverse=True):
            rj = os.path.join(report_dir, dirn, 'result.json')
            if dirn == exclude or not os.path.isfile(rj):
                continue
            try:
                rd = json.loads(open(rj, encoding='utf-8').read())
                if rd.get('platform') == 'H5':
                    scenes.append({'scene': dirn, 'app': rd.get('app', ''), 'ctime': rd.get('ctime', '')})
            except Exception:
                pass
    return scenes


@page.route('/h5_analysis', methods=['post', 'get'])
def h5_analysis():
    lan = request.args.get('lan')
    scene = request.args.get('scene')
    app = request.args.get('app')
    settings = m._settings(request)
    h5_data = {}
    try:
        h5_data = f._setH5Perfs(scene)
    except Exception as e:
        logger.exception(e)
    h5_scenes = _list_h5_scenes(exclude=scene)  # 其他 H5 报告,供对比下拉
    return render_template('h5_analysis.html', **locals())

@page.route('/h5_compare', methods=['post', 'get'])
def h5_compare():
    lan = request.args.get('lan')
    scene1 = request.args.get('scene1')
    scene2 = request.args.get('scene2')
    settings = m._settings(request)
    d1, d2 = {}, {}
    try:
        d1 = f._setH5Perfs(scene1)
        d2 = f._setH5Perfs(scene2)
    except Exception as e:
        logger.exception(e)
    return render_template('h5_compare.html', **locals())

@page.route('/pk')
def pk():
    lan = request.args.get('lan')
    model = request.args.get('model')
    settings = m._settings(request)
    return render_template('pk.html', **locals())

@page.route('/report')
def report():
    lan = request.args.get('lan')
    settings = m._settings(request)
    report_dir = f.report_dir
    if not os.path.exists(report_dir):
        os.mkdir(report_dir)
    dirs = os.listdir(report_dir)
    dir_list = reversed(sorted(dirs, key=lambda x: os.path.getmtime(os.path.join(report_dir, x))))
    apm_data = []
    for dir in dir_list:
        if not os.path.isdir(os.path.join(report_dir, dir)):
            continue
        if dir.split(".")[-1] not in ['log', 'json', 'mkv']:
            try:
                fpath = open(os.path.join(report_dir, dir, 'result.json'))
                json_data = json.loads(fpath.read())
                dict_data = {
                    'scene': dir,
                    'app': json_data['app'],
                    'platform': json_data['platform'],
                    'model': json_data['model'],
                    'devices': json_data['devices'],
                    'ctime': json_data['ctime'],
                    'video': json_data.get('video', 0)
                }
                fpath.close()
                apm_data.append(dict_data)
            except Exception as e:
                logger.exception(e)
                continue
    apm_data_len = len(apm_data)
    return render_template('report.html', **locals())

@page.route('/analysis', methods=['post', 'get'])
def analysis():
    lan = request.args.get('lan')
    scene = request.args.get('scene')
    app = request.args.get('app')
    platform = request.args.get('platform')
    settings = m._settings(request)
    report_dir = f.report_dir
    if not os.path.exists(report_dir):
        os.makedirs(report_dir, exist_ok=True)
    dirs = os.listdir(report_dir)
    filter_dir = f.filter_secen(scene)
    apm_data = {}
    # Initialize disk variables with defaults
    initial_disk = []
    current_disk = []
    sum_init_disk = {'sum_size': 0}
    sum_current_disk = {'sum_size': 0}
    for dir in dirs:
        if dir == scene:
            try:
                if platform == 'Android':
                    apm_data = f._setAndroidPerfs(scene)
                    disk = f.analysisDisk(scene)
                    if disk and len(disk) >= 4:
                        initial_disk  = disk[0]
                        current_disk  = disk[1]
                        sum_init_disk = disk[2]
                        sum_current_disk = disk[3]
                else:
                    apm_data = f._setiOSPerfs(scene)
            except ZeroDivisionError:
                pass
            except Exception as e:
                logger.exception(e)
            break
    return render_template('analysis.html', **locals())

@page.route('/pk_analysis', methods=['post', 'get'])
def analysis_pk():
    lan = request.args.get('lan')
    scene = request.args.get('scene')
    app = request.args.get('app')
    model = request.args.get('model')
    settings = m._settings(request)
    report_dir = f.report_dir
    if not os.path.exists(report_dir):
        os.makedirs(report_dir, exist_ok=True)
    dirs = os.listdir(report_dir)
    apm_data = {}
    for dir in dirs:
        if dir == scene:
            try:
                apm_data = f._setpkPerfs(scene)
            except Exception as e:
                logger.exception(e)
            break
    return render_template('analysis_pk.html', **locals())

@page.route('/compare_analysis', methods=['post', 'get'])
def analysis_compare():
    platform = request.args.get('platform')
    lan = request.args.get('lan')
    scene1 = request.args.get('scene1')
    scene2 = request.args.get('scene2')
    app = request.args.get('app')
    settings = m._settings(request)
    try:
        if platform == 'Android':
            apm_data1 = f._setAndroidPerfs(scene1)
            apm_data2 = f._setAndroidPerfs(scene2)
        elif platform == 'iOS':
            apm_data1 = f._setiOSPerfs(scene1)
            apm_data2 = f._setiOSPerfs(scene2)
    except ZeroDivisionError:
        pass 
    except Exception as e:
        logger.exception(e)          
    return render_template('analysis_compare.html', **locals())
