#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
"""
v5 裁剪工具 (行为后果客观版)
==========================
用 honest_model_v5.joblib (r²=+0.593) 替代 v3。
新增: 行为信号(F/R/C/I)作为评分依据, 宪法层保护, 来源保护, 无法评估标记。

输出裁剪报告 + 行为信号表, 验证"是否真实辨认冗余和熵增"。
"""
import os, re, sys, json, csv
from pathlib import Path
from datetime import date
import numpy as np
import joblib

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
from feature_engineering import (tokenize, struct_density_features, causal_density_features,
    executability_features, IDFComputer, semantic_entropy, temporal_decay_features,
    residual_fourier_features)
from objective_annotate import extract_behavior_signals

VAULT_JSON = BASE.parent / "entropy-dataset-v2.json"
PATH_MAP = BASE / "_all_md_paths.json"
MODEL = BASE / "honest_model_v5.joblib"
CONFIG = BASE / "honest_model_v5_config.json"

CONSTITUTION_KW = ["SOUL","MEMORY","AGENTS","IDENTITY","CLAUDE","思想钢印","persona","manifest","反熵增","信息代谢"]
SNAPSHOT_RE = re.compile(r"^(SOUL|MEMORY|AGENTS|IDENTITY|CLAUDE)[_\-\.]", re.I)

def is_constitution(fn, path):
    pl = path.lower().replace("\\","/")
    if any(k.lower() in fn.lower() or k.lower() in pl for k in CONSTITUTION_KW): return True
    if SNAPSHOT_RE.match(fn): return True
    if ".backup" in pl: return True
    return False

def read_safe(p):
    if not p or not os.path.exists(p): return ''
    for enc in ['utf-8','utf-8-sig','gbk','gb18030','latin-1']:
        try: return open(p, encoding=enc).read()
        except Exception: continue
    return ''

