# Import Dependencies
from bokeh.plotting import figure, show
from bokeh.io import output_notebook
from bokeh.layouts import column
from bokeh.models import ColumnDataSource, Legend, Band, Span
from datetime import date
import datetime
from hmmlearn import hmm
import numpy as np
from math import pi
from matplotlib import pyplot
from scipy.stats import norm
import streamlit as st
import time
import pandas as pd
from pypfopt import EfficientFrontier
from pypfopt import risk_models
from pypfopt import expected_returns
import yfinance as yf

# Helper Functions
def get_datetime(past_days=365):
  today = date.today()
  days = datetime.timedelta(past_days)
  one_year_ago = today - days

  return str(one_year_ago), str(today)

# Adjusted Close Prices
@st.cache(suppress_st_warning=True)
def get_adj_close_prices(ticks, one_year_ago, today):
  close_prices = {}
  warning = []
  for t in ticks:
    try:
      close_prices[t] = yf.download(t, start=one_year_ago, end=today)['Adj Close']
      
    except:
      warning.append(t) 

  close_prices = pd.DataFrame(close_prices)

  return close_prices, warning

def port_opt(acp):
  # Calculate expected returns and sample covariance
  mu = expected_returns.mean_historical_return(acp)
  S = risk_models.sample_cov(acp)

  # Optimize for maximal Sharpe ratio
  ef_min_volatility = EfficientFrontier(mu, S)
  ef_max_sharpe = EfficientFrontier(mu, S)

  # Set Constriants
  raw_weights_min_volatility = ef_min_volatility.min_volatility()
  raw_weights_max_sharpe = ef_max_sharpe.max_sharpe()

  # Store weights
  cleaned_weights_min_volatility = ef_min_volatility.clean_weights()
  cleaned_weights_max_sharpe = ef_max_sharpe.clean_weights()

  # Turn Weights Into Pandas Dataframes
  cleaned_weights_min_volatility = pd.DataFrame(
      cleaned_weights_min_volatility.values(), 
      index=cleaned_weights_min_volatility, 
      columns=['Min Volatility'])
  
  cleaned_weights_max_sharpe = pd.DataFrame(
      cleaned_weights_max_sharpe.values(), 
      index=cleaned_weights_max_sharpe, 
      columns=['Max Sharpe'])

  # Store Performance Stats
  performance_stats_min_volatility = ef_min_volatility.portfolio_performance()
  performance_stats_max_sharpe = ef_max_sharpe.portfolio_performance()

  return cleaned_weights_min_volatility, cleaned_weights_max_sharpe, performance_stats_min_volatility, performance_stats_max_sharpe

def regime_detection(historical_price, bollinger_bands="No", RSI="No", OBV="No"):
  log_ret = np.log1p(historical_price['Adj Close'].pct_change(-1))

  model = hmm.GaussianHMM(n_components=2, covariance_type='diag')
  X = log_ret.dropna().to_numpy().reshape(-1, 1)
