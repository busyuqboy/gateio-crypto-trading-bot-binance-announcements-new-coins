import ast
import os.path
import re
import time
import random
import string
import requests
import json
import pytz
from gate_api import ApiClient, SpotApi
from datetime import datetime
from dateutil import tz
from dateutil.parser import parse
from auth.gateio_auth import *
from logger import logger
from store_order import *
from trade_client import *
import globals

client = load_gateio_creds('auth/auth.yml')
spot_api = SpotApi(ApiClient(client))

global gateio_supported_currencies

previously_found_coins = set()

def to_EST(dt):
    if isinstance(dt, datetime):
        from_zone = tz.tzutc()
        to_zone = tz.gettz('America/New_York')

        # Tell the datetime object that it's in UTC time zone since 
        # datetime objects are 'naive' by default
        local = dt.replace(tzinfo=from_zone)

        # Convert time zone
        eastern = local.astimezone(to_zone)

        return eastern
    else:
        return dt



def get_kucoin_announcement():
    logger.debug("Pulling kucoin announcement page")
    request_url = f"https://www.kucoin.com/_api/cms/articles?page=1&pageSize=10&category=listing&lang=en_US"
    latest_announcement = requests.get(request_url)
    announcements = latest_announcement.json()
    announcement = announcements['items'][0]['title']
    announcement_launch = announcements['items'][0]['summary'].replace("Trading: ", "")
    first_published_at = announcements['items'][0]['first_publish_at']
    
    try:
        found_date_text = announcement_launch[8:-6]
        found_date_time = announcement_launch[0:5]
        d = parse(f'{found_date_text}, {found_date_time} UTC')
    except ValueError:
        d = datetime(1, 1, 1, 0, 0) #min value
        from_zone = tz.gettz('UTC')
        d.replace(tzinfo=from_zone)

    found_coin = re.findall('\(([^)]+)', announcement)
    if len(found_coin) == 1 and found_coin[0] not in previously_found_coins and "gets listed on kucoin" in announcement.lower():
            uppers = found_coin[0]
            previously_found_coins.add(uppers)
            logger.debug(f'New coin detected: {uppers} at {announcement_launch}')
            dt = datetime.now()
            value = {
                "symbol": uppers,
                "atUtc": d.timestamp(),
                "atLocal": d.astimezone().strftime("%Y-%m-%dT%H:%M:%S %z"),
                "foundUtc": dt.timestamp(),
                "foundLocal": dt.astimezone().strftime("%Y-%m-%dT%H:%M:%S %z"),
                "foundEst": to_EST(dt).strftime("%Y-%m-%dT%H:%M:%S %z"),
                "diff": dt.timestamp() - float(first_published_at)
            }
            
            return value

    return False


def get_binance_announcement(pairing):
    """
    Retrieves new coin listing announcements
    """
    logger.debug("Pulling kucoin announcement page")
    # Generate random query/params to help prevent caching
    rand_page_size = random.randint(1, 200)
    letters = string.ascii_letters
    random_string = ''.join(random.choice(letters) for i in range(random.randint(10, 20)))
    random_number = random.randint(1, 99999999999999999999)
    queries = ["type=1", "catalogId=48", "pageNo=1", f"pageSize={str(rand_page_size)}", f"rnd={str(time.time())}",
               f"{random_string}={str(random_number)}"]
    random.shuffle(queries)
    logger.debug(f"Queries: {queries}")
    request_url = f"https://www.binancezh.com/gateway-api/v1/public/cms/article/list/query" \
                  f"?{queries[0]}&{queries[1]}&{queries[2]}&{queries[3]}&{queries[4]}&{queries[5]}"
    latest_announcement = requests.get(request_url)
    try:
        logger.debug(f'X-Cache: {latest_announcement.headers["X-Cache"]}')
    except KeyError:
        # No X-Cache header was found - great news, we're hitting the source.
        pass

    latest_announcement = latest_announcement.json()
    logger.debug("Finished pulling announcement page")

    announcement = latest_announcement['data']['catalogs'][0]['articles'][0]['title']

    found = get_coins_by_accouncement_text(announcement, pairing)

    if found and len([l for l in found if l in previously_found_coins]) == 0:
        return found
    
    return False



