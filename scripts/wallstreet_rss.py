#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
华尔街见闻快讯抓取 - 基于wscn_cli.py
数据源: wscn_cli.py --json (调用华尔街见闻7x24快讯API)
"""

import json
import subprocess
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLI_SCRIPT = os.path.join(SCRIPT_DIR, 'wscn_cli.py')

def fetch_wallstreet_live(channel='要闻', count=10, important_only=False):
    """
    获取华尔街见闻7x24快讯
    
    Args:
        channel: 频道（要闻/美股/港股/外汇/商品/债券/科技）
        count: 获取条数
        important_only: 只看重要快讯
    
    Returns:
        list: 快讯列表，每条包含 id, datetime, content, score, uri
    """
    try:
        cmd = [sys.executable, CLI_SCRIPT, '-c', channel, '-n', str(count), '--json']
        if important_only:
            cmd.append('--important')
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"wscn_cli error: {result.stderr}")
            return []
        
        data = json.loads(result.stdout)
        return data
    except Exception as e:
        print(f"获取华尔街见闻快讯失败: {e}")
        return []

def fetch_wallstreet_important(count=10):
    """获取重要快讯（score >= 2）"""
    return fetch_wallstreet_live(channel='要闻', count=count, important_only=True)

if __name__ == '__main__':
    print(f"=== 华尔街见闻快讯 CLI ===\n")
    
    print("【重要快讯 Top10】")
    items = fetch_wallstreet_important(10)
    for i, item in enumerate(items, 1):
        score_icon = {2: '🔴', 3: '🔺'}.get(item.get('score', 1), '  ')
        print(f"{i}. {score_icon} {item.get('datetime')} - {item.get('content', '')[:60]}")
        print(f"   {item.get('uri', '')}")
        print()
