import pandas as pd
import pandas_ta as ta
import os
from datetime import datetime
from configparser import ConfigParser
from apscheduler.schedulers.blocking import BlockingScheduler
from backtesting import Strategy, Backtest
from oanda_candles import Pair, Gran, CandleClient
from oandapyV20 import API
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.trades as trades
from oandapyV20.contrib.requests import MarketOrderRequest
from oandapyV20.contrib.requests import TakeProfitDetails, StopLossDetails

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

#Forex trading bot for OANDA broker
#Only 28 forex pair combinations for the 8 major currencies are supported
#Following example with EUR_USD pair in 5min timeframe
#Requires Oanda Access token and account ID to initialize client
#Indicators can be removed/added and parameters tuned to generate more trading signals
#Strategy uses backtesting for weekly optimization of sl/tp values
#Script can be run on a VM in cloud with Paper/Demo account 
#Analyze results before deploying Live if profitable in long term

#Code explanation on CodeTrading YT channel: https://www.youtube.com/watch?v=WcfKaZL4vpA


config = ConfigParser(interpolation=None)
if os.path.exists('tokens_api.ini'):
    config.read('tokens_api.ini')
else:
    print("token file not found!")

accountID = config['oanda_demo']['accountID']
access_token = config['oanda_demo']['access_token']

def ema_signal(df, current_candle, backcandles):
    df_slice = df.reset_index().copy()
    start = max(0, current_candle - backcandles)
    end = current_candle
    relevant_rows = df_slice.iloc[start:end]
    if all(relevant_rows["EMA_fast"] < relevant_rows["EMA_slow"]):
        return 1
    elif all(relevant_rows["EMA_fast"] > relevant_rows["EMA_slow"]):
        return 2
    else:
        return 0

def total_signal(df, current_candle, backcandles):
    ema_signal_result = ema_signal(df, current_candle, backcandles)
    candle_open_price = df.Open[current_candle]
    bbl = df['BBL_15_1.5'][current_candle]
    bbu = df['BBU_15_1.5'][current_candle]
    if (ema_signal_result == 2 and candle_open_price <= bbl) and df.RSI[current_candle]<60:
        return 2
    if (ema_signal_result == 1 and candle_open_price >= bbu) and df.RSI[current_candle]>40:
        return 1
    return 0

def get_candles(n):
    client = CandleClient(access_token, real=False)
    collector = client.get_collector(Pair.EUR_USD, Gran.M5)
    candles = collector.grab(n)
    return candles
	
def count_opened_trades():
    client = API(access_token=access_token)
    r = trades.OpenTrades(accountID=accountID)
    client.request(r)
    return len(r.response['trades'])

def get_candles_frame(n):
    candles = get_candles(n)
    dfstream = pd.DataFrame(columns=['Open', 'Close', 'High', 'Low'])

    i = 0
    for candle in candles:
        dfstream.loc[i, ['Open']] = float(str(candle.bid.o))
        dfstream.loc[i, ['Close']] = float(str(candle.bid.c))
        dfstream.loc[i, ['High']] = float(str(candle.bid.h))
        dfstream.loc[i, ['Low']] = float(str(candle.bid.l))
        i = i+1

    dfstream['Open'] = dfstream['Open'].astype(float)
    dfstream['Close'] = dfstream['Close'].astype(float)
    dfstream['High'] = dfstream['High'].astype(float)
    dfstream['Low'] = dfstream['Low'].astype(float)

    dfstream["ATR"] = ta.atr(dfstream.High, dfstream.Low, dfstream.Close, length=7)
    dfstream["EMA_fast"] = ta.ema(dfstream.Close, length=30)
    dfstream["EMA_slow"] = ta.ema(dfstream.Close, length=50)
    dfstream['RSI'] = ta.rsi(dfstream.Close, length=10)
    my_bbands = ta.bbands(dfstream.Close, length=15, std=1.5)
    dfstream = dfstream.join(my_bbands)
    dfstream['TotalSignal'] = dfstream.apply(
        lambda row: total_signal(dfstream, row.name, 7), axis=1)

    return dfstream

#starting values
lotsize = 3000
slatrcoef = 1.2
TPSLRatio_coef = 1.1

