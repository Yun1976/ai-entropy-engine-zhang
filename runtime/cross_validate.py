#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交叉验证引擎 (Cross-Validation Engine)
======================================
替代人工交叉验证。对每个模块用确定性命令独立验证,
不依赖任何 facet 的主观判断。

工作流程:
  1. 读 state.db 各模块状态(某个 facet 写的)
  2. 对每个模块跑客观验证命令
  3. 比较:声称状态 vs 实测状态
  4. 标记 verified/mismatch/unknown
  5. mismatch 的追加事件 + 更新状态

触发方式:
  - Hermes 每日深度思考时跑一轮(hermes cron)
  - 手动: py -3 cross_validate.py
"""
import sys, os, subprocess, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from state_layer import get_all_modules, set_module, add_event, get_conn
from datetime import datetime

def run_cmd(cmd, timeout=10):
    """运行命令,返回(stdout, returncode)"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          timeout=timeout, encoding='utf-8', errors='replace')
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return '(timeout)', -1
    except Exception as e:
        return f'(error: {e})', -1

# ============================================================
# 各模块的客观验证器
# 每个返回 (actual_status, evidence)
# ============================================================
def verify_gateway():
    out, rc = run_cmd('curl -s http://127.0.0.1:18789/health')
    if '"ok":true' in out or "'ok': True" in out:
        return 'running', f'health={out[:40]}'
    return 'broken', f'health返回异常: {out[:60]}'

def verify_hermes():
    out, rc = run_cmd('tasklist /FI "IMAGENAME eq pythonw.exe" /FO CSV')
    if 'pythonw.exe' in out:
        count = out.count('pythonw.exe')
        return 'running', f'pythonw进程x{count}'
    # 也查gateway日志最近是否活跃(10分钟内)
    log_path = r'C:\Users\<USERNAME>\AppData\Local\hermes\logs\gateway.log'
    if os.path.exists(log_path):
        mtime = os.path.getmtime(log_path)
        age_min = (datetime.now().timestamp() - mtime) / 60
        if age_min < 30:
            return 'running', f'gateway日志{age_min:.0f}分钟前活跃(进程名可能不同)'
    return 'stopped', '无pythonw进程且gateway日志超30分钟未更新'

def verify_anti_entropy():
    res_path = r'E:\workspace\anti-entropy-runtime\residuals\residual-v5.jsonl'
    err_path = r'E:\workspace\anti-entropy-runtime\logs\entropy-loop-error.log'
    # error log必须0字节
    err_size = os.path.getsize(err_path) if os.path.exists(err_path) else -1
    if err_size > 0:
        return 'broken', f'error log={err_size}字节(应为0)'
    # 残差必须>50条(持续在增长)
    res_count = 0
    if os.path.exists(res_path):
        with open(res_path, encoding='utf-8') as f:
            res_count = sum(1 for l in f if l.strip())
    if res_count > 50 and err_size == 0:
        return 'stable_running', f'残差{res_count}条+error=0字节'
    return 'unknown', f'残差{res_count}条+error={err_size}字节'

def verify_scheduled_task(task_name):
    """通用: 验证Windows计划任务"""
    out, rc = run_cmd(f'schtasks /query /tn "{task_name}" /fo CSV', timeout=5)
    if rc != 0 or not out.strip():
        return 'stopped', f'任务{task_name}查询失败(rc={rc})'
    # schtasks输出含中文(GBK),匹配数字/英文部分
    # CSV第4列是状态,检查有没有"就绪"/"Ready"/"Running"
    lines = out.split('\n')
    if len(lines) >= 2:
        # 找状态相关关键词(中英文都试)
        for keyword in ['就绪', 'Ready', 'running', '运行']:
            if keyword.lower() in out.lower():
                return 'running', f'任务{task_name}状态={keyword}'
    # 检查是否禁用
    for keyword in ['已禁用', 'Disabled']:
        if keyword.lower() in out.lower():
            return 'stopped', f'任务{task_name}已禁用'
    return 'unknown', f'无法解析任务状态(CSV={lines[1][:60] if len(lines)>1 else "?"})'

def verify_searxng():
    out, rc = run_cmd('curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8888', timeout=5)
    if out == '200':
        return 'running', 'HTTP 200'
    return 'stopped', f'HTTP {out}'

# ============================================================
# 模块→验证器映射
# ============================================================
VERIFIERS = {
    'gateway': verify_gateway,
    'hermes': verify_hermes,
    'anti_entropy': verify_anti_entropy,
    'searxng': verify_searxng,
    'daily_planner': lambda: verify_scheduled_task('EndpointStar_DailyPlanner'),
    'weekly_review': lambda: verify_scheduled_task('EndpointStar_WeeklyReview'),
    'gateway_watchdog': lambda: verify_scheduled_task('OpenClaw Gateway Watchdog'),
    'vault_sync': lambda: verify_scheduled_task('EndpointStar-VaultSync-USB'),
    # 以下模块无客观验证方法(项目状态/未部署),跳过
}

def cross_validate():
    """对所有可验证模块跑一轮交叉验证"""
    modules = get_all_modules()
    results = []
    mismatches = []
    
    for mod in modules:
        name = mod['name']
        claimed_status = mod['status']
        
        if name not in VERIFIERS:
            results.append((name, claimed_status, 'skip', '无客观验证方法'))
            continue
        
        # 跑验证器
        verifier = VERIFIERS[name]
        actual_status, evidence = verifier()
        
        # 比较
        # 归一化比较(running/stable_running都算running)
        def normalize(s):
            if 'running' in s or 'stable' in s: return 'running'
            if 'stopped' in s or 'broken' in s: return 'down'
            return s
        
        match = normalize(claimed_status) == normalize(actual_status)
        
        if match:
            results.append((name, claimed_status, actual_status, '✓ verified'))
            # 更新state.db标记verified
            set_module(name, actual_status, evidence, verified_by=f'cross_validate: {evidence}',
                      actor='cross_validate')
        else:
            results.append((name, claimed_status, actual_status, f'✗ MISMATCH'))
            mismatches.append((name, claimed_status, actual_status, evidence))
            # 更新state.db为实测状态
            set_module(name, actual_status, f'交叉验证修正: 声称={claimed_status} 实测={actual_status} ({evidence})',
                      actor='cross_validate')
            add_event(f'交叉验证发现{mismatches[-1][0]}状态不一致: 声称={claimed_status} 实测={actual_status}',
                     actor='cross_validate', event_type='warning', module=name)
    
    return results, mismatches

def main():
    print(f"===== 交叉验证 {datetime.now().isoformat(timespec='seconds')} =====")
    print()
    results, mismatches = cross_validate()
    
    print(f"{'模块':<25} {'声称状态':<20} {'实测状态':<20} {'判定'}")
    print("-" * 85)
    for name, claimed, actual, verdict in results:
        print(f"{name:<25} {claimed[:18]:<20} {actual[:18]:<20} {verdict}")
    
    print()
    if mismatches:
        print(f"⚠️ 发现 {len(mismatches)} 个状态不一致:")
        for name, claimed, actual, evidence in mismatches:
            print(f"  {name}: 声称={claimed} → 实测={actual} ({evidence})")
    else:
        print("✓ 全部验证通过,无状态不一致")
    
    # 追加验证事件
    add_event(
        f'交叉验证完成: {len(results)}模块验证, {len(mismatches)}个不一致',
        actor='cross_validate', event_type='log', module='state_layer'
    )
    
    return len(mismatches)

if __name__ == '__main__':
    sys.exit(main())
