import sqlite3
import os
import time
from datetime import datetime

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

# ==========================================
#      ✨ 插件元数据 & 帮助信息 ✨
# ==========================================
__plugin_meta__ = PluginMetadata(
    name="看看群U发言(Pro Max)",
    description="全能群聊数据统计，支持日/月/年维度的流量分析",
    usage="""
📊【看看群U发言 Pro Max - 使用帮助】

👥 群友指令：
1. 今日发言 / 本月发言 / 今年发言
   ➤ 查看本群内的龙王排行榜 (Top 10)

👑 管理员指令 (Superuser)：
1. 今日DAU (别名: 全群统计)
   ➤ 查看今日实时数据、流量、活跃榜单
2. 本月DAU (别名: 本月统计)
   ➤ 查看本月累计数据、日均流量、月度榜单
3. 今年DAU (别名: 年度统计)
   ➤ 查看今年累计数据、年度榜单
""".strip(),
    type="application",
    supported_adapters={"~onebot.v11"},
)

# === 数据库配置 ===
DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")

# =======================
#      第一部分：数据库核心
# =======================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 1. 群消息统计表
    c.execute('''CREATE TABLE IF NOT EXISTS msg_stats
                 (date TEXT, group_id TEXT, user_id TEXT, count INTEGER, 
                 PRIMARY KEY (date, group_id, user_id))''')
    
    # 2. 私聊消息统计表
    c.execute('''CREATE TABLE IF NOT EXISTS private_stats
                 (date TEXT, user_id TEXT, count INTEGER,
                 PRIMARY KEY (date, user_id))''')

    # 3. 时段统计表
    c.execute('''CREATE TABLE IF NOT EXISTS hourly_stats
                 (date TEXT, hour INTEGER, count INTEGER,
                 PRIMARY KEY (date, hour))''')
                 
    # 4. 流量统计表 (新增: 记录字符总数)
    c.execute('''CREATE TABLE IF NOT EXISTS traffic_stats
                 (date TEXT PRIMARY KEY, total_chars INTEGER)''')
                 
    conn.commit()
    conn.close()

init_db()

def update_traffic(date_str: str, char_count: int):
    """更新流量记录"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO traffic_stats VALUES (?, 0)", (date_str,))
        c.execute("UPDATE traffic_stats SET total_chars = total_chars + ? WHERE date=?", (char_count, date_str))
        conn.commit()
    except:
        pass
    finally:
        conn.close()

def record_group_msg(group_id: str, user_id: str, msg_len: int):
    """记录群消息"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    hour = now.hour
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        # 消息数
        c.execute("INSERT OR IGNORE INTO msg_stats VALUES (?, ?, ?, 0)", (today, group_id, user_id))
        c.execute("UPDATE msg_stats SET count = count + 1 WHERE date=? AND group_id=? AND user_id=?", 
                  (today, group_id, user_id))
        # 时段
        c.execute("INSERT OR IGNORE INTO hourly_stats VALUES (?, ?, 0)", (today, hour))
        c.execute("UPDATE hourly_stats SET count = count + 1 WHERE date=? AND hour=?", (today, hour))
        conn.commit()
    except:
        pass
    finally:
        conn.close()
    
    # 记录流量
    update_traffic(today, msg_len)

def record_private_msg(user_id: str, msg_len: int):
    """记录私聊消息"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    hour = now.hour

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO private_stats VALUES (?, ?, 0)", (today, user_id))
        c.execute("UPDATE private_stats SET count = count + 1 WHERE date=? AND user_id=?", 
                  (today, user_id))
        c.execute("INSERT OR IGNORE INTO hourly_stats VALUES (?, ?, 0)", (today, hour))
        c.execute("UPDATE hourly_stats SET count = count + 1 WHERE date=? AND hour=?", (today, hour))
        conn.commit()
    except:
        pass
    finally:
        conn.close()
    
    # 记录流量
    update_traffic(today, msg_len)

# --- 数据查询接口 ---

def get_group_rank(group_id: str, mode: str):
    """获取单群排行榜 (Top 10)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")
    year = datetime.now().strftime("%Y")

    sql = ""
    params = ()
    if mode == "day":
        sql = "SELECT user_id, count FROM msg_stats WHERE group_id=? AND date=? ORDER BY count DESC LIMIT 10"
        params = (group_id, today)
    elif mode == "month":
        sql = "SELECT user_id, SUM(count) as total FROM msg_stats WHERE group_id=? AND date LIKE ? GROUP BY user_id ORDER BY total DESC LIMIT 10"
        params = (group_id, f"{month}%")
    elif mode == "year":
        sql = "SELECT user_id, SUM(count) as total FROM msg_stats WHERE group_id=? AND date LIKE ? GROUP BY user_id ORDER BY total DESC LIMIT 10"
        params = (group_id, f"{year}%")

    c.execute(sql, params)
    data = c.fetchall()
    conn.close()
    return data

