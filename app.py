import streamlit as st
import akshare as ak
import pandas as pd
from datetime import datetime

# ========== 页面基础设置 ==========
st.set_page_config(
    page_title="纳指ETF 159941 交易系统",
    layout="wide"
)

# 莫兰迪风格简单 CSS
st.markdown("""
<style>
body { background-color: #f5f5f5; }
[data-testid="stDataFrame"] { font-size: 16px; }
.highlight { background-color: #d8e3dc; }
</style>
""", unsafe_allow_html=True)

st.title("📈 纳指ETF（159941）周线交易系统")

# ========== 侧边栏：买入信息 ==========
st.sidebar.header("📌 买入信息（可选）")

cost = st.sidebar.number_input(
    "买入成本（元）",
    min_value=0.0,
    step=0.01
)

qty = st.sidebar.number_input(
    "买入数量（份）",
    min_value=0,
    step=100
)

use_position = cost > 0 and qty > 0

# ========== 获取数据按钮 ==========
if st.button("🔄 同步最新数据"):

    with st.spinner("正在同步数据，请稍等..."):

        # -------- ETF 实时行情 --------
        spot = ak.fund_etf_spot_em()
        etf = spot[spot["代码"] == "159941"].iloc[0]

        current_price = round(float(etf["最新价"]), 3)
        premium = round(float(etf["溢价率"].replace("%", "")), 3)

        # -------- 周K数据 --------
        hist = ak.fund_etf_hist_em(
            symbol="159941",
            period="weekly",
            adjust="qfq"
        )

        hist["日期"] = pd.to_datetime(hist["日期"])
        hist = hist.sort_values("日期")

        # 计算 M20
        hist["M20"] = hist["收盘"].rolling(20).mean()

        # 最近 50 周
        hist = hist.tail(50)

        # 判断 M20 方向
        hist["M20向上"] = hist["M20"].diff() > 0

        # 构造展示表
        rows = []

        for _, row in hist.iterrows():
            price = round(row["收盘"], 3)
            m20 = round(row["M20"], 3)

            above_m20 = price > m20 if not pd.isna(m20) else False

            profit = ""
            profit_m20 = ""

            if use_position:
                profit = round((price - cost) / cost * 100, 2)
                profit_m20 = round((m20 - cost) / cost * 100, 2)

            ok = (
                premium < 1 and
                above_m20 and
                row["M20向上"] and
                (profit == "" or profit > -8)
            )

            reason = ""
            if not ok:
                reasons = []
                if premium >= 1:
                    reasons.append("溢价率≥1%")
                if not above_m20:
                    reasons.append("价格在M20下")
                if not row["M20向上"]:
                    reasons.append("M20未向上")
                if profit != "" and profit <= -8:
                    reasons.append("回撤超过8%")
                reason = "，".join(reasons)

            rows.append({
                "时间": row["日期"].strftime("%Y%m%d"),
                "溢价率(%)": premium,
                "现价": price,
                "M20": m20,
                "在M20上": "是" if above_m20 else "否",
                "M20向上": "是" if row["M20向上"] else "否",
                "收益(%)": profit,
                "比对M20收益(%)": profit_m20,
                "判定": "✅ 可买入" if ok else "❌ 不符合",
                "理由": reason
            })

        df = pd.DataFrame(rows)

        # 倒序显示
        df = df.sort_values("时间", ascending=False)

        # ========== 高亮重点行 ==========
        def highlight_row(row):
            if row["判定"] == "✅ 可买入":
                return ["background-color: #cfe5dc"] * len(row)
            return [""] * len(row)

        st.subheader("📊 周线决策列表（最近 50 周）")
        st.dataframe(
            df.style.apply(highlight_row, axis=1),
            use_container_width=True,
            height=800
        )

else:
    st.info("点击「同步最新数据」开始计算")
