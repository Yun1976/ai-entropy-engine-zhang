#!/usr/bin/env python3
"""
端点星 Self-Harness 弱点挖掘器 (v2)
从 Hermes state.db 自动提取失败轨迹，聚类为结构化失败证据。

改进 (2026-07-25):
  1. days_back CLI 参数化 (--days 7/30/90)
  2. execute_code+terminal approval_blocked 去重 (同一事件只计一次)
  3. state.db 路径 fallback (hermes → endpoint_star)
  4. 失败时写 state.db 模块状态 (交叉验证可发现)

三阶段对应 Self-Harness：
  Stage 1 (本脚本): 弱点挖掘 — 从会话历史提取失败信号
  Stage 2 (cron LLM): Harness提案 — 基于失败证据生成 lesson 草稿
  Stage 3 (人工审核): 提案验证 — 审核后才晋升到 lessons/

输出: JSON 格式的结构化失败证据，供 LLM 二次处理生成 lesson 草稿。
"""

import sqlite3
import json
import os
import re
import sys
import argparse
from datetime import datetime, timedelta
from collections import defaultdict

# 数据库路径 (fallback 顺序)
DB_PATHS = [
    os.path.expanduser("~/AppData/Local/hermes/state.db"),
    r"E:\workspace\anti-entropy-runtime\state.db",
]
OUTPUT_DIR = os.path.expanduser("~/AppData/Local/hermes/weakness-reports")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_db():
    """连接数据库 (带 fallback)"""
    for path in DB_PATHS:
        if os.path.exists(path):
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn, path
    raise FileNotFoundError(f"state.db 不存在于: {DB_PATHS}")


# ============================================================
# Signal 1: 用户纠正消息
# ============================================================
USER_CORRECTION_PATTERNS = [
    r'不对', r'错了', r'不是这', r'没有', r'还没',
    r'失败', r'报错', r'不行', r'没做到', r'为什么没',
    r'怎么没', r'不是说', r'应该先', r'别.*了',
    r'怎么还', r'为什么还', r'又.*了',
]

EXCLUDE_PATTERNS = [
    r'\[Replying', r'\[OUT-OF-BAND',
    r'^https?://',
]

SESSION_CONTEXT_WINDOW = 3


def mine_user_corrections(conn, days_back=30):
    """提取用户纠正消息及其上下文。"""
    cur = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days_back)).timestamp()

    cur.execute("""
        SELECT m.id, m.session_id, m.content, m.timestamp,
               s.title, s.source, s.model
        FROM messages m
        JOIN sessions s ON m.session_id = s.id
        WHERE m.role = 'user'
          AND m.timestamp > ?
          AND m.content IS NOT NULL
        ORDER BY m.timestamp
    """, (cutoff,))

    corrections = []
    for row in cur.fetchall():
        content = row['content'] or ''
        if any(re.search(p, content) for p in EXCLUDE_PATTERNS):
            continue
        matched = [p for p in USER_CORRECTION_PATTERNS if re.search(p, content)]
        if not matched:
            continue
        if len(content) > 500:
            continue

        corrections.append({
            'type': 'user_correction',
            'message_id': row['id'],
            'session_id': row['session_id'],
            'session_title': row['title'],
            'source': row['source'],
            'timestamp': datetime.fromtimestamp(row['timestamp']).isoformat(),
            'content': content.strip(),
            'matched_patterns': matched,
        })

    return corrections


# ============================================================
# Signal 2: 工具失败
# 改进: approval_blocked 按 (session, error_type) 去重，
#       不再区分 execute_code vs terminal — 同一事件只计一次。
# ============================================================
TOOL_ERROR_PATTERNS = [
    (r'Traceback \(most recent call last\)', 'python_traceback'),
    (r'exit_code.*[^0-9]0\b.*error', 'nonzero_exit'),
    (r'BLOCKED:', 'approval_blocked'),
    (r'File not found', 'file_not_found'),
    (r'Permission denied', 'permission_denied'),
    (r'Connection.*refused|Connection.*timeout|SSH.*timeout', 'connection_error'),
    (r'JSON.*parse|json.*decode|json.loads.*failed', 'json_parse_error'),
    (r'syntax error|SyntaxError|IndentationError', 'syntax_error'),
]