#   try:
  model.fit(X) # Viterbi Algo is used to find the max proba, mean and variance

  Z = model.predict(X)
  Z_Close = np.append(Z, False)

  Z2 = pd.DataFrame(Z, index=log_ret.dropna().index, columns=['state'])
  Z2_Close = pd.DataFrame(Z_Close, index=log_ret.index, columns=['state'])

  # dying the returns
  returns_high_volatility = np.empty(len(Z))
  returns_low_volatility = np.empty(len(Z))

  returns_high_volatility[:] = np.nan
  returns_low_volatility[:] = np.nan

  if len(log_ret.dropna()[Z == 0]) > 0 and len(log_ret.dropna()[Z == 1]) > 0:
    if max(log_ret.dropna()[Z == 1]) > max(log_ret.dropna()[Z == 0]):
      returns_high_volatility[Z == 1] = log_ret.dropna()[Z == 1]
      returns_low_volatility[Z == 0] = log_ret.dropna()[Z == 0]

    else:
      returns_high_volatility[Z == 0] = log_ret.dropna()[Z == 0]
      returns_low_volatility[Z == 1] = log_ret.dropna()[Z == 1]

  elif len(log_ret.dropna()[Z == 0]) > 0 and len(log_ret.dropna()[Z == 1]) == 0:
      returns_high_volatility[Z == 1] = np.array([])
      returns_low_volatility[Z == 0] = log_ret.dropna()[Z == 0]

  elif len(log_ret.dropna()[Z == 0]) == 0 and len(log_ret.dropna()[Z == 1]) > 0:
      returns_high_volatility[Z == 0] = np.array([])
      returns_low_volatility[Z == 1] = log_ret.dropna()[Z == 1]    

  returns_high_volatility = np.concatenate(([np.nan], returns_high_volatility))
  returns_low_volatility = np.concatenate(([np.nan], returns_low_volatility))

  inc = historical_price["Adj Close"] > historical_price["Open"]
  dec = historical_price["Open"] > historical_price["Adj Close"]
  w = 12 * 60 * 60 * 1000 # half day in ms

  TOOLS = "pan, wheel_zoom, box_zoom, reset, save"

  # Historical Price
  p_historical = figure(x_axis_type="datetime", tools=TOOLS, width=1300, height=400)
  p_historical.xaxis.major_label_orientation = pi/4
  p_historical.grid.grid_line_alpha=0.3

  p_historical.segment(historical_price.index, historical_price["High"], historical_price.index, historical_price["Low"], color="black")
  p_historical.vbar(historical_price.index[inc], w, historical_price["Open"][inc], historical_price["Adj Close"][inc], width=w, fill_color="#99FFCC", line_color="black", legend_label="Adjusted Close Price (Inc)")
  p_historical.vbar(historical_price.index[dec], w, historical_price["Open"][dec], historical_price["Adj Close"][dec], width=w, fill_color="#F2583E", line_color="black", legend_label="Adjusted Close Price (Dec)")

  # Bollinger Bands
  if bollinger_bands == "Yes":
    bollinger_upper, bollinger_lower = bollinger(historical_price)
    source = ColumnDataSource({
        'base':bollinger_lower.index,
        'lower':bollinger_lower,
        'upper':bollinger_upper
        })

    band = Band(base='base', lower='lower', upper='upper', source=source, fill_color="#99CCFF", fill_alpha=0.4)
    p_historical.add_layout(band)

  # Log Return with High Volatility
  p_log_ret = figure(x_axis_type="datetime", x_range=p_historical.x_range, width=1300, height=200)
  p_log_ret.xaxis.major_label_orientation = pi/4
  p_log_ret.grid.grid_line_alpha=0.3

  p_log_ret.vbar(x=historical_price.index, top=(np.exp(returns_high_volatility) - 1) * 100, width=w, color="#FFDB46", line_color="black")
  p_log_ret.vbar(x=historical_price.index, top=(np.exp(returns_low_volatility) - 1) * 100, width=w, line_color="black")
  p_log_ret.yaxis.axis_label = 'Return (%)'

  # Relative Strength Index
  if RSI == "Yes":
    p_log_ret = figure(x_axis_type="datetime", x_range=p_historical.x_range, width=1300, height=200)
    p_log_ret.xaxis.major_label_orientation = pi/4
    p_log_ret.grid.grid_line_alpha=0.3

    rsi = relative_strength_index(historical_price)
    p_log_ret.line(rsi.index, rsi, line_width=1)
    upper_threshold = Span(location=70, dimension='width', line_color='black', line_width=1, line_alpha=0.4)
    lower_threshold = Span(location=30, dimension='width', line_color='black', line_width=1, line_alpha=0.4)
    p_log_ret.renderers.extend([upper_threshold, lower_threshold])
    p_log_ret.yaxis.axis_label = 'RSI (%)'

  # OBV
  if OBV == "Yes":
    obv, obv_ema, green_upper, green_lower, red_upper, red_lower = obv(historical_price)
    green_upper_filtered = con_list(green_upper)
    green_lower_filtered = con_list(green_lower)
    red_upper_filtered = con_list(red_upper)
    red_lower_filtered = con_list(red_lower)

    p_log_ret = figure(x_axis_type="datetime", x_range=p_historical.x_range, width=1300, height=200)
    p_log_ret.xaxis.major_label_orientation = pi/4
    p_log_ret.grid.grid_line_alpha=0.3

    p_log_ret.line(obv.index, obv, legend_label="OBV", line_width=1, line_color="green")
    p_log_ret.line(obv_ema.index, obv_ema, legend_label="OBV_EMA", line_width=1, line_color="red")

    for lower, upper in zip(green_lower_filtered, green_upper_filtered):
      green_source = ColumnDataSource({
            'base':lower.index,
            'lower':lower,
            'upper':upper
            })

      green_band = Band(base='base', lower='lower', upper='upper', source=green_source, fill_alpha=0.5, fill_color="green")
      p_log_ret.add_layout(green_band)

    for lower, upper in zip(red_lower_filtered, red_upper_filtered):
      red_source = ColumnDataSource({
            'base':lower.index,
            'lower':lower,
            'upper':upper
            })

      red_band = Band(base='base', lower='lower', upper='upper', source=red_source, fill_alpha=0.5, fill_color="red")
      p_log_ret.add_layout(red_band)

  # show the results
  p_historical.legend.location = "top_left"
  p_historical.xaxis.visible = False
  p_historical.yaxis.axis_label = 'Price (USD)'

  return column(p_historical, p_log_ret), returns_high_volatility, returns_low_volatility
  
