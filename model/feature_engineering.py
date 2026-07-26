#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真信息密度特征工程 (v3 诚实版)
================================
替代旧的表面特征(字数/链接数/标题长度)。从文档原文抽取与"信息价值"
真正相关的特征, 经金标准 59 篇验证。

设计依据(来自对金标准的对比观察):
  5分文档 = 可执行规则 + 根因分层 + 排除清单 + 复用性因果链
  1分文档 = 任务流水账 + 时间戳 + 一次性配置 + 重复信息

特征族(7族 23维):
  A. 结构密度     - 标题层级、列表、表格、代码块的密度(非绝对数)
  B. 因果密度     - 因果关键词、根因分析标记的密度
  C. 可执行性     - 命令/规则/清单/步骤的密度
  D. 独有信息比   - TF-IDF 类: 与全库均值的信息差异度(独有性)
  E. 语义熵       - 词分布的香农熵(信息丰富度 vs 重复)
  F. 时效衰减信号 - 日期密度、过期信号(流水账往往高日期密度)
  G. 残差时序傅里叶 - 系统级上下文(来自工程A的频谱特征)

关键: 所有"密度"都是 [per 1000 chars] 归一化, 消除文档长度偏差。
"""
import re, os, json, math, statistics
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parent
GOLD_CSV = BASE.parent / "lessons-causal-chain-v1.csv"
LOC_JSON = BASE.parent / "_gold_file_locations.json"

# ---------- 中文/英文分词(轻量, 无外部依赖) ----------
# 英文按非字母数字分割, 中文按字符 + 双字词滑动窗口
EN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-\.]*")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

def tokenize(text):
    toks = EN_TOKEN_RE.findall(text)
    # 中文双字词
    cjk = CJK_RE.findall(text)
    for i in range(len(cjk) - 1):
        toks.append(cjk[i] + cjk[i+1])
    toks.extend(cjk)  # 单字也计入(用于熵)
    return [t.lower() for t in toks]

# ---------- 特征族 A: 结构密度 ----------
LIST_RE = re.compile(r"^\s*[-*+] |^\s*\d+\. ", re.M)
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.M)
CODE_FENCE_RE = re.compile(r"```")
HEADING_RE = re.compile(r"^(#{1,6})\s", re.M)

def struct_density_features(text):
    n = max(len(text), 1)
    return {
        "heading_density": len(HEADING_RE.findall(text)) / n * 1000,
        "list_density": len(LIST_RE.findall(text)) / n * 1000,
        "table_density": len(TABLE_ROW_RE.findall(text)) / n * 1000,
        "codeblock_density": (CODE_FENCE_RE.findall(text).count("```") // 2) / n * 1000,
        "heading_depth_max": len(max(HEADING_RE.findall(text), key=len)) if HEADING_RE.search(text) else 0,
    }

# ---------- 特征族 B: 因果密度 ----------
CAUSAL_WORDS = ["根因", "因为", "由于", "导致", "从而", "因此", "所以", "根本原因",
                "关键原因", "深层次", "机制", "chain", "cause", "because", "therefore"]
ROOT_RE = re.compile(r"根因|根本原因|根原因|失败原因|原因分析")

def causal_density_features(text):
    n = max(len(text), 1)
    causal = sum(text.count(w) for w in CAUSAL_WORDS)
    return {
        "causal_kw_density": causal / n * 1000,
        "root_analysis_density": len(ROOT_RE.findall(text)) / n * 1000,
    }

# ---------- 特征族 C: 可执行性 ----------
RULE_RE = re.compile(r"必须|禁止|红线|规则|原则|清单|步骤|检查项|强制|不可|杜绝")
CMD_RE = re.compile(r"```[a-z]*\n|^\s*[$>]|npm |python |git |cd |rm | trash")
LESSON_RE = re.compile(r"教训|经验|启示|红线|钢印|教训总结")

def executability_features(text):
    n = max(len(text), 1)
    return {
        "rule_kw_density": len(RULE_RE.findall(text)) / n * 1000,
        "cmd_density": len(CMD_RE.findall(text)) / n * 1000,
        "lesson_kw_density": len(LESSON_RE.findall(text)) / n * 1000,
    }

# ---------- 特征族 D: 独有信息比 (类 TF-IDF, 需全库 IDF) ----------
class IDFComputer:
    """全库 IDF: 在所有金标准文档上预计算。"""
    def __init__(self):
        self.idf = {}
        self.n_docs = 0
        self.fitted = False
    def fit(self, docs_tokens):
        self.n_docs = len(docs_tokens)
        df = Counter()
        for toks in docs_tokens:
            for t in set(toks):
                df[t] += 1
        self.idf = {t: math.log((1 + self.n_docs) / (1 + d)) + 1 for t, d in df.items()}
        self.fitted = True
    def transform(self, tokens):
        """返回该文档的 (avg_tfidf, max_tfidf, top10_share)。"""
        if not tokens:
            return {"uniq_info_avg": 0, "uniq_info_max": 0, "top_concentration": 0}
        tf = Counter(tokens)
        total = sum(tf.values())
        tfidf_vals = []
        for t, c in tf.items():
            idf = self.idf.get(t, math.log((1 + self.n_docs) / 1) + 1)
            tfidf_vals.append((c / total) * idf)
        tfidf_vals.sort(reverse=True)
        top10 = sum(tfidf_vals[:10]) / max(sum(tfidf_vals), 1e-9)
        return {
            "uniq_info_avg": statistics.mean(tfidf_vals) if tfidf_vals else 0,
            "uniq_info_max": tfidf_vals[0] if tfidf_vals else 0,
            "top_concentration": top10,  # 高=信息集中; 低=平铺流水账
        }

# ---------- 特征族 E: 语义熵 ----------
def semantic_entropy(text):
    toks = tokenize(text)
    if not toks:
        return {"sem_entropy": 0, "lex_diversity": 0, "n_tokens": 0}
    tf = Counter(toks)
    total = sum(tf.values())
    probs = [c / total for c in tf.values()]
    ent = -sum(p * math.log(p + 1e-12) for p in probs)
    return {
        "sem_entropy": ent,
        "lex_diversity": len(tf) / total,  # TTR
        "n_tokens": total,
    }

# ---------- 特征族 F: 时效衰减信号 ----------
DATE_RE = re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}|\d{4}-\d{2}-\d{2}")
TASKID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
FILLER_RE = re.compile(r"执行时间|任务ID|执行结果|状态|Asia/Shanghai|质量评分|分数")

def temporal_decay_features(text):
    n = max(len(text), 1)
    return {
        "date_density": len(DATE_RE.findall(text)) / n * 1000,  # 高=流水账信号
        "taskid_density": len(TASKID_RE.findall(text)) / n * 1000,
        "filler_density": len(FILLER_RE.findall(text)) / n * 1000,
    }

# ---------- 特征族 G: 残差时序傅里叶 (系统级上下文) ----------
# 诚实声明: 残差点数极少(约10), 不做精细频率辨识, 只取频谱形状。
def residual_fourier_features(cycle_residuals):
    """
    cycle_residuals: 数值残差序列(来自工程A的 e 序列)。
    返回频谱形状特征。点数不足时回退到统计特征并标注。
    """
    feats = {"res_n": len(cycle_residuals)}
    rs = [x for x in cycle_residuals if isinstance(x, (int, float))]
    if len(rs) < 4:
        # 点数太少, 不做FFT, 只给统计量 + 标注
        feats.update({
            "res_mean": statistics.mean(rs) if rs else 0,
            "res_std": statistics.pstdev(rs) if len(rs) > 1 else 0,
            "res_spectrum_entropy": 0,
            "res_dominant_ratio": 0,
            "res_lowhigh_ratio": 0,
            "res_trend_slope": 0,
            "res_fft_reliable": 0,  # 0 = 不可靠
        })
        return feats
    # 零均值化 + FFT
    mu = statistics.mean(rs)
    centered = [x - mu for x in rs]
    # 补零到2的幂(短序列用下一幂)
    n2 = 1
    while n2 < len(centered):
        n2 *= 2
    padded = centered + [0.0] * (n2 - len(centered))
    # 离散傅里叶(DFT, 不依赖scipy.fft 以保可移植; 序列短无所谓)
    import cmath
    N = len(padded)
    spectrum = []
    for k in range(N // 2 + 1):
        s = sum(padded[j] * cmath.exp(-2j * math.pi * k * j / N) for j in range(N))
        spectrum.append(abs(s))
    total_energy = sum(x * x for x in spectrum) or 1e-12
    # 主频能量占比
    dom = max(spectrum) ** 2 / total_energy
    # 谱熵
    norm = [x * x / total_energy for x in spectrum]
    sent = -sum(p * math.log(p + 1e-12) for p in norm if p > 0)
    # 低频(前1/3)/高频(后1/3)能量比
    third = max(len(spectrum) // 3, 1)
    low_e = sum(spectrum[:third])
    high_e = sum(spectrum[-third:])
    lowhigh = low_e / (high_e + 1e-12)
    # 趋势: 线性回归斜率
    n = len(rs)
    xs = list(range(n))
    xm = statistics.mean(xs)
    num = sum((xs[i] - xm) * (rs[i] - mu) for i in range(n))
    den = sum((x - xm) ** 2 for x in xs) or 1
    slope = num / den
    feats.update({
        "res_mean": mu,
        "res_std": statistics.pstdev(rs),
        "res_spectrum_entropy": sent,
        "res_dominant_ratio": dom,
        "res_lowhigh_ratio": lowhigh,
        "res_trend_slope": slope,
        "res_fft_reliable": 1 if len(rs) >= 8 else 0,
    })
    return feats

# ---------- 主: 对单文档抽全部特征 ----------
def extract_all(text, idf: IDFComputer, residual_series=None):
    f = {}
    f.update(struct_density_features(text))
    f.update(causal_density_features(text))
    f.update(executability_features(text))
    f.update(idf.transform(tokenize(text)))
    f.update(semantic_entropy(text))
    f.update(temporal_decay_features(text))
    # 傅里叶特征是系统级(所有文档共享同一组), 这里注入
    if residual_series:
        for k, v in residual_series.items():
            f[k] = v
    return f

# ---------- 构建 59 条训练集 ----------
def build_training_set():
    import csv
    # 读金标准
    def read_gold():
        for enc in ["gbk", "gb18030", "utf-8-sig", "utf-8"]:
            try:
                with open(GOLD_CSV, encoding=enc) as f:
                    return list(csv.DictReader(f)), enc
            except Exception:
                continue
        raise RuntimeError("gold csv decode fail")
    gold, enc = read_gold()
    loc = json.load(open(LOC_JSON, encoding="utf-8"))

    # 第一遍: 收集所有文档 token, 拟合 IDF
    docs_tokens = []
    docs_text = {}
    for r in gold:
        fn = r["filename"]
        d = loc.get(fn)
        p = os.path.join(d, fn) if d else None
        txt = open(p, encoding="utf-8").read() if p and os.path.exists(p) else ""
        docs_text[fn] = txt
        docs_tokens.append(tokenize(txt))
    idf = IDFComputer()
    idf.fit(docs_tokens)

    # 残差傅里叶特征(系统级, 一次性算)
    cyc_path = BASE / "residual_cycle_clean.jsonl"
    cycle_residuals = []
    if cyc_path.exists():
        for line in cyc_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rc = json.loads(line)
                e = rc.get("residual")
                if isinstance(e, (int, float)):
                    cycle_residuals.append(e)
            except json.JSONDecodeError:
                continue
    res_feats = residual_fourier_features(cycle_residuals)

    # 第二遍: 抽特征
    rows = []
    for r in gold:
        fn = r["filename"]
        feats = extract_all(docs_text[fn], idf, res_feats)
        feats["filename"] = fn
        feats["title"] = r.get("title", "")
        feats["survival_score"] = int(float(r["survival_score"]))
        rows.append(feats)

    # 写出训练集 CSV + 特征元数据
    feat_cols = [k for k in rows[0].keys() if k not in ("filename", "title", "survival_score")]
    out_csv = BASE / "training_set_v3.csv"
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filename", "title", "survival_score"] + feat_cols)
        for row in rows:
            w.writerow([row["filename"], row["title"], row["survival_score"]]
                       + [row.get(c, 0) for c in feat_cols])

    # 特征清单
    meta = {
        "n_samples": len(rows),
        "n_features": len(feat_cols),
        "feature_cols": feat_cols,
        "label_dist": dict(Counter(r["survival_score"] for r in rows)),
        "residual_points": len(cycle_residuals),
        "idf_fitted_on": len(docs_tokens),
        "encoding_detected": enc,
    }
    json.dump(meta, open(BASE / "feature_meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"训练集构建完成: {len(rows)} 样本 x {len(feat_cols)} 特征 -> {out_csv.name}")
    print(f"标签分布: {meta['label_dist']}")
    print(f"残差点数: {len(cycle_residuals)} (FFT可靠={res_feats['res_fft_reliable']})")
    print(f"特征族: A结构5 + B因果2 + C可执行3 + D独有3 + E语义3 + F时效3 + G傅里叶7 = {5+2+3+3+3+3+7}")
    return rows, feat_cols

if __name__ == "__main__":
    build_training_set()
