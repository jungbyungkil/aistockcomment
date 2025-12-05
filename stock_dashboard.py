import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime

# 페이지 설정
st.set_page_config(
    page_title="AI Stock Advisor Dashboard",
    page_icon="📈",
    layout="wide",
)

# 데이터베이스 연결 함수
@st.cache_resource
def get_connection():
    # stock_advisor.db가 없으면 생성됩니다.
    return sqlite3.connect('stock_advisor.db', check_same_thread=False)

# 데이터 로드 함수
@st.cache_data(ttl=60)
def load_data(query):
    try:
        conn = get_connection()
        df = pd.read_sql_query(query, conn)
        if 'current_price' in df.columns:
            df['current_price'] = pd.to_numeric(df['current_price'], errors='coerce')
        return df
    except Exception as e:
        # 테이블이 아직 생성되지 않았을 경우를 대비
        st.warning(f"데이터 로딩 중 오류 발생: {e}. 'stock_advisor.py'를 먼저 실행해주세요.")
        return pd.DataFrame()

# --- UI ---

st.title("📈 AI 주식 매도 자문 대시보드")
st.markdown("---")

# 자동 새로고침 버튼
if st.button('새로고침'):
    st.cache_data.clear()
    st.rerun()

# 데이터 로드
advice_df = load_data("SELECT * FROM stock_advice ORDER BY timestamp DESC")

if advice_df.empty:
    st.info("아직 분석된 데이터가 없습니다. `stock_advisor.py`를 실행하여 데이터를 생성해주세요.")
    st.stop()

# 종목 필터
stock_list = ["전체"] + advice_df['stock_name'].unique().tolist()
selected_stock = st.selectbox("종목 선택", stock_list)

if selected_stock != "전체":
    display_df = advice_df[advice_df['stock_name'] == selected_stock]
else:
    display_df = advice_df

if display_df.empty:
    st.info("선택한 종목에 대한 데이터가 없습니다.")
    st.stop()

# --- 최신 분석 결과 ---
st.header(f"🔔 최신 분석 결과: {selected_stock if selected_stock != '전체' else '모든 종목'}")

latest_advice = display_df.iloc[0]

decision_icon = "💰" if latest_advice['decision'] == 'SELL NOW' else "⏳"

col1, col2 = st.columns(2)
with col1:
    st.metric("결정", f"{decision_icon} {latest_advice['decision']}")
with col2:
    st.metric("신뢰도", latest_advice['confidence'])

with st.expander("상세 분석 및 액션 플랜 보기", expanded=True):
    st.markdown("##### 📝 상세 분석")
    st.write(latest_advice['analysis_summary'])
    st.markdown("##### 🚀 액션 플랜")
    st.write(latest_advice['action_plan'])
    
    price = latest_advice['current_price']
    price_text = f"₩{price:,.0f}" if pd.notna(price) else "가격 정보 없음"
    st.caption(f"분석 시점: {latest_advice['timestamp']} | 당시 가격: {price_text}")

st.markdown("---")

# --- 분석 히스토리 ---
st.header("📚 분석 히스토리")

col1, col2 = st.columns(2)

with col1:
    # 결정 분포
    st.subheader("결정 분포")
    decision_counts = display_df['decision'].value_counts()
    fig_pie = px.pie(
        values=decision_counts.values,
        names=decision_counts.index,
        title=f"'{selected_stock}' 결정 분포",
        color_discrete_map={'SELL NOW': '#FF4B4B', 'HOLD': '#CCCCCC'}
    )
    st.plotly_chart(fig_pie, use_container_width=True)

with col2:
    # 가격 및 결정 추이
    st.subheader("가격 및 결정 추이")
    fig_scatter = px.scatter(
        display_df,
        x='timestamp',
        y='current_price',
        color='decision',
        title=f"'{selected_stock}' 분석 시점별 가격 및 결정",
        labels={'current_price': '가격 (KRW)', 'timestamp': '분석 시점'},
        color_discrete_map={'SELL NOW': '#FF4B4B', 'HOLD': '#1f77b4'}
    )
    st.plotly_chart(fig_scatter, use_container_width=True)

# 상세 데이터 테이블
st.subheader("📋 상세 데이터")
st.dataframe(display_df[['timestamp', 'stock_name', 'decision', 'confidence', 'current_price', 'action_plan']], use_container_width=True)