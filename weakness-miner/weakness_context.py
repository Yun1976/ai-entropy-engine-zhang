#!/usr/bin/env python3
"""
弱点上下文拼接器 (Weakness Context Builder)
=============================================
把弱点挖掘结果拼接成 Hermes 可理解的上下文,
让 Hermes 自动修补弱点进行系统优化。

流程:
  1. 读取弱点报告 (weakness-report-all-*.json)
  2. 按优先级聚类弱点 (高频/高影响/可自动修复)
  3. 拼接成 Hermes 的 prompt 上下文
  4. 调用 Hermes 自动修补 (generate lesson草稿/修复方案/系统优化建议)
  5. 输出修补结果到 _drafts/ 供人工审核

使用: python weakness_context.py <weakness-report.json>
"""
import json, os, sys, argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r'E:\workspace\anti-entropy-runtime')
from state_layer import set_module, add_event

DRAFTS_DIR = r'G:\obsidian-vault\lessons\_drafts'
os.makedirs(DRAFTS_DIR, exist_ok=True)


def build_context(report_path):
    """把弱点报告拼接成 Hermes 上下文"""
    report = json.load(open(report_path, encoding='utf-8'))
    s = report['summary']

    # 按优先级聚类弱点
    priorities = {
        'high': [],    # 高频+高影响(影响核心系统)
        'medium': [],  # 可自动修复
        'low': [],     # 需人工分析
    }

    for cat, count in s['top_tool_failure_types']:
        weakness = {'category': cat, 'count': count}
        if count > 100:
            priorities['high'].append(weakness)
        elif count > 20:
            priorities['medium'].append(weakness)
        else:
            priorities['low'].append(weakness)

    # 拼接上下文
    context_parts = []

    context_parts.append(f"""# 端点星弱点上下文 (Weakness Context)
> 生成时间: {datetime.now().isoformat()}
> 数据源: {report_path}
> 弱点总数: {s['total_tool_failures']}个工具失败 + {s['total_anomalies']}个异常session

## 弱点分布

| 优先级 | 弱点类型 | 失败次数 | 建议 |
|---|---|---|---|
""")

    for w in priorities['high']:
        context_parts.append(f"| 🔴 高 | {w['category']} | {w['count']}次 | 立即修复(影响核心系统) |")
    for w in priorities['medium']:
        context_parts.append(f"| 🟡 中 | {w['category']} | {w['count']}次 | 自动修复(技术层) |")
    for w in priorities['low']:
        context_parts.append(f"| ⚪ 低 | {w['category']} | {w['count']}次 | 人工分析(认知层) |")

    context_parts.append("""

## 高优先级弱点详情

""")

    # 高优先级弱点详情
    for w in priorities['high'][:5]:
        context_parts.append(f"### {w['category']} ({w['count']}次)")
        context_parts.append(f"影响: 高频失败,可能影响系统稳定性")
        context_parts.append(f"建议: 生成 lesson 草稿 + 自动修复方案")
        context_parts.append("")

    context_parts.append("""

## 系统优化建议

基于以上弱点, 端点星应该:
1. 生成 lesson 草稿 (弱点→经验转化)
2. 自动修复技术层弱点 (syntax/json/permission)
3. 优化 tool 调用策略 (避免高频失败的 tool)
4. 改进 session 管理 (减少被遗弃 session)
""")

    return '\n'.join(context_parts), priorities


