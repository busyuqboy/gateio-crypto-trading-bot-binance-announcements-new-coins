from send_sms import send_sms_message
from trade_client import *
from store_order import *
from logger import logger
from load_config import *
from new_listings_scraper import *
import globals
from collections import defaultdict
from datetime import datetime, time
import time
import threading
import copy
import json
from json import JSONEncoder
import os.path
import sys, os


old_coins = ["MATIC", "TRVL"]

# loads local configuration
config = load_config('config.yml')

# load necessary files
if os.path.isfile('sold.json'):
    sold_coins = load_order('sold.json')
else:
    sold_coins = {}

if os.path.isfile('order.json'):
    order = load_order('order.json')
else:
    order = {}

# memory store for all orders for a specific coin
if os.path.isfile('session.json'):
    session = load_order('session.json')
else:
    session = {}    

if os.path.isfile('new_listing.json'):
    announcement_coin = load_order('new_listing.json')
else:
    announcement_coin = False


# Keep the supported currencies loaded in RAM so no time is wasted fetching
# currencies.json from disk when an announcement is made
global gateio_supported_currencies


logger.debug("Starting get_all_currencies")
gateio_supported_currencies = get_all_gateio_currencies(single=True)
logger.debug("Finished get_all_currencies")


global new_gateio_listings

# load necessary files
if os.path.isfile('upcoming_listings.json'):
    upcoming_listings = read_upcoming_listing('upcoming_listings.json')
    new_gateio_listings = [c for c in list(upcoming_listings) if c not in order and c not in sold_coins]
    if announcement_coin:
        new_gateio_listings = [c for c in list(upcoming_listings) if c not in announcement_coin]
else:
    store_upcoming_listing([])
    new_gateio_listings = []