def get_admin_dashboard_data(mode: str = "day"):
    """
    获取管理员面板所需的所有数据
    mode: 'day', 'month', 'year'
    """
    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")
    year = datetime.now().strftime("%Y")
    
    date_condition = ""
    params = ()
    
    if mode == "day":
        date_condition = "date=?"
        params = (today,)
    elif mode == "month":
        date_condition = "date LIKE ?"
        params = (f"{month}%",)
    elif mode == "year":
        date_condition = "date LIKE ?"
        params = (f"{year}%",)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    data = {}
    
    # 1. 活跃用户数 (去重)
    c.execute(f"SELECT COUNT(DISTINCT user_id) FROM msg_stats WHERE {date_condition}", params)
    group_u = c.fetchone()[0] or 0
    c.execute(f"SELECT COUNT(DISTINCT user_id) FROM private_stats WHERE {date_condition}", params)
    priv_u = c.fetchone()[0] or 0
    data['active_users'] = group_u + priv_u # 近似值，简单相加
    
    # 2. 活跃群聊数
    c.execute(f"SELECT COUNT(DISTINCT group_id) FROM msg_stats WHERE {date_condition}", params)
    data['active_groups'] = c.fetchone()[0] or 0
    
    # 3. 消息总数
    c.execute(f"SELECT SUM(count) FROM msg_stats WHERE {date_condition}", params)
    data['total_group_msg'] = c.fetchone()[0] or 0
    
    c.execute(f"SELECT SUM(count) FROM private_stats WHERE {date_condition}", params)
    data['total_private_msg'] = c.fetchone()[0] or 0
    
    data['total_all_msg'] = data['total_group_msg'] + data['total_private_msg']

    # 4. 流量统计 (字符数)
    c.execute(f"SELECT SUM(total_chars) FROM traffic_stats WHERE {date_condition}", params)
    data['total_chars'] = c.fetchone()[0] or 0

    # 5. 最活跃时段 (仅限日榜)
    if mode == "day":
        c.execute("SELECT hour, count FROM hourly_stats WHERE date=? ORDER BY count DESC LIMIT 1", (today,))
        peak = c.fetchone()
        data['peak_str'] = f"{peak[0]}点 ({peak[1]}条)" if peak else "无数据"
    else:
        # 月/年榜显示日均
        days_passed = int(datetime.now().day) if mode == "month" else int(datetime.now().strftime("%j"))
        avg_msg = int(data['total_all_msg'] / max(1, days_passed))
        data['peak_str'] = f"日均 {avg_msg} 条"

    # 6. 最活跃群组 Top 10 (改成了10)
    c.execute(f"SELECT group_id, SUM(count) as total FROM msg_stats WHERE {date_condition} GROUP BY group_id ORDER BY total DESC LIMIT 10", params)
    data['top_groups'] = c.fetchall()

    # 7. 全局最活跃用户 Top 10 (改成了10)
    c.execute(f"SELECT user_id, SUM(count) as total FROM msg_stats WHERE {date_condition} GROUP BY user_id ORDER BY total DESC LIMIT 10", params)
    data['top_users'] = c.fetchall()
    
    conn.close()
    return data

def format_number(num: int):
    """数字格式化，超过1万显示1.2w"""
    if num >= 10000:
        return f"{num/10000:.1f}w"
    return str(num)

# =======================
#      第二部分：监听逻辑
# =======================

group_recorder = on_message(priority=0, block=False)
@group_recorder.handle()
async def _(event: GroupMessageEvent):
    msg_len = len(str(event.message))
    record_group_msg(str(event.group_id), str(event.user_id), msg_len)

private_recorder = on_message(priority=0, block=False)
@private_recorder.handle()
async def _(event: PrivateMessageEvent):
    msg_len = len(str(event.message))
    record_private_msg(str(event.user_id), msg_len)


# =======================
#      第三部分：指令逻辑
# =======================

# --- 普通群友指令 ---
cmd_day = on_command("今日发言", aliases={"今日排行榜"}, priority=5, block=True)
cmd_month = on_command("本月发言", aliases={"本月排行榜"}, priority=5, block=True)
cmd_year = on_command("今年发言", aliases={"今年排行榜"}, priority=5, block=True)