def get_coins_by_accouncement_text(latest_announcement, pairing):
    
    if "adds" in latest_announcement.lower() and "trading pair" in latest_announcement.lower() and pairing in latest_announcement:
        found_pairs = re.findall(r'[A-Z0-9]{1,10}[/][A-Z]*', latest_announcement)
        found_coins = [i.replace(f'/{pairing}', "") for i in found_pairs if i.find(pairing) != -1]
        return found_coins
    elif "will list" in latest_announcement.lower():
        found_coins = re.findall('\(([^)]+)', latest_announcement)
        if(len(found_coins) > 0):
            return found_coins
    
    return False



def get_upcoming_gateio_listings(pairing, new_listings):
    logger.debug("Pulling announcement page for [adds + trading pairs] or [will list] scenarios")
    seconds_offset = 10
    if len(new_listings) == 0:
        return False
    else:
        symbol = new_listings[0]
    
    start_time_utc = get_listing_start(symbol, pairing)
    if(start_time_utc):
        diff = datetime.fromtimestamp(start_time_utc.timestamp()) - datetime.fromtimestamp(datetime.now().timestamp())
        if diff.total_seconds() <= seconds_offset: # within seconds of listing
            found_coins = get_coins_by_accouncement_text(f"Will list ({symbol})", pairing)
            price = get_last_price(symbol, pairing, True)
            logger.info(f"[Gateio listing] {seconds_offset} seconds to go!! Lowest ask: {price}.  Starting buy phase.")
        
            if found_coins and len(found_coins) > 0:
                return found_coins
    
    return False


def read_upcoming_listing(file):
    """
    Get user inputed new listings (see https://www.gate.io/en/marketlist?tab=newlisted)
    """
    with open(file, "r+") as f:
        return json.load(f)

def store_upcoming_listing(listings):
    """
    Save order into local json file
    """
    with open('upcoming_listings.json', 'w') as f:
        json.dump(listings, f, indent=4)


def store_kucoin_announcement(announcement):
    """
    Save order into local json file
    """

    if os.path.isfile('kucoin_announcements.json'):
        file = load_order('kucoin_announcements.json')
        if len([l for l in file if l['symbol'] == announcement['symbol']]) > 0:
            return False
        else:
            file.append(announcement)

            with open('kucoin_announcements.json', 'w') as f:
                json.dump(file, f, indent=4)
           
            logger.info("Added KuCoin announcement to kucoin_announcements.json file")
    else:
        a = []
        a.append(announcement)
        store_order('kucoin_announcements.json', a)
        logger.info("File does not exist, creating file kucoin_announcements.json")


def store_binance_announcement(announcement):
    """
    Save order into local json file
    """

    if os.path.isfile('binance_announcements.json'):
        file = load_order('binance_announcements.json')
        if len([l for l in file if l['symbol'] == announcement['symbol']]) > 0:
            return False
        else:
            file.append(announcement)

            with open('binance_announcements.json', 'w') as f:
                json.dump(file, f, indent=4)
           
            logger.info("Added Binance announcement to binance_announcements.json file")
    else:
        a = []
        a.append(announcement)
        store_order('binance_announcements.json', a)
        logger.info("File does not exist, creating file binance_announcements.json")


def store_new_listing(listing):
    """
    Only store a new listing if different from existing value
    """

    if os.path.isfile('new_listing.json'):
        file = load_order('new_listing.json')
        if set(listing).intersection(set(file)) == set(listing):
            return False
        else:
            joined = file + listing
           
            with open('new_listing.json', 'w') as f:
                json.dump(joined, f, indent=4)
            
            logger.info("New listing detected, updating file")
            return file
    else:
        store_order('new_listing.json', listing)
        logger.info("File does not exist, creating file new_listing.json")