def main():
    """
    Sells, adjusts TP and SL according to trailing values
    and buys new coins
    """
    # store config deets
    tp = config['TRADE_OPTIONS']['TP']
    sl = config['TRADE_OPTIONS']['SL']
    enable_tsl = config['TRADE_OPTIONS']['ENABLE_TSL']
    tsl = config['TRADE_OPTIONS']['TSL']
    ttp = config['TRADE_OPTIONS']['TTP']
    pairing = config['TRADE_OPTIONS']['PAIRING']
    test_mode = config['TRADE_OPTIONS']['TEST']
    enable_sms = config['TRADE_OPTIONS']['ENABLE_SMS']
    sys_name = config['TRADE_OPTIONS']['SYS_NAME']

    globals.stop_threads = False
    globals.sys_name = sys_name

    if not test_mode:
        logger.info(f'!!! LIVE MODE !!!')
        if enable_sms:
            logger.info(f"!!! SMS ENABLED !!!")

    t1 = threading.Thread(target=search_gateio_and_update, args=[pairing, new_gateio_listings])
    t1.start()

    t2 = threading.Thread(target=search_binance_and_update, args=[pairing])
    t2.start()

    t3 = threading.Thread(target=get_all_gateio_currencies)
    t3.start()

    t4 = threading.Thread(target=search_kucion_and_update)
    t4.start()

    try:
        while True:
            # check if the order file exists and load the current orders
            # basically the sell block and update TP and SL logic
            if len(order) > 0:
                for coin in list(order):

                    if float(order[coin]['_tp']) == 0:
                        st = order[coin]['_status']
                        logger.info(f"Order is initialized but not ready. Continuing. | Status={st}")
                        continue

                    # store some necessary trade info for a sell
                    coin_tp = order[coin]['_tp']
                    coin_sl = order[coin]['_sl']

                    volume = order[coin]['_amount']
                    stored_price = float(order[coin]['_price'])
                    symbol = order[coin]['_fee_currency']
                    
                    # set ttp and tsl to what is stored in order.json
                    order_ttp = order[coin]['_ttp']
                    order_tsl = order[coin]['_tsl']
                    if order_ttp == 0:
                        order_ttp = ttp # use config value
                    if order_tsl == 0:
                        order_tsl = tsl # user config value

                    # avoid div by zero error
                    if float(stored_price) == 0:
                        continue 

                    logger.debug(f'Data for sell: {coin=} | {stored_price=} | {coin_tp=} | {coin_sl=} | {volume=} | {symbol=} ')

                    logger.debug(f"Data for sell: {coin=},  {stored_price=}, {coin_tp=}, {coin_sl=}, {volume=}, {symbol=}")
                    
                    logger.debug(f"get_last_price existing coin: {coin}")
                    obj = get_last_price(symbol, pairing, False)
                    if obj == False:
                        continue
                    highest_bid = obj.highest_bid
                    last_price = obj.last
                    logger.debug("Finished get_last_price")

                    top_position_price = stored_price + (stored_price*coin_tp /100)
                    stop_loss_price = stored_price + (stored_price*coin_sl /100)

                    # need positive price or continue to next iteration
                    if float(last_price) == 0:
                        continue

                    logger.info(f'{symbol=}-{last_price=}{highest_bid=}\t[STOP: ${"{:,.5f}".format(stop_loss_price)} or {"{:,.2f}".format(coin_sl)}%]\t[TOP: ${"{:,.5f}".format(top_position_price)} or {"{:,.2f}".format(coin_tp)}%]\t[BUY: ${"{:,.5f}".format(stored_price)} (+/-): {"{:,.2f}".format(((float(last_price) - stored_price) / stored_price) * 100)}%]')

                    # update stop loss and take profit values if threshold is reached
                    if float(last_price) > stored_price + (
                            stored_price * coin_tp / 100) and enable_tsl:
                        # increase as absolute value for TP
                        new_tp = float(last_price) + (float(last_price) * order_ttp / 100)
                        # convert back into % difference from when the coin was bought
                        new_tp = float((new_tp - stored_price) / stored_price * 100)

                        # same deal as above, only applied to trailing SL
                        new_sl = float(last_price) + (float(last_price) * order_tsl / 100)
                        new_sl = float((new_sl - stored_price) / stored_price * 100)

                        # new values to be added to the json file
                        order[coin]['_tp'] = new_tp
                        order[coin]['_sl'] = new_sl
                        store_order('order.json', order)

                        new_top_position_price = stored_price + (stored_price*new_tp /100)
                        new_stop_loss_price = stored_price + (stored_price*new_sl /100)

                        logger.info(f'updated tp: {round(new_tp, 3)}% / ${"{:,.3f}".format(new_top_position_price)}')
                        logger.info(f'updated sl: {round(new_sl, 3)}% / ${"{:,.3f}".format(new_stop_loss_price)}')


                    # close trade if tsl is reached or trail option is not enabled
                    elif float(last_price) < stored_price + (
                            stored_price * coin_sl / 100) or float(last_price) > stored_price + (
                            stored_price * coin_tp / 100) and not enable_tsl:
                        try:
                            fees = float(order[coin]['_fee'])
                            sell_volume_adjusted = float(volume) - fees
                            pnl = (float(last_price) - stored_price)
                            pnl_perc = pnl / stored_price * 100

                            logger.info(f'starting sell place_order with :{symbol} | {pairing} | {volume} | {sell_volume_adjusted} | {fees} | {float(sell_volume_adjusted)*float(last_price)} | side=sell | last={last_price} | {highest_bid=}')

                            # sell for real if test mode is set to false
                            if not test_mode:
                                sell = place_order(symbol, pairing, float(sell_volume_adjusted)*float(highest_bid), 'sell', highest_bid)
                                logger.info("Finish sell place_order")


                                #check for completed sell order
                                if sell._status != 'closed':

                                    # change order to sell remaing
                                    if float(sell._left) > 0 and float(sell._amount) > float(sell._left):
                                        # adjust down order _amount and _fee
                                        order[coin]['_amount'] = sell._left
                                        order[coin]['_fee'] = f'{fees - (float(sell._fee) / float(sell._price))}'

                                        # add sell order sold.json (handled better in session.json now)
                                        id = f"{coin}_{id}"
                                        sold_coins[id] = sell
                                        sold_coins[id] = sell.__dict__
                                        sold_coins[id].pop("local_vars_configuration")
                                        sold_coins[coin]['profit'] = pnl
                                        sold_coins[coin]['relative_profit_%'] = pnl_perc
                                        
                                        logger.info(f"Sell order did not close! {sell._left} of {coin} remaining. Adjusted order _amount and _fee to perform sell of remaining balance")

                                        # add to session orders
                                        try:
                                            if len(session) > 0:
                                                dp = copy.deepcopy(sold_coins[id])
                                                session[coin]['orders'].append(dp)
                                                session[coin]['total_pnl'] = session[coin]['total_pnl'] + pnl
                                                session[coin]['total_pnl_percentage'] = session[coin]['total_pnl_percentage'] + pnl_perc
                                        except Exception as e:
                                            print(e)
                                        pass
                                    
                                    # keep going.  Not finished until status is 'closed'
                                    continue
                                    
                            # remove order from json file
                            order.pop(coin)
                            store_order('order.json', order)
                            logger.debug('Order saved in order.json')

                        except Exception as e:
                            logger.error(e)

                        # store sold trades data
                        else:
                            if not test_mode:
                                sold_coins[coin] = sell
                                sold_coins[coin] = sell.__dict__
                                sold_coins[coin].pop("local_vars_configuration")
                                sold_coins[coin]['highest_bid'] = highest_bid
                                sold_coins[coin]['profit'] = f'{float(last_price) - stored_price}'
                                sold_coins[coin]['relative_profit_%'] = f'{(float(last_price) - stored_price) / stored_price * 100}%'
                            else:
                                sold_coins[coin] = {
                                    'symbol': coin,
                                    'price': last_price,
                                    'volume': volume,
                                    'time': datetime.timestamp(datetime.now()),
                                    'profit': f'{float(last_price) - stored_price}',
                                    'relative_profit_%': f'{(float(last_price) - stored_price) / stored_price * 100}%',
                                    'id': 'test-order',
                                    'text': 'test-order',
                                    'create_time': datetime.timestamp(datetime.now()),
                                    'update_time': datetime.timestamp(datetime.now()),
                                    'currency_pair': f'{symbol}_{pairing}',
                                    'status': 'closed',
                                    'type': 'limit',
                                    'account': 'spot',
                                    'side': 'sell',
                                    'iceberg': '0',
                                    'price': last_price
                                    }
                                
                                logger.info('Sold coins:\r\n' + str(sold_coins[coin]))

                            # add to session orders
                            try: 
                                if len(session) > 0:
                                    dp = copy.deepcopy(sold_coins[coin])
                                    session[coin]['orders'].append(dp)
                                    session[coin]['total_pnl'] = session[coin]['total_pnl'] + pnl
                                    session[coin]['total_pnl_percentage'] = session[coin]['total_pnl_percentage'] + pnl_perc

                                    store_order('session.json', session)
                                    logger.debug('Session saved in session.json')
                            except Exception as e:
                                print(e)
                                pass

                            store_order('sold.json', sold_coins)
                            logger.info('Order saved in sold.json')

                            total_pnl = session[coin]['total_pnl']
                            total_pnl_percentage = session[coin]['total_pnl_percentage']
                            message = f'Sold {coin} with {round(total_pnl, 3)} profit | {round(total_pnl_percentage, 3)}% PNL'

                            logger.info(message)
                            if enable_sms:
                                send_sms_message(message)
                            
                                

            # the buy block and logic pass
            # announcement_coin = load_order('new_listing.json')
            if os.path.isfile('new_listing.json'):
                announcement_coin = load_order('new_listing.json')
                if(len(announcement_coin) > 0):
                    if(len(order) > 0):
                        announcement_coin = [c for c in announcement_coin if c not in order]
                    
                    if(len(announcement_coin) > 0):
                        announcement_coin = [c for c in announcement_coin if c not in old_coins and c not in sold_coins]
                    
                    if(len(announcement_coin) > 0):
                        announcement_coin = announcement_coin[0]
                    else:
                        announcement_coin = False
                else:
                    announcement_coin = False
            else:
                announcement_coin = False

            global gateio_supported_currencies

            if announcement_coin and announcement_coin not in order and announcement_coin not in sold_coins and announcement_coin not in old_coins:
                logger.debug(f'New annoucement detected: {announcement_coin}')

                if gateio_supported_currencies is not False:
                    if announcement_coin in gateio_supported_currencies:
                        
                        # get latest price object.  We do this to get the lowest_ask price.
                        # The lowest asking price will be used to try to close a buy order faster
                        lp = get_last_price(announcement_coin, pairing, False)

                        buffer = 0.005 # add room for volatility (percentage rate)
                        price = lp.last
                        if float(lp.lowest_ask) > 0:
                            price = float(lp.lowest_ask) + (float(lp.lowest_ask) * buffer)

                        volume = config['TRADE_OPTIONS']['QUANTITY']
                        
                        if announcement_coin not in session:
                            session[announcement_coin] = {}
                            session[announcement_coin].update({'total_volume': 0})
                            session[announcement_coin].update({'total_amount': 0})
                            session[announcement_coin].update({'total_fees': 0})
                            session[announcement_coin].update({'total_pnl':  0})
                            session[announcement_coin].update({'total_pnl_percentage':  0})
                            session[announcement_coin]['orders'] = list()
                        
                        # initalize order object
                        if announcement_coin not in order:

                            volume = volume - session[announcement_coin]['total_volume']

                            order[announcement_coin] = {}
                            order[announcement_coin]['_amount'] = f'{volume / float(price)}'
                            order[announcement_coin]['_left'] = f'{volume / float(price)}'
                            order[announcement_coin]['_fee'] = f'{0}'
                            order[announcement_coin]['_tp'] = f'{0}'
                            order[announcement_coin]['_sl'] = f'{0}'
                            order[announcement_coin]['_ttp'] = f'{0}'
                            order[announcement_coin]['_tsl'] = f'{0}'
                            order[announcement_coin]['_status'] = 'unknown'
                            if announcement_coin in session:
                                if len(session[announcement_coin]['orders']) == 0:
                                    order[announcement_coin]['_status'] = 'test_partial_fill_order'
                                else:
                                    order[announcement_coin]['_status'] = 'cancelled'

                        amount = float(order[announcement_coin]['_amount'])
                        left = float(order[announcement_coin]['_left'])
                        status = order[announcement_coin]['_status']

                        if left - amount != 0:
                            # partial fill. 
                            amount = left
                        
                        logger.info(f'starting buy place_order with : {announcement_coin=} | {pairing=} | {volume=} | {amount=} x {price=} | side = buy | {status=}')

                        try:
                            # Run a test trade if true
                            if config['TRADE_OPTIONS']['TEST']:
                                
                                if order[announcement_coin]['_status'] == 'cancelled':
                                    status = 'closed'
                                    left = 0
                                    fee = f'{float(amount) * .02}'
                                else:
                                    status = 'cancelled'
                                    left = f'{amount *.66}'
                                    fee = f'{float(amount - float(left)) * .02}'

                                order[announcement_coin] = {
                                    '_fee_currency': announcement_coin,
                                    '_price': f'{price}',
                                    '_amount': f'{amount}',
                                    '_time': datetime.timestamp(datetime.now()),
                                    '_tp': tp,
                                    '_sl': sl,
                                    '_ttp': ttp,
                                    '_tsl': tsl,
                                    '_id': 'test-order',
                                    '_text': 'test-order',
                                    '_create_time': datetime.timestamp(datetime.now()),
                                    '_update_time': datetime.timestamp(datetime.now()),
                                    '_currency_pair': f'{announcement_coin}_{pairing}',
                                    '_status': status,
                                    '_type': 'limit',
                                    '_account': 'spot',
                                    '_side': 'buy',
                                    '_iceberg': '0',
                                    '_left': f'{left}',
                                    '_fee': fee
                                }
                                logger.info('PLACING TEST ORDER')
                                logger.info(order[announcement_coin])
                            # place a live order if False
                            else:
                                # just in case...stop buying more than our config amount
                                assert amount * float(price) <= float(volume)

                                # new strategy:  
                                # Skip the step of getting the latest price and waiting for a positive price
                                # Issue orders using lowest_ask.  This will fail for gateio listings. Just keep trying.
                                try: 
                                    # place an order that will fail by design until the coin becomes sellable
                                    create_order = Order(amount=str(float(volume)/float(price)), price=price, side='buy', currency_pair=f'{announcement_coin}_{pairing}', time_in_force='ioc')
                                    order[announcement_coin] = spot_api.create_order(create_order)
                                except GateApiException as ge:
                                    if ge and ge.label == "INVALID_CURRENCY":
                                        order.pop(announcement_coin)  # reset for next iteration
                                        continue # reset for next iteration
                                    else:
                                        logger.error(ge)
                                        order.pop(announcement_coin)  # reset for next iteration
                                        continue

                                order[announcement_coin] = order[announcement_coin].__dict__
                                order[announcement_coin].pop("local_vars_configuration")
                                order[announcement_coin]['_tp'] = tp
                                order[announcement_coin]['_sl'] = sl
                                order[announcement_coin]['_ttp'] = ttp
                                order[announcement_coin]['_tsl'] = tsl
                                logger.debug('Finished buy place_order')


                        except Exception as e:
                            logger.error(e)
                            order.pop(announcement_coin)  # reset for next iteration


                        else:
                            order_status = order[announcement_coin]['_status']

                            logger.info(f'Order created on {announcement_coin} at a price of {price} each.  {order_status=}')

                            if order_status == "closed":
                                order[announcement_coin]['_amount_filled'] = order[announcement_coin]['_amount']
                                session[announcement_coin]['total_volume'] = session[announcement_coin]['total_volume'] + (float(order[announcement_coin]['_amount']) * float(order[announcement_coin]['_price']))
                                session[announcement_coin]['total_amount'] = session[announcement_coin]['total_amount'] + float(order[announcement_coin]['_amount'])
                                session[announcement_coin]['total_fees'] = session[announcement_coin]['total_fees'] + float(order[announcement_coin]['_fee'])
                                session[announcement_coin]['orders'].append(copy.deepcopy(order[announcement_coin]))

                                # update order to sum all amounts and all fees
                                # this will set up our sell order for sale of all filled buy orders
                                tf = session[announcement_coin]['total_fees']
                                ta = session[announcement_coin]['total_amount']
                                order[announcement_coin]['_fee'] = f'{tf}'
                                order[announcement_coin]['_amount'] = f'{ta}'

                                store_order('order.json', order)
                                store_order('session.json', session)

                                if enable_sms:
                                    total_filled_volume = session[announcement_coin]['total_volume']
                                    message = f"Purchased {round(total_filled_volume)} {pairing} of {announcement_coin} at a price of {price}."
                                    send_sms_message(message)
                            else:
                                if order_status == "cancelled" and float(order[announcement_coin]['_amount']) > float(order[announcement_coin]['_left']) and float(order[announcement_coin]['_left']) > 0:
                                    # partial order. Change qty and fee_total in order and finish any remaining balance
                                    partial_amount = float(order[announcement_coin]['_amount']) - float(order[announcement_coin]['_left'])
                                    partial_fee = float(order[announcement_coin]['_fee'])
                                    order[announcement_coin]['_amount_filled'] = f'{partial_amount}'
                                    session[announcement_coin]['total_volume'] = session[announcement_coin]['total_volume'] + (partial_amount * float(order[announcement_coin]['_price']))
                                    session[announcement_coin]['total_amount'] = session[announcement_coin]['total_amount'] + partial_amount
                                    session[announcement_coin]['total_fees'] = session[announcement_coin]['total_fees'] + partial_fee

                                    session[announcement_coin]['orders'].append(copy.deepcopy(order[announcement_coin]))
                                    logger.info(f"Parial fill order detected.  {order_status=} | {partial_amount=} out of {amount=} | {partial_fee=} | {price=}")
                                
                                # order not filled, try again
                                logger.info(f"clearing order with a status of {order_status}.  Waiting for 'closed' status")
                                order.pop(announcement_coin)  # reset for next iteration
                            
                    else:
                        logger.warning(f'{announcement_coin=} is not supported on gate io')
                        old_coins.append(announcement_coin)
                        logger.debug('Removed new_listing.json due to coin not being '
                                    'listed on gate io')

                else:
                    get_all_gateio_currencies()
            #else:
            #    logger.info( 'No coins announced, or coin has already been bought/sold. Checking more frequently in case TP and SL need updating')

            time.sleep(1)


            # except Exception as e:
            # print(e)
    except KeyboardInterrupt:
        logger.info('Stopping Threads')
        globals.stop_threads = True
        t1.join()
        t2.join()
        t3.join()
        t4.join()


if __name__ == '__main__':
    logger.info('working...')
    main()