def generate_drafts(context, priorities, report_path):
    """生成 Hermes 修补草稿"""
    drafts = []

    # 草稿1: 高优先级弱点 lesson
    high_weaknesses = priorities['high'][:3]
    if high_weaknesses:
        draft1 = f"""[DRAFT-PENDING]

# 高频弱点自动修补 — {high_weaknesses[0]['category']}

> 来源: Self-Harness 弱点挖掘 + Hermes 自动修补
> 生成时间: {datetime.now().isoformat()}
> 优先级: 🔴 高 (影响核心系统)

## 弱点

| 类型 | 次数 | 影响 |
|---|---|---|
"""
        for w in high_weaknesses:
            draft1 += f"| {w['category']} | {w['count']}次 | 高频失败,影响系统稳定性 |\n"

        draft1 += f"""
## 根因分析

{high_weaknesses[0]['category']} 是端点星最高频的失败类型, 占全部失败的 {high_weaknesses[0]['count'] / 1405 * 100:.0f}%。

可能根因:
1. tool 调用策略不当(选择了不适合的 tool)
2. tool 参数错误(参数验证失败)
3. tool 依赖环境问题(路径/权限/网络)

## 修补方案

1. 生成 tool 使用预检器 (调用前检查参数/环境)
2. 优化 tool 选择策略 (避免高频失败的 tool)
3. 加入 tool 失败回退逻辑 (失败时自动切换到替代 tool)

## 验证

- [ ] 修补后同类失败减少 >50%
- [ ] 不影响现有功能
- [ ] 通过 cross_validate.py 验证

---
*Self-Harness 自动修补 | {datetime.now().strftime('%Y-%m-%d')} | 待审核*
"""
        drafts.append(('high_priority_weakness', draft1))

    # 草稿2: 系统优化建议
    draft2 = f"""[DRAFT-PENDING]

# 端点星系统优化建议 — 基于弱点挖掘的系统级改进

> 来源: Self-Harness 弱点挖掘 + Hermes 自动修补
> 生成时间: {datetime.now().isoformat()}

## 当前系统弱点全景

| 维度 | 当前状态 | 优化方向 |
|---|---|---|
| 工具调用 | {sum(w['count'] for w in priorities['high'] + priorities['medium'])}次失败 | 预检+回退+替代 |
| Session管理 | {len([a for a in priorities['high']])}个异常 | 超时检测+自动终止 |
| 代码质量 | {sum(w['count'] for w in priorities['medium'] if 'syntax' in w['category'])}次语法错误 | 预编译检查 |
| 数据质量 | {sum(w['count'] for w in priorities['medium'] if 'json' in w['category'])}次JSON错误 | 格式校验 |

## 系统优化路线

### Phase 1 (本周): 自动修复技术层
- [ ] 集成 syntax_checker.py 到 exec 流程
- [ ] 集成 json_validator.py 到文件读取流程
- [ ] 优化 cron 无人值守审批配置

### Phase 2 (下周): 优化 tool 策略
- [ ] 分析 tool_error_status:unknown 具体 tool 行为
- [ ] 生成 tool 使用预检器
- [ ] 优化 tool 选择策略

### Phase 3 (长期): 系统级优化
- [ ] 减少被遗弃 session (超时检测+自动终止)
- [ ] 优化跨分身任务交接 (避免交付物丢失)
- [ ] 改进宪法层执行约束 (减少高熵文档产出)

## 验证标准

- 同类失败减少 >50%
- 不影响现有功能
- 通过 cross_validate.py 验证
- 通过反熵增 B 环回证

---
*Self-Harness 自动修补 | {datetime.now().strftime('%Y-%m-%d')} | 待审核*
"""
    drafts.append(('system_optimization', draft2))

    return drafts


def main():
    parser = argparse.ArgumentParser(description='弱点上下文拼接器')
    parser.add_argument('report', help='弱点报告JSON路径')
    parser.add_argument('--hermes', action='store_true', help='调用Hermes自动修补')
    args = parser.parse_args()

    print("=== 弱点上下文拼接器 ===")
    print(f"报告: {args.report}")
    print()

    # 1. 拼接上下文
    context, priorities = build_context(args.report)
    print("上下文已拼接")
    print()

    # 2. 保存上下文(供Hermes读取)
    context_path = os.path.join(DRAFTS_DIR, 'weakness-context.md')
    with open(context_path, 'w', encoding='utf-8') as f:
        f.write(context)
    print(f"上下文已保存: {context_path}")

    # 3. 生成修补草稿
    drafts = generate_drafts(context, priorities, args.report)
    print(f"生成草稿: {len(drafts)}份")
    for name, content in drafts:
        draft_path = os.path.join(DRAFTS_DIR, f'{datetime.now().strftime("%Y-%m-%d")}-{name}.md')
        with open(draft_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  {name}: {draft_path}")

    # 4. 调用Hermes自动修补 (如果指定)
    if args.hermes:
        print()
        print("=== 调用Hermes自动修补 ===")
        # 这里通过OpenClaw agent调用Hermes
        # 或者通过lark-cli发飞书消息给Hermes
        print("(通过OpenClaw agent或飞书通知Hermes)")

    # 5. 写state.db
    set_module('weakness_context', 'built',
              f'弱点上下文已拼接, {len(drafts)}份草稿生成, 供Hermes自动修补',
              actor='weakness_context')
    add_event(f'弱点上下文拼接完成: {len(drafts)}份草稿生成, 供Hermes自动修补系统优化',
             actor='weakness_context', module='weakness_mining')

    print()
    print(f"草稿目录: {DRAFTS_DIR}")
    print("等待人工审核后晋升到 lessons/")


if __name__ == '__main__':
    main()
