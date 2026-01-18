import streamlit as st
import pandas as pd
import akshare as ak
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
import time
import re
import json

# === 页面配置 ===
st.set_page_config(
    page_title="纳指ETF(159941) 决策系统",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# === 样式配置 ===
COLOR_BUY_BG = "#6B8E23"    # 橄榄绿
COLOR_BUY_TEXT = "#FFFFFF"  # 白
COLOR_RT_BG = "#D6DCE5"     # 淡蓝灰

# === 网络请求增强模块 (核心修复) ===
def get_robust_session():
    """创建一个带有自动重试功能的 Session"""
    session = requests.Session()
    # 设置重试策略：总共重试3次，退避系数1(即间隔1s, 2s, 4s再试)，针对常见的500/502/503错误和连接错误
    retries = Retry(
        total=3,
        backoff_factor=1, 
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    # 将重试策略挂载到 http 和 https
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # 设置通用浏览器头
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive"
    })
    return session

# 初始化全局 session
http = get_robust_session()

# === 数据获取函数 (带缓存 + 增强网络) ===

@st.cache_data(ttl=60)
def get_tiantian_valuation(code="159941"):
    """获取天天基金实时估值"""
    try:
        timestamp = int(time.time() * 1000)
        url = f"http://fundgz.1234567.com.cn/js/{code}.js?rt={timestamp}"
        
        # 使用增强 session，超时设置为 15秒
        r = http.get(url, timeout=15)
        
        if r.status_code == 200:
            match = re.search(r'jsonpgz\((.*?)\);', r.text)
            if match:
                data = json.loads(match.group(1))
                val = data.get("gsz", data.get("dwjz", None))
                if val: return float(val)
        return 0.0
    except Exception as e:
        # 记录错误但不阻断，返回0让流程继续
        print(f"Valuation Error: {e}")
        return 0.0

@st.cache_data(ttl=60)
def get_realtime_data(code="159941"):
    """获取实时价格与溢价率"""
    price = 0.0
    premium = 0.0
    valuation = 0.0
    
    # 1. 获取估值 (优先获取，因为比较容易)
    valuation = get_tiantian_valuation(code)
    
    # 2. 获取现价
    try:
        # 使用 e1 接口可能比 push2 更稳定一些，或者继续用 push2 但加长超时
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "invt": "2", 
            "fltt": "2", 
            "secid": f"0.{code}", 
            "fields": "f43"
        }
        # 超时时间加长到 20秒
        r = http.get(url, params=params, timeout=20)
        data_json = r.json()
        
        if data_json.get("data"):
            p_str = str(data_json["data"].get("f43", "-"))
            price = float(p_str) if p_str != "-" else 0.0
        else:
            # 如果 push2 失败，尝试备用接口 (快照接口)
            url_backup = f"http://quote.eastmoney.com/{code}.html" # 仅作示例，实际API切换逻辑较复，这里主要靠重试
            pass

    except Exception as e:
        st.toast(f"获取现价超时: {str(e)}", icon="⚠️")

    # 3. 计算溢价
    if price > 0 and valuation > 0:
        premium = ((price - valuation) / valuation) * 100
        
    return price, premium, valuation

@st.cache_data(ttl=3600)
def get_historical_nav_map(code="159941"):
    try:
        # Akshare 内部使用了 requests，我们尽量捕获它的超时
        # 增加一个全局超时设置给 akshare (如果支持) 或者直接调用
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        df['净值日期'] = df['净值日期'].astype(str)
        nav_map = dict(zip(df['净值日期'], df['单位净值']))
        return nav_map
    except Exception:
        return {}

