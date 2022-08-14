import aiohttp
import asyncio
import time
import json
import pandas as pd
from datetime import datetime, timedelta

region = 10000002

buy_fee = 1
sell_fee = 2.4
tax = 8

start_time = time.time()
utcnow = datetime.utcnow()

async def get_orders_data(session, url):
    async with session.get(url) as resp:
        try:
            data = await resp.json()
            return data
        except:
            return None

async def get_history_data(session, url, type_id):
    async with session.get(url) as resp:
        try:
            data = await resp.json()
            return (type_id, data)
        except:
            return (type_id, None)

def get_last_history(history, days):
    oldest = utcnow - timedelta(days+1)

    last_history = []
    for h in reversed(history):
        try:
            if datetime.strptime(h['date'], '%Y-%m-%d') >= oldest:
                last_history.append(h)
        except:
            pass

    return last_history

async def main():

    async with aiohttp.ClientSession() as session:

        # Getting Market Orders
        orders_tasks = []
        async with session.get(f'https://esi.evetech.net/latest/markets/{region}/orders/?datasource=tranquility&page=1') as response:
            pages = int(response.headers['x-pages'])

        for page in range(1, pages+1):
            orders_url = f'https://esi.evetech.net/latest/markets/{region}/orders/?datasource=tranquility&page={page}'
            orders_tasks.append(asyncio.ensure_future(get_orders_data(session, orders_url)))

        orders_data = await asyncio.gather(*orders_tasks)

        # Grouping Orders
        grouped = {}
        for orders in orders_data:
            for order in orders:
                type_id = order['type_id']
                is_buy_order = order['is_buy_order']

                if type_id not in grouped.keys():
                    grouped[type_id] = {'buy_orders': [], 'sell_orders': []}
                
                if is_buy_order:
                    grouped[type_id]['buy_orders'].append(order)
                else:
                    grouped[type_id]['sell_orders'].append(order)

        # Processing Orders Data
        for type_id in list(grouped):
            buy_orders = grouped[type_id]['buy_orders']
            sell_orders = grouped[type_id]['sell_orders']
            if not (buy_orders and sell_orders):
                grouped.pop(type_id)
                continue

            buy_price = max([x['price'] for x in buy_orders])
            sell_price = min([x['price'] for x in sell_orders])
            cost = buy_price * (buy_fee/100) + sell_price * (sell_fee/100 + tax/100)
            margin = sell_price - buy_price - cost

            if not margin > 0:
                grouped.pop(type_id)
                continue
            roi = round(margin/buy_price * 100, 1)
            

            yesterday = utcnow - timedelta(1)
            issued_format = '%Y-%m-%dT%H:%M:%SZ'
            buy_competition = 0
            sell_competition = 0
            for buy_order in buy_orders:
                if datetime.strptime(buy_order['issued'], issued_format) > yesterday:
                    buy_competition += 1
            for sell_order in sell_orders:
                if datetime.strptime(sell_order['issued'], issued_format) > yesterday:
                    sell_competition += 1

            grouped[type_id]['buy_price'] = buy_price
            grouped[type_id]['sell_price'] = sell_price

            grouped[type_id]['buy_competition'] = buy_competition
            grouped[type_id]['sell_competition'] = sell_competition

            grouped[type_id]['cost'] = cost
            grouped[type_id]['margin'] = margin
            grouped[type_id]['roi'] = roi
            

        # Getting Market History
        history_tasks = []
        for type_id in grouped.keys():
            history_url = f'https://esi.evetech.net/latest/markets/{region}/history/?datasource=tranquility&type_id={type_id}'
            history_tasks.append(asyncio.ensure_future(get_history_data(session, history_url, type_id)))
        
        history_data = await asyncio.gather(*history_tasks)
        
        # Processing Market History
        for data in history_data:
            type_id, history = data
            
            avg_isk_traded = 0
            avg_volume_30d = 0
            real_roi_7d = 0

            if history:
                history_30d = get_last_history(history, 30)
                if history_30d:
                    avg_price_30d = sum([x['average'] for x in history_30d]) / len(history_30d)
                    avg_volume_30d = sum([x['volume'] for x in history_30d]) / len(history_30d)
                    avg_isk_traded = avg_price_30d * avg_volume_30d
                
                history_7d = get_last_history(history, 7)
                if history_7d:
                    avg_highest_7d = sum([x['highest'] for x in history_7d]) / len(history_7d)
                    avg_lowest_7d = sum([x['lowest'] for x in history_7d]) / len(history_7d)

                    real_margin_7d = avg_highest_7d - avg_lowest_7d - grouped[type_id]['cost']
                    real_roi_7d = real_margin_7d / avg_lowest_7d * 100

            grouped[type_id]['avg_volume'] = avg_volume_30d
            grouped[type_id]['avg_isk_traded'] = avg_isk_traded
            grouped[type_id]['real_roi_7d'] = real_roi_7d

    # Creating Spreadsheet
    with open('type_ids.json', 'r') as file:
        type_ids = json.load(file)

    recommendations = []
    for type_id in list(grouped):
        try:
            name = type_ids[str(type_id)]
        except:
            continue

        d = {'Item': name,
             'Buy Price': grouped[type_id]['buy_price'], 
             'Sell Price': grouped[type_id]['sell_price'], 
             'Margin': grouped[type_id]['margin'],
             'ROI': grouped[type_id]['roi'],
             '7d Real ROI': grouped[type_id]['real_roi_7d'], 
             'Avg. Volume': grouped[type_id]['avg_volume'], 
             'Avg. ISK traded': grouped[type_id]['avg_isk_traded'], 
             'Buy Competition': grouped[type_id]['buy_competition'], 
             'Sell Competition': grouped[type_id]['sell_competition'],
            }
        recommendations.append(d)

    for recommendation in recommendations:
        if (
            recommendation['ROI'] > 70 and

            recommendation['ROI'] < 400 and
            recommendation['7d Real ROI'] > 30 and
            recommendation['Avg. Volume'] > 10 and
            recommendation['Avg. ISK traded'] > 100000000 and
            recommendation['Buy Competition'] < 5 and
            recommendation['Sell Competition'] < 5
            ):
            print(recommendation['Item'])

    df = pd.DataFrame(recommendations)
    df.to_excel('recommendations.xlsx', sheet_name='Sheet1', index=False)
 

asyncio.run(main())
print("--- %s seconds ---" % (time.time() - start_time))