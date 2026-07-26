# ZCode exec log 挖掘 (tool stdout 里的失败信号)
import os
import re
from datetime import datetime, timedelta

ZCODE_EXEC_DIR = r'C:\Users\<USERNAME>\.zcode\cli\exec'
CLAUDE_CODE_MEMORY_DIR = r'C:\Users\<USERNAME>\.claude\projects\C--Users-<USERNAME>\memory'

TOOL_ERROR_PATTERNS = [
    (r'Traceback \(most recent call last\)', 'python_traceback'),
    (r'exit_code.*[^0-9]0\b.*error', 'nonzero_exit'),
    (r'BLOCKED:', 'approval_blocked'),
    (r'File not found', 'file_not_found'),
    (r'Permission denied', 'permission_denied'),
    (r'Connection.*refused|Connection.*timeout|SSH.*timeout', 'connection_error'),
    (r'JSON.*parse|json.*decode|json.loads.*failed', 'json_parse_error'),
    (r'syntax error|SyntaxError|IndentationError', 'syntax_error'),
    (r'Validation failed for tool', 'tool_validation_error'),
    (r'"status":\s*"error"', 'tool_error_status'),
    (r'must be equal to one of', 'tool_param_error'),
    (r'must mat', 'tool_target_error'),
    (r'Invoke-\w+.*缺少参数', 'powershell_param_error'),
    (r'所在位置 行:\d+ 字符:\d+', 'powershell_syntax_error'),
    (r'TimeoutError', 'timeout_error'),
    (r'MemoryError', 'memory_error'),
    (r'AttributeError', 'attribute_error'),
]


def mine_zcode(days_back):
    """ZCode exec log 挖掘 (tool stdout 里的失败信号)"""
    corrections = []
    failures = []
    anomalies = []

    if not os.path.exists(ZCODE_EXEC_DIR):
        return corrections, failures, anomalies

    for sess in sorted(os.listdir(ZCODE_EXEC_DIR)):
        sess_path = os.path.join(ZCODE_EXEC_DIR, sess)
        if not os.path.isdir(sess_path):
            continue
        # session被遗弃(有stdout但没stderr输出)
        has_stdout = any(f.endswith('-stdout.log') for f in os.listdir(sess_path))
        has_stderr_content = any(
            f.endswith('-stderr.log') and os.path.getsize(os.path.join(sess_path, f)) > 0
            for f in os.listdir(sess_path)
        )
        if has_stdout and not has_stderr_content:
            anomalies.append({
                'type': 'abandoned_session', 'source': 'zcode',
                'session_id': sess, 'title': sess[:30],
            })

        for f in sorted(os.listdir(sess_path)):
            if 'stdout' not in f:
                continue
            fp = os.path.join(sess_path, f)
            if os.path.getsize(fp) == 0:
                continue
            # 容错读取
            text = ''
            for enc in ['utf-8', 'gbk', 'gb18030', 'latin-1']:
                try:
                    text = open(fp, encoding=enc).read()
                    break
                except Exception:
                    continue
            if not text:
                continue

            for pattern, error_type in TOOL_ERROR_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    failures.append({
                        'type': 'tool_failure', 'source': 'zcode',
                        'error_type': error_type, 'tool_name': 'zcode_exec',
                        'session_id': sess, 'session_title': sess[:30],
                        'timestamp': '', 'error_snippet': text[:300],
                    })
                    break

    return corrections, failures, anomalies


def mine_claude_code(days_back):
    """Claude Code memory 上下文 (人工经验,非失败信号)"""
    context = []
    if not os.path.exists(CLAUDE_CODE_MEMORY_DIR):
        return context

    for f in sorted(os.listdir(CLAUDE_CODE_MEMORY_DIR)):
        if not f.endswith('.md'):
            continue
        fp = os.path.join(CLAUDE_CODE_MEMORY_DIR, f)
        try:
            text = open(fp, encoding='utf-8').read()
        except Exception:
            continue
        context.append({
            'type': 'human_experience', 'source': 'claude_code',
            'filename': f, 'content': text[:500],
            'size': len(text),
        })
    return context
