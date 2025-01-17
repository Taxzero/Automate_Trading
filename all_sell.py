# all_sell.py

import logging
import sys
import datetime
from typing import Optional, Dict
from config import mydb, DISCORD_WEBHOOK_URL
from trading_api import TradingAPI
from utils import get_access_token
import requests
import time

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

def main():
    logger.info("전체 매도 스크립트 시작.")

    # 데이터베이스 연결 확인
    try:
        cursor = mydb.cursor()
        cursor.execute("SELECT 1 FROM DUAL")
        cursor.close()
        logger.info("Oracle DB 연결 성공")
    except Exception as e:
        logger.error("데이터베이스에 연결할 수 없습니다.")
        logger.error(str(e))
        sys.exit(1)

    # 접근 토큰 가져오기
    access_token = get_access_token()
    if access_token is None:
        logger.error("접근 토큰을 가져올 수 없습니다.")
        sys.exit(1)
    else:
        logger.debug("접근 토큰을 성공적으로 가져왔습니다.")
        send_message("접근 토큰 가져오기 성공")

    trading_api = TradingAPI(access_token)

    # 해외증거금 통화별 조회 (매도 종목 리스트 파악을 위해 필요)
    balance_details, balance_error = trading_api.get_balance_details()
    if balance_details is None:
        logger.error(f"해외증거금 조회 실패: {balance_error}")
        send_message(f"해외증거금 조회 실패: {balance_error}")
        sys.exit(1)

    # 보유 종목(포지션) 조회
    holdings, balance_error = trading_api.get_balance()
    if holdings is None:
        logger.error(f"보유 종목 조회 실패: {balance_error}")
        send_message(f"보유 종목 조회 실패: {balance_error}")
        sys.exit(1)

    if not holdings:
        logger.info("현재 보유 종목이 없습니다. 매도할 종목이 없습니다.")
        send_message("현재 보유 종목이 없습니다. 매도할 종목이 없습니다.")
        sys.exit(0)

    send_message("보유 종목 전량 매도 시작")
    sold_stocks = 0
    request_delay = 1.0

    for holding in holdings:
        symbol = holding['symbol']
        buy_quantity = holding['buy_quantity']
        current_price = trading_api.get_current_price(symbol)

        if current_price is None:
            logger.warning(f"{symbol}의 현재 가격을 가져올 수 없어 매도를 건너뜀.")
            continue

        # 매도 주문 시도
        order_info = trading_api.send_order(
            symbol=symbol,
            order_type='SELL',
            quantity=int(buy_quantity),
            order_price=current_price
        )

        if order_info['success']:
            sold_stocks += 1
            logger.info(f"{symbol} {buy_quantity}주 매도 성공")
        else:
            logger.error(f"{symbol} 매도 주문 실패: {order_info}")
        time.sleep(request_delay)

    send_message(f"총 매도 완료 종목 수: {sold_stocks} 개")

    # 매도 후 현재 보유 종목 수 확인
    holdings_after_sell, _ = trading_api.get_balance()
    current_holdings = len(holdings_after_sell) if holdings_after_sell else 0
    logger.info(f"매도 후 현재 보유 종목: {current_holdings} 개")
    send_message(f"매도 후 현재 보유 종목: {current_holdings} 개")

    # 해외실현손익금액 재조회
    balance_details_after, balance_error_after = trading_api.get_balance_details()
    if balance_details_after is not None:
        usd_balance_after = next((item for item in balance_details_after if item['natn_name'] == '미국' and item['crcy_cd'] == 'USD'), None)
        if usd_balance_after:
            ovrs_rlzt_pfls_amt_after = float(usd_balance_after.get('ovrs_rlzt_pfls_amt', '0.0000'))
        else:
            ovrs_rlzt_pfls_amt_after = 0.0
    else:
        ovrs_rlzt_pfls_amt_after = 0.0

    logger.info(f"총 해외실현손익금액: {ovrs_rlzt_pfls_amt_after:.4f} USD")
    send_message(f"총 해외실현손익금액: {ovrs_rlzt_pfls_amt_after:.4f} USD")

    logger.info("전체 매도 스크립트 종료.")
    send_message("전체 매도 스크립트 종료.")

if __name__ == "__main__":
    main()
