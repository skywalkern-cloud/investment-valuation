#!/usr/bin/env python3
"""华尔街见闻 7x24 快讯 CLI 工具"""

import argparse
import curses
import html
import json
import re
import sys
import time as _time
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

CHANNEL_MAP = {
    "要闻": "global-channel",
    "a股": "a-stock-channel",
    "美股": "us-stock-channel",
    "港股": "hk-stock-channel",
    "外汇": "forex-channel",
    "商品": "commodity-channel",
    "债券": "bond-channel",
    "科技": "tech-channel",
}

API_BASE = "https://api-one.wallstcn.com/apiv1/content/lives"


def display_width(s):
    """计算字符串的终端显示宽度（中文占2列）"""
    w = 0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            w += 2
        else:
            w += 1
    return w


def cjk_wrap(text, width, initial_indent="", subsequent_indent=""):
    """CJK 感知的文本换行，按显示宽度折行"""
    lines = []
    indent = initial_indent
    line = indent
    line_w = display_width(indent)
    for ch in text:
        ch_w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if line_w + ch_w > width:
            lines.append(line)
            indent = subsequent_indent
            line = indent + ch
            line_w = display_width(indent) + ch_w
        else:
            line += ch
            line_w += ch_w
    if line.strip():
        lines.append(line)
    return lines

MACRO_SUFFIX = {
    "US": "DXY.OTC",
    "CN": "USDCNH.OTC",
    "JP": "USDJPY.OTC",
    "UK": "UK100.OTC",
}


def html_to_text(s):
    """去除 HTML 标签，保留纯文本"""
    s = re.sub(r'<br\s*/?>','\n', s)
    s = re.sub(r'</p>\s*<p>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    return s.strip()
CST = timezone(timedelta(hours=8))


def fetch_page(channel, limit=50, cursor=None):
    """请求一页快讯数据"""
    url = f"{API_BASE}?channel={channel}&client=pc&limit={limit}"
    if cursor is None:
        url += "&first_page=true"
    else:
        url += f"&cursor={cursor}"

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    items = data.get("data", {}).get("items", [])
    next_cursor = data.get("data", {}).get("next_cursor")
    return items, next_cursor


def parse_time(s):
    """解析用户输入的时间字符串为 CST datetime"""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=CST)
        except ValueError:
            continue
    raise ValueError(f"无法解析时间: {s}，请使用 YYYY-MM-DD 或 YYYY-MM-DD HH:MM 格式")


def parse_item(item):
    """将 API 返回的单条快讯转为结果字典"""
    ts = item.get("display_time", 0)
    dt = datetime.fromtimestamp(ts, tz=CST)
    images = [img["uri"] for img in item.get("images", []) if img.get("uri")]
    content_html = item.get("content", "")
    content_more = item.get("content_more", "")
    if content_more:
        full_text = html_to_text(content_html + "\n" + content_more)
    else:
        full_text = item.get("content_text", "").strip()
    article_raw = item.get("article")
    article = None
    if article_raw:
        article = {
            "id": article_raw.get("id"),
            "title": article_raw.get("title", ""),
            "uri": article_raw.get("uri", ""),
        }
    # 财经日历字段
    calendar = None
    if item.get("is_calendar"):
        ticker = item.get("wscn_ticker", "")
        country = ticker[:2] if ticker else ""
        suffix = MACRO_SUFFIX.get(country, "DXY.OTC")
        calendar = {
            "wscn_ticker": ticker,
            "calendar_key": item.get("calendar_key", ""),
            "data_analyse_url": f"https://wallstreetcn.com/data-analyse/{ticker}/{suffix}" if ticker else "",
        }
    return {
        "time": dt.strftime("%H:%M:%S"),
        "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "content": full_text,
        "title": item.get("title", ""),
        "id": item.get("id", ""),
        "uri": item.get("uri", ""),
        "images": images,
        "score": item.get("score", 1),
        "article": article,
        "calendar": calendar,
    }


