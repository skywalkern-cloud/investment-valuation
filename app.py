#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Entry Point - 云南锗业估值仪表盘
部署: Streamlit Community Cloud

打开: https://share.streamlit.io/skywalkern-cloud/investment-valuation/main
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Run the dashboard
from common.ui.dashboard import main

if __name__ == '__main__':
    main()