def main():
    lib = json.load(open(VAULT_JSON, encoding="utf-8"))
    paths = json.load(open(PATH_MAP, encoding="utf-8"))
    model = joblib.load(MODEL)
    config = json.load(open(CONFIG, encoding="utf-8"))
    feat_cols = config["feature_cols"]  # 23维

    # IDF (用金标准+客观标注拟合, 与训练一致)
    import csv as c2
    loc_gold = json.load(open(BASE.parent / "_gold_file_locations.json", encoding="utf-8"))
    gold = [r for r in c2.DictReader(open(BASE.parent/'lessons-causal-chain-v1.csv', encoding='gbk'))]
    obj = list(c2.DictReader(open(BASE/'objective_annotated.csv', encoding='utf-8-sig')))
    all_fns = [r['filename'] for r in gold] + [r['filename'] for r in obj]
    texts_cache = {}
    for fn in all_fns:
        p = loc_gold.get(fn) or paths.get(fn,'')
        fp = os.path.join(p,fn) if (p and not p.endswith(fn)) else p
        texts_cache[fn] = read_safe(fp)
    idf = IDFComputer()
    idf.fit([tokenize(texts_cache[fn]) for fn in all_fns])
    res = residual_fourier_features([])

    results = []
    for item in lib:
        fn = item["filename"]
        fullpath = paths.get(fn, "")
        protected = is_constitution(fn, fullpath)
        text = ""; readable = False
        if fullpath and os.path.exists(fullpath):
            try:
                text = read_safe(fullpath)
                readable = len(text.strip()) > 0
            except Exception:
                readable = False
        if protected:
            score = 5.0; status = "🛡️宪法"
        elif not readable:
            score = None; status = "❓无法评估"
        else:
            f = {}
            f.update(struct_density_features(text)); f.update(causal_density_features(text))
            f.update(executability_features(text)); f.update(idf.transform(tokenize(text)))
            f.update(semantic_entropy(text)); f.update(temporal_decay_features(text))
            bsig = extract_behavior_signals(text)
            for k, sk in [('F_failure','F'),('R_response','R'),('C_cognition','C'),('I_integrity','I')]:
                f[k] = bsig[sk]
            x = np.array([[float(f.get(c,0.0)) for c in feat_cols]])
            score = float(model.predict(x)[0]); status = "✓已评估"
        results.append({
            "filename": fn, "category": item.get("category",""),
            "source_dir": item.get("source_dir",""), "internal_links": item.get("internal_links",0),
            "chars": item.get("chars",0), "protected": protected, "score": score,
            "status": status, "F": bsig.get('F',0) if readable else 0,
            "R": bsig.get('R',0) if readable else 0, "C": bsig.get('C',0) if readable else 0,
            "I": bsig.get('I',0) if readable else 0,
        })

    # 决策
    valid = [r["score"] for r in results if not r["protected"] and isinstance(r["score"],(int,float))]
    threshold = float(np.percentile(valid, 20))
    for r in results:
        if r["protected"]: r["decision"]="🛡️宪法保护"; r["reason"]="宪法层/备份"
        elif not isinstance(r["score"],(int,float)): r["decision"]="❓无法评估"; r["reason"]="无法读取"
        elif r["internal_links"]>=5 and r["score"]<threshold:
            r["decision"]="🔗依赖保护"; r["reason"]=f"低分{r['score']:.2f}但被引用{r['internal_links']}次"
        elif r["score"]<threshold:
            # 行为信号判冗余: 仅对系统类文档生效(科学资讯的error是领域术语,不可靠)
            sys_type = r["source_dir"] in ("lessons","daily_memory","ops_schema","workflows","concepts","projects")
            # 空报告(洞察数=0的科学日报)直接判冗余,无视R值(伪应对不算)
            fp = paths.get(r["filename"], "")
            txt = read_safe(fp)
            is_empty_report = ('总洞察数' in txt and
                               bool(re.search(r'总洞察数\s*\|?\s*0|搜索失败|数据获取失败', txt)) and
                               not bool(re.search(r'铁律|Workflow|思想钢印', txt[:800])))
            if is_empty_report:
                r["decision"]="🗑️熵增冗余"; r["reason"]=f"空报告(洞察数=0, 零信息价值)"
            elif sys_type and r["F"]>=2 and r["R"]<2:
                r["decision"]="🗑️熵增冗余"; r["reason"]=f"低分{r['score']:.2f}+故障{r['F']}无应对{r['R']}(系统类真冗余)"
            elif not sys_type and r["F"]>=3 and r["R"]==0 and r["chars"]<600:
                r["decision"]="🗑️熵增冗余"; r["reason"]=f"极短故障流水账({r['chars']}字,F={r['F']},R=0)"
            else:
                r["decision"]="⚠️低分观察"; r["reason"]=f"低分{r['score']:.2f},F={r['F']}R={r['R']},人工复核"
        else:
            r["decision"]="✅保留"; r["reason"]=f"分数{r['score']:.2f}≥P20线{threshold:.2f}"

    # 报告
    today = date.today().isoformat()
    from collections import Counter
    dec = Counter(r["decision"] for r in results)
    print(f"=== v5 全库裁剪 ({len(results)}篇) ===")
    print(f"模型: v5 GBR | r²={config['metrics']['r2_loo']:+.3f} | Spearman={config['metrics']['spearman_loo']:+.3f}")
    print(f"阈值 P20 = {threshold:.2f}")
    for d,n in dec.most_common(): print(f"  {d}: {n}")

    prune = [r for r in results if r["decision"]=="🗑️熵增冗余"]
    print(f"\n=== 🗑️ 熵增冗余清单(真冗余:有故障无应对) {len(prune)}篇 ===")
    for r in sorted(prune, key=lambda x:x["score"])[:20]:
        print(f"  [{r['score']:.2f}] {r['filename'][:38]:38s} | F={r['F']} R={r['R']} | {r['category']}")

    # 保存
    out = BASE / f"v5_pruner_scores_{today}.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename","category","source_dir","score","decision","reason","F","R","C","I","internal_links"], extrasaction="ignore")
        w.writeheader()
        for r in sorted(results, key=lambda x: x["score"] if isinstance(x["score"],(int,float)) else -1):
            w.writerow(r)
    print(f"\n完整评分: {out.name}")

if __name__ == "__main__":
    main()
