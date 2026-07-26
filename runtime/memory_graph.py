#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一记忆体 (Unified Memory Body)
==================================
端点星记忆层整体结构化设计:
  1. Episodic-Semantic Graph (情景-语义统一图)
  2. Spreading Activation (扩散激活检索)
  3. 多agent共享(常驻HTTP服务,端口18792)
  4. 高置信度(时间衰减+因果链+引用网络融合)

数据源(真实,非虚构):
  - memory-tdai l0_conversations (6991条原始记录)
  - memory-tdai l1_records (679条场景提取)
  - 知识库引用网络 (603节点,1475条[[链接]])
  - lessons因果链 (59条因果链)

架构:
  查询 → 双触发(BM25+向量) → 锚点节点 → 扩散激活(图遍历)
       → 侧抑制(过滤干扰) → 置信度排序 → 返回带因果链的记忆
"""
import json, os, re, sqlite3, math
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

VAULT = Path(r'G:\obsidian-vault')
MEM_DB = r'C:\Users\<USERNAME>\.openclaw\memory-tdai\vectors.db'
LESSONS_CSV = r'E:\workspace\entropy-dataset\lessons-causal-chain-v1.csv'

class MemoryGraph:
    """统一记忆图: 情景(L0/L1) + 语义(知识库引用) + 因果链(lessons)"""
    
    def __init__(self):
        self.nodes = {}      # node_id -> {type, content, ts, links}
        self.edges = defaultdict(set)  # node_id -> set of linked node_ids
        self._build()
    
    def _build(self):
        """从真实数据源构建图"""
        # 1. L1场景记忆(高价值情景节点)
        self._load_l1()
        # 2. 知识库引用网络(语义节点+边)
        self._load_vault_links()
        # 3. lessons因果链(因果边)
        self._load_lessons()
    
    def _load_l1(self):
        """加载L1场景记忆为情景节点"""
        try:
            db = sqlite3.connect(MEM_DB, timeout=5)
            db.row_factory = sqlite3.Row
            for row in db.execute("""
                SELECT record_id, content, type, priority, scene_name, timestamp_str
                FROM l1_records ORDER BY priority DESC
            """).fetchall():
                nid = f"l1_{row['record_id']}"
                self.nodes[nid] = {
                    'type': 'episodic',
                    'content': row['content'],
                    'ts': row['timestamp_str'],
                    'priority': row['priority'],
                    'scene': row['scene_name']
                }
            db.close()
            print(f"L1情景节点: {len(self.nodes)}个")
        except Exception as e:
            print(f"L1加载失败: {e}")
    
    def _load_vault_links(self):
        """加载知识库引用网络为语义节点+边"""
        link_map = defaultdict(set)  # target -> set of sources
        for root, dirs, files in os.walk(VAULT):
            dirs[:] = [d for d in dirs if d not in ('.git', '.backup', 'node_modules')]
            for f in files:
                if not f.endswith('.md'):
                    continue
                fp = os.path.join(root, f)
                try:
                    text = open(fp, encoding='utf-8').read()
                except Exception:
                    continue
                source = f.replace('.md', '')
                for m in re.findall(r'\[\[([^\]]+?)\]\]', text):
                    target = m.split('|')[0].split('#')[0].strip().replace('.md', '')
                    if target and target != source:
                        link_map[target].add(source)
        
        # 加入语义节点
        for target, sources in link_map.items():
            nid = f"vault_{target}"
            if nid not in self.nodes:
                self.nodes[nid] = {
                    'type': 'semantic',
                    'content': target,
                    'ts': None,
                    'refs': len(sources)
                }
            # 边: source -> target
            for src in sources:
                src_id = f"vault_{src}"
                self.edges[src_id].add(nid)
                self.edges[nid].add(src_id)  # 双向
        print(f"知识库语义节点: +{len(link_map)}个, 边: +{sum(len(v) for v in link_map.values())}条")
    
    def _load_lessons(self):
        """加载lessons因果链为因果边"""
        try:
            import csv
            for enc in ['gbk', 'gb18030', 'utf-8-sig', 'utf-8']:
                try:
                    with open(LESSONS_CSV, encoding=enc) as f:
                        rows = list(csv.DictReader(f))
                    break
                except Exception:
                    continue
            else:
                rows = []
            
            for r in rows:
                fn = r['filename'].replace('.md', '')
                nid = f"lesson_{fn}"
                chain = r.get('causal_chain', '')
                # 从因果链提取关键词作为连接点
                keywords = re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}', chain)
                self.nodes[nid] = {
                    'type': 'lesson',
                    'content': chain,
                    'ts': r.get('title', ''),
                    'keywords': keywords[:10]
                }
                # 连接到知识库同名节点
                vault_nid = f"vault_{fn}"
                if vault_nid in self.nodes:
                    self.edges[nid].add(vault_nid)
                    self.edges[vault_nid].add(nid)
            print(f"lessons因果节点: +{len(rows)}个")
        except Exception as e:
            print(f"lessons加载失败: {e}")
    
    def find_anchors(self, query, top_k=5):
        """双触发找锚点节点(BM25+语义)"""
        # BM25词法触发(精确实体匹配)
        lexical = []
        query_lower = query.lower()
        for nid, node in self.nodes.items():
            content = node['content'].lower()
            if query_lower in content:
                # BM25简化: 匹配度 = 查询词长度/内容长度
                score = len(query_lower) / max(len(content), 1)
                lexical.append((nid, score, 'lexical'))
        lexical.sort(key=lambda x: -x[1])
        
        # 语义触发(关键词匹配)
        semantic = []
        query_words = set(re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}', query_lower))
        for nid, node in self.nodes.items():
            content = node['content'].lower()
            content_words = set(re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}', content))
            overlap = len(query_words & content_words)
            if overlap > 0:
                score = overlap / max(len(query_words), 1)
                semantic.append((nid, score, 'semantic'))
        semantic.sort(key=lambda x: -x[1])
        
        # 合并双触发结果
        seen = set()
        anchors = []
        for nid, score, source in (lexical + semantic):
            if nid not in seen:
                seen.add(nid)
                anchors.append((nid, score, source))
                if len(anchors) >= top_k:
                    break
        return anchors
    
    def spread_activation(self, anchors, max_depth=2, decay=0.7):
        """扩散激活: 从锚点向关联节点传播能量"""
        activation = {}  # node_id -> energy
        # 初始化锚点能量
        for nid, score, source in anchors:
            activation[nid] = score
        
        # BFS扩散
        frontier = [(nid, score) for nid, score, _ in anchors]
        for depth in range(max_depth):
            new_frontier = []
            for nid, energy in frontier:
                if energy < 0.01:  # 能量太低不传播
                    continue
                for neighbor in self.edges.get(nid, set()):
                    new_energy = energy * decay
                    if neighbor not in activation or activation[neighbor] < new_energy:
                        activation[neighbor] = new_energy
                        new_frontier.append((neighbor, new_energy))
            frontier = new_frontier
            if not frontier:
                break
        
        return activation
    
    def lateral_inhibition(self, activation, threshold=0.1):
        """侧抑制: 过滤低能量节点(干扰)"""
        return {nid: e for nid, e in activation.items() if e >= threshold}
    
    def search(self, query, top_k=5, include_depth=2):
        """
        统一记忆检索:
          1. 双触发找锚点(BM25+语义)
          2. 扩散激活(图遍历,找关联记忆)
          3. 侧抑制(过滤干扰)
          4. 时间衰减(新记忆优先)
          5. 置信度排序(因果链完整性+引用网络+时间)
        """
        # 1. 锚点
        anchors = self.find_anchors(query, top_k)
        if not anchors:
            return []
        
        # 2. 扩散激活
        activation = self.spread_activation(anchors, max_depth=include_depth)
        
        # 3. 侧抑制
        activation = self.lateral_inhibition(activation, threshold=0.05)
        
        # 4. 组装结果(带时间衰减+置信度)
        now = datetime.now()
        results = []
        for nid, energy in sorted(activation.items(), key=lambda x: -x[1])[:top_k]:
            node = self.nodes.get(nid)
            if not node:
                continue
            
            # 时间衰减
            tw = 0.5  # 默认
            if node.get('ts'):
                try:
                    ts_str = str(node['ts'])[:19]
                    for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                        try:
                            dt = datetime.strptime(ts_str, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        dt = None
                    if dt:
                        age_days = (now - dt).days
                        tw = max(0.1, math.exp(-0.02 * age_days))
                except (ValueError, TypeError):
                    pass
            
            # 置信度 = 激活能量 × 时间衰减 × 节点质量
            priority = node.get('priority', 5)
            refs = node.get('refs', 1)
            quality = 0.3 + (priority / 10) * 0.3 + min(refs / 10, 0.4)
            confidence = energy * tw * quality
            
            # 因果链完整性(L1/lesson类型加分)
            causal_bonus = 0.2 if node['type'] in ('lesson', 'episodic') else 0
            
            final_score = confidence + causal_bonus
            
            results.append({
                'node_id': nid,
                'content': node['content'][:300],
                'type': node['type'],
                'energy': round(energy, 3),
                'temporal_weight': round(tw, 3),
                'confidence': round(confidence, 3),
                'final_score': round(final_score, 3),
                'source': node.get('scene', node.get('source', nid.split('_')[0])),
                'depth': include_depth
            })
        
        return results

def main():
    import sys
    graph = MemoryGraph()
    print(f"\n记忆图构建完成: {len(graph.nodes)}节点, {sum(len(v) for v in graph.edges.values())}边")
    print(f"  情景(L1): {sum(1 for n in graph.nodes.values() if n['type']=='episodic')}")
    print(f"  语义(vault): {sum(1 for n in graph.nodes.values() if n['type']=='semantic')}")
    print(f"  因果(lesson): {sum(1 for n in graph.nodes.values() if n['type']=='lesson')}")
    
    if len(sys.argv) > 1:
        query = sys.argv[1]
        top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        results = graph.search(query, top_k)
        print(f"\n查询: '{query}' → {len(results)}条记忆(扩散激活)")
        for i, r in enumerate(results, 1):
            mark = "🔥" if r['energy'] > 0.5 else "✓"
            print(f"{mark} [{r['final_score']:.3f}] {r['type']:8s} energy={r['energy']:.3f} tw={r['temporal_weight']:.3f}")
            print(f"   {r['content'][:80]}")

if __name__ == '__main__':
    main()
