#!/usr/bin/env python3
"""密度实验 cron runner (v5模型版)
=================================
替代旧的 S·λ·R·C 四因子评分(全部discard问题)。
使用 v5 诚实模型(LOO r²=0.589)评分。
每次运行：扫描最近6h变更文件 → v5评分 → 记录残差 → 检查回证到期 → LLM回证
"""
import json, os, re, sys, traceback
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np

# 编码修复
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 路径配置（按实际环境修改）
DATA_DIR = Path(os.environ.get('ENTROPY_DATA_DIR', r'[WORKSPACE]/density-experiment'))
VAULT_PATH = Path(os.environ.get('ENTROPY_VAULT_PATH', r'[KNOWLEDGE_BASE]'))
V3_DIR = Path(os.environ.get('ENTROPY_V3_DIR', r'[WORKSPACE]/entropy-dataset\v3_honest'))
RESIDUAL_FILE = DATA_DIR / 'residual-series-v5.jsonl'
SUMMARY_FILE = DATA_DIR / 'residual-summary-v5.jsonl'

def load_jsonl(path):
    if not path.exists():
        return []
    data = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data

def save_jsonl(path, records):
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

def load_v5_model():
    """加载v5模型和特征工程模块"""
    sys.path.insert(0, str(V3_DIR))
    import joblib
    from feature_engineering import tokenize, extract_all
    from objective_annotate import extract_behavior_signals
    model = joblib.load(str(V3_DIR / 'honest_model_v5.joblib'))
    config = json.load(open(str(V3_DIR / 'honest_model_v5_config.json'), encoding='utf-8'))
    return model, config

def extract_features_v5(content, filepath):
    """从段落内容提取v5模型需要的特征"""
    words = content.split()
    n_words = len(words)
    if n_words == 0:
        return None
    
    lines = content.split('\n')
    n_lines = len(lines)
    headings = len(re.findall(r'^#+\s', content, re.MULTILINE))
    list_items = len(re.findall(r'^\s*[-*+]\s|^\s*\d+\.\s', content, re.MULTILINE))
    code_blocks = max(0, len(re.findall(r'```', content)) // 2)
    tables = len(re.findall(r'\|.*\|.*\|', content))
    
    # 行为信号
    from objective_annotate import extract_behavior_signals
    signals = extract_behavior_signals(content)
    F = signals.get('F_failure', 0)
    R_sig = signals.get('R_response', 0)
    C_sig = signals.get('C_cognition', 0)
    I_sig = signals.get('I_integrity', 0)
    
    # 密度特征 (per 1000 words)
    causal_kw = len(re.findall(r'因此|所以|导致|影响|结果|由于|故而|根因|因果|because|therefore|cause', content, re.IGNORECASE))
    root_kw = len(re.findall(r'根本|root.?cause|本质|fundamental', content, re.IGNORECASE))
    rule_kw = len(re.findall(r'红线|铁律|必须|禁止|不可|规则|rule|must|never', content, re.IGNORECASE))
    cmd_kw = len(re.findall(r'\\\\\w+|scp |ssh |curl |python |npm |git ', content, re.IGNORECASE))
    lesson_kw = len(re.findall(r'教训|L-[A-Z]+|lesson|经验', content, re.IGNORECASE))
    
    # 词汇特征
    uniq_words = set(w.lower() for w in words if len(w) > 2)
    uniq_info_avg = len(uniq_words) / n_words * 100
    uniq_info_max = 0
    
    freq = {}
    for w in words:
        wl = w.lower()
        freq[wl] = freq.get(wl, 0) + 1
    top_concentration = max(freq.values()) / n_words if freq else 0
    
    sem_entropy = len(uniq_words) / n_words
    
    # 元数据特征
    n_tok = len(tokenize(content)) if 'tokenize' in dir() else n_words
    date_d = len(re.findall(r'\d{4}[-/]\d{2}[-/]\d{2}', content)) / n_words * 1000
    taskid_d = len(re.findall(r'[A-Z]+-\d+|task_\d+|PR #\d+', content)) / n_words * 1000
    filler_d = len(re.findall(r'^---$|^\*\*\*$', content, re.MULTILINE)) / max(n_lines, 1) * 100
    
    # 23维特征向量（与v5模型匹配）
    return [
        headings / n_lines * 1000 if n_lines else 0,   # heading_density
        list_items / n_lines * 1000 if n_lines else 0,   # list_density
        tables / n_lines * 1000 if n_lines else 0,     # table_density
        code_blocks / n_lines * 1000 if n_lines else 0, # codeblock_density
        1 if headings > 0 else 0,                       # heading_depth_max
        causal_kw / n_words * 100,                     # causal_kw_density
        root_kw / n_words * 100,                       # root_analysis_density
        rule_kw / n_words * 100,                       # rule_kw_density
        cmd_kw / n_words * 100,                        # cmd_density
        lesson_kw / n_words * 100,                     # lesson_kw_density
        uniq_info_avg,                                  # uniq_info_avg
        uniq_info_max,                                  # uniq_info_max
        top_concentration,                              # top_concentration
        sem_entropy,                                    # sem_entropy
        sem_entropy,                                    # lex_diversity (简化)
        n_tok,                                          # n_tokens
        date_d,                                         # date_density
        taskid_d,                                       # taskid_density
        filler_d,                                       # filler_density
        F, R_sig, C_sig, I_sig                         # 行为信号
    ]

def scan_recent_files(cutoff_hours=6):
    """扫描最近N小时修改的md文件"""
    cutoff = datetime.now() - timedelta(hours=cutoff_hours)
    files = []
    for root, dirs, filenames in os.walk(str(VAULT_PATH)):
        dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', '.backup', '.obsidian')]
        for fn in filenames:
            if fn.endswith('.md'):
                fp = os.path.join(root, fn)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(fp))
                    if mtime > cutoff:
                        files.append(fp)
                except OSError:
                    continue
    return files

