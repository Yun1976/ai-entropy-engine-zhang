#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v5 训练: 客观标注(行为后果) + 行为信号特征
=========================================
对比基准: v3 (59条, LOO r²=+0.207, 仅lessons, 主观rubric)

升级:
  1. 标签: 59真金标准 + 221客观标注(行为后果锥点)
  2. 特征: 原19维 + 新增4维行为信号(F故障/R应对/C认知/I完整性)
  3. 评估: LOO + 分类型 + 硬案例回归测试

关键假设(待验证):
  行为信号(F/R/C/I)是否比文本表面特征更能预测信息价值?
"""
import csv, json, os, sys, warnings
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore")

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
from feature_engineering import tokenize, IDFComputer, extract_all, residual_fourier_features
from objective_annotate import extract_behavior_signals
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.model_selection import LeaveOneOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.base import clone
from scipy.stats import spearmanr, kendalltau
import joblib

def load_gold59():
    for enc in ['gbk','gb18030','utf-8-sig','utf-8']:
        try:
            with open(BASE.parent / 'lessons-causal-chain-v1.csv', encoding=enc) as f:
                rows = list(csv.DictReader(f))
                return [(r['filename'], int(float(r['survival_score'])), 'HUMAN', 'lessons') for r in rows]
        except Exception:
            continue
    return []

def load_obj221():
    with open(BASE / 'objective_annotated.csv', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        s = r.get('obj_score', '')
        if not s: continue
        out.append((r['filename'], int(s), r.get('confidence','MEDIUM'),
                    r.get('source_dir','?'), r['filename']))
    return out

def main():
    gold = load_gold59()
    obj = load_obj221()
    print(f'=== 数据合并 ===')
    print(f'真金标准(人): {len(gold)} 条')
    print(f'客观标注(行为后果): {len(obj)} 条')
    print(f'合计: {len(gold)+len(obj)} 条')

    loc_gold = json.load(open(BASE.parent / '_gold_file_locations.json', encoding='utf-8'))
    paths_all = json.load(open(BASE / '_all_md_paths.json', encoding='utf-8'))

    # 读文本
    texts = {}
    all_fns = [g[0] for g in gold] + [o[0] for o in obj]
    for fn in all_fns:
        if fn in texts: continue
        p = loc_gold.get(fn) or paths_all.get(fn, '')
        fullp = os.path.join(p, fn) if (p and not p.endswith(fn)) else p
        if fullp and os.path.exists(fullp):
            try: texts[fn] = open(fullp, encoding='utf-8').read()
            except: texts[fn] = ''
        else: texts[fn] = ''

    idf = IDFComputer()
    idf.fit([tokenize(texts[fn]) for fn in all_fns])
    res = residual_fourier_features([])

    config_v3 = json.load(open(BASE / 'honest_model_config.json', encoding='utf-8'))
    base_feat_cols = config_v3['feature_cols']  # 原19维
    behavior_feat_cols = ['F_failure', 'R_response', 'C_cognition', 'I_integrity']
    # 行为信号返回的key是F/R/C/I, 映射到特征列名
    beh_key_map = {'F_failure': 'F', 'R_response': 'R', 'C_cognition': 'C', 'I_integrity': 'I'}
    feat_cols = base_feat_cols + behavior_feat_cols  # 23维

    X, y, types, confs, fnames = [], [], [], [], []
    def add_sample(fn, score, conf, sd):
        t = texts[fn]
        f = extract_all(t, idf, res)
        bsig = extract_behavior_signals(t)
        for feat_name, sig_key in beh_key_map.items():
            f[feat_name] = bsig[sig_key]
        X.append([float(f.get(c, 0.0)) for c in feat_cols])
        y.append(score); types.append(sd); confs.append(conf); fnames.append(fn)

    for fn, score, conf, sd in gold:
        add_sample(fn, score, conf, sd)
    for fn, score, conf, sd, _ in obj:
        add_sample(fn, score, conf, sd)

    X = np.array(X); y = np.array(y)
    print(f'特征矩阵: {X.shape} (原19 + 行为4 = {len(feat_cols)}维)')

    def eval_loo(model, X, y):
        loo = LeaveOneOut()
        preds = np.zeros(len(y))
        for tr, te in loo.split(X):
            m = clone(model); m.fit(X[tr], y[tr]); preds[te] = m.predict(X[te])
        r2 = 1 - np.sum((y-preds)**2)/np.sum((y-y.mean())**2)
        mae = np.mean(np.abs(y-preds))
        sp = spearmanr(y, preds).correlation
        kt = kendalltau(y, preds).correlation
        return r2, mae, sp, kt, preds

    candidates = {
        'RF(d4)': RandomForestRegressor(n_estimators=80, max_depth=4, min_samples_leaf=3, random_state=42),
        'Ridge(a5)': Pipeline([('sc',StandardScaler()),('m',Ridge(5.0))]),
        'GBR(d3)': GradientBoostingRegressor(n_estimators=100, max_depth=3, learning_rate=0.08, subsample=0.8, random_state=42),
    }
    print(f'\n=== v5 训练 (280条, 23维含行为信号) ===')
    print(f'{"模型":<12} {"r²":>8} {"MAE":>6} {"Spearman":>9} {"Kendall":>8}')
    best = None; results = {}
    for name, model in candidates.items():
        r2, mae, sp, kt, preds = eval_loo(model, X, y)
        results[name] = (r2, mae, sp, kt, preds)
        print(f'{name:<12} {r2:>+8.3f} {mae:>6.3f} {sp:>+9.3f} {kt:>+8.3f}')
        if best is None or sp > best[1]:
            best = (name, sp, model, preds)

    print(f'\n=== 对比 ===')
    print(f'  v3(59条,19维,主观): r²=+0.207 | Spearman=+0.487')
    print(f'  v5({best[0]},{len(y)}条,23维,客观): r²={results[best[0]][0]:+.3f} | Spearman={results[best[0]][2]:+.3f}')
    print(f'  提升: r² {results[best[0]][0]-0.207:+.3f} | Spearman {results[best[0]][2]-0.487:+.3f}')

    # 硬案例回归测试
    print(f'\n=== 硬案例回归测试 ===')
    hc = json.load(open(BASE / 'hard_cases.json', encoding='utf-8'))
    hc_map = {h['filename']: h['expected_score'] for h in hc}
    preds = best[3]
    fn_idx = {fn: i for i, fn in enumerate(fnames)}
    correct = 0; total = 0; hard_results = []
    for h in hc:
        fn = h['filename']
        if fn in fn_idx:
            i = fn_idx[fn]
            pred = preds[i]; exp = h['expected_score']
            # 容差1分内算通过
            ok = abs(pred - exp) <= 1.0
            if ok: correct += 1
            total += 1
            hard_results.append((fn[:30], exp, round(pred,2), '✓' if ok else '✗'))
    print(f'  通过(±1分容差): {correct}/{total}')
    for fn, exp, pred, ok in hard_results:
        print(f'    {ok} {fn:30s} 期望{exp} 预测{pred}')

    # 分类型
    print(f'\n=== 分类型 Spearman ===')
    for sd in sorted(set(types)):
        idx = [i for i, t in enumerate(types) if t == sd]
        if len(idx) < 5: continue
        sp = spearmanr(y[idx], preds[idx]).correlation
        print(f'  {sd:16s}: n={len(idx):3d} Spearman={sp:+.3f}')

    # 单调性
    print(f'\n=== 各档预测单调性 ===')
    for s in [1,2,3,4,5]:
        idx = [i for i, v in enumerate(y) if v==s]
        if idx:
            print(f'  真实{s}分(n={len(idx)}): 预测均值={preds[idx].mean():.2f}')

    # 保存
    best_model = best[2]; best_model.fit(X, y)
    joblib.dump(best_model, BASE / 'honest_model_v5.joblib')
    cfg = {
        'model_name': best[0], 'feature_cols': feat_cols, 'n_samples': len(y),
        'metrics': {'r2_loo': results[best[0]][0], 'spearman_loo': results[best[0]][2]},
        'vs_v3': {'v3_r2': 0.207, 'v5_r2': results[best[0]][0]},
        'hard_case_pass': f'{correct}/{total}',
        'label_source': '59 human + 221 objective(behavior consequence)',
        'new_features': 'F_failure/R_response/C_cognition/I_integrity',
    }
    json.dump(cfg, open(BASE / 'honest_model_v5_config.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'\nv5模型已保存: honest_model_v5.joblib')

if __name__ == '__main__':
    main()