@st.cache_data(ttl=300)
def get_kline_data(code="159941"):
    try:
        # K线数据量大，更容易超时，这里不做特殊处理，依赖 akshare 自身的重试
        # 如果 akshare 经常报错，可能需要自己写 requests 请求 K线 API
        hist_df = ak.fund_etf_hist_em(symbol=code, period="weekly", adjust="")
        hist_df = hist_df.loc[:, ~hist_df.columns.duplicated()]
        hist_df['M20'] = hist_df['收盘'].rolling(window=20).mean()
        hist_df = hist_df.sort_values(by='日期', ascending=False).reset_index(drop=True)
        return hist_df
    except Exception as e:
        print(f"K-Line Error: {e}")
        return pd.DataFrame()

# === 主逻辑处理 ===

def calculate_analysis(cost, qty):
    # 并行或串行获取数据
    # 为防止云端线程池限制，保持串行但有缓存
    
    # 提示用户进度
    status_text = st.empty()
    status_text.text("正在连接天天基金获取估值...")
    current_price, current_premium, current_valuation = get_realtime_data()
    
    if current_price == 0:
        status_text.error("无法连接到行情服务器，请刷新页面重试 (可能因网络波动)。")
        return pd.DataFrame()
        
    status_text.text("正在获取历史K线数据...")
    hist_df = get_kline_data()
    
    if hist_df.empty:
        status_text.error("K线数据获取失败，请稍后重试。")
        return pd.DataFrame()
        
    status_text.text("正在匹配历史净值...")
    nav_map = get_historical_nav_map()
    
    status_text.empty() # 清除进度提示

    rows = []
    
    # === 实时行 ===
    latest_k_m20 = float(hist_df.iloc[0]['M20'])
    prev_k_m20 = float(hist_df.iloc[1]['M20'])
    
    is_above_m20 = current_price > latest_k_m20
    is_m20_up = latest_k_m20 > prev_k_m20
    
    profit_str = f"{(current_price - cost)/cost*100:.2f}%" if cost > 0 else "-"
    m20_diff_str = f"{(latest_k_m20 - cost)/cost*100:.2f}%" if cost > 0 else "-"
    
    reasons = []
    can_buy = True
    if current_premium >= 1.0: can_buy=False; reasons.append(f"溢价高({current_premium:.2f}%)")
    if not is_above_m20: can_buy=False; reasons.append("低于M20")
    if not is_m20_up: can_buy=False; reasons.append("M20未向上")
    if cost > 0 and ((current_price - cost)/cost*100) <= -8.0: can_buy=False; reasons.append("亏损超8%")

    rows.append({
        "type": "realtime",
        "时间": f"{datetime.now().strftime('%m-%d %H:%M')} (实时)",
        "溢价率": f"{current_premium:.3f}%",
        "现价": current_price,
        "周M20": f"{latest_k_m20:.3f}",
        "在M20上": "是" if is_above_m20 else "否",
        "M20向上": "是" if is_m20_up else "否",
        "收益": profit_str,
        "比对M20": m20_diff_str,
        "判定": "符合条件" if can_buy else "不符合",
        "理由": "" if can_buy else "，".join(reasons),
        "is_buy": can_buy
    })

    # === 历史行 (50周) ===
    for i in range(51):
        if i >= len(hist_df) - 1: break
        
        row = hist_df.iloc[i]
        prev_row = hist_df.iloc[i+1]
        
        raw_date = str(row['日期']).split()[0]
        h_price = float(row['收盘'])
        h_m20 = float(row['M20']) if pd.notna(row['M20']) else None
        
        h_premium_val = None
        if raw_date in nav_map:
            nav = float(nav_map[raw_date])
            if nav > 0: h_premium_val = (h_price - nav) / nav * 100
        elif i == 0 and current_valuation > 0:
            h_premium_val = (h_price - current_valuation) / current_valuation * 100
        
        h_premium_str = f"{h_premium_val:.3f}%" if h_premium_val is not None else "--"
        
        h_m20_up = False
        if h_m20 and pd.notna(prev_row['M20']):
            h_m20_up = h_m20 > float(prev_row['M20'])
        
        h_above_m20 = h_price > h_m20 if h_m20 else False
        
        h_prof = f"{(h_price-cost)/cost*100:.2f}%" if cost > 0 else "-"
        h_diff = f"{(h_m20-cost)/cost*100:.2f}%" if cost > 0 and h_m20 else "-"
        
        h_buy = True
        h_rsn = []
        if h_premium_val is not None and h_premium_val >= 1.0: h_buy=False; h_rsn.append("溢价高")
        if not h_above_m20: h_buy=False; h_rsn.append("低于M20")
        if not h_m20_up: h_buy=False; h_rsn.append("M20向下")
        if cost > 0 and ((h_price-cost)/cost*100) <= -8.0: h_buy=False; h_rsn.append("亏损超8%")
        
        rows.append({
            "type": "history",
            "时间": raw_date,
            "溢价率": h_premium_str,
            "现价": h_price,
            "周M20": f"{h_m20:.3f}" if h_m20 else "-",
            "在M20上": "是" if h_above_m20 else "否",
            "M20向上": "是" if h_m20_up else "否",
            "收益": h_prof,
            "比对M20": h_diff,
            "判定": "符合" if h_buy else "不符合",
            "理由": "" if h_buy else "，".join(h_rsn),
            "is_buy": h_buy
        })
        
    return pd.DataFrame(rows)

