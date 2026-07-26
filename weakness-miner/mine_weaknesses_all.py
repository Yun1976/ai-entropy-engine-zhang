#!/usr/bin/env python3
"""
Self-Harness 全量弱点挖掘 (v3)
================================
从全部 session 数据源挖掘失败轨迹, 不只是 Hermes state.db。

数据源:
  1. Hermes state.db (54 sessions + 3322 messages)
  2. OpenClaw sessions (3858 files + ~75K messages)  ← 主体
  3. memory-tdai l0_conversations (7338条原始对话)  ← 补充

改进 (v3, 2026-07-25):
  - 支持 OpenClaw sessions 挖掘 (3858个JSONL文件)
  - 跨数据源聚类 (同一失败在多个数据源中合并)
  - 数据源标记 (hermes/openclaw/tdai)
"""

import sqlite3
import json
import os
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mine_zcode import mine_zcode as _mine_zcode, mine_claude_code as _mine_claude_code

# 数据源路径
HERMES_DB = os.path.expanduser("~/AppData/Local/hermes/state.db")
OPENCLAW_SESSIONS = Path(r'C:\Users\<USERNAME>\.openclaw\agents\main\sessions')
TDAI_DB = r'C:\Users\<USERNAME>\.openclaw\memory-tdai\vectors.db'
OUTPUT_DIR = os.path.expanduser("~/AppData/Local/hermes/weakness-reports")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_hermes_db():
    if os.path.exists(HERMES_DB):
        conn = sqlite3.connect(HERMES_DB)
        conn.row_factory = sqlite3.Row
        return conn
    return None


# ============================================================
# Signal 1: 用户纠正 (Hermes + OpenClaw + TDAI)
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

TOOL_ERROR_PATTERNS = [
    (r'Traceback \(most recent call last\)', 'python_traceback'),
    (r'exit_code.*[^0-9]0\b.*error', 'nonzero_exit'),
    (r'BLOCKED:', 'approval_blocked'),
    (r'File not found', 'file_not_found'),
    (r'Permission denied', 'permission_denied'),
    (r'Connection.*refused|Connection.*timeout|SSH.*timeout', 'connection_error'),
    (r'JSON.*parse|json.*decode|json.loads.*failed', 'json_parse_error'),
    (r'syntax error|SyntaxError|IndentationError', 'syntax_error'),
    # OpenClaw特有
    (r'Validation failed for tool', 'tool_validation_error'),
    (r'"status":\s*"error"', 'tool_error_status'),
    (r'must be equal to one of', 'tool_param_error'),
    (r'must mat', 'tool_target_error'),
    # PowerShell/curl错误
    (r'Invoke-\w+.*缺少参数|缺少参数.*Invoke-\w+', 'powershell_param_error'),
    (r'所在位置 行:\d+ 字符:\d+', 'powershell_syntax_error'),
    (r'curl.*error|curl.*failed|curl.*timeout', 'curl_error'),
    (r'HTTP \d{3}.*error|error.*HTTP \d{3}', 'http_error'),
]


