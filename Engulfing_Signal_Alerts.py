import yfinance as yf
import os
from configparser import ConfigParser
from email.message import EmailMessage
import ssl
import smtplib


#Data Function
def get_data(symbol: str):
    ''' symbol is the ticker from yf, reset the date index of the data dataframe 
        to an integer index (drop it if not needed) also drop the ticker header
    '''
    data = yf.download(tickers=symbol, period='5d', interval='1d')
    data.columns = data.columns.droplevel(-1)
    data.reset_index(inplace=True)
    return data


#SIGNAL generation function
def test_engulfing(df):
    ''' Generate bearish/bullish signal based on simple engulfing patterns
    '''
    last_open = df.iloc[-1, :].Open
    last_close = df.iloc[-1, :].Close
    previous_open = df.iloc[-2, :].Open
    previous_close = df.iloc[-2, :].Close

    if (previous_open < previous_close 
        and last_open > previous_close 
        and last_close < previous_open):
        return 1  # Bearish Engulfing Pattern
    elif (previous_open > previous_close
          and last_open < previous_close 
          and last_close > previous_open):
        return 2  # Bullish Engulfing Pattern
    else:
        return 0  # No Engulfing Pattern


#Gmail config using a tokens_api file
#(Generate your own token in your Gmail account)
config = ConfigParser(interpolation=None)
if os.path.exists('tokens_api.ini'):
    #API config ini file
    config.read('tokens_api.ini')

    gmail_user = config['gmail']['gmail_user']
    gmail_password = config['gmail']['gmail_password']

em = EmailMessage()

gmail_user = gmail_user
gmail_password = gmail_password
subject = 'info signal'
email_from = 'xxx@gmail.com'
email_to = 'xxx@email.com'
em['From'] = email_from
em['To'] =  email_to
em['Subject'] = subject


#Multiple Tickers
symbols =  ['AAPL', 'NVDA', 'META']

def tickers_job():
    ''' Send email if signal detected for any ticker in symbols list
    '''
    msg= "Results: \n"

    for symb in symbols:
        historical_data = get_data(symb)

        if test_engulfing(historical_data)==1:
            msg = msg + str(symb+": the signal is 1 bearish") + "\n"

        elif test_engulfing(historical_data)==2:
            msg = msg + str(symb+": the signal is 2 bullish") + "\n"
    
        elif test_engulfing(historical_data)==0:
            msg = msg + str(symb+": no signal") + "\n"

    em.set_content(msg)

    context = ssl.create_default_context()

    server = smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context)
    server.set_debuglevel(False)
    server.ehlo()
    server.login(gmail_user, gmail_password)
    server.sendmail(gmail_user, gmail_user, em.as_string())
    server.close()

tickers_job()