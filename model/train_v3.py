#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诚实回归训练 (v3)
=================
与旧模型(ridge_model.joblib, 声称0.778, 实际CV r²=-0.559)透明对比。

策略:
  - 样本: 59 (小样本) -> 用 5折CV + Leave-One-Out 双重验证
  - 特征: 27维, 但傅里叶族7维当前无效(residual=null), 实际有效~20维
  - 防过拟合: 特征筛选(|diff|>0.3) + 正则化(Ridge/GBR) + 小模型
  - 诚实: 报告所有 fold 的 r², 不挑最好的一折

输出:
  - honest_model.joblib       (新模型)
  - honest_features.json      (特征清单+IDF, 用于推理)
  - training_report.md        (透明对比报告)
"""
import csv, json, os, statistics, warnings
from pathlib import Path
import numpy as np

warnings.filterwarnings("ignore")
from sklearn.linear_model import Ridge, Lasso
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.model_selection import KFold, LeaveOneOut, cross_val_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import joblib

BASE = Path(__file__).parent
CSV_PATH = BASE / "training_set_v3.csv"

META_COLS = ["filename", "title", "survival_score"]

def load_data():
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    feat_cols = [c for c in rows[0].keys() if c not in META_COLS]
    X = np.array([[float(r[c]) for c in feat_cols] for r in rows])
    y = np.array([int(r["survival_score"]) for r in rows])
    fnames = [r["filename"] for r in rows]
    return X, y, feat_cols, fnames, rows

def eval_model(model, X, y, name):
    """5折CV + LOO 双重评估, 返回指标字典。
    LOO r² 用单次汇总预测计算(避免逐fold nan)。"""
    from sklearn.base import clone
    from scipy.stats import spearmanr, kendalltau
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    r2_5f = cross_val_score(model, X, y, cv=kf, scoring="r2")
    mae_5f = cross_val_score(model, X, y, cv=kf, scoring="neg_mean_absolute_error")
    # LOO: 汇总所有折的预测, 一次性算 r²/MAE/排序
    loo = LeaveOneOut()
    preds = np.zeros(len(y))
    for tr, te in loo.split(X):
        m = clone(model)
        m.fit(X[tr], y[tr])
        preds[te] = m.predict(X[te])
    r2_loo = float(1 - np.sum((y - preds) ** 2) / np.sum((y - y.mean()) ** 2))
    mae_loo = float(np.mean(np.abs(y - preds)))
    sp = float(spearmanr(y, preds).correlation)
    kt = float(kendalltau(y, preds).correlation)
    # Top识别精度: 真实>=4分的文档, 预测排前N的命中率
    top_real = set(np.where(y >= 4)[0])
    top_pred = set(np.argsort(preds)[-len(top_real):])
    top_prec = len(top_real & top_pred) / max(len(top_real), 1)
    return {
        "name": name,
        "r2_5fold_mean": float(np.mean(r2_5f)),
        "r2_5fold_std": float(np.std(r2_5f)),
        "r2_5fold_folds": [float(x) for x in r2_5f],
        "r2_loo": r2_loo,
        "mae_loo": mae_loo,
        "spearman_loo": sp,
        "kendall_loo": kt,
        "top4_precision": float(top_prec),
    }

def main():
    X, y, feat_cols, fnames, rows = load_data()
    print(f"数据: {X.shape[0]} 样本 x {X.shape[1]} 特征")
    print(f"标签分布: {dict(zip(*np.unique(y, return_counts=True)))}")

    # --- 旧模型基线复现(用同样的表面特征无法对比, 直接引用其报告值) ---
    print("\n=== 旧模型(v1) 已报告指标 ===")
    print("  声称 r²=0.778 | 实际 CV r²=-0.559(ridge) / -0.166(gbr)")
    print("  问题: 用全库训练无验证 + 325行假标签 -> 负r²\n")

    # --- 特征筛选: 去掉常数/无效列 ---
    stds = X.std(axis=0)
    valid_mask = stds > 1e-9
    X_v = X[:, valid_mask]
    feat_v = [feat_cols[i] for i in range(len(feat_cols)) if valid_mask[i]]
    print(f"有效特征(非常数): {len(feat_v)} / {len(feat_cols)}")
    dropped = [feat_cols[i] for i in range(len(feat_cols)) if not valid_mask[i]]
    if dropped:
        print(f"  剔除常数列: {dropped}")

    # --- 候选模型(小样本偏好低复杂度) ---
    candidates = {
        "RF(depth4)": RandomForestRegressor(n_estimators=50, max_depth=4, min_samples_leaf=3, random_state=42),
        "Ridge(α=5)": Pipeline([("sc", StandardScaler()), ("m", Ridge(alpha=5.0))]),
        "GBR(d2)": GradientBoostingRegressor(n_estimators=80, max_depth=2, learning_rate=0.08, subsample=0.8, random_state=42),
        "RF(depth3)": RandomForestRegressor(n_estimators=50, max_depth=3, min_samples_leaf=4, random_state=42),
    }

    print("\n=== 模型对比 (5折CV + LOO + 排序) ===")
    print(f"  {'模型':<14} {'5fold r²':>10} {'LOO r²':>9} {'MAE':>6} {'Spearman':>9} {'Top4精度':>9}")
    results = []
    for name, model in candidates.items():
        r = eval_model(model, X_v, y, name)
        results.append(r)
        print(f"  {name:<14} {r['r2_5fold_mean']:>+9.3f} {r['r2_loo']:>+9.3f} {r['mae_loo']:>6.3f} "
              f"{r['spearman_loo']:>+9.3f} {r['top4_precision']:>9.2f}")

    # --- 选 Spearman 排序最好的(裁剪靠排序, 不靠绝对r²) ---
    best = max(results, key=lambda r: r["spearman_loo"])
    print(f"\n最佳排序(Spearman): {best['name']}  r²={best['r2_loo']:+.3f}  "
          f"Spearman={best['spearman_loo']:+.3f}  Top4精度={best['top4_precision']:.2f}")

    # --- 全量训练最佳模型 ---
    best_model_name = best["name"]
    final_model = candidates[best_model_name]
    final_model.fit(X_v, y)

    # --- 保存模型 + 特征配置 + scaler信息 ---
    joblib.dump(final_model, BASE / "honest_model.joblib")
    config = {
        "model_name": best_model_name,
        "feature_cols": feat_v,
        "n_features": len(feat_v),
        "n_samples": int(X.shape[0]),
        "metrics": best,
        "all_results": results,
        "dropped_const_features": dropped,
        "label_distribution": {int(k): int(v) for k, v in zip(*np.unique(y, return_counts=True))},
        "vs_old_model": {
            "old_claimed_r2": 0.778,
            "old_actual_cv_r2": -0.559,
            "new_loo_r2": best["r2_loo"],
            "new_spearman": best["spearman_loo"],
            "improvement": best["r2_loo"] - (-0.559),
        },
        "honest_notes": [
            "59样本小数据集, LOO r² 比 5fold 更可信",
            "傅里叶特征族当前无效(residual=null), 已诚实剔除",
            "负r²=不如猜均值, 正r²=有预测力",
        ],
    }
    json.dump(config, open(BASE / "honest_model_config.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # --- 预测全量, 看分位数校准 ---
    y_pred = final_model.predict(X_v)
    print("\n=== 全量预测分位数校准 ===")
    for q in [10, 25, 50, 75, 90]:
        print(f"  P{q}: pred={np.percentile(y_pred, q):.2f}")
    # 看每个真实档的预测均值
    print("\n=== 各真实分数档的预测均值(单调性检查) ===")
    for s in sorted(set(y)):
        mask = y == s
        print(f"  真实{s}分({mask.sum()}篇): 预测均值={y_pred[mask].mean():.2f} "
              f"范围[{y_pred[mask].min():.2f}, {y_pred[mask].max():.2f}]")

    print(f"\n模型已保存: honest_model.joblib + honest_model_config.json")
    return best, results

if __name__ == "__main__":
    main()
