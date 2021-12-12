from re import search
import time

import globals

from gate_api import ApiClient, SpotApi
from auth.gateio_auth import *
from auth.binance_auth import *
from logger import logger
from binance import Client


client = load_gateio_creds('auth/auth_gateio.yml')
spot_api = SpotApi(ApiClient(client))

access_key, secret_key = load_binance_creds('auth/auth_binance.yml')
binance_api = Client(api_key=access_key, api_secret=secret_key, tld='us')


def get_ticker_prices(pairing, second_pairing):
    result = []
    try:
        all_gateio_ticker_pairs = spot_api.list_tickers()
        all_binance_ticker_pairs = binance_api.get_all_tickers()
        all_gateio_tickers = [t.currency_pair.replace(f"_{pairing}", "") for t in all_gateio_ticker_pairs if pairing in t.currency_pair]
        all_binance_tickers = [t['symbol'].replace(f"{pairing}", "") for t in all_binance_ticker_pairs if pairing in t['symbol']]
        
        all_gateio_second_pairs = [t.currency_pair.replace(f"_{second_pairing}", "") for t in all_gateio_ticker_pairs if second_pairing in t.currency_pair]
        all_binance_second_pairs = [t['symbol'].replace(f"{second_pairing}", "") for t in all_binance_ticker_pairs if second_pairing in t['symbol']]


        all_symbols = [value for value in all_gateio_tickers if value in all_binance_tickers]

        for symbol in all_symbols:
            
            binance_response = [t for t in all_binance_ticker_pairs if pairing in t['symbol'] and symbol in t['symbol'] and t['symbol'].replace(f"{pairing}", "") == symbol]
            gateio_response = [t for t in all_gateio_ticker_pairs if pairing in t.currency_pair and symbol in t.currency_pair and t.currency_pair.replace(f"_{pairing}", "") == symbol]
            
            if len(binance_response) > 0 and len(gateio_response) > 0:
                result.append({
                    "symbol": symbol,
                    "binance_symbol": binance_response[0]['symbol'],
                    "gateio_symbol": gateio_response[0].currency_pair,
                    "binance_price": binance_response[0]['price'],
                    "gateio_price": gateio_response[0].last,
                    "gateio_difference": float(gateio_response[0].last) - float(binance_response[0]['price']),
                    "binance_difference": float(binance_response[0]['price']) - float(gateio_response[0].last),
                    "gateio_difference_%": float(gateio_response[0].last) - float(binance_response[0]['price']) / float(gateio_response[0].last) * 100,
                    "binance_difference_%": float(binance_response[0]['price']) - float(gateio_response[0].last) / float(binance_response[0]['price']) * 100,
                    "diff": abs(1 - abs(float(gateio_response[0].last) - float(binance_response[0]['price']))),
                    "diff_p": abs(1 - abs(float(gateio_response[0].last) - float(binance_response[0]['price']))) / 100
                })

        return result
    except Exception as ex:
        print(ex)


