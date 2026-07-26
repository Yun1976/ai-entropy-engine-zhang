#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
记忆检索增强层 (Memory Retrieval Enhancer)
=============================================
基于 SYNAPSE 论文改进, 在 memory-tdai 现有检索之上增加:
  1. Temporal Decay (时间衰减) — 新记忆优先,旧记忆保留但权重降低
  2. Confidence Gating (置信度门控) — 低置信度结果标记为"不确定",防幻觉
  3. 增强排序 — similarity × time_decay, 输出带置信度

用法:
  enhancer = MemoryEnhancer()
  results = enhancer.search("反熵增残差傅里叶", limit=5)
  # 返回: [{content, score, confidence, age_days, temporal_weight, source}]
"""
import json, math, os, sqlite3, sys

# Windows 终端默认 GBK 编码，输出含非 GBK 字符(如 ² · 等)的 JSON 会触发
# UnicodeEncodeError。强制 stdout/stderr 为 UTF-8，给 OpenClaw/Hermes 的
# exec 工具提供稳定可解析的 JSON。errors='replace' 仅作极端兜底。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from datetime import datetime, timedelta

class MemoryEnhancer:
    """在现有 memory-tdai 检索之上加时间衰减+置信度"""
    
    # 时间衰减参数(参考SYNAPSE的temporal decay)
    # 7天内: 权重1.0, 30天: 0.7, 90天: 0.4, 365天: 0.1
    TIME_DECAY_LAMBDA = 0.02  # λ=0.02 → 35天半衰期
    
    # 置信度阈值(低于此标记为uncertain)
    CONFIDENCE_THRESHOLD = 0.15
    
    def __init__(self, memory_db_path=None):
        if memory_db_path is None:
            memory_db_path = r'C:\Users\<USERNAME>\.openclaw\memory-tdai\vectors.db'
        self.db_path = memory_db_path
        self._conn = None
    
    def _get_conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, timeout=5)
            self._conn.row_factory = sqlite3.Row
        return self._conn
    
    def temporal_weight(self, ts_str):
        """计算时间衰减权重 (1.0 ~ 0.1)"""
        if not ts_str:
            return 0.5  # 无时间戳给中位数
        try:
            # 支持多种时间格式
            for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                try:
                    dt = datetime.strptime(str(ts_str)[:19], fmt)
                    break
                except ValueError:
                    continue
            else:
                return 0.5
            age_days = (datetime.now() - dt).days
            # 指数衰减: e^(-λ * days), 最低0.1
            w = max(0.1, math.exp(-self.TIME_DECAY_LAMBDA * age_days))
            return round(w, 3)
        except (ValueError, TypeError):
            return 0.5
    
    def compute_confidence(self, similarity_score, n_results, temporal_w):
        """计算综合置信度 (0.0 ~ 1.0)
        基于: 相似度分数 + 结果数 + 时间衰减
        """
        # 相似度本身占60%, 时间新鲜度占25%, 结果丰富度占15%
        base = similarity_score * 0.6
        recency = temporal_w * 0.25
        abundance = min(1.0, n_results / 5) * 0.15
        conf = base + recency + abundance
        return round(min(1.0, conf), 3)
    
    def search(self, query, limit=5, min_confidence=None):
        """
        增强检索: 向量相似度 + 时间衰减 + 置信度
        
        流程:
          1. 从memory-tdai vectors.db查语义相似记忆
          2. 计算时间衰减权重
          3. 计算综合置信度
          4. 按 confidence * temporal_weight 排序
          5. 低于CONFIDENCE_THRESHOLD的标记为uncertain
        
        返回: [{content, score, confidence, age_days, temporal_weight, source, uncertain}]
        """
        conn = self._get_conn()
        # 查memory-tdai的实际表结构
        results = []
        try:
            # L1层: 提取的场景记忆(高价值,优先)
            cursor = conn.execute("""
                SELECT content, type, priority, scene_name, timestamp_str 
                FROM l1_records 
                WHERE content LIKE ?
                ORDER BY priority DESC, timestamp_str DESC
                LIMIT ?
            """, (f'%{query}%', limit * 2))
            
            for row in cursor.fetchall():
                results.append({
                    'content': row['content'],
                    'score': 0.8,  # L1提取层=高价值
                    'source': 'l1_episodic',
                    'type': row['type'],
                    'priority': row['priority'],
                    'timestamp': row['timestamp_str']
                })
            
            # L0层: 原始会话记录(补充,低价值但覆盖广)
            if len(results) < limit * 2:
                cursor = conn.execute("""
                    SELECT message_text, role, recorded_at
                    FROM l0_conversations 
                    WHERE message_text LIKE ?
                    ORDER BY recorded_at DESC
                    LIMIT ?
                """, (f'%{query}%', limit * 2))
                
                for row in cursor.fetchall():
                    results.append({
                        'content': row['message_text'],
                        'score': 0.4,  # L0原始层=低价值
                        'source': 'l0_conversation',
                        'role': row['role'],
                        'timestamp': row['recorded_at']
                    })
        except sqlite3.OperationalError as e:
            print(f'查询错误: {e}')
        
        if not results:
            return []
        
        # 计算时间衰减和置信度
        enhanced = []
        for r in results[:limit]:
            # 尝试从content提取时间戳
            ts = self._extract_timestamp(r['content'])
            tw = self.temporal_weight(ts)
            conf = self.compute_confidence(r['score'], len(results), tw)
            
            # 综合排序分: confidence × temporal_weight
            final_score = round(conf * tw, 3)
            
            enhanced.append({
                'content': r['content'][:500],
                'score': r['score'],
                'confidence': conf,
                'temporal_weight': tw,
                'age_days': self._age_days(ts),
                'final_score': final_score,
                'uncertain': conf < (min_confidence or self.CONFIDENCE_THRESHOLD),
                'source': r['source']
            })
        
        # 按综合分排序
        enhanced.sort(key=lambda x: -x['final_score'])
        return enhanced[:limit]
    
    def _extract_timestamp(self, content):
        """从memory内容提取时间戳"""
        # 尝试从常见格式提取
        import re
        patterns = [
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})',
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',
            r'(\d{4}-\d{2}-\d{2})',
        ]
        for p in patterns:
            m = re.search(p, content)
            if m:
                return m.group(1)
        return None
    
    def _age_days(self, ts_str):
        if not ts_str:
            return -1
        try:
            for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                try:
                    dt = datetime.strptime(str(ts_str)[:19], fmt)
                    return (datetime.now() - dt).days
                except ValueError:
                    continue
        except (ValueError, TypeError):
            pass
        return -1

# ============================================================
# 命令行接口
# ============================================================
def main():
    import sys
    if len(sys.argv) < 2:
        print("用法: memory_enhancer.py <query> [limit]")
        print("示例: memory_enhancer.py 反熵增残差 5")
        return
    
    query = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    
    enhancer = MemoryEnhancer()
    results = enhancer.search(query, limit)
    
    if not results:
        print(f"没有找到与 '{query}' 相关的记忆")
        return
    
    print(f"找到 {len(results)} 条记忆(按综合分排序):")
    print()
    for i, r in enumerate(results, 1):
        mark = "⚠️" if r['uncertain'] else "✓"
        print(f"{mark} [{r['final_score']:.3f}] 置信度={r['confidence']:.3f} 时间权重={r['temporal_weight']:.3f} 天数={r['age_days']}d")
        print(f"   {r['content'][:120]}")
        print()

def cli_json():
    """给OpenClaw/Hermes的exec工具用的JSON输出模式"""
    import sys
    if len(sys.argv) < 3 or sys.argv[1] != '--json':
        return False
    query = sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    enhancer = MemoryEnhancer()
    results = enhancer.search(query, limit)
    output = {
        'ok': True,
        'service': 'memory_enhancer',
        'query': query,
        'count': len(results),
        'memories': results
    }
    print(json.dumps(output, ensure_ascii=False))
    return True

if __name__ == '__main__':
    if not cli_json():
        main()
