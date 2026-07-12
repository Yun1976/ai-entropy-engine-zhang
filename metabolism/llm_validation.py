"""
llm_validation.py — LLM 驱动的真实回证模块
============================================================================
替代 judge_round.py 的模拟回证(硬编码 u 值)。
用 GLM-5-turbo 语义判断:信息块在后续轮次是否真的被引用/依赖。

核心逻辑:
  输入: 信息块内容摘要 + W 窗口内知识库的新增/修改文档摘要
  LLM 判断: 这个信息块的内容,是否在后续文档中被引用/复用/激活?
  输出: u_observed (0.0=无用 ... 1.0=明确有用) + 理由

u 值定义(与 EXPERIMENT_DESIGN.md 一致):
  1.0 = 明确有用(被后续文档明确引用/复现)
  0.5 = 部分有用(摘要/概念被间接采用)
  0.3 = 隐式依赖(路径/架构假设等间接依赖)
  0.0 = 无用(W窗口内从未被引用或依赖)

设计原则(L-FRAUD 教训):
  - 不用决策反推效用(那是幻觉回路)
  - 用语义证据(后续文档是否真的用了这个信息)
  - 每次回证附 evidence(哪些后续文档引用了),可审计
  - LLM 不确定时给中间值(0.3/0.5),不硬判 0 或 1
============================================================================
"""
import json
import urllib.request
import os
from datetime import datetime, timedelta

# GLM API 配置
GLM_URL = 'https://open.bigmodel.cn/api/coding/paas/v4/chat/completions'

def get_api_key():
    """从环境变量读 API key（不依赖任何特定框架的配置路径）"""
    key = os.environ.get('GLM_API_KEY')
    if not key:
        raise EnvironmentError('GLM_API_KEY not set. Export it: export GLM_API_KEY=your_key')
    return key

def call_glm(prompt, max_tokens=200):
    """调用 GLM-5-turbo"""
    api_key = get_api_key()
    req = urllib.request.Request(
        GLM_URL,
        data=json.dumps({
            'model': 'glm-5-turbo',
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': max_tokens,
            'temperature': 0.3  # 低温度,求稳定判断
        }).encode(),
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'}
    )
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    return data['choices'][0]['message']['content'].strip()

def find_subsequent_docs(block_timestamp, vault_path, window_hours=72):
    """找信息块产生后,W窗口内(默认72h=3轮×24h)知识库的新增/修改文档"""
    try:
        block_time = datetime.fromisoformat(block_timestamp.replace('Z', '+00:00'))
    except:
        return []

    cutoff_end = block_time + timedelta(hours=window_hours)
    subsequent = []

    for root, dirs, files in os.walk(vault_path):
        # 排除目录
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                   ('node_modules', '__pycache__', '00-archive', '.git', '.obsidian')]
        for fn in files:
            if not fn.endswith('.md'):
                continue
            fp = os.path.join(root, fn)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(fp)).astimezone()
                if block_time < mtime < cutoff_end:
                    subsequent.append(fp)
            except:
                continue
    return subsequent[:20]  # 限制数量,避免 prompt 过长

def read_doc_excerpt(filepath, max_chars=300):
    """读文档摘要(标题+首段)"""
    try:
        with open(filepath, encoding='utf-8') as f:
            text = f.read(max_chars * 2)
        import re
        tm = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
        title = tm.group(1).strip() if tm else os.path.basename(filepath)
        body_start = tm.end() if tm else 0
        first = text[body_start:body_start+300].strip()
        return title, first.replace('\n', ' ')[:200]
    except:
        return os.path.basename(filepath), '(无法读取)'