def fetch_by_ids(ids):
    """按 ID 列表逐条获取快讯"""
    results = []
    for live_id in ids:
        url = f"{API_BASE}/{live_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            item = data.get("data", {})
            if item:
                results.append(parse_item(item))
        except urllib.error.HTTPError as e:
            print(f"警告: ID {live_id} 获取失败 ({e.code})", file=sys.stderr)
    return results


def collect_news(channel, count=None, start=None, end=None, important=False):
    """收集快讯，支持按条数或按时间范围"""
    results = []
    cursor = None
    per_page = 50

    while True:
        items, next_cursor = fetch_page(channel, limit=per_page, cursor=cursor)
        if not items:
            break

        for item in items:
            ts = item.get("display_time", 0)
            dt = datetime.fromtimestamp(ts, tz=CST)

            # 按时间范围过滤
            if end and dt > end:
                continue
            if start and dt < start:
                # 已经早于开始时间，后续只会更早，停止
                return results

            if important and item.get("score", 1) < 2:
                continue

            results.append(parse_item(item))

            if count and len(results) >= count:
                return results

        if not next_cursor:
            break
        cursor = next_cursor

    return results


def print_news(news, channel_name, label):
    """终端格式化输出"""
    header = f"📡 华尔街见闻快讯 | 频道: {channel_name} | {label}"
    print(header)
    print("─" * 40)
    if not news:
        print("（无数据）")
        return
    for i, item in enumerate(news):
        if i > 0:
            print()
        time_str = f"\033[36m[{item['time']}]\033[0m"
        score = item.get("score", 1)
        if score >= 3:
            print(f"{time_str} \033[1;31m‼️  {item['content']}\033[0m")
        elif score == 2:
            print(f"{time_str} \033[31m🔴 {item['content']}\033[0m")
        else:
            print(f"{time_str} {item['content']}")
        for img in item.get("images", []):
            print(f"         \033[33m📷 {img}\033[0m")
        if item.get("article"):
            a = item["article"]
            print(f"         \033[35m📎 {a['title']}  {a['uri']}\033[0m")
        if item.get("calendar"):
            c = item["calendar"]
            print(f"         \033[32m📊 数据解读  {c['data_analyse_url']}\033[0m")


def render_item_lines(item, width):
    """将一条快讯渲染为多行纯文本 (tag, text) 列表，tag 用于上色"""
    lines = []
    score = item.get("score", 1)
    prefix = f"[{item['time']}] "
    if score >= 3:
        tag = "score3"
        prefix = f"[{item['time']}] ‼️  "
    elif score == 2:
        tag = "score2"
        prefix = f"[{item['time']}] 🔴 "
    else:
        tag = "normal"

    content = item.get("content", "")
    # 第一行带时间前缀，后续行缩进
    indent = "         "
    first = True
    for paragraph in content.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if first:
            wrapped = cjk_wrap(paragraph, width - 1,
                               initial_indent=prefix,
                               subsequent_indent=indent)
            first = False
        else:
            wrapped = cjk_wrap(paragraph, width - 1,
                               initial_indent=indent,
                               subsequent_indent=indent)
        for line in wrapped:
            lines.append((tag, line))

    for img in item.get("images", []):
        lines.append(("image", f"{indent}📷 {img}"))
    if item.get("article"):
        a = item["article"]
        lines.append(("article", f"{indent}📎 {a['title']}  {a['uri']}"))
    if item.get("calendar"):
        c = item["calendar"]
        lines.append(("calendar", f"{indent}📊 数据解读  {c['data_analyse_url']}"))

    return lines


WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def live_monitor(channel, channel_name, interval=15, important=False):
    """curses 实时监控模式"""

    def _main(stdscr):
        curses.curs_set(0)
        curses.use_default_colors()
        # 启用鼠标事件捕获，防止鼠标滚轮滚出 alternate screen
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        curses.init_pair(1, curses.COLOR_CYAN, -1)     # 时间/普通
        curses.init_pair(2, curses.COLOR_RED, -1)       # score2
        curses.init_pair(3, curses.COLOR_RED, -1)       # score3 bold
        curses.init_pair(4, curses.COLOR_YELLOW, -1)    # 图片
        curses.init_pair(5, curses.COLOR_MAGENTA, -1)   # 文章
        curses.init_pair(6, curses.COLOR_GREEN, -1)     # 状态栏
        curses.init_pair(7, curses.COLOR_WHITE, -1)     # NEW 标记

        TAG_ATTR = {
            "normal": curses.color_pair(1),
            "score2": curses.color_pair(2),
            "score3": curses.color_pair(3) | curses.A_BOLD,
            "image": curses.color_pair(4),
            "article": curses.color_pair(5),
            "calendar": curses.color_pair(6),
            "date": curses.color_pair(7) | curses.A_BOLD,
            "sep": curses.color_pair(0),
            "new": curses.color_pair(7) | curses.A_BOLD | curses.A_REVERSE,
        }

        curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_YELLOW)  # 搜索高亮

        last_key = -1       # 上一次按键，用于 gg 组合
        all_items = []      # 所有快讯，新的在前
        seen_ids = set()
        display_lines = []  # (tag, text) 渲染行
        scroll_pos = 0
        last_fetch = 0
        first_load = True
        new_ids = set()     # 本轮新增的 ID，用于高亮
        history_cursor = None  # 向下翻页加载历史用的 cursor
        loading_history = False
        error_msg = ""
        search_keyword = ""     # 当前搜索关键词
        search_matches = []     # 匹配行的索引列表
        search_match_idx = -1   # 当前匹配位置

        def refresh_data():
            """定时刷新最新数据"""
            nonlocal all_items, seen_ids, display_lines, last_fetch, first_load, new_ids, history_cursor, error_msg
            try:
                items_raw, next_cur = fetch_page(channel, limit=50)
                fetched = [parse_item(it) for it in items_raw]
                new_ids = set()
                for it in fetched:
                    if it["id"] not in seen_ids:
                        if not first_load:
                            new_ids.add(it["id"])
                        seen_ids.add(it["id"])
                # 首次加载记录 cursor
                if first_load:
                    history_cursor = next_cur
                first_load = False
                # 合并：新的在前，去重保持顺序
                merged = []
                merged_ids = set()
                for it in fetched + all_items:
                    if it["id"] not in merged_ids:
                        merged.append(it)
                        merged_ids.add(it["id"])
                all_items = merged
                error_msg = ""
            except Exception as e:
                error_msg = f"刷新失败: {e}"
            last_fetch = _time.time()
            rebuild_lines()

        def load_history():
            """滚到底部时加载更多历史数据"""
            nonlocal all_items, seen_ids, history_cursor, loading_history, error_msg
            if not history_cursor or loading_history:
                return
            loading_history = True
            try:
                items_raw, next_cur = fetch_page(channel, limit=50, cursor=history_cursor)
                fetched = [parse_item(it) for it in items_raw]
                for it in fetched:
                    if it["id"] not in seen_ids:
                        all_items.append(it)
                        seen_ids.add(it["id"])
                history_cursor = next_cur
                error_msg = ""
            except Exception as e:
                error_msg = f"加载历史失败: {e}"
            loading_history = False
            rebuild_lines()

        def rebuild_lines():
            nonlocal display_lines
            h, w = stdscr.getmaxyx()
            display_lines = []
            current_date = None
            first_item = True
            for it in all_items:
                if important and it.get("score", 1) < 2:
                    continue
                # 日期分隔线
                item_date = it["datetime"][:10]  # YYYY-MM-DD
                if item_date != current_date:
                    current_date = item_date
                    if not first_item:
                        # 跨天时插入日期分隔（第一天和顶部栏重复，跳过）
                        dt = datetime.strptime(item_date, "%Y-%m-%d")
                        wd = WEEKDAYS[dt.weekday()]
                        date_label = f"{dt.month:02d}月{dt.day:02d}日，{wd}"
                        display_lines.append(("sep", ""))
                        display_lines.append(("date", date_label))
                        display_lines.append(("sep", ""))
                else:
                    if not first_item:
                        display_lines.append(("sep", ""))
                first_item = False
                if it["id"] in new_ids and len(all_items) > len(new_ids):
                    display_lines.append(("new", " ★ NEW "))
                display_lines.extend(render_item_lines(it, w))
            if search_keyword:
                update_search()

        def update_search():
            """根据 search_keyword 更新匹配列表"""
            nonlocal search_matches, search_match_idx
            search_matches = []
            if not search_keyword:
                search_match_idx = -1
                return
            kw = search_keyword.lower()
            for i, (tag, text) in enumerate(display_lines):
                if tag != "sep" and kw in text.lower():
                    search_matches.append(i)
            search_match_idx = 0 if search_matches else -1

        def search_goto(idx):
            """跳转到第 idx 个匹配"""
            nonlocal scroll_pos, search_match_idx
            if not search_matches:
                return
            search_match_idx = idx % len(search_matches)
            h, _ = stdscr.getmaxyx()
            body_h = h - 4
            target = search_matches[search_match_idx]
            # 让匹配行出现在屏幕中间偏上
            scroll_pos = max(0, target - body_h // 3)
            max_scroll = max(0, len(display_lines) - body_h)
            scroll_pos = min(scroll_pos, max_scroll)

        def do_search_input():
            """在底部显示搜索输入框，返回输入的关键词（ESC 取消返回 None）"""
            nonlocal search_keyword
            curses.curs_set(1)
            h, w = stdscr.getmaxyx()
            prompt_y = h - 1
            buf = ""
            while True:
                # 画输入行
                try:
                    stdscr.move(prompt_y, 0)
                    stdscr.clrtoeol()
                    display = f"/{buf}"
                    stdscr.addnstr(prompt_y, 0, display, w - 1, curses.A_BOLD)
                except curses.error:
                    pass
                stdscr.refresh()

                ch = stdscr.getch()
                if ch == 27:  # ESC 取消
                    curses.curs_set(0)
                    return None
                elif ch in (curses.KEY_ENTER, 10, 13):  # Enter 确认
                    curses.curs_set(0)
                    return buf
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    buf = buf[:-1]
                elif 32 <= ch <= 126:
                    buf += chr(ch)
                else:
                    # 处理多字节 UTF-8 输入
                    try:
                        curses.ungetch(ch)
                        raw = stdscr.get_wch()
                        if isinstance(raw, str) and raw.isprintable():
                            buf += raw
                    except Exception:
                        pass

        def draw():
            stdscr.erase()
            h, w = stdscr.getmaxyx()

            # 顶部日期时间栏
            now_dt = datetime.now(CST)
            now_time = now_dt.strftime("%H:%M:%S")
            wd = WEEKDAYS[now_dt.weekday()]
            header = f" {now_dt.month:02d}月{now_dt.day:02d}日，{wd}，{now_time}"
            if important:
                header += "  | ★ 只看重要的"
            try:
                stdscr.addnstr(0, 0, header, w - 1, curses.color_pair(7) | curses.A_BOLD)
            except curses.error:
                pass
            try:
                stdscr.addnstr(1, 0, "─" * (w - 1), w - 1, curses.color_pair(6))
            except curses.error:
                pass

            # 状态栏（最后两行）
            status_y = h - 2
            body_start = 2
            body_h = status_y - body_start
            highlight_attr = curses.color_pair(8) | curses.A_BOLD
            match_set = set(search_matches) if search_keyword else set()
            current_match = search_matches[search_match_idx] if search_matches and search_match_idx >= 0 else -1

            # 绘制快讯内容
            for i in range(body_h):
                line_idx = scroll_pos + i
                if line_idx >= len(display_lines):
                    break
                tag, text = display_lines[line_idx]
                if line_idx in match_set:
                    if line_idx == current_match:
                        attr = highlight_attr
                    else:
                        attr = curses.color_pair(8)
                    try:
                        stdscr.addnstr(body_start + i, 0, text, w - 1, attr)
                    except curses.error:
                        pass
                else:
                    attr = TAG_ATTR.get(tag, 0)
                    try:
                        stdscr.addnstr(body_start + i, 0, text, w - 1, attr)
                    except curses.error:
                        pass

            # 分隔线
            try:
                stdscr.addnstr(status_y, 0, "─" * (w - 1), w - 1, curses.color_pair(6))
            except curses.error:
                pass

            # 状态信息
            total = len(all_items)
            countdown = max(0, int(interval - (_time.time() - last_fetch)))
            status = f" 📡 {channel_name} | 共 {total} 条 | {countdown}s 后刷新 | ↑↓翻页 /搜索 q退出"
            if search_keyword:
                mi = search_match_idx + 1 if search_matches else 0
                status += f" | 🔍 \"{search_keyword}\" [{mi}/{len(search_matches)}]"
            if error_msg:
                status += f" | ⚠ {error_msg}"
            try:
                stdscr.addnstr(status_y + 1, 0, status, w - 1, curses.color_pair(6) | curses.A_BOLD)
            except curses.error:
                pass

            stdscr.refresh()

        # 首次加载
        refresh_data()
        stdscr.timeout(200)  # 200ms 轮询键盘

        while True:
            draw()
            key = stdscr.getch()
            h, w = stdscr.getmaxyx()
            body_h = h - 4  # 顶部2行 + 底部2行
            max_scroll = max(0, len(display_lines) - body_h)

            if key == 27:  # ESC
                if search_keyword:
                    search_keyword = ""
                    search_matches = []
                    search_match_idx = -1
                else:
                    break
            elif key == ord('q') or key == ord('Q'):
                break
            elif key == curses.KEY_UP or key == ord('k'):
                if scroll_pos == 0:
                    if _time.time() - last_fetch >= 3:
                        refresh_data()
                else:
                    scroll_pos = max(0, scroll_pos - 1)
            elif key == curses.KEY_DOWN or key == ord('j'):
                scroll_pos = min(max_scroll, scroll_pos + 1)
            elif key == curses.KEY_MOUSE:
                try:
                    _, _, _, _, bstate = curses.getmouse()
                    if bstate & curses.BUTTON4_PRESSED:  # 滚轮上
                        scroll_pos = max(0, scroll_pos - 3)
                    elif bstate & curses.BUTTON5_PRESSED:  # 滚轮下
                        scroll_pos = min(max_scroll, scroll_pos + 3)
                except curses.error:
                    pass
            elif key == curses.KEY_PPAGE:  # Page Up
                scroll_pos = max(0, scroll_pos - body_h)
            elif key == curses.KEY_NPAGE:  # Page Down
                scroll_pos = min(max_scroll, scroll_pos + body_h)
            elif key == ord('g'):
                if last_key == ord('g'):  # gg 回到顶部
                    scroll_pos = 0
            elif key == ord('G'):  # 跳到底部
                scroll_pos = max_scroll
            elif key == ord('/'):  # 搜索
                kw = do_search_input()
                if kw is not None:
                    search_keyword = kw
                    update_search()
                    if search_matches:
                        search_goto(0)
            elif key == ord('n'):  # 下一个匹配
                if search_matches:
                    search_goto(search_match_idx + 1)
            elif key == ord('N'):  # 上一个匹配
                if search_matches:
                    search_goto(search_match_idx - 1)
            elif key == curses.KEY_RESIZE:
                rebuild_lines()
                if search_keyword:
                    update_search()

            # 已在底部再按下键时加载更多历史
            if (key in (curses.KEY_DOWN, ord('j'), curses.KEY_NPAGE)
                    and scroll_pos >= max_scroll and max_scroll > 0 and history_cursor):
                load_history()

            last_key = key

            # 定时刷新
            if _time.time() - last_fetch >= interval:
                old_count = len(all_items)
                refresh_data()
                if len(all_items) > old_count:
                    scroll_pos = 0  # 有新内容自动回顶部

    curses.wrapper(_main)


def main():
    parser = argparse.ArgumentParser(description="华尔街见闻 7x24 快讯")
    parser.add_argument("-c", "--channel", default="要闻",
                        help=f"频道: {'/'.join(CHANNEL_MAP.keys())}（默认: 要闻）")
    parser.add_argument("-n", "--count", type=int, default=20,
                        help="获取条数（默认: 20）")
    parser.add_argument("--start", help="开始时间 (YYYY-MM-DD 或 YYYY-MM-DD HH:MM)")
    parser.add_argument("--end", help="结束时间 (YYYY-MM-DD 或 YYYY-MM-DD HH:MM)")
    parser.add_argument("--today", action="store_true", help="只获取今天的快讯")
    parser.add_argument("--important", action="store_true",
                        help="只看重要快讯（score > 1）")
    parser.add_argument("--live", action="store_true",
                        help="持续监控模式，每 15 秒刷新，ESC/q 退出")
    parser.add_argument("--interval", type=int, default=15,
                        help="监控模式刷新间隔秒数（默认: 15）")
    parser.add_argument("--id", nargs="+", dest="ids",
                        help="按 ID 获取，支持一个或多个 ID")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="以 JSON 格式输出")
    args = parser.parse_args()

    # 按 ID 获取模式
    if args.ids:
        try:
            news = fetch_by_ids(args.ids)
        except urllib.error.URLError as e:
            print(f"网络错误: {e}", file=sys.stderr)
            sys.exit(1)
        if args.json_output:
            print(json.dumps(news, ensure_ascii=False, indent=2))
        else:
            print_news(news, "—", f"指定 ID ({len(news)} 条)")
        return

    # 频道映射
    ch_key = args.channel.lower()
    channel = CHANNEL_MAP.get(ch_key)
    if not channel:
        print(f"错误: 未知频道 '{args.channel}'，可选: {'/'.join(CHANNEL_MAP.keys())}", file=sys.stderr)
        sys.exit(1)

    # 持续监控模式
    if args.live:
        live_monitor(channel, args.channel, interval=args.interval, important=args.important)
        return

    # 时间参数处理
    start, end, count = None, None, args.count
    if args.today:
        now = datetime.now(CST)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = None
        count = None  # 今天模式不限条数
    elif args.start or args.end:
        if args.start:
            start = parse_time(args.start)
        if args.end:
            end = parse_time(args.end)
            # 如果只给了日期没给时间，end 设为当天末尾
            if len(args.end) <= 10:
                end = end.replace(hour=23, minute=59, second=59)
        count = None  # 时间模式不限条数

    # 抓取
    try:
        news = collect_news(channel, count=count, start=start, end=end, important=args.important)
    except urllib.error.URLError as e:
        print(f"网络错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 输出
    if args.json_output:
        print(json.dumps(news, ensure_ascii=False, indent=2))
    else:
        if args.today:
            label = "今日快讯"
        elif start or end:
            parts = []
            if start:
                parts.append(f"从 {start.strftime('%Y-%m-%d %H:%M')}")
            if end:
                parts.append(f"到 {end.strftime('%Y-%m-%d %H:%M')}")
            label = " ".join(parts)
        else:
            label = f"最新 {args.count} 条"
        print_news(news, args.channel, label)


if __name__ == "__main__":
    main()
