#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反熵增模型部署配置 (v5/v7 双模型策略)
=========================================
v5: 关键词特征 → 端点星知识库/MEMORY.md压缩 (当前领域最优)
v7: embedding特征 → 泛化场景/新领域 (换领域不需要改代码)
等数据积累到200+后重新评估v6/v7

模型文件:
  v5: E:\workspace\entropy-dataset\v3_honest\honest_model_v5.joblib
  v7: E:\workspace\entropy-dataset\v3_honest\honest_model_v7.joblib + v7_embedding_transformer.joblib
"""
import json, os, sys
from pathlib import Path

DEPLOYMENT_CONFIG = {
    "version": "2026-07-25",
    "strategy": "dual_model_deployment",
    "models": {
        "v5": {
            "name": "honest_model_v5",
            "algorithm": "GradientBoostingRegressor",
            "features": "23维关键词特征(结构密度/因果密度/可执行性/时间衰减/行为信号)",
            "metrics": {"r2": 0.589, "spearman": 0.767},
            "use_for": [
                "MEMORY.md压缩(端点星知识库,当前领域)",
                "知识库文档裁剪(端点星知识库)",
                "心跳裁剪(每6h)",
                "残差评分(密度预测)",
            ],
            "path": r"E:\workspace\entropy-dataset\v3_honest\honest_model_v5.joblib",
            "config_path": r"E:\workspace\entropy-dataset\v3_honest\honest_model_v5_config.json",
            "label_source": "59人工金标准 + 221条AI规则标注(行为信号)",
        },
        "v7": {
            "name": "honest_model_v7",
            "algorithm": "GradientBoostingRegressor",
            "features": "104维embedding(TF-IDF 100维 + 统计4维)",
            "metrics": {"r2": 0.524, "spearman": 0.747},
            "use_for": [
                "泛化场景(新领域/新文档类型)",
                "换领域部署(不需要改代码,重新TF-IDF拟合)",
                "高价值文档预测(不再被低估)",
            ],
            "path": r"E:\workspace\entropy-dataset\v3_honest\honest_model_v7.joblib",
            "transformer_path": r"E:\workspace\entropy-dataset\v3_honest\v7_embedding_transformer.joblib",
            "config_path": r"E:\workspace\entropy-dataset\v3_honest\honest_model_v7_config.json",
            "label_source": "59人工金标准 + 221条AI规则标注",
        },
    },
    "deployment_rules": [
        {
            "rule": "MEMORY.md压缩",
            "model": "v5",
            "reason": "刚验证成功(8333→7779 tokens,宪法级信息完整)",
        },
        {
            "rule": "端点星知识库裁剪",
            "model": "v5",
            "reason": "r²=0.589最高,23维关键词最精准",
        },
        {
            "rule": "新领域/泛化场景",
            "model": "v7",
            "reason": "embedding泛化强,换领域不需要改代码",
        },
        {
            "rule": "高价值文档预测",
            "model": "v7",
            "reason": "高价值不再被低估(5分→3.84 vs v5的3.15)",
        },
    ],
    "future_evaluation": {
        "v6": {
            "condition": "真实回证数据积累到200+条匹配原文",
            "action": "重新评估v6(真实回证标签)是否超越v5",
            "expected_timeline": "2-3周(回证每天~10条)",
        },
        "v8": {
            "condition": "embedding模型升级到LLM(如qwen3.6-4b的2560维embedding)",
            "action": "用LLM embedding替代TF-IDF,看泛化效果是否进一步提升",
            "expected_timeline": "1-2个月(观自在GPU就绪后)",
        },
    },
    "honest_notes": [
        "v5不是最优模型,只是当前最优。等真实回证数据积累到200+后重新评估。",
        "v7 r²=0.524略低于v5的0.589,但高价值不再被低估(5分→3.84 vs v5的3.15)。",
        "双模型共存不是冗余,是分工: v5管当前领域,v7管泛化场景。",
    ],
}


def save_config():
    path = Path(r'E:\workspace\entropy-dataset\v3_honest\model_deployment.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(DEPLOYMENT_CONFIG, f, ensure_ascii=False, indent=2)
    print(f'✓ 部署配置已保存: {path}')
    print(f'  v5: {DEPLOYMENT_CONFIG["models"]["v5"]["path"]}')
    print(f'  v7: {DEPLOYMENT_CONFIG["models"]["v7"]["path"]}')
    print()
    print('部署规则:')
    for rule in DEPLOYMENT_CONFIG['deployment_rules']:
        print(f'  {rule["rule"]}: {rule["model"]} ({rule["reason"]})')


def load_config():
    """加载部署配置(供心跳/裁剪用)"""
    path = Path(r'E:\workspace\entropy-dataset\v3_honest\model_deployment.json')
    if not path.exists():
        save_config()
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def get_model_for_task(task):
    """根据任务类型选择模型"""
    config = load_config()
    for rule in config['deployment_rules']:
        if rule['rule'] in task or task in rule['rule']:
            model_name = rule['model']
            model_info = config['models'][model_name]
            return model_info['path'], model_info.get('transformer_path'), model_name
    # 默认v5
    return config['models']['v5']['path'], None, 'v5'


if __name__ == '__main__':
    save_config()
    print()
    print('测试: MEMORY.md压缩用哪个模型?')
    path, transformer, model = get_model_for_task('MEMORY.md压缩')
    print(f'  → {model} ({path})')
    print()
    print('测试: 量子计算文档裁剪用哪个模型?')
    path, transformer, model = get_model_for_task('量子计算')
    print(f'  → {model} ({path})')