def mine_tool_failures(conn, days_back=30):
    """提取工具失败信号，approval_blocked 按 session+error_type 去重。"""
    cur = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days_back)).timestamp()

    cur.execute("""
        SELECT m.id, m.session_id, m.tool_name, m.content, m.timestamp,
               s.title, s.source
        FROM messages m
        JOIN sessions s ON m.session_id = s.id
        WHERE m.role = 'tool'
          AND m.timestamp > ?
          AND m.content IS NOT NULL
        ORDER BY m.timestamp
    """, (cutoff,))

    failures = []
    seen_keys = set()  # (session_id, tool_name, error_type) 去重
    seen_approval = set()  # (session_id, error_type) 跨工具去重(approval_blocked)

    for row in cur.fetchall():
        content = row['content'] or ''
        for pattern, error_type in TOOL_ERROR_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                key = (row['session_id'], row['tool_name'], error_type)
                if key in seen_keys:
                    continue

                # approval_blocked 跨工具去重 (execute_code 和 terminal 是同一事件)
                if error_type == 'approval_blocked':
                    akey = (row['session_id'], error_type)
                    if akey in seen_approval:
                        continue
                    seen_approval.add(akey)

                seen_keys.add(key)
                failures.append({
                    'type': 'tool_failure',
                    'error_type': error_type,
                    'tool_name': row['tool_name'],
                    'message_id': row['id'],
                    'session_id': row['session_id'],
                    'session_title': row['title'],
                    'source': row['source'],
                    'timestamp': datetime.fromtimestamp(row['timestamp']).isoformat(),
                    'error_snippet': content[:300],
                })
                break

    return failures


# ============================================================
# Signal 3: 异常 session
# ============================================================
def mine_anomalous_sessions(conn, days_back=30):
    """提取异常 session。"""
    cur = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days_back)).timestamp()

    cur.execute("""
        SELECT id, title, source, model, started_at, ended_at,
               end_reason, message_count, tool_call_count,
               input_tokens, output_tokens, estimated_cost_usd
        FROM sessions
        WHERE started_at > ?
        ORDER BY started_at DESC
    """, (cutoff,))

    anomalies = []
    for row in cur.fetchall():
        if row['end_reason'] is None and row['message_count'] and row['message_count'] > 5:
            anomalies.append({
                'type': 'abandoned_session',
                'session_id': row['id'],
                'title': row['title'],
                'source': row['source'],
                'message_count': row['message_count'],
                'tool_call_count': row['tool_call_count'],
                'started_at': datetime.fromtimestamp(row['started_at']).isoformat() if row['started_at'] else None,
            })

        if (row['input_tokens'] and row['output_tokens']
                and row['input_tokens'] > 10000
                and row['output_tokens'] < 200
                and (row['tool_call_count'] or 0) == 0):
            anomalies.append({
                'type': 'low_yield_session',
                'session_id': row['id'],
                'title': row['title'],
                'input_tokens': row['input_tokens'],
                'output_tokens': row['output_tokens'],
                'tool_calls': row['tool_call_count'],
            })

    return anomalies


