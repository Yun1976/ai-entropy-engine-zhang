#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双脑记忆检索 (Dual-Brain Memory Retrieval)
============================================
端点星检索真实记忆(memory_graph) → 观自在组织语言(本地LLM)
记忆在端点星,推理在观自在。模型不靠权重记忆,靠检索增强。

流程:
  1. 端点星 memory_graph 检索真实记忆(1341节点图遍历)
  2. 检索结果发送给观自在的 Ollama(duanjianxing-memory模型)
  3. 模型基于真实记忆组织回答(不编造)
  4. 返回带溯源的回答

用法:
  python dual_brain_memory.py "反熵增系统是什么"
"""
import json, sys, os, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GUANZIZAI_OLLAMA = "http://<GUANZIZAI_IP>:11434"
MEMORY_MODEL = "gemma4:12b"

def retrieve_from_graph(query, limit=5):
    """端点星: 从memory_graph检索真实记忆"""
    from memory_graph import MemoryGraph
    graph = MemoryGraph()
    results = graph.search(query, limit)
    return results

def generate_with_context(query, retrieved_memories):
    """观自在: 基于检索到的真实记忆组织回答"""
    # 构建上下文(真实记忆)
    context_parts = []
    for i, m in enumerate(retrieved_memories, 1):
        context_parts.append(f"[记忆{i}] 类型:{m['type']} 置信度:{m['confidence']:.2f}\n{m['content']}")
    context = "\n\n".join(context_parts)
    
    prompt = f"""基于以下真实记忆回答问题。只使用记忆中的信息,不要编造。如果记忆中没有相关信息,直接说"记忆中没有相关信息"。

真实记忆:
{context}

问题: {query}

回答:"""
    
    try:
        resp = requests.post(
            f"{GUANZIZAI_OLLAMA}/api/generate",
            json={
                "model": MEMORY_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3}  # 低温度=少编造
            },
            timeout=60
        )
        d = resp.json()
        answer = d.get("response", "")
        # 去掉think标签
        if "</think>" in answer:
            answer = answer.split("</think>")[-1].strip()
        return {
            "answer": answer,
            "tokens": d.get("eval_count", 0),
            "duration_s": round(d.get("total_duration", 0) / 1e9, 1),
            "model": MEMORY_MODEL
        }
    except Exception as e:
        return {"answer": f"(观自在推理失败: {e})", "tokens": 0, "duration_s": 0}

def search(query, limit=5):
    """双脑记忆检索: 端点星检索 + 观自在组织"""
    # 1. 端点星检索真实记忆
    memories = retrieve_from_graph(query, limit)
    if not memories:
        return {
            "query": query,
            "answer": "记忆图中没有找到相关记忆",
            "retrieved": 0,
            "source": "memory_graph(空)"
        }
    
    # 2. 观自在组织回答
    result = generate_with_context(query, memories)
    
    return {
        "query": query,
        "answer": result["answer"],
        "retrieved": len(memories),
        "retrieval_sources": [
            {"type": m["type"], "confidence": m["confidence"], "content": m["content"][:80]}
            for m in memories
        ],
        "inference": {
            "model": result["model"],
            "tokens": result["tokens"],
            "duration_s": result["duration_s"]
        },
        "architecture": "dual_brain(endpoint_star_retrieve + guanzizai_generate)"
    }

if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "反熵增系统"
    result = search(query)
    print(json.dumps(result, ensure_ascii=False, indent=2))
