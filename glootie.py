import os
import streamlit as st
import pandas as pd
from polygon import RESTClient, exceptions as polygon_exceptions
import yfinance as yf
from py_vollib.black_scholes import black_scholes
from py_vollib.black_scholes.greeks.analytical import delta, gamma, vega, theta
from datetime import datetime, timedelta
import logging
import plotly.graph_objects as go
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(filename='stock_app_error.log', level=logging.ERROR,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Initialize OpenAI client
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def search_stock_symbol(query):
    try:
        tickers = yf.Ticker(query)
        if hasattr(tickers, 'info') and tickers.info:
            return tickers.info['symbol']
        else:
            return None
    except Exception as e:
        logging.error(f"Error searching stock symbol: {e}")
        return None

def get_stock_details(symbol):
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if info:
            return info
        st.warning(f"No details found for symbol: {symbol}")
        return None
    except Exception as e:
        logging.error(f"Error fetching stock details: {e}")
        st.error(f"Error fetching stock details: {str(e)}")
        return None

def get_option_greeks(symbol):
    try:
        ticker = yf.Ticker(symbol)
        options = ticker.options
        if options:
            current_price = ticker.history(period="1d")["Close"].iloc[-1]
            expiration = options[0]
            option_chain = ticker.option_chain(expiration)
            call = option_chain.calls.iloc[0]
            
            # Calculate Greeks (simplified)
            S = current_price
            K = call['strike']
            T = 30/365
            r = 0.01
            sigma = call['impliedVolatility']
            delta_value = delta('c', S, K, T, r, sigma)
            gamma_value = gamma('c', S, K, T, r, sigma)
            theta_value = theta('c', S, K, T, r, sigma)
            vega_value = vega('c', S, K, T, r, sigma)
            
            return {'delta': delta_value, 'gamma': gamma_value, 'theta': theta_value, 'vega': vega_value}
    except Exception as e:
        logging.error(f"Error fetching option Greeks: {e}")
        return None

def get_current_quote(symbol, client):
    try:
        aggs = list(client.get_previous_close_agg(symbol))
        if aggs:
            return aggs[0]
        else:
            st.warning(f"No current quote available for symbol: {symbol}")
            return None
    except Exception as e:
        logging.error(f"Error fetching current quote: {e}")
        st.error(f"Error fetching current quote: {str(e)}")
        return None

def get_historical_data(symbol, from_date, to_date, timeframe, client):
    try:
        if timeframe == "1 Day":
            multiplier, span = 1, "day"
        elif timeframe == "1 Hour":
            multiplier, span = 1, "hour"
        elif timeframe == "30 Minutes":
            multiplier, span = 30, "minute"
        elif timeframe == "15 Minutes":
            multiplier, span = 15, "minute"
        elif timeframe == "5 Minutes":
            multiplier, span = 5, "minute"
        else:  # 1 Minute
            multiplier, span = 1, "minute"
        
        data = list(client.list_aggs(
            ticker=symbol,
            multiplier=multiplier,
            timespan=span,
            from_=from_date.strftime("%Y-%m-%d"),
            to=to_date.strftime("%Y-%m-%d"),
            limit=50000
        ))
        
        if data:
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        else:
            st.warning(f"No historical data available for symbol: {symbol}")
            return None
    except Exception as e:
        logging.error(f"Error fetching historical data: {e}")
        st.error(f"Error fetching historical data: {str(e)}")
        return None

def create_candlestick_chart(df, symbol):
    fig = go.Figure(data=[go.Candlestick(x=df['date'],
                    open=df['open'],
                    high=df['high'],
                    low=df['low'],
                    close=df['close'])])
    fig.update_layout(title=f'{symbol} Candlestick Chart',
                      xaxis_title='Date',
                      yaxis_title='Price')
    return fig

def get_ai_analysis(stock_data):
    prompt = f"Analyze the following stock data for {stock_data['symbol']}:\n"
    prompt += f"Current Price: ${stock_data['current_price']}\n"
    prompt += f"52-Week High: ${stock_data['52_week_high']}\n"
    prompt += f"52-Week Low: ${stock_data['52_week_low']}\n"
    prompt += f"P/E Ratio: {stock_data['pe_ratio']}\n"
    prompt += "Provide a brief analysis and limited advice based on this data."

    try:
        completion = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        logging.error(f"Error getting AI analysis: {e}")
        return "Unable to generate AI analysis at this time."

# Streamlit app
st.set_page_config(page_title="Stock Analysis App", layout="wide")

st.title("Stock Analysis Application")

# Sidebar for general settings
with st.sidebar:
    st.header("Settings")
    
    date_range = st.radio(
        "Select Date Range",
        ["1 Day", "3 Days", "1 Month", "3 Months", "1 Year"]
    )

    timeframe = st.selectbox(
        "Select Timeframe for Graph",
        ["1 Minute", "5 Minutes", "15 Minutes", "30 Minutes", "1 Hour", "1 Day"]
    )

    end_date = datetime.now()
    if date_range == "1 Day":
        start_date = end_date - timedelta(days=1)
    elif date_range == "3 Days":
        start_date = end_date - timedelta(days=3)
    elif date_range == "1 Month":
        start_date = end_date - timedelta(days=30)
    elif date_range == "3 Months":
        start_date = end_date - timedelta(days=90)
    else:  # 1 Year
        start_date = end_date - timedelta(days=365)

# Main content area
st.subheader("Stock Search and Analysis")
query = st.text_input("Enter company name or stock symbol")

if st.button("Analyze Stock"):
    polygon_api_key = os.getenv('POLYGON_API_KEY')
    if not polygon_api_key or not query.strip():
        st.error("Please ensure the Polygon API Key is set in the environment variables and enter a company name or stock symbol.")
    else:
        with st.spinner("Analyzing stock data..."):
            try:
                symbol = search_stock_symbol(query)
                if not symbol:
                    st.error(f"Could not find symbol for {query}")
                else:
                    st.success(f"Analyzing symbol: {symbol}")

                    # Initialize Polygon client
                    client = RESTClient(polygon_api_key)

                    # Display all data sections
                    col1, col2 = st.columns(2)

                    with col1:
                        st.subheader("Stock Details")
                        details = get_stock_details(symbol)
                        if details:
                            st.write(f"Ticker: {details.get('symbol', 'N/A')}")
                            st.write(f"Name: {details.get('longName', 'N/A')}")
                            st.write(f"Market Cap: ${details.get('marketCap', 'N/A'):,.2f}")
                            st.write(f"Exchange: {details.get('exchange', 'N/A')}")

                        st.subheader("Current Quote")
                        quote = get_current_quote(symbol, client)
                        if quote:
                            st.write(f"Close: ${quote.close:.2f}")
                            st.write(f"High: ${quote.high:.2f}")
                            st.write(f"Low: ${quote.low:.2f}")
                            st.write(f"Open: ${quote.open:.2f}")
                            st.write(f"Volume: {quote.volume:,}")

                    with col2:
                        st.subheader("Option Greeks")
                        greeks = get_option_greeks(symbol)
                        if greeks:
                            st.write(f"Delta: {greeks['delta']:.4f}")
                            st.write(f"Gamma: {greeks['gamma']:.4f}")
                            st.write(f"Theta: {greeks['theta']:.4f}")
                            st.write(f"Vega: {greeks['vega']:.4f}")
                            st.info("Note: These are simplified calculations and may not reflect real-time market values.")
                        else:
                            st.warning("Option Greeks are not available for this stock.")

                    st.subheader("Historical Data Analysis")
                    historical_data = get_historical_data(symbol, start_date, end_date, timeframe, client)
                    if historical_data is not None and not historical_data.empty:
                        # Line chart
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=historical_data['date'], y=historical_data['close'], mode='lines', name='Close Price'))
                        fig.update_layout(title=f'{symbol} Price Chart', xaxis_title='Date', yaxis_title='Price')
                        fig.update_yaxes(range=[historical_data['low'].min() * 0.99, historical_data['high'].max() * 1.01])
                        st.plotly_chart(fig, use_container_width=True)

                        # Candlestick chart
                        fig = create_candlestick_chart(historical_data, symbol)
                        st.plotly_chart(fig, use_container_width=True)

                        # Basic statistics
                        st.subheader("Basic Statistics")
                        st.write(historical_data['close'].describe())

                        # Download CSV
                        csv = historical_data.to_csv(index=False)
                        st.download_button(
                            label="Download Historical Data as CSV",
                            data=csv,
                            file_name=f"{symbol}_historical_data.csv",
                            mime="text/csv",
                        )

                    # AI Analysis
                    st.subheader("AI Analysis")
                    if st.button("Get AI Analysis"):
                        stock_data = {
                            'symbol': symbol,
                            'current_price': quote.close if quote else 'N/A',
                            '52_week_high': details.get('fiftyTwoWeekHigh', 'N/A'),
                            '52_week_low': details.get('fiftyTwoWeekLow', 'N/A'),
                            'pe_ratio': details.get('trailingPE', 'N/A'),
                        }
                        ai_analysis = get_ai_analysis(stock_data)
                        st.write(ai_analysis)

            except Exception as e:
                logging.error(f"Unexpected error during stock analysis: {e}")
                st.error(f"An unexpected error occurred: {str(e)}")

st.sidebar.info("This app uses data from Polygon.io and yfinance. Please ensure you comply with their terms of service.")