# ============================================================
# 聚类
# ============================================================
def cluster_failures(corrections, tool_failures, anomalies):
    """将三类信号按主题聚类。"""
    clusters = defaultdict(list)

    for c in corrections:
        clusters[f"correction:{c['session_id']}"].append(c)

    tool_clusters = defaultdict(list)
    for f in tool_failures:
        key = f"{f['tool_name']}:{f['error_type']}"
        tool_clusters[key].append(f)

    evidence = {
        'summary': {
            'total_corrections': len(corrections),
            'total_tool_failures': len(tool_failures),
            'total_anomalies': len(anomalies),
            'unique_correction_sessions': len(set(c['session_id'] for c in corrections)),
            'top_tool_failure_types': sorted(
                [(k, len(v)) for k, v in tool_clusters.items()],
                key=lambda x: -x[1]
            )[:10],
        },
        'correction_clusters': [
            {
                'session_id': sid,
                'session_title': cluster[0].get('session_title', ''),
                'correction_count': len(cluster),
                'corrections': [c['content'] for c in cluster],
                'timestamps': [c['timestamp'] for c in cluster],
            }
            for sid, cluster in sorted(clusters.items(), key=lambda x: -len(x[1]))
        ],
        'tool_failure_clusters': [
            {
                'category': key,
                'count': len(items),
                'sample_errors': [i['error_snippet'][:150] for i in items[:3]],
                'sessions': list(set(i['session_title'] for i in items)),
            }
            for key, items in sorted(tool_clusters.items(), key=lambda x: -len(x[1]))
        ],
        'anomalies': anomalies,
    }

    return evidence


# ============================================================
# 写状态到 state.db (交叉验证可发现)
# ============================================================
def update_state(status, detail, actor='weakness-miner'):
    """将挖掘结果写入 state.db 模块状态。"""
    try:
        sys.path.insert(0, r'E:\workspace\anti-entropy-runtime')
        from state_layer import set_module, add_event
        set_module('weakness_mining', status, detail, actor=actor)
        add_event(f'弱点挖掘完成: {status} ({detail})', actor=actor, module='weakness_mining')
        return True
    except Exception:
        return False


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='端点星 Self-Harness 弱点挖掘器')
    parser.add_argument('--days', type=int, default=30, help='回溯天数 (默认 30)')
    parser.add_argument('--quiet', action='store_true', help='静默模式 (只输出 JSON 路径)')
    args = parser.parse_args()

    print("=== 端点星 Self-Harness 弱点挖掘 v2 ===")
    print(f"时间: {datetime.now().isoformat()}")
    print(f"回溯: {args.days} 天")
    print()

    try:
        conn, db_path = get_db()
        print(f"DB: {db_path}")
    except FileNotFoundError as e:
        print(f"❌ {e}")
        update_state('broken', f'state.db 不存在: {DB_PATHS}', actor='weakness-miner')
        sys.exit(1)

    print()

    corrections = mine_user_corrections(conn, days_back=args.days)
    if not args.quiet:
        print(f"[1/3] 用户纠正信号: {len(corrections)} 条")

    tool_failures = mine_tool_failures(conn, days_back=args.days)
    if not args.quiet:
        print(f"[2/3] 工具失败信号: {len(tool_failures)} 条")

    anomalies = mine_anomalous_sessions(conn, days_back=args.days)
    if not args.quiet:
        print(f"[3/3] 异常 session: {len(anomalies)} 条")

    evidence = cluster_failures(corrections, tool_failures, anomalies)

    # 输出
    output_file = os.path.join(
        OUTPUT_DIR,
        f"weakness-report-{datetime.now().strftime('%Y-%m-%d')}.json"
    )
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)

    if not args.quiet:
        print(f"\n=== 聚类结果 ===")
        print(f"用户纠正聚类: {len(evidence['correction_clusters'])} 组")
        print(f"工具失败聚类: {len(evidence['tool_failure_clusters'])} 类")
        print(f"Top 工具失败:")
        for cat, cnt in evidence['summary']['top_tool_failure_types'][:5]:
            print(f"  {cat}: {cnt}次")

    # 写状态到 state.db
    status = 'stable' if len(tool_failures) < 50 else 'elevated_failures'
    detail = f"{args.days}天: {len(corrections)}纠正+{len(tool_failures)}工具失败+{len(anomalies)}异常"
    update_state(status, detail)

    print(f"\n报告已保存: {output_file}")
    conn.close()
    return output_file


if __name__ == '__main__':
    main()
