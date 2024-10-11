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
import openai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(filename='stock_app_error.log', level=logging.ERROR,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Set up OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

def search_stock_symbol(company_name):
    try:
        ticker = yf.Ticker(company_name)
        return ticker.ticker
    except Exception as e:
        logging.error(f"Error searching stock symbol: {e}")
        return None

st.set_page_config(page_title="Stock Analysis App", layout="wide")

st.title("Stock Analysis Application")

# Sidebar for API key and general settings
with st.sidebar:
    st.header("Settings")
    polygon_api_key = st.text_input("Polygon API Key", type="password")
    
    # Radio buttons for date range selection
    date_range = st.radio(
        "Select Date Range",
        ["1 Day", "3 Days", "1 Month", "3 Months", "1 Year"]
    )

    # Add timeframe selection for graph resolution
    timeframe = st.selectbox(
        "Select Timeframe for Graph",
        ["1 Minute", "5 Minutes", "15 Minutes", "30 Minutes", "1 Hour", "1 Day"]
    )

    # Calculate the date range based on selection
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
col1, col2 = st.columns(2)

with col1:
    st.subheader("Stock Search")
    company_name = st.text_input("Enter company name to search for symbol")
    if st.button("Search Symbol"):
        if company_name:
            symbol = search_stock_symbol(company_name)
            if symbol:
                st.success(f"Symbol for {company_name}: {symbol}")
            else:
                st.error(f"Could not find symbol for {company_name}")

with col2:
    st.subheader("Stock Analysis")
    symbol = st.text_input("Enter a stock symbol", "AAPL")

# Initialize Polygon client
client = RESTClient(polygon_api_key)

# Function to get stock details
def get_stock_details(symbol):
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if info:
            return info
        st.warning(f"No details found for symbol: {symbol}")
        return None
    except polygon_exceptions.NoResultsError:
        st.warning(f"No details found for symbol: {symbol}")
        return None
    except Exception as e:
        logging.error(f"Error fetching stock details: {e}")
        st.error(f"Error fetching stock details: {str(e)}")
        return None

# Function to get option Greeks
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

def format_stock_data_for_chatgpt(symbol, details, quote, historical_data, greeks):
    prompt = f"""
    Analyze the following stock data for {symbol}:

    Stock Details:
    - Name: {details.get('longName', 'N/A')}
    - Market Cap: ${details.get('marketCap', 'N/A'):,.2f}
    - Exchange: {details.get('exchange', 'N/A')}

    Current Quote:
    - Close: ${quote.close:.2f}
    - High: ${quote.high:.2f}
    - Low: ${quote.low:.2f}
    - Open: ${quote.open:.2f}
    - Volume: {quote.volume:,}

    Historical Data (Last 5 days):
    {historical_data.tail().to_string()}

    Option Greeks:
    - Delta: {greeks['delta']:.4f}
    - Gamma: {greeks['gamma']:.4f}
    - Theta: {greeks['theta']:.4f}
    - Vega: {greeks['vega']:.4f}

    Please provide a concise analysis of this stock, including:
    1. An overview of the company's current market position
    2. Recent price trends and potential factors influencing them
    3. Options market sentiment based on the Greeks
    4. Any notable risks or opportunities for investors

    Limit your response to 250 words.
    """
    return prompt

# Function to get current quote
def get_current_quote(symbol):
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

# Updated function to get historical data with timeframe
def get_historical_data(symbol, from_date, to_date, timeframe):
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

def get_chatgpt_analysis(prompt):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that provides stock market analysis."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            n=1,
            stop=None,
            temperature=0.7,
        )
        return response.choices[0].message['content'].strip()
    except Exception as e:
        logging.error(f"Error getting ChatGPT analysis: {e}")
        return None

# Function to create a candlestick chart using Plotly
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

# Function to format and display table data
def display_formatted_table(data, title):
    st.subheader(title)
    df = pd.DataFrame(data, index=[0])
    st.table(df.style.format("{:.2f}"))

# Function to add tooltips
def add_tooltip(text, tooltip):
    return f"<span title='{tooltip}'>{text}</span>"

# Main analysis section with tabs
if st.button("Analyze Stock"):
    if not polygon_api_key.strip() or not symbol.strip():
        st.error("Please add your Polygon API Key and enter a stock symbol.")
    else:
        with st.spinner("Analyzing stock data..."):
            try:
                tab1, tab2, tab3, tab4 = st.tabs(["Stock Details", "Current Quote", "Historical Data", "Option Greeks"])
                
                with tab1:
                    details = get_stock_details(symbol)
                    if details:
                        st.subheader("Stock Details")
                        st.write(add_tooltip(f"Ticker: {details.get('symbol', 'N/A')}", "The stock's unique identifier"))
                        st.write(add_tooltip(f"Name: {details.get('longName', 'N/A')}", "The full name of the company"))
                        st.write(add_tooltip(f"Market Cap: ${details.get('marketCap', 'N/A'):,.2f}", "Total value of all outstanding shares"))
                        st.write(add_tooltip(f"Exchange: {details.get('exchange', 'N/A')}", "The stock exchange where the stock is traded"))

                with tab2:
                    quote = get_current_quote(symbol)
                    if quote:
                        display_formatted_table({
                            "Close": quote.close,
                            "High": quote.high,
                            "Low": quote.low,
                            "Open": quote.open,
                            "Volume": quote.volume
                        }, "Latest Quote")

                with tab3:
                    historical_data = get_historical_data(symbol, start_date, end_date, timeframe)
                    if historical_data is not None and not historical_data.empty:
                        st.subheader("Historical Data Analysis")

                        # Line chart with adjusted y-axis
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

                with tab4:
                    greeks = get_option_greeks(symbol)
                    if greeks:
                        display_formatted_table(greeks, "Option Greeks")
                        st.info("Note: These are simplified calculations and may not reflect real-time market values.")
                    else:
                        st.warning("Option Greeks are not available for this stock.")

                # New tab for AI-driven insights
                tab5 = st.tabs(["AI Insights"])[0]
                with tab5:
                    st.subheader("AI-Driven Stock Analysis")
                    if details and quote and historical_data is not None and greeks:
                        prompt = format_stock_data_for_chatgpt(symbol, details, quote, historical_data, greeks)
                        ai_analysis = get_chatgpt_analysis(prompt)
                        if ai_analysis:
                            st.write(ai_analysis)
                        else:
                            st.warning("Unable to generate AI-driven insights at this time.")
                    else:
                        st.warning("Insufficient data to generate AI-driven insights.")

            except Exception as e:
                logging.error(f"Unexpected error during stock analysis: {e}")
                st.error(f"An unexpected error occurred: {str(e)}")

st.sidebar.info("This app uses data from Polygon.io, yfinance, and OpenAI. Please ensure you comply with their terms of service.")
