import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta
import schedule
import time
import sqlite3
import requests
from bs4 import BeautifulSoup
import pandas as pd
from pykrx import stock
from ta.trend import MACD
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands

load_dotenv()

# OpenAI 클라이언트 초기화
client = OpenAI()

def init_stock_database():
    """SQLite 데이터베이스 및 주식 분석 테이블 초기화"""
    conn = sqlite3.connect('stock_advisor.db')
    cursor = conn.cursor()
    
    # AI 주식 분석 결과 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_advice (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            ticker TEXT NOT NULL,
            decision TEXT,
            confidence TEXT,
            analysis_summary TEXT,
            action_plan TEXT,
            current_price REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ 주식 분석 데이터베이스 초기화 완료")

def save_stock_advice(stock_name, ticker, current_price, advice):
    """AI의 분석 결과를 데이터베이스에 저장"""
    if not advice: return
    try:
        conn = sqlite3.connect('stock_advisor.db')
        cursor = conn.cursor()
        cursor.execute('INSERT INTO stock_advice (timestamp, stock_name, ticker, decision, confidence, analysis_summary, action_plan, current_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), stock_name, ticker, advice.get('decision'), advice.get('confidence'), advice.get('analysis_summary'), advice.get('action_plan'), float(current_price)))
        conn.commit()
        conn.close()
        print(f"  💾 [{stock_name}] AI 분석 결과 저장 완료")
    except Exception as e:
        print(f"  ❌ [{stock_name}] AI 분석 결과 저장 실패: {e}")

def get_news_headlines(ticker, count=5):
    """네이버 금융에서 최신 뉴스 헤드라인을 스크레이핑합니다."""
    headlines = []
    try:
        # 네이버 금융 뉴스 URL
        url = f"https://finance.naver.com/item/news_news.naver?code={ticker}&page=1"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
        response = requests.get(url, headers=headers)
        response.raise_for_status() # HTTP 오류 발생 시 예외 발생
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 뉴스 제목이 포함된 'title' 클래스를 가진 <a> 태그를 찾습니다.
        news_list = soup.select('.title a')
        
        for news in news_list[:count]:
            headlines.append(news.get_text(strip=True))
            
        print(f"  📰 뉴스 헤드라인 {len(headlines)}건 수집 완료")
        return headlines
    except Exception as e:
        print(f"  ❌ 뉴스 헤드라인 수집 오류: {e}")
        return []

def get_fundamental_data(ticker):
    """pykrx를 이용해 기업 기본 정보를 가져옵니다."""
    try:
        # 가장 최근 시장 영업일의 펀더멘털 정보 조회
        latest_date = stock.get_market_ohlcv_by_date(end=datetime.now().strftime("%Y%m%d"), ticker=ticker, adjusted=False).index[-1].strftime("%Y%m%d")
        df_fund = stock.get_market_fundamental_by_ticker(latest_date, market="ALL")
        
        # 해당 종목의 정보만 필터링
        fundamental_data = df_fund.loc[ticker]
        
        if fundamental_data is not None and not fundamental_data.empty:
            data = {
                "BPS": fundamental_data.get('BPS'),
                "PER": fundamental_data.get('PER'),
                "PBR": fundamental_data.get('PBR'),
                "EPS": fundamental_data.get('EPS'),
                "DIV": fundamental_data.get('DIV'), # Dividend Yield (배당수익률)
                "DPS": fundamental_data.get('DPS')  # Dividend Per Share (주당배당금)
            }
            print(f"  🏢 기업 정보 수집 완료 (PBR: {data['PBR']}, PER: {data['PER']})")
            return data
        return None
    except Exception as e:
        print(f"  ❌ 기업 정보 수집 오류: {e}")
        return None

def add_technical_indicators(df):
    """DataFrame에 기술적 지표 추가"""
    try:
        # RSI
        df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
        
        # MACD
        macd = MACD(close=df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        
        # Bollinger Bands
        bollinger = BollingerBands(close=df['close'])
        df['bb_high'] = bollinger.bollinger_hband()
        df['bb_mid'] = bollinger.bollinger_mavg()
        df['bb_low'] = bollinger.bollinger_lband()
        
        df = df.round(2) # 소수점 2자리로 반올림
        return df
    except KeyError as e:
        # 'close' 컬럼이 없는 등 예상치 못한 DataFrame 형식일 경우 예외 처리
        print(f"  ❌ 기술적 지표 계산 오류: 필요한 컬럼({e})이 없습니다.")
        raise e # 오류를 다시 발생시켜 get_stock_data에서 처리하도록 함

def get_stock_data(ticker, days=90):
    """pykrx를 이용해 주식 데이터와 기술적 지표를 가져오는 함수"""
    try:
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
        
        df = stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
        df.reset_index(inplace=True)
        df.rename(columns={'날짜': 'date', '시가': 'open', '고가': 'high', '저가': 'low', '종가': 'close', '거래량': 'volume'}, inplace=True)
        
        if df.empty:
            return None
            
        df_with_indicators = add_technical_indicators(df)
        return df_with_indicators
    except pd.errors.EmptyDataError:
        print(f"  ❌ [{stock.get_market_ticker_name(ticker)}] 데이터 수집 오류: 빈 데이터를 받았습니다.")
        return None
    except Exception as e:
        ticker_name = ticker
        try: ticker_name = stock.get_market_ticker_name(ticker)
        except: pass
        print(f"  ❌ [{ticker_name}] 데이터 처리 중 오류 발생: {e}")
        return None

def get_ai_advice(stock_name, ticker, goal, avg_buy_price, stock_data, news_headlines, fundamental_data):
    """AI에게 주식 매도 시점 조언을 구하는 함수"""
    
    # DataFrame을 JSON으로 변환하기 전 날짜 형식 변경
    stock_data['date'] = stock_data['date'].dt.strftime('%Y-%m-%d')
    data_json = stock_data.to_json(orient='records', indent=2)

    # AI에게 전달할 추가 정보
    additional_info = {
        "recent_news_headlines": news_headlines,
        "fundamental_data": fundamental_data,
        "client_average_buy_price": avg_buy_price
    }

    system_prompt = f"""
당신은 최고의 주식 시장 분석가입니다. 고객이 보유 중인 주식을 언제 매도해야 할지에 대한 조언을 구하고 있습니다.

종목: {stock_name} ({ticker})
고객의 평균 매수 단가: {avg_buy_price:,.0f}원
고객의 목표: {goal}

제공된 모든 데이터를 분석하세요:
1.  **최신 뉴스 헤드라인**: 현재 시장 심리와 잠재적 이벤트를 파악합니다.
2.  **기본적 분석 데이터 (PBR, PER 등)**: 주식의 가치 평가를 이해합니다.
3.  **기술적 분석 데이터 (OHLCV + 지표)**: 가격 추세와 모멘텀을 분석합니다.

이 세 가지 측면(뉴스 심리, 기본적 가치 평가, 기술적 분석)을 종합하여 전체적이고 논리적인 추천을 제공하세요.

**[매우 중요한 규칙]**
고객의 목표가 '최소 매수 단가 이상에서 매도'하는 것일 경우, 현재 주가가 고객의 평균 매수 단가보다 낮다면 **절대로 'SELL NOW'를 추천해서는 안 됩니다.**
이 경우, 기술적으로 하락 추세가 예상되더라도 반드시 'HOLD'를 추천하고, 손실을 최소화하기 위한 전략(예: 추가 하락 시 손절 라인 제안) 또는 반등을 기다리기 위한 조건을 설명해야 합니다.
고객의 심리적 안정과 원금 회복 의지가 기술적 분석보다 우선순위가 높습니다.

응답은 다음 구조의 한국어 JSON 형식으로 제공해야 합니다:
{{
  "decision": "SELL NOW" | "HOLD",
  "confidence": "High" | "Medium" | "Low",
  "analysis_summary": "뉴스, 기본적 분석, 기술적 분석을 결합한 종합적인 분석 요약.",
  "action_plan": "고객을 위한 구체적인 실행 계획. 'SELL NOW'의 경우 가격을 명시하고, 'HOLD'의 경우 주시해야 할 조건을 명시하세요."
}}
"""

    user_content = f"""
Here is the data for analysis.

### Additional Information
{json.dumps(additional_info, indent=2, ensure_ascii=False)}

### Technical Data
{data_json}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"},
            temperature=0.5
        )
        
        advice = json.loads(response.choices[0].message.content)
        return advice

    except Exception as e:
        print(f"  ❌ [{stock_name}] AI 분석 중 오류 발생: {e}")
        return None

def print_advice(stock_name, advice):
    """AI의 조언을 보기 쉽게 출력하는 함수"""
    print("\n" + "="*50)
    print(f"📈 AI 매도 자문: {stock_name}")
    print("="*50)
    
    if not advice:
        print("  AI 분석 결과를 가져오지 못했습니다.")
        return

    decision_icon = "💰" if advice['decision'] == 'SELL NOW' else "⏳"
    print(f"  ▶️ 결정: {decision_icon} {advice['decision']}")
    print(f"  ▶️ 신뢰도: {advice['confidence']}")
    print("\n  [상세 분석]")
    print(f"  {advice['analysis_summary']}")
    
    print("\n  [액션 플랜]")
    print(f"  {advice['action_plan']}")
    print("="*50 + "\n")


def run_analysis():
    """주식 분석 및 AI 조언 요청 작업을 수행하는 메인 함수"""
    # 분석할 주식 목록 (종목명, 종목코드, 매도 목표)
    # 여기에 고객님의 평균 매수 단가를 추가했습니다.
    stocks_to_analyze = [
        {
            "name": "한화오션", 
            "ticker": "042660", 
            "avg_buy_price": 132800,
            "goal": "평균 매수 단가는 132,800원입니다. 현재 상당한 손실 상태이며, 심리적으로 손해를 보지 않는 선(최소한 매수 단가 이상)에서 매도하고 싶습니다. 기술적 반등을 이용해 손실을 최소화하거나 수익을 낼 수 있는 최적의 매도 시점을 찾아주세요."
        },
        {
            "name": "모아데이타", 
            "ticker": "288980", 
            "avg_buy_price": 2530,
            "goal": "평균 매수 단가는 2,530원입니다. 현재 상당한 손실 상태이며, 심리적으로 손해를 보지 않는 선(최소한 매수 단가 이상)에서 매도하고 싶습니다. 기술적 반등을 이용해 손실을 최소화하거나 수익을 낼 수 있는 최적의 매도 시점을 찾아주세요."
        },
        {
            "name": "TIGER 미국S&P500", 
            "ticker": "360750", 
            "avg_buy_price": 0, # 매수 단가 정보 없음
            "goal": "개인적인 용도로 사용할 현금 확보를 위해 매도 희망. 시장 고점에서 이익을 실현할 좋은 기회를 찾고 있음."
        }
    ]

    print(f"\n{'='*60}")
    print(f"🚀 AI 주식 매도 타이밍 분석을 시작합니다... ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print(f"{'='*60}")

    for stock_info in stocks_to_analyze:
        print(f"\n[1/3] 📊 '{stock_info['name']}'의 기술적 데이터를 수집합니다...")
        
        # 최근 180일(약 6개월) 데이터 수집
        stock_data = get_stock_data(stock_info['ticker'], days=180)
        
        if stock_data is not None and not stock_data.empty:
            current_price = stock_data.iloc[-1]['close']
            print(f"  ✅ 기술적 데이터 수집 완료. (최근 종가: {current_price:,.0f}원)")
            
            print(f"\n[2/3] 📰 '{stock_info['name']}'의 최신 뉴스와 기업 정보를 수집합니다...")
            # 뉴스 헤드라인 수집
            news = get_news_headlines(stock_info['ticker'])
            # 기업 펀더멘털 정보 수집
            fundamentals = get_fundamental_data(stock_info['ticker'])

            print(f"\n[3/3] 🤖 AI에게 '{stock_info['name']}'의 매도 전략을 종합적으로 묻습니다...")
            
            # AI에게 조언 요청
            advice = get_ai_advice(
                stock_info['name'], 
                stock_info['ticker'], 
                stock_info['goal'], 
                stock_info['avg_buy_price'],
                stock_data,
                news,
                fundamentals
            )
            
            # 결과 출력
            print_advice(stock_info['name'], advice)

            # 결과 저장
            save_stock_advice(stock_info['name'], stock_info['ticker'], current_price, advice)
        else:
            print(f"  ⚠️ '{stock_info['name']}'의 데이터를 가져올 수 없어 분석을 건너뜁니다.")

    print("\n✅ 모든 주식에 대한 분석이 완료되었습니다.")
    print(f"다음 스케줄까지 대기합니다...")


if __name__ == "__main__":
    # 데이터베이스 초기화
    init_stock_database()

    # 스케줄 설정
    # 장 시작 직전(08:50)과 장 마감 직전(15:00)에 실행
    schedule.every().day.at("08:50").do(run_analysis)
    schedule.every().day.at("15:00").do(run_analysis)

    print("✅ 스케줄러가 설정되었습니다. (매일 08:50, 15:00)")
    print("프로그램 시작 시 1회 즉시 실행합니다.")
    run_analysis() # 프로그램 시작 시 1회 즉시 실행

    while True:
        schedule.run_pending()
        time.sleep(1)


 