def mine_hermes(conn, days_back):
    """Hermes state.db 挖掘 (v2 逻辑)"""
    cur = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days_back)).timestamp()

    # 用户纠正
    corrections = []
    cur.execute("""
        SELECT m.id, m.session_id, m.content, m.timestamp, s.title, s.source
        FROM messages m JOIN sessions s ON m.session_id = s.id
        WHERE m.role = 'user' AND m.timestamp > ? AND m.content IS NOT NULL
        ORDER BY m.timestamp
    """, (cutoff,))
    for row in cur.fetchall():
        content = row['content'] or ''
        if any(re.search(p, content) for p in EXCLUDE_PATTERNS):
            continue
        matched = [p for p in USER_CORRECTION_PATTERNS if re.search(p, content)]
        if not matched or len(content) > 500:
            continue
        corrections.append({
            'type': 'user_correction', 'source': 'hermes',
            'session_id': row['session_id'], 'session_title': row['title'],
            'timestamp': datetime.fromtimestamp(row['timestamp']).isoformat(),
            'content': content.strip(), 'matched_patterns': matched,
        })

    # 工具失败
    failures = []
    seen_keys = set()
    seen_approval = set()
    tool_call_map = {}  # toolCall_id -> tool_name
    cur.execute("""
        SELECT m.id, m.session_id, m.tool_name, m.content, m.timestamp, s.title
        FROM messages m JOIN sessions s ON m.session_id = s.id
        WHERE m.role = 'tool' AND m.timestamp > ? AND m.content IS NOT NULL
        ORDER BY m.timestamp
    """, (cutoff,))
    for row in cur.fetchall():
        content = row['content'] or ''
        for pattern, error_type in TOOL_ERROR_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                key = (row['session_id'], row['tool_name'], error_type)
                if key in seen_keys:
                    continue
                if error_type == 'approval_blocked':
                    akey = (row['session_id'], error_type)
                    if akey in seen_approval:
                        continue
                    seen_approval.add(akey)
                seen_keys.add(key)
                failures.append({
                    'type': 'tool_failure', 'source': 'hermes',
                    'error_type': error_type, 'tool_name': row['tool_name'],
                    'session_id': row['session_id'], 'session_title': row['title'],
                    'timestamp': datetime.fromtimestamp(row['timestamp']).isoformat(),
                    'error_snippet': content[:300],
                })
                break

    # 异常 session
    anomalies = []
    cur.execute("""
        SELECT id, title, source, started_at, end_reason, message_count,
               tool_call_count, input_tokens, output_tokens
        FROM sessions WHERE started_at > ? ORDER BY started_at DESC
    """, (cutoff,))
    for row in cur.fetchall():
        if row['end_reason'] is None and row['message_count'] and row['message_count'] > 5:
            anomalies.append({
                'type': 'abandoned_session', 'source': 'hermes',
                'session_id': row['id'], 'title': row['title'],
                'message_count': row['message_count'],
            })

    return corrections, failures, anomalies


def mine_openclaw_sessions(days_back, max_files=None):
    """OpenClaw sessions 挖掘 (JSONL 文件)"""
    corrections = []
    failures = []
    anomalies = []
    cutoff = (datetime.now() - timedelta(days=days_back)).timestamp()

    files = [f for f in OPENCLAW_SESSIONS.glob('*.jsonl') if 'trajectory' not in f.name]
    if max_files:
        files = files[:max_files]

    seen_keys = set()
    seen_approval = set()
    tool_call_map = {}  # toolCall_id -> tool_name

    for sf in files:
        try:
            mtime = sf.stat().st_mtime
            if mtime < cutoff:
                continue
            session_id = sf.stem
            anomalies.append({
                'type': 'abandoned_session', 'source': 'openclaw',
                'session_id': session_id, 'title': sf.stem[:30],
                'message_count': 0,
            })

            with open(sf, encoding='utf-8') as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = d.get('message', {})
                    role = msg.get('role')
                    content = msg.get('content', '')

                    # 提取文本
                    if isinstance(content, list):
                        text_parts = []
                        for c in content:
                            if isinstance(c, dict):
                                if c.get('type') == 'text':
                                    text_parts.append(c.get('text', ''))
                                elif c.get('type') == 'toolCall':
                                    text_parts.append(str(c.get('input', '')))
                        text = ' '.join(text_parts)
                    elif isinstance(content, dict):
                        text = content.get('text', str(content))
                    elif isinstance(content, str):
                        text = content
                    else:
                        text = str(content)

                    # 提取toolCall的工具名(用于关联toolResult)
                    if role == 'assistant':
                        c = msg.get('content', [])
                        if isinstance(c, list):
                            for item in c:
                                if isinstance(item, dict) and item.get('type') == 'toolCall':
                                    tool_call_map[item.get('id', '')] = item.get('name', 'unknown')

                    if role in ('toolResult', 'tool'):
                        for pattern, error_type in TOOL_ERROR_PATTERNS:
                            if re.search(pattern, text, re.IGNORECASE):
                                key = (session_id, msg.get('toolName', msg.get('name', 'unknown')), error_type)
                                if key in seen_keys:
                                    continue
                                if error_type == 'approval_blocked':
                                    akey = (session_id, error_type)
                                    if akey in seen_approval:
                                        continue
                                    seen_approval.add(akey)
                                seen_keys.add(key)
                                tool_name = tool_call_map.get(msg.get('toolUseId', ''), 'unknown')
                                failures.append({
                                    'type': 'tool_failure', 'source': 'openclaw',
                                    'error_type': error_type, 'tool_name': tool_name,
                                    'session_id': session_id,
                                    'session_title': sf.stem[:30],
                                    'timestamp': '', 'error_snippet': text[:300],
                                })
                                break
        except Exception:
            continue

    return corrections, failures, anomalies