def llm_validate_block(block, vault_path):
    """
    LLM 回证:判断信息块在后续文档中是否被引用/复用。

    输入: block (dict,含 content_preview, source, rho_estimated, timestamp)
    返回: (u_observed, evidence, reasoning) 或 None(无法回证)
    """
    # 找后续文档
    subsequent = find_subsequent_docs(block.get('timestamp', ''), vault_path)
    if not subsequent:
        return (0.0, '无后续文档', 'W窗口内无新增文档,无法证明有用性')

    # 构建后续文档摘要
    doc_summaries = []
    for fp in subsequent[:10]:  # 最多10篇,控制 token
        title, excerpt = read_doc_excerpt(fp)
        doc_summaries.append('《%s》: %s' % (title, excerpt[:100]))

    # 信息块内容
    block_content = block.get('content_preview', '')[:200]
    block_source = block.get('source', '未知')

    # LLM prompt(让模型做语义判断,不给暗示)
    prompt = """你是信息密度实验的回证裁判。判断一个信息块在后续文档中是否真的被引用/复用/激活。

## 待回证的信息块
来源: %s
内容摘要: %s

## 后续产生的文档(W窗口内)
%s

## 判断任务
这个信息块的内容,是否在上述后续文档中被:
1. 直接引用(后续文档提到了相同的概念/结论/方法)
2. 间接复用(后续文档基于这个信息块的思路继续发展)
3. 完全未涉及(后续文档与这个信息块无关)

## 输出格式(严格)
u值: <0.0到1.0的数字>
证据: <哪些后续文档引用了,或为什么说无用>
置信: <high/medium/low>

u值标准: 1.0=明确引用, 0.5=间接复用, 0.3=隐式依赖, 0.0=未涉及
只输出这三行,不要其他内容。""" % (
        block_source,
        block_content,
        '\n'.join(doc_summaries)
    )

    try:
        result = call_glm(prompt, max_tokens=150)
        # 解析 LLM 输出
        u_value = 0.0
        evidence = ''
        confidence = 'low'

        for line in result.split('\n'):
            line = line.strip()
            if line.startswith('u值') or line.startswith('u值:'):
                try:
                    u_str = line.split(':', 1)[1].strip().rstrip('。')
                    u_value = float(u_str)
                    u_value = max(0.0, min(1.0, u_value))  # clamp
                except:
                    pass
            elif line.startswith('证据') or line.startswith('证据:'):
                evidence = line.split(':', 1)[1].strip() if ':' in line else line
            elif line.startswith('置信') or line.startswith('置信:'):
                confidence = line.split(':', 1)[1].strip() if ':' in line else 'low'

        return (u_value, evidence, confidence)
    except Exception as e:
        return (None, 'LLM调用失败: %s' % str(e)[:100], 'error')

def validate_pending_blocks(residual_series, vault_path, max_per_round=5):
    """
    回证所有到期的 pending 块(每轮最多5个,控成本)。
    修改 residual_series in-place(更新 u_observed/residual/validation_status)。
    """
    validated = 0
    current_cycle = residual_series[-1].get('cycle', 0) if residual_series else 0

    for block in residual_series:
        if block.get('validation_status') != 'pending':
            continue
        if block.get('validation_deadline', 999) > current_cycle:
            continue  # 还没到期
        if validated >= max_per_round:
            break  # 成本控制

        result = llm_validate_block(block, vault_path)
        if result and result[0] is not None:
            u, evidence, confidence = result
            block['u_observed'] = u
            block['u_source'] = 'LLM回证(GLM-5-turbo): ' + evidence[:100]
            block['u_round'] = current_cycle
            block['u_confidence'] = confidence
            block['residual'] = round(u - block.get('rho_estimated', 0), 3)
            block['validation_status'] = 'validated'
            validated += 1
            print('  ✅ 回证 %s: u=%.1f e=%.3f (%s)' % (
                block.get('block_id', '?')[:30], u, block['residual'], confidence))
        else:
            block['validation_status'] = 'validation_failed'
            block['u_source'] = 'LLM回证失败'
            print('  ❌ 回证失败: %s' % block.get('block_id', '?')[:30])

    return validated

if __name__ == '__main__':
    # 自测:用现有 residual-series 里的 pending 块测试
    series_path = os.environ.get('ENTROPY_RESIDUAL_PATH', r'[WORKSPACE]/density-experiment\residual-series.jsonl')
    vault = os.environ.get('ENTROPY_VAULT_PATH', r'[KNOWLEDGE_BASE]')

    blocks = []
    with open(series_path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    blocks.append(json.loads(line))
                except:
                    continue

    print('加载 %d 个信息块' % len(blocks))
    pending = [b for b in blocks if b.get('validation_status') == 'pending' or 'residual' not in b or b.get('residual') is None]
    print('待回证(pending/null residual): %d' % len(pending))

    if pending:
        # 测试第一个
        test_block = pending[0]
        print('\n测试回证: %s' % test_block.get('block_id', test_block.get('source', '?'))[:50])
        result = llm_validate_block(test_block, vault)
        if result and result[0] is not None:
            u, evidence, conf = result
            print('u_observed: %.2f' % u)
            print('证据: %s' % evidence[:150])
            print('置信: %s' % conf)
            print('residual: %.3f' % (u - test_block.get('rho_estimated', 0)))
        else:
            print('回证失败:', result)