#   except:
#     return None, None, None

def var(ret, initial_investment, conf_level=.05):
  cov_matrix = ret.cov()
  avg_return = ret.mean()

  port_mean = avg_return.dot(cleaned_weights_min_volatility)
  port_stdev = np.sqrt(cleaned_weights_min_volatility.T.dot(cov_matrix).dot(cleaned_weights_min_volatility))

  mean_investment = (1 + port_mean) * initial_investment
  stdev_investment = initial_investment * port_stdev

  cutoff1 = norm.ppf(conf_level, mean_investment, stdev_investment)
  var_1d1 = initial_investment - cutoff1
  
  return var_1d1[0][0]

def consecutive_list(iterable):
  res = []
  for p in iterable:
    if p > 0:
      res.append(True)
    elif p < 0:
      res.append(False)

  volatility_clusters = {}
  count = 0
  st = 0
  for i, j in enumerate(res):
    if i + 1 < len(res):
      if res[i] is not res[i + 1]:
        volatility_clusters[count] = res[st:i + 1]
        count += 1
        st = i + 1
    
    else:
      volatility_clusters[count] = res[st+1:]
  
  if len(volatility_clusters.keys()) > 0:
    n_grp = list(volatility_clusters.keys())[-1]
    list_cluster_len = [len(v) for v in volatility_clusters.values()]
    group_duration_median = np.median(list_cluster_len)
    group_duration_mean = sum(list_cluster_len) / len(volatility_clusters.values())
    net_return = np.expm1(np.nansum(iterable))
    
  else:
    return 0, 0, 0, 0

  return n_grp, group_duration_median, group_duration_mean, net_return

# -------------------------------------------------------------------Technical Analysis-----------------------------------------------------------------------------

def bollinger(historical_price, window=7, m=2):
  historical_price.loc[:, 'Typical Price'] = (historical_price["High"] + historical_price["Low"] + historical_price["Adj Close"]) / 3
  
  bollinger_sma = historical_price.loc[:, 'Typical Price'].rolling(window=window).mean()
  bollinger_std = historical_price.loc[:, 'Typical Price'].rolling(window=window).std()
  
  bollinger_upper = bollinger_sma + bollinger_std * m
  bollinger_lower = bollinger_sma - bollinger_std * m

  return bollinger_upper, bollinger_lower

def relative_strength_index(historical_price):
  historical_return = historical_price["Adj Close"].pct_change(-1).dropna()
  avg_gain = pd.Series(np.where(historical_return > 0, historical_return, 0)).rolling(14).mean()
  avg_loss = pd.Series(np.where(historical_return < 0, abs(historical_return), 0)).rolling(14).mean()
  RSI = 100 - (100/(1 + avg_gain/avg_loss))
  RSI = RSI.append(pd.Series(np.nan))
  RSI.index = historical_price.index  
  
  return RSI

def obv(historical_price, window=20):
  obv = []
  obv.append(0)

  for i in range(1, len(historical_price['Close'])):
      if historical_price["Close"].iloc[i] > historical_price["Close"].iloc[i-1]:
          obv.append(obv[-1] + historical_price["Volume"].iloc[i])
      elif historical_price["Close"].iloc[i] < historical_price["Close"].iloc[i-1]:
          obv.append(obv[-1] - historical_price["Volume"].iloc[i])
      else:
          obv.append(obv[-1])

  obv_ema = pd.Series(obv).ewm(span=window).mean()
  obv_ema.index = historical_price.index

  obv = pd.Series(obv)
  obv.index = historical_price.index

  green_upper = []
  green_lower = []
  red_upper = []
  red_lower = []
  for i in range(len(obv)):
    if obv[i] >= obv_ema[i]:
      green_upper.append(obv[i])
      green_lower.append(obv_ema[i])
      red_upper.append(np.nan)
      red_lower.append(np.nan)

    else:
      red_upper.append(obv[i])
      red_lower.append(obv_ema[i])
      green_upper.append(np.nan)
      green_lower.append(np.nan)
      
  green_upper = pd.Series(green_upper)
  green_lower = pd.Series(green_lower)
  red_upper = pd.Series(red_upper)
  red_lower = pd.Series(red_lower)

  green_upper.index = obv.index
  green_lower.index = obv.index
  red_upper.index = obv.index
  red_lower.index = obv.index

  return obv, obv_ema, green_upper, green_lower, red_upper, red_lower
  