def get_gateio_triangular_arbitrage_opportunities(pairing, second_pairing):
    """
    Triangular arbitrage.  One exchange.

    :return:
    """
    result = []
    try:
        all_gateio_ticker_pairs = spot_api.list_tickers()

        all_gateio_tickers = [t.currency_pair.replace(f"_{pairing}", "") for t in all_gateio_ticker_pairs if pairing in t.currency_pair]
        all_gateio_second_pairs = [t.currency_pair.replace(f"_{second_pairing}", "") for t in all_gateio_ticker_pairs if second_pairing in t.currency_pair]

        all_symbols = [value for value in all_gateio_tickers if value in all_gateio_second_pairs]
        
        # get second_pairing back to USDT (final trade pair)
        third_pairs = [t for t in all_gateio_ticker_pairs if second_pairing in t.currency_pair and pairing in t.currency_pair and t.currency_pair.replace(f"_{pairing}", "") == second_pairing]

        if len(third_pairs) == 0:
            return result
        
        for symbol in all_symbols:
            # get USDT pairing of symbol
            first_pairs = [t for t in all_gateio_ticker_pairs if pairing in t.currency_pair and symbol in t.currency_pair and t.currency_pair.replace(f"_{pairing}", "") == symbol]
            
            # get second_pairing with symbol
            second_pairs = [t for t in all_gateio_ticker_pairs if second_pairing in t.currency_pair and symbol in t.currency_pair and t.currency_pair.replace(f"_{second_pairing}", "") == symbol]

            if len(first_pairs) > 0 and len(second_pairs) > 0:
                first_pair = first_pairs[0]
                second_pair = second_pairs[0]
                third_pair = third_pairs[0]

                if float(first_pair.last) == 0:
                    continue #avoid divide by zero

                #USDT
                volume = 100

                # Symbol volume
                first_stage_volume = volume / float(first_pair.last)
                
                # second_pairing volume
                second_stage_volume = first_stage_volume * float(second_pair.last)

                #Back to USDT volume
                third_stage_volume = second_stage_volume * float(third_pair.last)

                diff = third_stage_volume - volume

                if diff > 0:
                    diff_r = 1 + (diff / volume)
                    diff_p = diff / volume
                    
                    result.append({
                        "symbol": symbol,
                        "gateio_symbol": first_pair.currency_pair,
                        "gateio_price": first_pair.last,
                        "gateio_second_price": second_pair.last,
                        "gateio_third_price": third_pair.last,
                        "diff": diff,
                        "diff_r": diff_r,
                        "diff_p": diff_p
                    })

        return result
    except Exception as ex:
        print(ex)
        return result



def search_arbitrage_opportunities(pairing, second_paring, percentage_diff):
    """
    Get a list of arbitrage position favorable to buy and then sell on gateio
    :return:
    """

    ignore_coins = ["BCDN", "LUFFY", "ZSC", "BU"]

    while not globals.stop_threads:

        obj = get_gateio_triangular_arbitrage_opportunities(pairing, second_paring)
        obj = [t for t in obj if t['symbol'] not in ignore_coins]
        if len(obj) != 0:
            prospects = sorted([t for t in obj if t['diff_p'] >= percentage_diff], key=lambda d: d['diff_p'], reverse=True)
            if len(prospects) > 0:
                logger.info('{:<20s} {:<14s} {:<14s} {:<14s} {:<14s} {:<14s}'.format("symbol", "diff_p(%)", "100_PNL($)","p1($)", "p2($)", "p3($)"))
                for top in prospects:
                    logger.info('{:<20s} {:<14s} {:<14s} {:<14s} {:<14s} {:<14s}'.format(f"{top['symbol']}->ETH->USDT", "{:.4f}%".format(top['diff_p']), "{:.2f}".format(top['diff_p'] * 100), "{:.8f}".format(float(top['gateio_price'])), "{:.8f}".format(float(top['gateio_second_price'])), "{:.8f}".format(float(top['gateio_third_price']))))
                
                print("\n")
            else:
                logger.info("No arbitrage prospects found")
        for x in range(5):
            time.sleep(1)
            if globals.stop_threads:
                break


#search_arbitrage_opportunities("USDT", "ETH", 0.5)

#obj = get_ticker_prices()
#print('{:<8s} {:<10s} {:<10s} {:<10s} {:<10s} {:<10s}'.format("symbol", "diff_p", "bin_diff", "gate_diff", "bin_$", "gate_$"))
#for top in [t for t in obj if t['diff_p'] >= 0.5]:
    #print('{:<8s} {:<10s} {:<10s} {:<10s} {:<10s} {:<10s}'.format(top['symbol'], "{:.2f}".format(top['diff_p']), "{:.2f}".format(top['binance_difference']), "{:.2f}".format(top['gateio_difference']), "{:.2f}".format(float(top['binance_price'])), "{:.2f}".format(float(top['gateio_price']))))
#print ("done")



      