def mine_tdai(days_back):
    """memory-tdai l0_conversations 挖掘"""
    corrections = []
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()

    try:
        conn = sqlite3.connect(TDAI_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT message_text, role, recorded_at, session_id
            FROM l0_conversations
            WHERE recorded_at > ? AND role = 'user'
            ORDER BY recorded_at
        """, (cutoff,))

        for row in cur.fetchall():
            content = row['message_text'] or ''
            if any(re.search(p, content) for p in EXCLUDE_PATTERNS):
                continue
            matched = [p for p in USER_CORRECTION_PATTERNS if re.search(p, content)]
            if not matched or len(content) > 500:
                continue
            corrections.append({
                'type': 'user_correction', 'source': 'tdai',
                'session_id': row['session_id'], 'session_title': 'tdai_memory',
                'timestamp': row['recorded_at'], 'content': content.strip(),
                'matched_patterns': matched,
            })
        conn.close()
    except Exception:
        pass

    return corrections, [], []


def cluster_all(all_corrections, all_failures, all_anomalies):
    """跨数据源聚类"""
    # 按数据源统计
    by_source = defaultdict(lambda: {'corrections': 0, 'failures': 0, 'anomalies': 0})
    for c in all_corrections:
        by_source[c['source']]['corrections'] += 1
    for f in all_failures:
        by_source[f['source']]['failures'] += 1
    for a in all_anomalies:
        by_source[a['source']]['anomalies'] += 1

    # 跨数据源失败聚类 (同一 session+error_type 在多个数据源中合并)
    failure_clusters = defaultdict(list)
    for f in all_failures:
        key = f"{f['error_type']}:{f['tool_name']}"
        failure_clusters[key].append(f)

    evidence = {
        'summary': {
            'total_corrections': len(all_corrections),
            'total_tool_failures': len(all_failures),
            'total_anomalies': len(all_anomalies),
            'by_source': dict(by_source),
            'top_tool_failure_types': sorted(
                [(k, len(v)) for k, v in failure_clusters.items()],
                key=lambda x: -x[1]
            )[:10],
        },
        'correction_clusters': [
            {
                'session_id': sid,
                'sources': list(set(c['source'] for c in cluster)),
                'correction_count': len(cluster),
                'corrections': [c['content'] for c in cluster],
            }
            for sid, cluster in sorted(
                ((sid, [c for c in all_corrections if c['session_id'] == sid]) for sid in set(c['session_id'] for c in all_corrections)),
                key=lambda x: -len(x[1])
            )
        ],
        'tool_failure_clusters': [
            {
                'category': key,
                'count': len(items),
                'sources': list(set(i['source'] for i in items)),
                'sessions': list(set(i['session_title'] for i in items)),
            }
            for key, items in sorted(failure_clusters.items(), key=lambda x: -len(x[1]))
        ],
        'anomalies': all_anomalies,
    }
    return evidence


def update_state(status, detail, actor='weakness-miner'):
    try:
        sys.path.insert(0, r'E:\workspace\anti-entropy-runtime')
        from state_layer import set_module, add_event
        set_module('weakness_mining', status, detail, actor=actor)
        add_event(f'全量弱点挖掘完成: {detail}', actor=actor, module='weakness_mining')
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description='端点星 Self-Harness 全量弱点挖掘')
    parser.add_argument('--days', type=int, default=999, help='回溯天数 (默认999=全部)')
    parser.add_argument('--sources', nargs='+', choices=['hermes', 'openclaw', 'tdai', 'zcode', 'claude_code'],
                       default=['hermes', 'openclaw', 'tdai'], help='数据源')
    parser.add_argument('--max-openclaw-files', type=int, default=None,
                       help='限制OpenClaw文件数(调试用)')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    print("=== 端点星 Self-Harness 全量弱点挖掘 v3 ===")
    print(f"时间: {datetime.now().isoformat()}")
    print(f"回溯: {args.days} 天")
    print(f"数据源: {', '.join(args.sources)}")
    print()

    all_corrections, all_failures, all_anomalies = [], [], []

    # Hermes
    if 'hermes' in args.sources:
        conn = get_hermes_db()
        if conn:
            c, f, a = mine_hermes(conn, args.days)
            all_corrections.extend(c)
            all_failures.extend(f)
            all_anomalies.extend(a)
            conn.close()
            if not args.quiet:
                print(f"[hermes] 纠正:{len(c)} 失败:{len(f)} 异常:{len(a)}")

    # OpenClaw
    if 'openclaw' in args.sources:
        if OPENCLAW_SESSIONS.exists():
            c, f, a = mine_openclaw_sessions(args.days, args.max_openclaw_files)
            all_corrections.extend(c)
            all_failures.extend(f)
            all_anomalies.extend(a)
            if not args.quiet:
                print(f"[openclaw] 纠正:{len(c)} 失败:{len(f)} 异常:{len(a)}")

    # ZCode (exec log)
    if 'zcode' in args.sources:
        c, f, a = _mine_zcode(args.days)
        all_corrections.extend(c)
        all_failures.extend(f)
        all_anomalies.extend(a)
        if not args.quiet:
            print(f'[zcode] 纠正:{len(c)} 失败:{len(f)} 异常:{len(a)}')

    # Claude Code (memory context)
    if 'claude_code' in args.sources:
        ctx = _mine_claude_code(args.days)
        if not args.quiet:
            print(f'[claude_code] 上下文:{len(ctx)}条')

    # TDAI
    if 'tdai' in args.sources:
        if os.path.exists(TDAI_DB):
            c, f, a = mine_tdai(args.days)
            all_corrections.extend(c)
            all_failures.extend(f)
            all_anomalies.extend(a)
            if not args.quiet:
                print(f"[tdai] 纠正:{len(c)} 失败:{len(f)} 异常:{len(a)}")

    evidence = cluster_all(all_corrections, all_failures, all_anomalies)

    output_file = os.path.join(
        OUTPUT_DIR,
        f"weakness-report-all-{datetime.now().strftime('%Y-%m-%d')}.json"
    )
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)

    if not args.quiet:
        print(f"\n=== 汇总 ===")
        for src, stats in evidence['summary']['by_source'].items():
            print(f"  {src}: 纠正{stats['corrections']} 失败{stats['failures']} 异常{stats['anomalies']}")
        print(f"\nTop 工具失败:")
        for cat, cnt in evidence['summary']['top_tool_failure_types'][:5]:
            print(f"  {cat}: {cnt}次")

    status = 'elevated_failures' if len(all_failures) > 100 else 'stable'
    detail = f"全部数据源: {len(all_corrections)}纠正+{len(all_failures)}失败+{len(all_anomalies)}异常"
    update_state(status, detail)

    print(f"\n报告已保存: {output_file}")
    return output_file


if __name__ == '__main__':
    main()
