#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一记忆体服务 (Unified Memory Body Service)
==============================================
基于 memory_graph.py 的 Episodic-Semantic Graph,
提供 HTTP API 给所有 facet (OpenClaw/Hermes/ZCode/CC) 调用。

端口: 18792 (与memory_service.py的18791区分, 这个是图检索版)
用法:
  python memory_body_service.py          # 启动HTTP服务
  python memory_body_service.py --once "query"  # 单次查询测试
"""
import json, sys, os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory_graph import MemoryGraph

PORT = 18792
graph = None  # 懒加载

def get_graph():
    global graph
    if graph is None:
        graph = MemoryGraph()
    return graph

class MemoryBodyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
    
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        
        if parsed.path == '/health':
            g = get_graph()
            self._send_json({
                'ok': True,
                'service': 'memory_body_service',
                'port': PORT,
                'nodes': len(g.nodes),
                'edges': sum(len(v) for v in g.edges.values())
            })
            return
        
        if parsed.path == '/graph':
            g = get_graph()
            types = {}
            for n in g.nodes.values():
                t = n['type']
                types[t] = types.get(t, 0) + 1
            self._send_json({
                'ok': True,
                'nodes': len(g.nodes),
                'edges': sum(len(v) for v in g.edges.values()),
                'types': types
            })
            return
        
        if parsed.path == '/search':
            query = params.get('q', [''])[0]
            limit = int(params.get('limit', ['5'])[0])
            depth = int(params.get('depth', ['2'])[0])
            
            if not query:
                self._send_json({'error': 'missing q parameter'}, 400)
                return
            
            g = get_graph()
            results = g.search(query, limit, depth)
            
            memories = []
            for r in results:
                memories.append({
                    'content': r['content'],
                    'score': r['final_score'],
                    'confidence': r['confidence'],
                    'temporal_weight': r['temporal_weight'],
                    'energy': r['energy'],
                    'type': r['type'],
                    'source': r['source'],
                    'depth': r['depth']
                })
            
            self._send_json({
                'ok': True,
                'query': query,
                'count': len(memories),
                'memories': memories,
                'service': 'memory_body_v1',
                'graph': {
                    'nodes': len(g.nodes),
                    'edges': sum(len(v) for v in g.edges.values())
                }
            })
            return
        
        self._send_json({'error': 'unknown path'}, 404)

def run_service():
    server = HTTPServer(('127.0.0.1', PORT), MemoryBodyHandler)
    print(f"统一记忆体服务已启动: http://127.0.0.1:{PORT}")
    print(f"健康检查: http://127.0.0.1:{PORT}/health")
    print(f"图统计: http://127.0.0.1:{PORT}/graph")
    print(f"检索: http://127.0.0.1:{PORT}/search?q=关键词&limit=5&depth=2")
    server.serve_forever()

if __name__ == '__main__':
    if '--once' in sys.argv:
        query_idx = sys.argv.index('--once') + 1
        query = sys.argv[query_idx] if query_idx < len(sys.argv) else '反熵增'
        limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 5
        g = get_graph()
        results = g.search(query, limit)
        print(json.dumps({'ok': True, 'count': len(results), 'memories': results}, 
                        ensure_ascii=False, indent=2))
    else:
        run_service()
