import os
import streamlit as st
import pandas as pd
from polygon import RESTClient
import yfinance as yf
from datetime import datetime, timedelta
import logging
import plotly.graph_objects as go

# Setup logging
logging.basicConfig(filename='stock_app_error.log', level=logging.ERROR,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def search_stock_symbol(company_name):
    try:
        ticker = yf.Ticker(company_name)
        info = ticker.info
        return info.get('symbol', None)
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
        details = client.get_ticker_details(symbol)
        if details:
            return details
        else:
            st.warning(f"No details found for symbol: {symbol}")
            return None
    except Exception as e:
        logging.error(f"Error fetching stock details: {e}")
        st.error(f"Error fetching stock details: {str(e)}")
        return None

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

# Function to get historical data
def get_historical_data(symbol, from_date, to_date):
    try:
        data = list(client.list_aggs(
            ticker=symbol,
            multiplier=1,
            timespan="day",
            from_=from_date.strftime("%Y-%m-%d"),
            to=to_date.strftime("%Y-%m-%d")
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

# Main analysis section
if st.button("Analyze Stock"):
    if not polygon_api_key.strip() or not symbol.strip():
        st.error("Please add your Polygon API Key and enter a stock symbol.")
    else:
        with st.spinner("Analyzing stock data..."):
            try:
                # Get stock details
                details = get_stock_details(symbol)
                if details:
                    st.subheader("Stock Details")
                    st.write(f"Ticker: {details.ticker}")
                    st.write(f"Name: {details.name}")
                    st.write(f"Market Cap: ${details.market_cap:,.2f}")
                    st.write(f"Primary Exchange: {details.primary_exchange}")

                # Get current quote
                quote = get_current_quote(symbol)
                if quote:
                    st.subheader("Latest Quote")
                    st.write(f"Close: ${quote.close:.2f}")
                    st.write(f"High: ${quote.high:.2f}")
                    st.write(f"Low: ${quote.low:.2f}")
                    st.write(f"Open: ${quote.open:.2f}")
                    st.write(f"Volume: {quote.volume:,}")

                # Get historical data
                historical_data = get_historical_data(symbol, start_date, end_date)
                if historical_data is not None and not historical_data.empty:
                    st.subheader("Historical Data Analysis")

                    # Line chart
                    st.line_chart(historical_data.set_index('date')['close'])

                    # Candlestick chart using Plotly
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
                else:
                    st.warning("No historical data available for the selected date range.")
            except Exception as e:
                logging.error(f"Unexpected error during stock analysis: {e}")
                st.error(f"An unexpected error occurred: {str(e)}")

st.sidebar.info("This app uses data from Polygon.io and yfinance. Please ensure you comply with their terms of service.")