from logger import logger
from auth.gateio_auth import *
import gate_api
from gate_api import ApiClient, Configuration, Order, SpotApi
from gate_api.exceptions import ApiException, GateApiException
import dateutil.parser as dparser
from datetime import datetime
from dateutil import tz
from store_order import store_order

client = load_gateio_creds('auth/auth.yml')
spot_api = SpotApi(ApiClient(client))
import json



def get_last_price(base,quote, return_price_only):
    """
    Args:
    'DOT', 'USDT'
    """
    try:
        tickers = spot_api.list_tickers(currency_pair=f'{base}_{quote}')
    except GateApiException as ge:
        if ge and ge.label == "INVALID_CURRENCY_PAIR":
            return 0
        logger.error(ge)
    except (ApiException, Exception) as ae:
        logger.error(ae)
        return False
    else: 
        assert len(tickers) == 1
        t = tickers[0]
        if return_price_only:
            return t.lowest_ask
    
        logger.info(f"GET PRICE: {t.currency_pair} | last={t.last} | change%={t.change_percentage} | lowest_ask={t.lowest_ask} | highest_bid={t.highest_bid} | base_volue={t.base_volume} | quote_volume={t.quote_volume}")
        return t
 
    
def is_currency_trade_ready(base, quote):
    status = spot_api.get_currency_pair(currency_pair=f'{base}_{quote}')
    return status._trade_status == "tradable"


def get_min_amount(base,quote):
    """
    Args:
    'DOT', 'USDT'
    """
    try:
        min_amount = spot_api.get_currency_pair(currency_pair=f'{base}_{quote}').min_quote_amount
    except Exception as e:
        logger.error(e)
    else:
        return min_amount


def place_order(base,quote, amount, side, last_price):
    """
    Args:
    'DOT', 'USDT', 50, 'buy', 400
    """
    try:
        order = Order(amount=str(float(amount)/float(last_price)), price=last_price, side=side, currency_pair=f'{base}_{quote}', time_in_force='ioc')
        order = spot_api.create_order(order)
        t = order
        logger.info(f"PLACE ORDER: {t.side} | {t.id} | {t.account} | {t.type} | {t.currency_pair} | {t.status} | amount={t.amount} | price={t.price} | left={t.left} | filled_total={t.filled_total} | fill_price={t.fill_price} | fee={t.fee} {t.fee_currency}")
    except Exception as e:
        logger.error(e)
        raise

    else:
        return order

def get_listing_start(base, quote):
    d = False
    
    try:
        if is_currency_trade_ready(base, quote) is False:
            # place an order that will fail by design to buy because the coin is marked as sellable only.
            order = Order(amount=str(float(1)/float(0.1)), price=0.1, side='buy', currency_pair=f'{base}_{quote}', time_in_force='ioc')
            order = spot_api.create_order(order)
    except GateApiException as ge:
        if ge and ge.label == "INVALID_CURRENCY":
            # need to strip out the listing time listed in the error message and return as the datetime object
            d = dparser.parse(ge.message, fuzzy="True")
            from_zone = tz.gettz('Asia/Shanghai')
            d.replace(tzinfo=from_zone)
            return d
   
    return d