# === 界面渲染 ===

st.title("📊 纳指ETF(159941) 决策系统")
st.markdown("---")

with st.sidebar:
    st.header("⚙️ 参数设置")
    cost_input = st.number_input("买入成本 (元)", min_value=0.0, value=0.0, step=0.001, format="%.3f")
    qty_input = st.number_input("持有数量 (股)", min_value=0, value=0, step=100)
    
    st.markdown("### 💡 决策标准")
    st.markdown("- 溢价率 < 1%")
    st.markdown("- 现价 > 周M20")
    st.markdown("- 周M20 趋势向上")
    
    # 使用回调函数处理按钮点击，避免页面重载逻辑错误
    if st.button("🔄 同步并分析数据", type="primary", use_container_width=True):
        st.session_state['refresh'] = True

if st.session_state.get('refresh', False):
    df = calculate_analysis(cost_input, qty_input)
    
    if not df.empty:
        realtime_row = df.iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.metric("当前现价", f"¥{realtime_row['现价']}")
        with c2: st.metric("实时溢价率", realtime_row['溢价率'], delta="-高" if "高" in realtime_row['理由'] else "正常", delta_color="inverse")
        with c3: st.metric("周M20", realtime_row['周M20'])
        with c4: 
            is_ok = realtime_row['is_buy']
            st.metric("综合判定", "可买入" if is_ok else "观望", delta="✅" if is_ok else "⛔", delta_color="normal")

        def highlight_rows(row):
            styles = [''] * len(row)
            bg_color = ""
            font_color = ""
            font_weight = ""
            if row['is_buy']:
                bg_color = COLOR_BUY_BG
                font_color = COLOR_BUY_TEXT
                font_weight = "bold"
            elif row['type'] == 'realtime':
                bg_color = COLOR_RT_BG
                font_weight = "bold"
            
            for i in range(len(row)):
                css = ""
                if bg_color: css += f"background-color: {bg_color}; "
                if font_color: css += f"color: {font_color}; "
                if font_weight: css += f"font-weight: {font_weight}; "
                styles[i] = css
            return styles

        display_df = df.drop(columns=['type', 'is_buy'])
        styled_df = df.style.apply(highlight_rows, axis=1).format({"现价": "{:.3f}"})

        st.markdown("### 📋 详细分析报表 (过去50周)")
        st.dataframe(
            styled_df, 
            use_container_width=True, 
            height=800,
            column_config={
                "type": None, 
                "is_buy": None,
                "理由": st.column_config.TextColumn("详细理由", width="medium"),
                "判定": st.column_config.TextColumn("判定", width="small"),
            }
        )
else:
    st.info("👈 请在左侧侧边栏点击“同步并分析数据”按钮。")
