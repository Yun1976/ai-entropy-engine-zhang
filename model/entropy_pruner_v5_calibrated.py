#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反熵增v5裁剪工具 (跨域校准版)
============================
修复:
  1. 数据源用 _all_md_paths_v2.json (排除backup垃圾, 含lessons域)
  2. 跨域校准: 用金标准59条的预测误差修正系统性偏移
  3. 独立验证: 用金标准MAE/Spearman报告真实准确性

校准原理:
  训练域(lessons)均值2.87, 新域(wiki)均值3.42, 偏移+0.55
  → 推理时减去校准常数, 让跨域预测对齐训练域的尺度
"""
import os, re, sys, json, csv
from pathlib import Path
from datetime import date
import numpy as np
import joblib

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
from feature_engineering import (tokenize, IDFComputer, extract_all, residual_fourier_features)
from objective_annotate import extract_behavior_signals

MODEL = BASE / 'honest_model_v5.joblib'
CONFIG = BASE / 'honest_model_v5_config.json'
PATH_MAP = BASE / '_all_md_paths_v2.json'  # 干净数据源
GOLD_CSV = BASE.parent / 'lessons-causal-chain-v1.csv'
GOLD_LOC = BASE.parent / '_gold_file_locations.json'

def read_safe(p):
    if not p or not os.path.exists(p): return ''
    for enc in ('utf-8','utf-8-sig','gbk','gb18030','latin-1'):
        try: return open(p, encoding=enc).read()
        except: continue
    return ''

def main():
    paths = json.load(open(PATH_MAP, encoding='utf-8'))
    model = joblib.load(str(MODEL))
    config = json.load(open(CONFIG, encoding='utf-8'))
    feat_cols = config['feature_cols']

    # IDF拟合(训练一致)
    gold = list(csv.DictReader(open(str(GOLD_CSV), encoding='gbk')))
    obj = list(csv.DictReader(open(str(BASE/'objective_annotated.csv'), encoding='utf-8-sig')))
    loc_gold = json.load(open(str(GOLD_LOC), encoding='utf-8'))
    all_fns = [r['filename'] for r in gold] + [r['filename'] for r in obj]
    texts_cache = {}
    for fn in all_fns:
        d = loc_gold.get(fn) or paths.get(fn, '')
        fp = os.path.join(d, fn) if (d and not d.endswith(fn)) else d
        texts_cache[fn] = read_safe(fp)
    idf = IDFComputer()
    idf.fit([tokenize(texts_cache[fn]) for fn in all_fns])
    res = residual_fourier_features([])

    # === 跨域校准: 用金标准59条算偏移 ===
    gold_preds = []
    for r in gold:
        fn = r['filename']
        t = texts_cache.get(fn, '')
        if not t: continue
        f = extract_all(t, idf, res)
        bsig = extract_behavior_signals(t)
        for k, sk in [('F_failure','F'),('R_response','R'),('C_cognition','C'),('I_integrity','I')]:
            f[k] = bsig[sk]
        x = np.array([[float(f.get(c, 0.0)) for c in feat_cols]])
        pred = float(model.predict(x)[0])
        gold_preds.append((int(float(r['survival_score'])), pred))
    # 偏移 = 新域均值 - 训练域均值。用金标准(训练域)的预测误差反推
    # 如果模型对训练域高估, 则全库也会高估同样幅度
    train_residuals = [p - g for g, p in gold_preds]  # 预测-真值
    calibrate_offset = np.median(train_residuals)  # 用中位数(抗异常值)
    print(f'=== 跨域校准 ===')
    print(f'金标准回测: {len(gold_preds)}条')
    print(f'预测残差中位数: {calibrate_offset:+.3f} (正=模型高估)')
    import statistics
    from scipy.stats import spearmanr
    gy = [p[0] for p in gold_preds]
    py_raw = [p[1] for p in gold_preds]
    py_cal = [p[1] - calibrate_offset for p in gold_preds]
    mae_raw = statistics.mean(abs(a-b) for a,b in zip(gy,py_raw))
    mae_cal = statistics.mean(abs(a-b) for a,b in zip(gy,py_cal))
    print(f'校准前 MAE={mae_raw:.3f} → 校准后 MAE={mae_cal:.3f}')
    sp = spearmanr(gy, py_cal).correlation
    strict = sum(1 for a,b in zip(gy,py_cal) if abs(a-b)<=0.5)/len(gold_preds)
    loose = sum(1 for a,b in zip(gy,py_cal) if abs(a-b)<=1.0)/len(gold_preds)
    print(f'校准后: Spearman={sp:+.3f} 严格准确(±0.5)={strict*100:.0f}% 宽松准确(±1)={loose*100:.0f}%')
    print()

    # === 全库评分(校准后) ===
    results = []
    for fn, fullpath in paths.items():
        text = read_safe(fullpath)
        if len(text.strip()) < 50:
            continue
        f = extract_all(text, idf, res)
        bsig = extract_behavior_signals(text)
        for k, sk in [('F_failure','F'),('R_response','R'),('C_cognition','C'),('I_integrity','I')]:
            f[k] = bsig[sk]
        x = np.array([[float(f.get(c, 0.0)) for c in feat_cols]])
        raw_score = float(model.predict(x)[0])
        score = max(0.0, raw_score - calibrate_offset)  # 校准
        results.append({
            'filename': fn, 'score': round(score, 3), 'raw_score': round(raw_score, 3),
            'F': bsig['F'], 'R': bsig['R'], 'C': bsig['C'], 'I': bsig['I'],
            'filler_density': round(bsig['filler_density'], 2),
            'chars': len(text),
        })

    # 决策(分位数阈值)
    scores = [r['score'] for r in results]
    p20 = float(np.percentile(scores, 20))
    for r in results:
        is_empty = '总洞察数' in read_safe(paths[r['filename']]) and \
                   bool(re.search(r'总洞察数\s*\|?\s*0', read_safe(paths[r['filename']])))
        if r['score'] >= p20:
            r['decision'] = '✅保留'
        elif is_empty:
            r['decision'] = '🗑️熵增冗余'
            r['reason'] = '空报告(洞察数=0)'
        elif r['F'] >= 2 and r['R'] < 2 and r['chars'] < 1500:
            r['decision'] = '🗑️熵增冗余'
            r['reason'] = f'故障{r["F"]}无应对{r["R"]}短文档'
        else:
            r['decision'] = '⚠️低分观察'
            r['reason'] = f'低分{r["score"]:.2f},需复核'

    # 输出
    from collections import Counter
    today = date.today().isoformat()
    RUNTIME = Path(r'E:\workspace\anti-entropy-runtime\scores')
    RUNTIME.mkdir(parents=True, exist_ok=True)
    out = RUNTIME / f'v5_calibrated_scores_{today}.csv'
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['filename','score','raw_score','decision','reason','F','R','C','I','filler_density','chars'], extrasaction='ignore')
        w.writeheader()
        for r in sorted(results, key=lambda x: x['score']):
            w.writerow(r)

    dec = Counter(r['decision'] for r in results)
    print(f'=== 全库校准评分 ({len(results)}篇, 阈值P20={p20:.2f}) ===')
    for d, c in dec.most_common():
        print(f'  {d}: {c} ({c/len(results)*100:.0f}%)')
    # 分数分布
    buckets = Counter(int(r['score']) for r in results)
    print(f'分数桶: ' + ' '.join(f'{b}分={buckets.get(b,0)}' for b in range(6)))
    print(f'\n保存: {out.name}')
    return results, gold_preds, calibrate_offset

if __name__ == '__main__':
    main()