def fitting_job():
    global slatrcoef
    global TPSLRatio_coef

    dfstream = get_candles_frame(7000)

    def SIGNAL():
        return dfstream.TotalSignal

    class MyStrat(Strategy):
        mysize = 3000
        slcoef = 1.2
        TPSLRatio = 1.1

        def init(self):
            super().init()
            self.signal1 = self.I(SIGNAL)

        def next(self):
            super().next()
            slatr = self.slcoef*self.data.ATR[-1]
            TPSLRatio = self.TPSLRatio

            if self.signal1 == 2 and len(self.trades) == 0:
                sl1 = self.data.Close[-1] - slatr
                tp1 = self.data.Close[-1] + slatr*TPSLRatio
                self.buy(sl=sl1, tp=tp1, size=self.mysize)

            elif self.signal1 == 1 and len(self.trades) == 0:
                sl1 = self.data.Close[-1] + slatr
                tp1 = self.data.Close[-1] - slatr*TPSLRatio
                self.sell(sl=sl1, tp=tp1, size=self.mysize)

    bt = Backtest(dfstream, MyStrat, cash=250, margin=1/30)
    stats = bt.optimize(slcoef=[i/10 for i in range(10, 26)],
                                 TPSLRatio=[i/10 for i in range(10, 26)],
                                 maximize='Return [%]', max_tries=300,
                                 random_state=0,
                                 return_heatmap=False)

    slatrcoef = stats["_strategy"].slcoef
    TPSLRatio_coef = stats["_strategy"].TPSLRatio
    print(slatrcoef, TPSLRatio_coef)

    with open("fitting_data_file.txt", "a") as file:
        file.write(
            f"{slatrcoef}, {TPSLRatio_coef}, expected return, {stats['Return [%]']}\n")

def trading_job():
    dfstream = get_candles_frame(70)
    signal = total_signal(dfstream, len(dfstream)-1, 7)

    global slatrcoef
    global TPSLRatio_coef

    now = datetime.now()
    if now.weekday() == 0 and now.hour < 7 and now.minute < 5:
        fitting_job()
        print(slatrcoef, TPSLRatio_coef)

    slatr = slatrcoef*dfstream.ATR.iloc[-1]
    TPSLRatio = TPSLRatio_coef
    max_spread = 16e-5

    candle = get_candles(1)[-1]
    candle_open_bid = float(str(candle.bid.o))
    candle_open_ask = float(str(candle.ask.o))
    spread = candle_open_ask-candle_open_bid

    SLBuy = candle_open_bid-slatr-spread
    SLSell = candle_open_ask+slatr+spread

    TPBuy = candle_open_ask+slatr*TPSLRatio+spread
    TPSell = candle_open_bid-slatr*TPSLRatio-spread

    client = API(access_token=access_token)

    if signal == 1 and count_opened_trades() == 0 and spread < max_spread:
        print("Sell Signal Found...")
        mo = MarketOrderRequest(instrument="EUR_USD", units=-lotsize, takeProfitOnFill=TakeProfitDetails(
            price=TPSell).data, stopLossOnFill=StopLossDetails(price=SLSell).data)
        r = orders.OrderCreate(accountID, data=mo.data)
        rv = client.request(r)
        with open("trading_data_file.txt", "a") as file:
            file.write(f"{slatrcoef}, {TPSLRatio_coef}\n")
            file.write(f"{rv}\n")

    elif signal == 2 and count_opened_trades() == 0 and spread < max_spread:
        print("Buy Signal Found...")
        mo = MarketOrderRequest(instrument="EUR_USD", units=lotsize, takeProfitOnFill=TakeProfitDetails(
            price=TPBuy).data, stopLossOnFill=StopLossDetails(price=SLBuy).data)
        r = orders.OrderCreate(accountID, data=mo.data)
        rv = client.request(r)
        with open("trading_data_file.txt", "a") as file:
            file.write(f"{slatrcoef}, {TPSLRatio_coef}\n")
            file.write(f"{rv}\n")
    else:
        print(now, "- No Signal!")

scheduler = BlockingScheduler()
scheduler.add_job(trading_job, 'cron', day_of_week='mon-fri', hour='07-18',
                  minute='1, 6, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56', timezone='America/Toronto', misfire_grace_time=15)
scheduler.start()