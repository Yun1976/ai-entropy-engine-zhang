#!/usr/bin/env python3
"""Python语法预检器 (Self-Harness自动修复生成)
在运行Python脚本前检查语法, 防止syntax_error"""
import sys, py_compile

def check_syntax(script_path):
    try:
        py_compile.compile(script_path, doraise=True)
        return True, None
    except py_compile.PyCompileError as e:
        return False, str(e)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('用法: syntax_checker.py <script.py>')
        sys.exit(1)
    ok, err = check_syntax(sys.argv[1])
    if ok:
        print(f'✓ {sys.argv[1]} 语法正确')
    else:
        print(f'✗ {sys.argv[1]} 语法错误: {err}')
        sys.exit(1)