def con_list(list1):
  res = []
  count = 0
  start = 0
  for i in range(len(list1)):
    if i + 1 < len(list1):
      if np.isnan(list1[i + 1]) and ~np.isnan(list1[i]):
        res.append(list1[start:i + 1])
        count += 1
        start = i + 1

      elif np.isnan(list1[i]) and ~np.isnan(list1[i + 1]):
        start = i + 1

  res.append(list1[start+1:])

  return res

# -----------------------------------------------------------------------------------------------------------------------------------------------------------------

st.set_page_config(
    page_title="Pynance",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

for key in ["", "Watchlist", "Portfolios"]:
  if key not in st.session_state:
    st.session_state[key] = {} 
    
# -----------------------------------------------------------------Side Bar-----------------------------------------------------------------------------------------
today = date.today() - datetime.timedelta(1)
add_ticker = st.sidebar.text_input(label="Add To Watchlist", value="Type a stock symbol", key="add_ticker")    
if add_ticker not in st.session_state['Watchlist']:
  if add_ticker != "Type a stock symbol":
    days = datetime.timedelta(2)
    three_day_ago = today - days
    close_prices = yf.download(add_ticker, start=three_day_ago, end=today)['Adj Close']
    st.session_state['Watchlist'][add_ticker] = round(close_prices.pct_change(-1).dropna()[-1] * 100, 2)
    
else:
  st.session_state['Watchlist'].pop(add_ticker)
  
st.sidebar.text('Watchlist\n')
watchlist_str = "\n".join(["\t" + ticker + "\t" + str(ret) + "%" for ticker, ret in st.session_state['Watchlist'].items()])
st.sidebar.text(watchlist_str)

# ----------------------------------------------------------------------------Main----------------------------------------------------------------------------------
st.title('Pynance')
    
# Regime Detection 
st.header("Regime Detection")
cols_regime_detection = st.columns(3)
cols_regime_detection2 = st.columns(8)
cols_regime_detection3 = st.columns(16)
one_year_ago = today - datetime.timedelta(365)

ticker = cols_regime_detection[0].text_input(label="Please type in a stock symbol.", value="AAPL")
start_date = cols_regime_detection[1].date_input("From", one_year_ago)
end_date = cols_regime_detection[2].date_input("To", today, max_value=today)  

one_week = cols_regime_detection2[0].button("1 Week")
one_month = cols_regime_detection2[1].button("1 Month")
three_months = cols_regime_detection2[2].button("3 Months")
six_months = cols_regime_detection2[3].button("6 Months")
one_year = cols_regime_detection2[4].button("1 Year")
three_years = cols_regime_detection2[5].button("3 Years")
five_years = cols_regime_detection2[6].button("5 Years")
ten_years = cols_regime_detection2[7].button("10 Years")

BB = cols_regime_detection3[0].select_slider('Bollinger', options=['No', 'Yes'], value="No")
RSI = cols_regime_detection3[2].select_slider('RSI', options=['No', 'Yes'], value="No")
OBV = cols_regime_detection3[4].select_slider('OBV', options=['No', 'Yes'], value="No")

buttons = [one_week, one_month, three_months, six_months, one_year, three_years, five_years, ten_years]
buttons_val = [7, 30, 90, 180, 365, 1095, 1825, 3650]
for b, bv in zip(buttons, buttons_val):
  if b:
    start_date = today - datetime.timedelta(bv)
    end_date = today

# Regime Detection Inputs
if ticker.isupper() and len(ticker) <= 5:
  historical_price = yf.download(ticker, start=start_date, end=end_date)
  if len(historical_price) > 1:
    p, returns_high_volatility, returns_low_volatility = regime_detection(historical_price, BB, RSI, OBV)
    if p != None:
      st.bokeh_chart(p, use_container_width=True)

      # Regime Stats 
      n_grp_hv, group_duration_median_hv, group_duration_mean_hv, net_return_hv = consecutive_list(returns_high_volatility)     
      n_grp_lv, group_duration_median_lv, group_duration_mean_lv, net_return_lv = consecutive_list(returns_low_volatility)

      volatility_stats = pd.DataFrame({
          "Number Of Groups":[n_grp_hv, n_grp_lv], 
          "Median Durations":[group_duration_median_hv, group_duration_median_lv], 
          "Mean Durations":[group_duration_mean_hv, group_duration_mean_lv], 
          "Return (%)":[round(net_return_hv * 100, 2), round(net_return_lv * 100, 2)]}, 
          index=["High Volatility", "Low Volatility"])

      st.subheader("Regime Stats")
      st.dataframe(volatility_stats)
      
    else:
      st.write("Less than two regime detected, please try a longer date range.")
    
  else:
    st.write("Selected date range must be greater than one day, try a longer period.")

# ----------------------------------------------------------------Portfolio Optimization---------------------------------------------------------------------------
st.header("Portfolio Optimization")
cols_tickers_from_to_capital = st.columns(3)

default_tickers = "FB, AAPL, AMZN, NFLX, GOOG"
tickers = st.text_input(label="Please type in a portfolio", value=default_tickers)
start_date_port_opt = cols_tickers_from_to_capital[0].date_input("From", one_year_ago, key="port_opt")
end_date_port_opt = cols_tickers_from_to_capital[1].date_input("To", today, key="port_opt")
capital = cols_tickers_from_to_capital[2].number_input('Capital', value=10000)

acp, warning = get_adj_close_prices(tickers.split(","), start_date_port_opt, end_date_port_opt)

if warning != []:
  st.write(f"Ticker: {' '.join(warning)} cannot be found.")

cleaned_weights_min_volatility, cleaned_weights_max_sharpe, performance_stats_min_volatility, performance_stats_max_sharpe = port_opt(acp)

# Rounding
cleaned_weights = np.hstack([cleaned_weights_min_volatility, cleaned_weights_max_sharpe])
performance_stats = np.vstack([performance_stats_min_volatility, performance_stats_max_sharpe])

cleaned_weights_performance_stats = np.vstack([cleaned_weights, performance_stats.T])

cleaned_weights_performance_stats = pd.DataFrame(cleaned_weights_performance_stats, 
                                                 columns=['Min Volatility (%)', 'Max Sharpe (%)'], 
                                                 index=tickers.split(",") + ["Expected annual return", "Annual volatility", "Sharpe Ratio"])

cleaned_weights_performance_stats.loc[:, 'Min Volatility (%)'] = cleaned_weights_performance_stats.loc[:, 'Min Volatility (%)'] * 100
cleaned_weights_performance_stats.loc[:, 'Max Sharpe (%)'] = cleaned_weights_performance_stats.loc[:, 'Max Sharpe (%)'] * 100
cleaned_weights_performance_stats.loc[:, 'Min Volatility'] = cleaned_weights_performance_stats.loc[:, 'Min Volatility (%)'] * capital / (100 * 7.8)
cleaned_weights_performance_stats.loc[:, 'Max Sharpe'] = cleaned_weights_performance_stats.loc[:, 'Max Sharpe (%)'] * capital / (100 * 7.8)

st.subheader("Optimized Portfolio")
st.dataframe(cleaned_weights_performance_stats.style.format("{:,.2f}"))

# Save Load port
cols_load_save = st.columns(2)
cols_load_save[0].subheader("Save Portfolio") 
cols_load_save[1].subheader("Load a Portfolio") 
port_name = cols_load_save[0].text_input("Name your portfolio", key="save_portfolio")
option = cols_load_save[1].selectbox('Load a portfolio', st.session_state["Portfolios"].keys())

if port_name != "":
  if port_name not in st.session_state["Portfolios"]:
    st.session_state["Portfolios"][port_name] = tickers
    st.write("Porfolio Saved Successfully!")

# -------------------------------------------------------------Value At Risk---------------------------------------------------------------------------------------
cols_value_at_risk = st.columns(2)
investing_period = end_date_port_opt - start_date_port_opt
cols_value_at_risk[0].subheader("Value At Risk") 
choose_condidence_lvl = cols_value_at_risk[0].slider("Confidence Level", .05, .5)

value_at_risk = var(acp.pct_change(-1).dropna(), capital, choose_condidence_lvl)
cols_value_at_risk[0].text(f"{(1 - choose_condidence_lvl) * 100}% confidence that your portfolio of ${capital}\nwill not exceed losses greater than ${round(value_at_risk, 2)} over a {investing_period.days} day period.")