def search_binance_and_update(pairing):
    """
    Pretty much our main func for binance
    """
    count = 597
    while not globals.stop_threads:
        sleep_time = 3
        for x in range(sleep_time):
            time.sleep(1)
            if globals.stop_threads:
                break
        try:
            latest_coins = get_binance_announcement(pairing)
            if latest_coins and len(latest_coins) > 0:
                t = datetime.utcnow()

                # add to found list
                for lc in latest_coins:
                    previously_found_coins.add(lc)

                # only keep first
                single_coin = list()
                single_coin.append(latest_coins[0])

                # add to array. Tell the main thread run the buy/sell feature
                store_new_listing(single_coin)

                logger.info(f'[Binance] Found new coin(s) {", ".join(latest_coins)}!! Adding to new listings.')

                # log to file all announcements from binance
                l = { 
                    'symbol': ", ".join(latest_coins),
                    'foundUtc': t.timestamp(),
                    'foundLocal': t.astimezone().strftime("%Y-%m-%dT%H:%M:%S %z"),
                    'foundEst': to_EST(t).astimezone().strftime("%Y-%m-%dT%H:%M:%S %z")
                }
                store_binance_announcement(l)
            
            count = count + sleep_time
            if count % 600 == 0:
                logger.info("Ten minutes have passed.  Checking for coin announcements on Binanace every 3 seconds (in a separate thread)")
                count = 0
        except Exception as e:
            logger.info(e)

        



def search_gateio_and_update(pairing, new_listings):
    """
    Pretty much our main func for gateio listings
    """
    count = 599
    while not globals.stop_threads:
        
        latest_coins = get_upcoming_gateio_listings(pairing, new_listings)
        if latest_coins:
            try:
                ready = is_currency_trade_ready(latest_coins[0], pairing) or True
                #price = get_last_price(latest_coins[0], pairing, True)
                if ready:
                        logger.info(f"[Gate.io] Found new coin {latest_coins[0]}!! Adding to new listings.")
                    
                        # store as announcement coin for main thread to pick up (It's go time!!!)
                        store_new_listing(latest_coins)

                        # remove from list of coins to be listed
                        new_listings.pop(0)
                
                
            except GateApiException as e:
                if e.label != "INVALID_CURRENCY":
                    logger.error(e)
            except Exception as e:
                logger.info(e)
        
        
        
        count = count + 1
        if count % 600 == 0:
            nl = ""
            if len(new_listings) > 0:
                nl = new_listings[0]
            logger.info(f"Ten minutes have passed.  Checking for coin listing {nl} on Gate.io every 1 seconds (in a separate thread)")
            count = 0
       
        time.sleep(1)
        if globals.stop_threads:
                break


def search_kucion_and_update():
    """
    Pretty much our main func for gateio listings
    """
    count = 597
    while not globals.stop_threads:
        sleep_time = 3
        for x in range(sleep_time):
            time.sleep(1)
            if globals.stop_threads:
                break
        try:
            latest_coin = get_kucoin_announcement()
            if latest_coin:
                symbol = latest_coin['symbol']
                logger.info(f'[Kucoin] Found new coin {symbol}!! Adding to new listings.')
                
                # add to array. Tell the main thread run the buy/sell feature
                found = list()
                found.append(symbol)
                store_new_listing(found)
                
                # log to file all announements from kucoin
                store_kucoin_announcement(latest_coin)
                    
            
            count = count + sleep_time
            if count % 600 == 0:
                logger.info("Ten minutes have passed.  Checking for coin announcements on Kucoin every 3 seconds (in a separate thread)")
                count = 0
        except Exception as e:
            logger.info(e)



def get_all_gateio_currencies(single=False):
    """
    Get a list of all currencies supported on gate io
    :return:
    """
    global gateio_supported_currencies
    while not globals.stop_threads:
        logger.info("Getting the list of supported currencies from gate io")
        try:
            response = spot_api.list_currencies()
        except Exception as ge:
            logger.error(ge)
        else:   
            all_currencies = ast.literal_eval(str(response))
            currency_list = [currency['currency'] for currency in all_currencies]
            with open('currencies.json', 'w') as f:
                json.dump(currency_list, f, indent=4)
                logger.info("List of gate io currencies saved to currencies.json. Waiting 5 "
                    "minutes before refreshing list...")
            gateio_supported_currencies = currency_list
        
        if single:
            return gateio_supported_currencies
        else:
            for x in range(600):
                time.sleep(1)
                if globals.stop_threads:
                    break

      

