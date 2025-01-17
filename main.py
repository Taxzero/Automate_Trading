# main.py

import logging
import sys
import time
import datetime
from typing import Optional, Dict
from config import mydb, DISCORD_WEBHOOK_URL
from trading_api import TradingAPI
from data_loader import get_actions
from utils import get_access_token
import requests

# 로깅 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

from logging.handlers import RotatingFileHandler

file_handler = RotatingFileHandler('trading.log', maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

def send_message(msg):
    """디스코드 메시지 전송"""
    now = datetime.datetime.now()
    message = f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {str(msg)}"
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        if response.status_code != 204:
            logger.warning(f"디스코드 메시지 전송 실패: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"디스코드 메시지 전송 중 오류 발생: {e}")
    print({"content": message})

def send_batched_messages(messages, max_length=2000):
    """메시지를 최대 길이에 맞춰 배치로 전송"""
    if not messages:
        return
    current_batch = ""
    for msg in messages:
        if len(current_batch) + len(msg) + 1 > max_length:
            send_message(current_batch)
            current_batch = msg + "\n"
        else:
            current_batch += msg + "\n"
    if current_batch:
        send_message(current_batch)

def main():
    logger.info("자동매매 프로그램 시작.")

    # 데이터베이스 연결 확인
    try:
        cursor = mydb.cursor()
        cursor.execute("SELECT 1 FROM DUAL")
        cursor.close()
        print("Oracle DB 연결 성공")
    except Exception as e:
        logger.error("데이터베이스에 연결할 수 없습니다.")
        logger.error(str(e))
        sys.exit(1)

    # 접근 토큰
    access_token = get_access_token()
    print(f"access_token: {access_token}")
    if access_token is None:
        logger.error("접근 토큰을 가져올 수 없습니다.")
        sys.exit(1)
    else:
        logger.debug("접근 토큰을 성공적으로 가져왔습니다.")
        print("접근 토큰 가져오기 성공")

    trading_api = TradingAPI(access_token)

    # 해외증거금 통화별 조회
    balance_details, balance_error = trading_api.get_balance_details()
    if balance_details is None:
        logger.error(f"해외증거금 조회 실패: {balance_error}")
        send_message(f"해외증거금 조회 실패: {balance_error}")
        sys.exit(1)

    if not balance_details:
        logger.info("해외증거금 정보가 없습니다.")
        send_message("해외증거금 정보가 없습니다.")
        sys.exit(0)

    # 미국(USD) 통화 정보
    usd_balance = next((item for item in balance_details if item['natn_name'] == '미국' and item['crcy_cd'] == 'USD'), None)

    if usd_balance is None:
        logger.error("미국(USD) 통화 정보가 없습니다.")
        send_message("미국(USD) 통화 정보가 없습니다.")
        sys.exit(1)

    # 필요한 정보
    frcr_dncl_amt1 = float(usd_balance['frcr_dncl_amt1'])
    frcr_gnrl_ord_psbl_amt = float(usd_balance['frcr_gnrl_ord_psbl_amt'])
    frcr_ord_psbl_amt1 = float(usd_balance['frcr_ord_psbl_amt1'])
    ovrs_rlzt_pfls_amt = float(usd_balance.get('ovrs_rlzt_pfls_amt', '0.0000'))

    # 매수 가능 현금
    total_purchase_cash = frcr_gnrl_ord_psbl_amt

    total_info_str = (
        f"총 외화예수금액: {frcr_dncl_amt1:.6f} USD\n"
        f"총 외화일반주문가능금액: {frcr_gnrl_ord_psbl_amt:.2f} USD\n"
        f"총 외화주문가능금액(원화주문가능환산금액): {frcr_ord_psbl_amt1:.6f} USD"
    )
    logger.info(total_info_str)
    send_message(total_info_str)

    # ==============================
    #           매도 로직
    # ==============================
    logger.info("매도 조건 확인 및 매도 주문 실행 중...")
    sold_stocks = 0
    total_profit = 0.0
    request_delay = 1.0

    profitable_positions = {}
    non_profitable_positions = {}

    sell_start_time = datetime.datetime.now()
    send_message("매도 조건 확인.....")
    send_message(f"[{sell_start_time.strftime('%Y-%m-%d %H:%M:%S')}] 매도 시작")

    holdings, balance_error = trading_api.get_balance()
    if holdings is None:
        logger.error(f"보유 종목 조회 실패: {balance_error}")
        send_message(f"보유 종목 조회 실패: {balance_error}")
        # 여기서 sys.exit(1) 대신 매수 로직 진행
    if holdings and len(holdings) > 0:
        positions = {holding['symbol']: holding for holding in holdings}
        today = datetime.date.today()

        # 보유종목들 매도 로직
        for symbol, holding in positions.items():
            buy_date = trading_api.get_buy_date(symbol)
            if buy_date is None:
                logger.warning(f"{symbol}의 매수 일자를 가져올 수 없습니다. 매도 로직에서 제외됩니다.")
                continue

            if buy_date == today:
                logger.info(f"{symbol}: 매수일({buy_date})이 오늘({today})이므로 매도 로직 건너뜀.")
                continue

            buy_price = holding['buy_price']
            buy_quantity = holding['buy_quantity']
            current_price = holding.get('current_price', 0.0)
            if buy_price != 0:
                profit_percentage = ((current_price - buy_price) / buy_price) * 100
            else:
                profit_percentage = 0.0

            if profit_percentage > 0:
                profitable_positions[symbol] = {
                    "buy_price": buy_price,
                    "buy_quantity": buy_quantity,
                    "buy_date": buy_date,
                    "current_price": current_price
                }
            else:
                non_profitable_positions[symbol] = {
                    "buy_price": buy_price,
                    "buy_quantity": buy_quantity,
                    "buy_date": buy_date,
                    "current_price": current_price
                }

        # 익절 매도
        for symbol, position in profitable_positions.items():
            buy_price = position['buy_price']
            buy_quantity = position['buy_quantity']
            current_price = trading_api.get_current_price(symbol)
            if current_price is None:
                logger.warning(f"{symbol} 현재 가격 조회 실패, 익절 스킵.")
                continue
            profit_amount = (current_price - buy_price) * buy_quantity
            if buy_price != 0:
                profit_percentage = (profit_amount / (buy_price * buy_quantity)) * 100
            else:
                profit_percentage = 0

            if profit_percentage > 0:
                order_info = trading_api.send_order(
                    symbol=symbol,
                    order_type='SELL',
                    quantity=int(buy_quantity),
                    order_price=current_price
                )
                if order_info['success']:
                    total_profit += profit_amount
                    sold_stocks += 1
                time.sleep(request_delay)

        sell_end_time = datetime.datetime.now()
        send_message(f"[{sell_end_time.strftime('%Y-%m-%d %H:%M:%S')}] 매도 종료")

        # 손절 로직
        holdings_after_sell, _ = trading_api.get_balance()
        current_holdings = len(holdings_after_sell) if holdings_after_sell else 0

        logger.info("음수/0% 포지션 보유 기간 확인 및 손절 로직 진행...")
        send_message("음수/0% 포지션 보유 기간 확인 중...")

        for symbol, position in non_profitable_positions.items():
            buy_price = position['buy_price']
            buy_quantity = position['buy_quantity']
            buy_date = position['buy_date']
            current_price = position.get('current_price', 0.0)

            today = datetime.date.today()
            holding_period = (today - buy_date).days
            logger.debug(f"{symbol} 보유기간: {holding_period}일")

            # # 3일째 -10% 이하 조기 손절
            # if holding_period == 3:
            #     if buy_price != 0:
            #         profit_percentage = ((current_price - buy_price) / buy_price) * 100
            #     else:
            #         profit_percentage = 0

            #     if profit_percentage <= -10:
            #         logger.info(f"{symbol}: 3일차, 수익률 {profit_percentage:.2f}% <= -10%, 조기 손절")
            #         cur_p = trading_api.get_current_price(symbol)
            #         if cur_p is not None:
            #             # 실제 손절
            #             order_info = trading_api.send_order(
            #                 symbol=symbol,
            #                 order_type='SELL',
            #                 quantity=int(buy_quantity),
            #                 order_price=cur_p
            #             )
            #             if order_info['success']:
            #                 loss_amount = (cur_p - buy_price) * buy_quantity
            #                 total_profit += loss_amount
            #                 sold_stocks += 1
            #         time.sleep(request_delay)
            #         continue

            # 5일 이상 보유, 수익률 <=0 손절
            if holding_period >= 5:
                if buy_price != 0:
                    profit_percentage = ((current_price - buy_price) / buy_price) * 100
                else:
                    profit_percentage = 0

                if profit_percentage <= 0:
                    logger.info(f"{symbol}: 5일 이상 보유, 0% 이하 손절.")
                    cur_p = trading_api.get_current_price(symbol)
                    if cur_p is None:
                        logger.warning(f"{symbol} 현재가 조회 실패, 손절 불가")
                        continue
                    loss_amount = (cur_p - buy_price) * buy_quantity
                    if loss_amount <= 0:
                        order_info = trading_api.send_order(
                            symbol=symbol,
                            order_type='SELL',
                            quantity=int(buy_quantity),
                            order_price=cur_p
                        )
                        if order_info['success']:
                            total_profit += loss_amount
                            sold_stocks += 1
                        time.sleep(request_delay)
                else:
                    logger.info(f"{symbol}: 5일 이상이지만 수익률>0, 손절 안함.")
    else:
        logger.info("보유 포지션 없음 -> 매도 로직 스킵, 매수 진행")
        send_message("보유 포지션이 없습니다 -> 매도 스킵")
        sell_end_time = datetime.datetime.now()
        send_message(f"[{sell_end_time.strftime('%Y-%m-%d %H:%M:%S')}] 매도 종료") 

    # =============
    #   매수 로직
    # =============
    buy_start_time = datetime.datetime.now()
    send_message("매수 조건 확인.....")
    send_message(f"[{buy_start_time.strftime('%Y-%m-%d %H:%M:%S')}] 매수 시작")

    bought_stocks = 0
    actions = get_actions()  # 수정된 data_loader get_actions
    logger.info(f"받은 매매 신호 수: {len(actions)}")
    send_message(f"총 매수 신호 개수: {len(actions)} 개")

    if len(actions) == 0:
        logger.info("매수 신호 없음 -> 매수 건너뜀")
        send_message("매수 신호가 없습니다. 매수 없음.")
    else:
        # 분할: 종목 수 n개
        n = len(actions)
        if n > 0:
            per_stock_cash = total_purchase_cash / n
        else:
            per_stock_cash = 0.0

        request_delay = 1.0
        MIN_BUY_AMOUNT = 0.01
        MIN_BUY_QUANTITY = 1

        logger.info(f"매수 가능 현금: {total_purchase_cash:.6f} USD, 종목 수: {n}, 1종목당 {per_stock_cash:.6f} USD")
        send_message(f"매수 가능 현금: {total_purchase_cash:.6f} USD\n"
                     f"종목 수: {n}, 종목당 {per_stock_cash:.6f} USD")

        insufficient_buy_messages = []
        buy_summary = {}  # 종목별 매수 수량 기록

        for action in actions:
            symbol = action['symbol']
            buy_amount = per_stock_cash
            if buy_amount < MIN_BUY_AMOUNT:
                warning_msg = f"{symbol}: 매수 금액({buy_amount:.6f}) < {MIN_BUY_AMOUNT}, 건너뜀"
                logger.warning(warning_msg)
                insufficient_buy_messages.append(warning_msg)
                continue

            # 10호가 조회
            asking_prices, asking_error = trading_api.get_asking_price_10(symbol)
            if asking_prices is None:
                warning_msg = f"{symbol}: 10호가 조회 실패 -> 건너뜀"
                logger.warning(warning_msg)
                insufficient_buy_messages.append(warning_msg)
                continue

            if not asking_prices:
                warning_msg = f"{symbol}: 10호가 정보가 없음 -> 건너뜀"
                logger.warning(warning_msg)
                insufficient_buy_messages.append(warning_msg)
                continue

            # 매도호가 가격 기준으로 오름차순 정렬 (최저 가격 우선)
            asking_prices_sorted = sorted(asking_prices, key=lambda x: x['price'])

            desired_quantity = int(buy_amount / min([ask['price'] for ask in asking_prices_sorted if ask['price'] > 0] or [1]))
            remaining_quantity = desired_quantity
            total_bought = 0
            buy_quantities = []

            for ask in asking_prices_sorted:
                price = ask['price']
                volume = ask['volume']

                if price <= 0:
                    continue  # 가격이 0이거나 음수인 호가 제외

                possible_quantity = int(buy_amount / price)
                if possible_quantity <= 0:
                    continue  # 매수 금액이 호가 가격보다 낮아 매수 불가능

                buy_quantity = min(volume, possible_quantity, remaining_quantity)
                if buy_quantity < MIN_BUY_QUANTITY:
                    continue  # 매수 수량이 최소 매수 수량보다 작으면 건너뜀

                # 실제 매수 주문
                order_price = round(price, 2)  # 소수점 두 자리로 반올림
                order_info = trading_api.send_order(
                    symbol=symbol,
                    order_type='BUY',
                    quantity=int(buy_quantity),
                    order_price=order_price
                )

                if not order_info['success']:
                    logger.warning(f"{symbol}: 매수 주문 실패, 가격을 반올림하여 다시 시도.")
                    rounded_order_price = round(price)  # 정수로 반올림
                    order_info = trading_api.send_order(
                        symbol=symbol,
                        order_type='BUY',
                        quantity=int(buy_quantity),
                        order_price=rounded_order_price
                    )

                if order_info['success']:
                    buy_quantities.append({'price': order_price, 'quantity': buy_quantity})
                    total_bought += buy_quantity
                    remaining_quantity -= buy_quantity
                    bought_stocks += 1
                    buy_amount -= buy_quantity * price
                    time.sleep(request_delay)
                else:
                    logger.error(f"{symbol}: 매수 주문 실패. 두 번 시도 모두 실패.")
                if remaining_quantity <= 0:
                    break  # 원하는 수량을 모두 매수했으면 종료

            buy_summary[symbol] = total_bought

            if total_bought == 0:
                warning_msg = f"{symbol}: 매수 수량이 0개여서 매수하지 않았습니다."
                logger.warning(warning_msg)
                insufficient_buy_messages.append(warning_msg)
            else:
                bought_details = ', '.join([f"{item['quantity']}주 @ {item['price']} USD" for item in buy_quantities])
                info_msg = f"{symbol}: 총 {total_bought}주 매수 - {bought_details}"
                logger.info(info_msg)
                send_message(info_msg)

        buy_end_time = datetime.datetime.now()
        send_message(f"[{buy_end_time.strftime('%Y-%m-%d %H:%M:%S')}] 매수 종료")

        if insufficient_buy_messages:
            send_batched_messages(insufficient_buy_messages)

        sell_order_count = sold_stocks
        buy_order_count = bought_stocks

        logger.info(f"총 매도 주문 종목 수 : {sell_order_count} 개")
        logger.info(f"총 매수 주문 종목 수 : {buy_order_count} 개")
        send_message(f"총 매도 주문 종목 수 : {sell_order_count} 개\n총 매수 주문 종목 수 : {buy_order_count} 개")

        # 매수 종목 및 수량 출력
        buy_summary_str = "매수 종목 및 수량:\n"
        for symbol, quantity in buy_summary.items():
            buy_summary_str += f"{symbol}: {quantity}주\n"
        logger.info(buy_summary_str.strip())
        send_message(buy_summary_str.strip())

        updated_holdings, _ = trading_api.get_balance()
        current_holdings = len(updated_holdings) if updated_holdings else 0
        logger.info(f"현재 보유 종목: {current_holdings} 개")
        send_message(f"현재 보유 종목: {current_holdings} 개")

        balance_details_after, balance_error_after = trading_api.get_balance_details()
        if balance_details_after is not None:
            usd_balance_after = next((item for item in balance_details_after if item['natn_name'] == '미국' and item['crcy_cd'] == 'USD'), None)
            if usd_balance_after:
                ovrs_rlzt_pfls_amt_after = float(usd_balance_after.get('ovrs_rlzt_pfls_amt', '0.0000'))
            else:
                ovrs_rlzt_pfls_amt_after = 0.0
        else:
            ovrs_rlzt_pfls_amt_after = 0.0

    logger.info("자동매매 프로그램 종료.")
    send_message(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 자동매매 프로그램 종료.")

if __name__ == "__main__":
    main()