async def send_group_rank(bot: Bot, event: GroupMessageEvent, mode: str, title: str):
    group_id = str(event.group_id)
    data = get_group_rank(group_id, mode)
    if not data:
        await cmd_day.finish(f"📊 {title}\n" + "-"*15 + "\n暂无数据，快来水群！")
        return

    msg = [f"📊 {title} (Top 10)", "-" * 20]
    for i, (uid, count) in enumerate(data):
        rank = i + 1
        icon = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")
        try:
            info = await bot.get_group_member_info(group_id=int(group_id), user_id=int(uid))
            name = info.get("card") or info.get("nickname") or str(uid)
        except:
            name = str(uid)
        msg.append(f"{icon} {name} ({count})")
    
    msg.append("-" * 20)
    msg.append(f"⏱ 统计时间: {datetime.now().strftime('%H:%M')}")
    await cmd_day.finish("\n".join(msg))

@cmd_day.handle()
async def _(bot: Bot, event: GroupMessageEvent): await send_group_rank(bot, event, "day", "今日龙王榜")
@cmd_month.handle()
async def _(bot: Bot, event: GroupMessageEvent): await send_group_rank(bot, event, "month", "本月龙王榜")
@cmd_year.handle()
async def _(bot: Bot, event: GroupMessageEvent): await send_group_rank(bot, event, "year", "年度龙王榜")


# --- 超级管理员指令 (高端面板) ---

admin_day = on_command("今日DAU", aliases={"全群统计", "bot数据"}, permission=SUPERUSER, priority=1, block=True)
admin_month = on_command("本月DAU", aliases={"本月统计"}, permission=SUPERUSER, priority=1, block=True)
admin_year = on_command("今年DAU", aliases={"年度统计"}, permission=SUPERUSER, priority=1, block=True)

async def send_admin_dashboard(bot: Bot, mode: str, title_prefix: str):
    start_time = time.time()
    
    # 1. 获取数据
    data = get_admin_dashboard_data(mode)
    
    # 2. 构建消息头
    traffic_mb = data['total_chars'] / 1024 / 1024
    traffic_str = f"{traffic_mb:.2f}MB" if traffic_mb > 1 else f"{data['total_chars']/1024:.2f}KB"
    if data['total_chars'] < 1024: traffic_str = f"{data['total_chars']}字符"

    msg = []
    msg.append(f"📊 {title_prefix} 活跃概览")
    msg.append(f"👥 活跃群聊: {data['active_groups']}")
    msg.append(f"👤 活跃用户: {format_number(data['active_users'])}")
    msg.append(f"💬 消息总数: {format_number(data['total_all_msg'])}")
    msg.append(f"📡 流量记录: {traffic_str} (估算)")
    
    # 根据模式显示不同指标
    if mode == "day":
        msg.append(f"⏰ 爆发时段: {data['peak_str']}")
    else:
        msg.append(f"📅 平均热度: {data['peak_str']}")
        
    msg.append("") 

    # 3. 最活跃群组 Top 10
    msg.append(f"🔝 最活跃群组 (Top 10):")
    for i, (gid, count) in enumerate(data['top_groups']):
        try:
            g_info = await bot.get_group_info(group_id=int(gid))
            g_name = g_info.get("group_name", str(gid))
        except:
            g_name = "未知群聊"
        msg.append(f"{i+1}. {g_name} ({gid}) - {format_number(count)}")
        
    msg.append("") 

    # 4. 最活跃用户 Top 10
    msg.append(f"👑 全局卷王 (Top 10):")
    for i, (uid, count) in enumerate(data['top_users']):
        try:
            u_info = await bot.get_stranger_info(user_id=int(uid))
            u_name = u_info.get("nickname", str(uid))
        except:
            u_name = "未知用户"
        msg.append(f"{i+1}. {u_name} ({uid}) - {format_number(count)}")

    # 5. 底部
    end_time = time.time()
    cost_ms = int((end_time - start_time) * 1000)
    
    msg.append("")
    msg.append(f"⏱ 查询: {cost_ms}ms | 源: SQLite")
    
    # 这里用 admin_day 发送，因为三个指令公用一个发送逻辑
    await admin_day.finish("\n".join(msg))

@admin_day.handle()
async def _(bot: Bot):
    today_str = datetime.now().strftime("%m-%d")
    await send_admin_dashboard(bot, "day", f"{today_str} 今日")

@admin_month.handle()
async def _(bot: Bot):
    month_str = datetime.now().strftime("%Y-%m")
    await send_admin_dashboard(bot, "month", f"{month_str} 本月")

@admin_year.handle()
async def _(bot: Bot):
    year_str = datetime.now().strftime("%Y年")
    await send_admin_dashboard(bot, "year", f"{year_str} 年度")