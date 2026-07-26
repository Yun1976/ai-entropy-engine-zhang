#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端点星统一状态层 (Unified State Layer)
======================================
替代 BLACKBOARD.json + engine-state.json 的分散状态。
所有 facet (OpenClaw/Hermes/ZCode/CC) 通过统一 API 读写状态。

设计原则:
  1. SQLite + WAL模式: 并发安全(多进程读写不冲突)
  2. JSON字段: 灵活存储复杂结构(兼容现有数据)
  3. 原子写入: 事务保护, 永不损坏(解决JSON文件写写冲突)
  4. 残差文件保持独立: 它是训练数据集,不是运行时状态
  5. 审计追踪: 每次写入记录 who/when/what

位置: E:\\workspace\\anti-entropy-runtime\\state.db (统一运行时目录)
"""
import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

DB_PATH = Path(r'E:\workspace\anti-entropy-runtime\state.db')

SCHEMA = """
-- ============================================================
-- 表1: meta — 系统元信息(单行表)
-- ============================================================
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL
);

-- ============================================================
-- 表2: modules — 各模块状态(替代 BLACKBOARD.json.modules)
-- ============================================================
CREATE TABLE IF NOT EXISTS modules (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL,          -- running/stable_running/broken/stopped/unknown/installed_not_running
    detail TEXT DEFAULT '',
    blocker TEXT,
    last_verified TEXT,
    verified_by TEXT,
    metrics_json TEXT,             -- JSON: 灵活存储各模块特有指标
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL
);

-- ============================================================
-- 表3: events — 事件流(替代 BLACKBOARD.json.recent_events)
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,              -- ISO timestamp
    actor TEXT NOT NULL,           -- 谁做的(ZCode/OpenClaw/Hermes/谢顿)
    event_type TEXT DEFAULT 'log', -- log/plan/blocker/recovery/warning
    module TEXT,                   -- 涉及哪个模块
    detail TEXT NOT NULL,
    verified INTEGER DEFAULT 0     -- 是否经过交叉验证
);

-- ============================================================
-- 表4: tasks — 任务调度状态(替代 engine-state.json)
-- ============================================================
CREATE TABLE IF NOT EXISTS tasks (
    name TEXT PRIMARY KEY,         -- daily-planner/heartbeat/science-daily等
    status TEXT DEFAULT 'unknown', -- running/due/blocked/done/skipped
    last_run TEXT,
    last_result TEXT,              -- 成功/失败/超时
    run_count_today INTEGER DEFAULT 0,
    next_run TEXT,
    updated_at TEXT NOT NULL
);

-- ============================================================
-- 表5: pending — 待处理事项(替代 engine-state.json.pending_tasks)
-- ============================================================
CREATE TABLE IF NOT EXISTS pending (
    id TEXT PRIMARY KEY,
    desc TEXT NOT NULL,
    source TEXT,                   -- 谁添加的
    added_at TEXT NOT NULL,
    status TEXT DEFAULT 'open',    -- open/stale/resolved
    stale_at TEXT,
    resolved_at TEXT,
    resolved_by TEXT
);

-- ============================================================
-- 表6: write_log — 审计追踪(每次写入记录)
-- ============================================================
CREATE TABLE IF NOT EXISTS write_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    table_name TEXT NOT NULL,
    operation TEXT NOT NULL,       -- insert/update/delete
    key_field TEXT,
    detail TEXT
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_module ON events(module);
CREATE INDEX IF NOT EXISTS idx_pending_status ON pending(status);
"""

# ============================================================
# 连接管理
# ============================================================
@contextmanager
def get_conn():
    """获取数据库连接(WAL模式,并发安全)"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """初始化数据库(创建表)"""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    print(f"数据库已初始化: {DB_PATH}")

# ============================================================
# 写入接口
# ============================================================
def set_module(name, status, detail='', blocker=None, verified_by='', 
               metrics=None, actor='unknown'):
    """更新模块状态(原子写入,自动记录审计)"""
    now = datetime.now().isoformat(timespec='seconds')
    metrics_json = json.dumps(metrics, ensure_ascii=False) if metrics else None
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO modules (name, status, detail, blocker, last_verified, 
                                verified_by, metrics_json, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                status=excluded.status, detail=excluded.detail,
                blocker=excluded.blocker, last_verified=excluded.last_verified,
                verified_by=excluded.verified_by, metrics_json=excluded.metrics_json,
                updated_at=excluded.updated_at, updated_by=excluded.updated_by
        """, (name, status, detail, blocker, now, verified_by,
              metrics_json, now, actor))
        conn.execute("""
            INSERT INTO write_log (ts, actor, table_name, operation, key_field, detail)
            VALUES (?, ?, 'modules', 'update', ?, ?)
        """, (now, actor, name, f'status={status}'))

def add_event(detail, actor='unknown', event_type='log', module=None, verified=False):
    """追加事件"""
    now = datetime.now().isoformat(timespec='seconds')
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO events (ts, actor, event_type, module, detail, verified)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (now, actor, event_type, module, detail, int(verified)))
    return now

