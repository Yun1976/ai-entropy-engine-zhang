#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
客观标注引擎 v2 (行为后果锥点)
===============================
替代主观 rubric。标注标准完全基于the AI system的真实行为后果:

  文档价值 = 它是否帮助the AI system维持 功能正确性 + 记忆完整性

客观信号(可验证, 非主观):
  F = 故障记录 (报错/失败/崩溃/超时 — the AI system真实遇到的问题)
  R = 应对有效性 (根因/修复/防止/红线/检查清单 — 真实解决方案)
  C = 认知一致性 (矛盾/偏差/误解/幻觉 — the AI system的认知状态)
  I = 上下文完整性 (断链/丢失/腐烂/配置损坏 — 记忆健康)

客观分数规则:
  5分 (命脉): F>=2 且 R>=3 — 记录了真实故障 + 完整应对 (删了会重蹈覆辙)
  4分 (重要): R>=3 且 (F>=1 或 C>=1) — 有应对+有真实问题场景
  3分 (中等): R>=2 或 (F>=1 且 R>=1) — 部分有用但不完整
  2分 (低值): F>=2 且 R<2 — 只记录故障无应对 (流水账式报错)
  1分 (垃圾): F>=1 且 R=0 且 短文档 — 纯报错堆栈/失败日志

这与主观rubric的根本区别: 分数来自the AI system的真实运行后果, 不是"我觉得好不好"。
"""
import os, re, json, csv
from pathlib import Path
from collections import Counter

BASE = Path(__file__).parent
paths = json.load(open(BASE / '_all_md_paths.json', encoding='utf-8'))

# ============ 客观行为信号 (来自the AI system真实运行) ============
# 这些关键词来自 .hermes/logs/errors.log, gateway-restart.log, config-audit.jsonl
# 以及 lessons/ 里已验证的真实故障案例
SIGNALS = {
    'F_failure': re.compile(
        r'报错|错误|异常|失败|HTTP\s*4\d\d|HTTP\s*5\d\d|超时|timeout|崩溃|crash|'
        r'宕机|outage|不可达|unreachable|断线|掉线|重启失败|启动失败|执行失败|'
        r'返回403|返回500|connection\s*refused|ECONNREFUSED'
    ),
    'R_response': re.compile(
        r'根因|根本原因|修复|解决|应对|防止|避免|验证|回滚|恢复|红线|铁律|'
        r'检查清单|排除清单|强制检查|必须|禁止|不可触碰|杜绝|经验教训|'
        r'L-[A-Z]+\d+|教训总结|应对方案|修复方案|解决方案'
    ),
    'C_cognition': re.compile(
        r'矛盾|自相矛盾|认知错乱|误判|幻觉|偏差|理解偏差|指令误解|'
        r'理解错误|判断错误|决策错误|系统性偏差|不一致|配置不一致'
    ),
    'I_integrity': re.compile(
        r'上下文|context|腐烂|丢失|遗忘|断链|断裂|记忆断档|配置损坏|'
        r'config.*corrupt|corruption|数据丢失|文件丢失|状态丢失'
    ),
}

def extract_behavior_signals(text):
    """抽取文档的4类行为信号强度。
    关键修正: 排除科学领域术语(error correction/crash=崩溃星系等),
    只统计the AI system系统级的真实故障/应对。
    """
    n = max(len(text), 1)
    # 先标记领域术语区域(科学资讯里的error/correction不是系统故障)
    is_science_doc = bool(re.search(r'quantum|CRISPR|量子|基因|biotech|robotics|ScienceDaily|Nature|Microsoft\s*Quantum', text[:500]))

    F = len(SIGNALS['F_failure'].findall(text))
    R = len(SIGNALS['R_response'].findall(text))
    C = len(SIGNALS['C_cognition'].findall(text))
    I = len(SIGNALS['I_integrity'].findall(text))

    # 科学文档: 扣除领域术语污染(error correction/failure mode等非系统故障)
    if is_science_doc:
        domain_noise = len(re.findall(r'error correction|error-correcting|quantum error|相位翻转|退相干|noise.*quantum|failure mode|crash.*星|fault.?toleran', text, re.I))
        F = max(0, F - domain_noise)

    return {
        'F': F, 'R': R, 'C': C, 'I': I,
        'filler_density': len(re.findall(r'执行时间|任务ID|任务类型|Asia/Shanghai|质量评分', text)) / n * 1000,
    }


def objective_score(signals, text_len, filename='', text_for_check=''):
    """
    客观打分。基于行为后果, 非主观。
    返回 (score, confidence, reasoning)
    """
    F, R, C, I = signals['F'], signals['R'], signals['C'], signals['I']
    failure_total = F + C + I  # 总故障信号(报错+认知+完整性)
    filler = signals['filler_density']

    # 规则1: 纯垃圾 (失败记录无应对, 高填充词)
    is_sleeplog = 'sleep' in filename.lower() and 'log' in filename.lower()
    is_backup = filename.lower().startswith('backup-')
    if is_sleeplog or is_backup:
        return 1, 'HIGH', f'客观1分:一次性记录(sleeplog={is_sleeplog},backup={is_backup})'

    # 空报告: 洞察数=0 且 非Workflow/铁律文档(避免误伤"讨论如何应对失败"的核心文档)
    is_workflow_doc = bool(re.search(r'铁律|Workflow|思想钢印|行为准则|Phase\s*\d', text_for_check[:800]))
    is_empty_report = (not is_workflow_doc and '总洞察数' in text_for_check and
                       re.search(r'总洞察数\s*\|?\s*0|洞察数.*\s0\b', text_for_check))
    if is_empty_report:
        return 1, 'HIGH', f'客观1分:空报告(洞察数=0, 非Workflow文档)'

    if failure_total >= 2 and R == 0 and text_len < 1000:
        return 1, 'HIGH', f'客观1分:纯故障无应对且短(故障={failure_total},应对=0,{text_len}字)'

    if filler > 4 and R < 2:
        return 1, 'MEDIUM', f'客观1分:高填充词流水账(filler={filler:.1f},应对={R})'

    # 规则5: 命脉 (真实故障 + 完整应对)
    if failure_total >= 2 and R >= 3:
        return 5, 'HIGH', f'客观5分:故障+应对齐全(故障={failure_total},应对={R})'

    if R >= 5 and (F >= 1 or C >= 1 or I >= 1):
        return 5, 'HIGH', f'客观5分:强应对+真实问题场景(应对={R},故障={failure_total})'

    # 规则4: 重要 (有应对+有问题场景, 但不够命脉级)
    if R >= 3 and failure_total >= 1:
        return 4, 'HIGH', f'客观4分:有应对+问题场景(应对={R},故障={failure_total})'

    if R >= 4:
        return 4, 'MEDIUM', f'客观4分:强应对信号(应对={R})'

    # 规则2: 低价值 (只记录故障无应对)
    if failure_total >= 2 and R < 2:
        return 2, 'HIGH', f'客观2分:故障无应对=流水账(故障={failure_total},应对={R})'

    # 规则3: 中等 (部分有用)
    if R >= 2 or (failure_total >= 1 and R >= 1):
        return 3, 'MEDIUM', f'客观3分:部分有用(故障={failure_total},应对={R})'

    # 默认: 有内容但无行为信号
    if text_len > 800:
        return 3, 'LOW', f'客观3分:有内容无行为信号({text_len}字,需人工确认)'
    return 2, 'MEDIUM', f'客观2分:短文档无信号({text_len}字)'


def main():
    ws = BASE / 'annotation_worksheet.csv'
    with open(ws, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    results = []
    score_dist = Counter()
    conf_dist = Counter()

    for r in rows:
        fn = r['filename']
        fullp = paths.get(fn, '')
        text = ''
        if fullp and os.path.exists(fullp):
            try:
                text = open(fullp, encoding='utf-8').read()
            except Exception:
                text = ''
        signals = extract_behavior_signals(text)
        score, conf, reasoning = objective_score(signals, len(text), fn, text)
        results.append({
            **r,
            'obj_score': score,
            'confidence': conf,
            'F_failure': signals['F'],
            'R_response': signals['R'],
            'C_cognition': signals['C'],
            'I_integrity': signals['I'],
            'reasoning': reasoning,
        })
        score_dist[score] += 1
        conf_dist[conf] += 1

    out = BASE / 'objective_annotated.csv'
    cols = list(rows[0].keys()) + ['obj_score', 'confidence', 'F_failure',
            'R_response', 'C_cognition', 'I_integrity', 'reasoning']
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for r in results:
            w.writerow(r)

    print(f'客观标注完成: {len(results)} 条 -> {out.name}')
    print(f'\n=== 分数分布 ===')
    for s in [1, 2, 3, 4, 5]:
        print(f'  {s}分: {score_dist[s]:3d}篇')
    print(f'\n=== 置信度 ===')
    for c in ['HIGH', 'MEDIUM', 'LOW']:
        print(f'  {c}: {conf_dist[c]:3d}篇')

    # 验证: 检查已知硬案例
    print(f'\n=== 硬案例验证 ===')
    hc = json.load(open(BASE / 'hard_cases.json', encoding='utf-8'))
    hc_map = {h['filename']: h['expected_score'] for h in hc}
    correct = 0; total = 0
    mismatches = []
    for r in results:
        if r['filename'] in hc_map:
            total += 1
            expected = hc_map[r['filename']]
            actual = r['obj_score']
            if actual == expected:
                correct += 1
            else:
                mismatches.append((r['filename'][:35], expected, actual))
    print(f'  硬案例通过: {correct}/{total}')
    if mismatches:
        print(f'  不一致:')
        for fn, exp, act in mismatches[:8]:
            print(f'    {fn:35s} 期望{exp} 实际{act}')

if __name__ == '__main__':
    main()
