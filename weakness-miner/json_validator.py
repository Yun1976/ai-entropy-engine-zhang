#!/usr/bin/env python3
"""JSON格式校验器 (Self-Harness自动修复生成)
在解析JSON前检查格式, 防止json_parse_error"""
import json, sys

def validate_json(text):
    try:
        json.loads(text)
        return True, None
    except json.JSONDecodeError as e:
        return False, str(e)

def validate_file(filepath):
    try:
        with open(filepath, encoding='utf-8') as f:
            return validate_json(f.read())
    except Exception as e:
        return False, str(e)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('用法: json_validator.py <file.json 或 "json文本">')
        sys.exit(1)
    arg = sys.argv[1]
    if os.path.exists(arg):
        ok, err = validate_file(arg)
    else:
        ok, err = validate_json(arg)
    if ok:
        print('✓ JSON格式正确')
    else:
        print(f'✗ JSON格式错误: {err}')
        sys.exit(1)