def update_task(name, status=None, last_run=None, last_result=None,
                run_count_today=None, next_run=None):
    """更新任务状态"""
    now = datetime.now().isoformat(timespec='seconds')
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM tasks WHERE name=?", (name,)).fetchone()
        if existing:
            updates = []
            params = []
            for k, v in [('status',status),('last_run',last_run),('last_result',last_result),
                         ('next_run',next_run)]:
                if v is not None:
                    updates.append(f'{k}=?')
                    params.append(v)
            if run_count_today is not None:
                updates.append('run_count_today=?')
                params.append(run_count_today)
            updates.append('updated_at=?')
            params.append(now)
            params.append(name)
            conn.execute(f"UPDATE tasks SET {','.join(updates)} WHERE name=?", params)
        else:
            conn.execute("""
                INSERT INTO tasks (name, status, last_run, last_result, 
                                  run_count_today, next_run, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, status or 'unknown', last_run, last_result,
                  run_count_today or 0, next_run, now))

def add_pending(pid, desc, source='unknown'):
    """添加待处理事项"""
    now = datetime.now().isoformat(timespec='seconds')
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO pending (id, desc, source, added_at, status)
            VALUES (?, ?, ?, ?, 'open')
        """, (pid, desc, source, now))

def resolve_pending(pid, resolved_by='unknown'):
    """标记待处理事项为已解决"""
    now = datetime.now().isoformat(timespec='seconds')
    with get_conn() as conn:
        conn.execute("""
            UPDATE pending SET status='resolved', resolved_at=?, resolved_by=?
            WHERE id=?
        """, (now, resolved_by, pid))

def set_meta(key, value, actor='unknown'):
    """设置元信息"""
    now = datetime.now().isoformat(timespec='seconds')
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO meta (key, value, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value, updated_at=excluded.updated_at,
                updated_by=excluded.updated_by
        """, (key, str(value), now, actor))

# ============================================================
# 读取接口
# ============================================================
def get_module(name):
    """读取模块状态"""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM modules WHERE name=?", (name,)).fetchone()
        if row:
            d = dict(row)
            if d.get('metrics_json'):
                d['metrics'] = json.loads(d['metrics_json'])
            return d
    return None

def get_all_modules():
    """读取所有模块状态"""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM modules ORDER BY name").fetchall()
        return [dict(r) for r in rows]

def get_recent_events(limit=20):
    """读取最近事件"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

def get_pending(status='open'):
    """读取待处理事项"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pending WHERE status=? ORDER BY added_at DESC", (status,)
        ).fetchall()
        return [dict(r) for r in rows]

def get_system_summary():
    """获取系统摘要(给心跳/LLM快速读)"""
    with get_conn() as conn:
        modules = [dict(r) for r in conn.execute(
            "SELECT name, status, blocker, updated_at FROM modules ORDER BY name"
        ).fetchall()]
        events = [dict(r) for r in conn.execute(
            "SELECT ts, actor, detail FROM events ORDER BY ts DESC LIMIT 5"
        ).fetchall()]
        pending = conn.execute(
            "SELECT COUNT(*) as c FROM pending WHERE status='open'"
        ).fetchone()['c']
        last_meta = conn.execute(
            "SELECT value FROM meta WHERE key='last_updated'"
        ).fetchone()
        last_updated = last_meta['value'] if last_meta else 'unknown'
    return {
        'last_updated': last_updated,
        'modules': modules,
        'recent_events': events,
        'pending_count': pending
    }

def cli():
    """命令行接口: 让LLM心跳/脚本直接读写状态"""
    import sys
    if len(sys.argv) < 2:
        print("用法: state_layer.py summary|module <name>|set_module <name> <status> <detail>|event <detail>")
        return
    cmd = sys.argv[1]
    if cmd == 'summary':
        s = get_system_summary()
        print(json.dumps(s, ensure_ascii=False, indent=2))
    elif cmd == 'module' and len(sys.argv) >= 3:
        m = get_module(sys.argv[2])
        if m:
            print(json.dumps(m, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"模块 {sys.argv[2]} 不存在")
    elif cmd == 'modules':
        for m in get_all_modules():
            print(f"  {m['name']:25s} {m['status']:25s}")
    elif cmd == 'events' and len(sys.argv) >= 3:
        for e in get_recent_events(int(sys.argv[2])):
            print(f"  [{e['ts'][:16]}] {e['actor']}: {e['detail'][:60]}")
    elif cmd == 'set_module' and len(sys.argv) >= 5:
        actor = os.environ.get('STATE_ACTOR', 'cli')
        set_module(sys.argv[2], sys.argv[3], sys.argv[4], actor=actor)
        print(f"✓ {sys.argv[2]} → {sys.argv[3]}")
    elif cmd == 'event' and len(sys.argv) >= 3:
        actor = os.environ.get('STATE_ACTOR', 'cli')
        ts = add_event(sys.argv[2], actor=actor)
        print(f"✓ 事件已追加: {ts}")
    elif cmd == 'pending':
        for p in get_pending():
            print(f"  [{p['status']}] {p['id'][:30]}: {p['desc'][:50]}")
    elif cmd == 'init':
        init_db()
    else:
        print("命令: summary|module <name>|modules|events <n>|set_module <name> <status> <detail>|event <detail>|pending|init")

if __name__ == '__main__':
    cli()