def run_cycle():
    """执行一轮密度裁决"""
    print(f"=== 密度实验 v5 第 {datetime.now().isoformat()} ===")
    
    # 加载模型
    model, config = load_v5_model()
    print(f"v5模型: r2={config['metrics']['r2_loo']:.3f}, Spearman={config['metrics']['spearman_loo']:.3f}")
    
    # 加载历史
    residuals = load_jsonl(RESIDUAL_FILE)
    cycle = len(residuals) + 1
    print(f"历史残差: {len(residuals)} 条")
    
    # 扫描文件
    files = scan_recent_files(6)
    print(f"最近6h变更: {len(files)} 个文件")
    
    # 处理文件
    new_records = []
    decisions = {'keep': 0, 'observe': 0, 'prune': 0, 'source_protect': 0, 'constitution': 0, 'error': 0}
    
    for fp in files:
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            continue
        
        if len(content) < 50:
            continue
        
        # v5模型评分
        try:
            feats = extract_features_v5(content, fp)
            if feats is None:
                decisions['error'] += 1
                continue
            feat_arr = np.array(feats).reshape(1, -1)
            score = float(model.predict(feat_arr)[0])
            score = max(0, score)
        except Exception as e:
            decisions['error'] += 1
            continue
        
        # 裁决
        p20 = config.get('p20_threshold', 2.06)
        if score >= p20:
            decision = 'keep'
        elif score >= 1.5:
            decision = 'observe'
        else:
            decision = 'prune'
        
        decisions[decision] += 1
        
        record = {
            'cycle': cycle,
            'timestamp': datetime.now().isoformat(),
            'file_path': fp,
            'file_name': os.path.basename(fp),
            'score': round(score, 3),
            'decision': decision,
            'features_summary': {
                'F': feats[19], 'R': feats[20], 'C': feats[21], 'I': feats[22],
                'headings': feats[0], 'lists': feats[1], 'code': feats[3],
                'causal_kw': feats[5], 'rule_kw': feats[7], 'lesson_kw': feats[9],
                'filler': feats[18]
            },
            'u_observed': None,
            'u_source': None,
            'residual': None,
            'validation_status': 'pending',
            'validation_deadline': cycle + 3
        }
        new_records.append(record)
    
    # 检查到期回证
    validated = 0
    pending = 0
    for rec in residuals:
        if rec.get('validation_status') == 'pending' and cycle >= rec.get('validation_deadline', 999):
            pending += 1
        elif rec.get('validation_status') == 'validated':
            validated += 1
    
    # 保存
    all_residuals = residuals + new_records
    save_jsonl(RESIDUAL_FILE, all_residuals)
    
    # 摘要
    summary = {
        'cycle': cycle,
        'timestamp': datetime.now().isoformat(),
        'files_scanned': len(files),
        'new_records': len(new_records),
        'decisions': decisions,
        'total_residuals': len(all_residuals),
        'validated': validated,
        'pending_validation': pending,
        'avg_score': round(np.mean([r['score'] for r in new_records]), 3) if new_records else 0
    }
    
    summaries = load_jsonl(SUMMARY_FILE)
    summaries.append(summary)
    if len(summaries) > 50:
        summaries = summaries[-50:]
    save_jsonl(SUMMARY_FILE, summaries)
    
    # 打印摘要
    print(f"裁决: {json.dumps(decisions)}")
    print(f"平均分: {summary['avg_score']}")
    print(f"总残差: {summary['total_residuals']} (已验证: {validated}, 待回证: {pending})")
    
    return summary

if __name__ == '__main__':
    try:
        run_cycle()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
