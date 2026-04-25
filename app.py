#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Entry Point - 云南锗业估值仪表盘
部署: Streamlit Community Cloud
"""

import sys
import os

# Change to repo root (where this file lives)
repo_root = os.path.dirname(os.path.abspath(__file__))
os.chdir(repo_root)
sys.path.insert(0, repo_root)

# Run the dashboard
from common.ui.dashboard import main

if __name__ == '__main__':
    main()