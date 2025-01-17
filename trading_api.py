# trading_api.py

import requests
import logging
import datetime
from typing import Optional, Dict, Tuple, List
import json
from config import BASE_URL, ACCOUNT_NO, ACNT_PRDT_CD, API_KEY, API_SECRET
from utils import get_hashkey
import time

logger = logging.getLogger(__name__)

class TradingAPI:
    def __init__(self, access_token: str):
        self.base_url = BASE_URL
        self.access_token = access_token
        self.headers = {
            'Content-Type': 'application/json; charset=UTF-8',
            'authorization': f'Bearer {self.access_token}',
            'appkey': API_KEY,
            'appsecret': API_SECRET,
        }
        self.account_no = ACCOUNT_NO
        self.acnt_prdt_cd = ACNT_PRDT_CD
        self.session = requests.Session()

        # 세션 어댑터 설정
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=5,
            pool_maxsize=20,
            max_retries=3
        )
        self.session.mount('https://', adapter)

        # 국가별 tr_id 매핑 (실전투자 기준)
        self.tr_id_map = {
            ('US', 'BUY'): 'TTTT1002U',     # 미국 매수 주문
            ('US', 'SELL'): 'TTTT1006U',    # 미국 매도 주문
            # 필요한 추가 국가 및 주문 타입 매핑
        }


    def get_balance_details(self) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """해외증거금 통화별조회 API를 사용하여 외화 증거금 정보를 조회합니다."""
        PATH = "/uapi/overseas-stock/v1/trading/foreign-margin"
        URL = f"{self.base_url}{PATH}"
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": API_KEY,
            "appsecret": API_SECRET,
            "tr_id": "TTTC2101R",
            "custtype": "P",  # 개인 고객인 경우
        }
        params = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": self.acnt_prdt_cd
        }

        logger.debug(f"해외증거금 조회 요청 URL: {URL}")
        logger.debug(f"해외증거금 조회 요청 파라미터: {params}")
        logger.debug(f"해외증거금 조회 요청 헤더: {headers}")

        try:
            response = self.session.get(URL, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"해외증거금 조회 응답 데이터: {json.dumps(data, ensure_ascii=False, indent=4)}")

            rt_cd = data.get('rt_cd')
            if rt_cd != '0':
                msg1 = data.get('msg1', 'No message provided.')
                logger.error(f"해외증거금 조회 실패: rt_cd={rt_cd}, msg1={msg1}")
                return None, f"해외증거금 조회 실패: {msg1}"

            output = data.get('output', [])
            if not output:
                logger.info("해외증거금 정보가 없습니다.")
                return [], None

            # 필요한 필드만 추출하고, 유효한 통화만 필터링
            balance_details = []
            for item in output:
                natn_name = item.get('natn_name')
                crcy_cd = item.get('crcy_cd')
                if not natn_name or not crcy_cd:
                    continue  # 유효하지 않은 항목 건너뜀

                balance_info = {
                    "natn_name": natn_name,
                    "crcy_cd": crcy_cd,
                    "frcr_dncl_amt1": item.get('frcr_dncl_amt1', '0.000000'),
                    "frcr_gnrl_ord_psbl_amt": item.get('frcr_gnrl_ord_psbl_amt', '0.00'),
                    "frcr_ord_psbl_amt1": item.get('frcr_ord_psbl_amt1', '0.000000'),
                    "itgr_ord_psbl_amt": item.get('itgr_ord_psbl_amt', '0.00'),
                    "bass_exrt": item.get('bass_exrt', '0.00000000'),
                    "ovrs_rlzt_pfls_amt": item.get('ovrs_rlzt_pfls_amt', '0.0000')  # 해외실현손익금액 추가
                }
                balance_details.append(balance_info)

            logger.info("해외증거금 조회 성공.")
            return balance_details, None

        except requests.HTTPError as http_err:
            logger.error(f"HTTP 오류 발생: {http_err} - 응답 내용: {response.text}")
            return None, f"해외증거금 조회 HTTP 오류 발생: {http_err} - 응답 내용: {response.text}"
        except requests.RequestException as req_err:
            logger.error(f"요청 오류 발생: {req_err}")
            return None, f"해외증거금 조회 요청 오류 발생: {req_err}"
        except KeyError as key_err:
            logger.error(f"응답 데이터에 필요한 키가 없습니다: {key_err}")
            return None, f"해외증거금 조회 응답 데이터 누락: {key_err}"
        except ValueError as val_err:
            logger.error(f"데이터 변환 오류: {val_err}")
            return None, f"해외증거금 조회 데이터 변환 오류: {val_err}"
        except Exception as e:
            logger.error(f"예상치 못한 오류 발생: {e}", exc_info=True)
            return None, f"해외증거금 조회 중 예상치 못한 오류 발생: {e}"


    def send_order(self, symbol: str, order_type: str, quantity: int, order_price: float) -> Dict:
        """
        해외주식 매수/매도 주문을 전송합니다.
        :param symbol: 주식 종목 코드 (PDNO)
        :param order_type: 'BUY' 또는 'SELL'
        :param quantity: 주문 수량
        :param order_price: 주문 단가 (지정가 주문 시 필요)
        :return: 주문 성공 여부 및 상세 정보
        """
        std_symbol = symbol.upper()

        # 주문 타입에 따른 국가 설정
        countries = ['US']  # 현재는 미국만 고려. 필요 시 확장 가능

        for country in countries:
            tr_id = self.tr_id_map.get((country, order_type.upper()))
            if not tr_id:
                error_msg = f"{country} 국가에 대한 {order_type} 주문 tr_id를 찾을 수 없습니다."
                logger.error(error_msg)
                return {'success': False, 'data': None, 'error': error_msg}

            # 해외거래소 코드 순서 설정: NASD → NYSE → AMEX
            exchange_codes = ['NASD', 'NYSE', 'AMEX']

            for exchange_code in exchange_codes:
                # 주문 구분 설정
                if order_type.upper() == 'BUY':
                    ord_div = "00"  # 지정가 주문
                    ovrs_ord_unpr = f"{order_price:.2f}"  # 매수 시 지정가 가격
                elif order_type.upper() == 'SELL':
                    ord_div = "00"  # 지정가 주문
                    ovrs_ord_unpr = f"{order_price:.2f}"  # 매도 시 지정가 가격
                else:
                    error_msg = f"알 수 없는 주문 타입: {order_type}"
                    logger.error(error_msg)
                    return {'success': False, 'data': None, 'error': error_msg}

                url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"

                headers = self.headers.copy()
                headers['tr_id'] = tr_id

                # 주문 데이터 구성 (API 문서에 맞게 대문자 키 사용)
                order_data = {
                    "CANO": self.account_no,
                    "ACNT_PRDT_CD": self.acnt_prdt_cd,
                    "OVRS_EXCG_CD": exchange_code,
                    "PDNO": std_symbol,
                    "ORD_QTY": str(quantity),
                    "OVRS_ORD_UNPR": ovrs_ord_unpr,
                    "CTAC_TLNO": "",
                    "MGCO_APTM_ODNO": "",
                    "ORD_SVR_DVSN_CD": "0",
                    "ORD_DVSN": ord_div
                }

                # 해시 키 생성
                hashkey = get_hashkey(order_data)
                if not hashkey:
                    error_msg = "해시 키 생성 실패. 주문을 진행할 수 없습니다."
                    logger.error(error_msg)
                    return {'success': False, 'data': None, 'error': error_msg}
                headers['hashkey'] = hashkey

                logger.debug(f"{symbol} {order_type} 주문 요청 URL: {url}")
                logger.debug(f"{symbol} {order_type} 주문 요청 데이터: {json.dumps(order_data, ensure_ascii=False, indent=4)}")
                logger.debug(f"{symbol} {order_type} 주문 요청 헤더: {headers}")

                try:
                    response = self.session.post(url, headers=headers, data=json.dumps(order_data), timeout=10)
                    response.raise_for_status()
                    data = response.json()
                    logger.debug(f"{symbol} {order_type} 주문 응답 데이터: {json.dumps(data, ensure_ascii=False, indent=4)}")

                    rt_cd = data.get('rt_cd')
                    if rt_cd == '0':
                        msg1 = data.get('msg1', '주문이 성공적으로 처리되었습니다.')
                        logger.info(f"{symbol} {order_type} 주문 성공 - 수량: {quantity}, 가격: {order_price} USD")
                        output = data.get('output', {})
                        odno = output.get('ODNO')
                        exchange_code_used = exchange_code
                        if odno:
                            logger.info(f"{symbol} 주문 번호: {odno}")
                        return {
                            'success': True,
                            'data': {
                                'quantity': quantity,
                                'price': order_price,
                                'exchange_code': exchange_code_used,
                                'odno': odno
                            },
                            'error': None
                        }
                    else:
                        msg1 = data.get('msg1', '주문 실패')
                        error_code = data.get('msg_cd', '')
                        detailed_error = self.parse_error(rt_cd, error_code, msg1)
                        logger.error(f"{symbol} {order_type} 주문 실패: {detailed_error}")
                        # 다음 거래소 시도
                        continue

                except requests.HTTPError as http_err:
                    if response.status_code == 429 or "EGW00201" in response.text:
                        logger.warning(f"{symbol} {exchange_code} {order_type} 주문: API 호출 한도를 초과했습니다. 1초 후 재시도합니다.")
                        time.sleep(1)
                        continue  # 재시도
                    else:
                        error_msg = f"HTTP 오류 발생: {http_err} - 응답 내용: {response.text}"
                        logger.error(error_msg)
                        continue  # 다음 거래소 시도
                except requests.RequestException as req_err:
                    error_msg = f"요청 오류 발생: {req_err}"
                    logger.error(error_msg)
                    continue  # 다음 거래소 시도
                except Exception as e:
                    error_msg = f"{symbol} {exchange_code} {order_type} 주문 처리 중 예상치 못한 오류 발생: {e}"
                    logger.error(error_msg, exc_info=True)
                    continue  # 다음 거래소 시도

            # 모든 거래소에서 주문 실패 시
            error_msg = f"{symbol} {order_type} 주문: 모든 거래소에서 주문이 실패했습니다."
            logger.error(error_msg)
            return {'success': False, 'data': None, 'error': error_msg}


    def parse_error(self, rt_cd: str, msg_cd: str, msg1: str) -> str:
        """
        API 에러 메시지 파싱
        """
        error_mapping = {
            "APBK0952": "주문가능금액을 초과했습니다.",
            "APBK0656": "해당 종목 정보가 없습니다.",
            "IGW00009": "응답전문 구성 중 오류가 발생하였습니다.",
            "EGW00201": "초당 거래건수를 초과하였습니다.",
            # 추가적인 에러 코드 매핑
        }
        return error_mapping.get(msg_cd, f"알 수 없는 오류: {msg1}")


    def get_balance(self) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """해외주식 잔고 API를 통해 보유 포지션을 가져옵니다."""
        PATH = "/uapi/overseas-stock/v1/trading/inquire-balance"
        URL = f"{self.base_url}{PATH}"
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": API_KEY,
            "appsecret": API_SECRET,
            "tr_id": "TTTS3012R",  # 실전투자 tr_id
            "custtype": "P",  # 개인 고객인 경우
        }
        params = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": "NASD",  # 필요에 따라 변경 가능
            "TR_CRCY_CD": "USD",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }

        logger.debug(f"해외주식 잔고 조회 요청 URL: {URL}")
        logger.debug(f"해외주식 잔고 조회 요청 파라미터: {params}")
        logger.debug(f"해외주식 잔고 조회 요청 헤더: {headers}")

        try:
            response = self.session.get(URL, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"해외주식 잔고 조회 응답 데이터: {json.dumps(data, ensure_ascii=False, indent=4)}")

            rt_cd = data.get('rt_cd')
            if rt_cd != '0':
                msg1 = data.get('msg1', 'No message provided.')
                logger.error(f"해외주식 잔고 조회 실패: rt_cd={rt_cd}, msg1={msg1}")
                return None, f"해외주식 잔고 조회 실패: {msg1}"

            output1 = data.get('output1', [])
            if not output1:
                logger.info("보유 포지션이 없습니다.")
                return [], None

            holdings = []
            for item in output1:
                symbol = item.get('ovrs_pdno')
                buy_price_str = item.get('pchs_avg_pric', '0.0')
                try:
                    buy_price = float(buy_price_str)
                except ValueError:
                    buy_price = 0.0
                    logger.warning(f"{symbol}의 매입 평균 가격이 유효하지 않습니다: {buy_price_str}")

                buy_quantity_str = item.get('ovrs_cblc_qty', '0')
                try:
                    buy_quantity = int(buy_quantity_str)
                except ValueError:
                    buy_quantity = 0
                    logger.warning(f"{symbol}의 보유 수량이 유효하지 않습니다: {buy_quantity_str}")

                current_price_str = item.get('now_pric2', '0.0')
                try:
                    current_price = float(current_price_str)
                except ValueError:
                    current_price = 0.0
                    logger.warning(f"{symbol}의 현재 가격이 유효하지 않습니다: {current_price_str}")

                holdings.append({
                    "symbol": symbol,
                    "buy_price": buy_price,
                    "buy_quantity": buy_quantity,
                    "current_price": current_price
                })

            logger.info("보유 포지션 조회 성공.")
            return holdings, None

        except requests.HTTPError as http_err:
            logger.error(f"HTTP 오류 발생: {http_err} - 응답 내용: {response.text}")
            return None, f"해외주식 잔고 조회 HTTP 오류 발생: {http_err} - 응답 내용: {response.text}"
        except requests.RequestException as req_err:
            logger.error(f"요청 오류 발생: {req_err}")
            return None, f"해외주식 잔고 조회 요청 오류 발생: {req_err}"
        except KeyError as key_err:
            logger.error(f"응답 데이터에 필요한 키가 없습니다: {key_err}")
            return None, f"해외주식 잔고 조회 응답 데이터 누락: {key_err}"
        except ValueError as val_err:
            logger.error(f"데이터 변환 오류: {val_err}")
            return None, f"해외주식 잔고 조회 데이터 변환 오류: {val_err}"
        except Exception as e:
            logger.error(f"예상치 못한 오류 발생: {e}", exc_info=True)
            return None, f"해외주식 잔고 조회 중 예상치 못한 오류 발생: {e}"


    def get_buy_date(self, symbol: str) -> Optional[datetime.date]:
        """
        특정 종목의 최근 매수 일자를 조회합니다.
        :param symbol: 주식 종목 코드 (PDNO)
        :return: 매수 일자 (datetime.date) 또는 None
        """
        PATH = "/uapi/overseas-stock/v1/trading/inquire-period-trans"
        URL = f"{self.base_url}{PATH}"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": API_KEY,
            "appsecret": API_SECRET,
            "tr_id": "CTOS4001R",
            "custtype": "P"
        }
        today = datetime.date.today()
        start_date = (today - datetime.timedelta(days=365)).strftime('%Y%m%d')  # 1년 전
        end_date = today.strftime('%Y%m%d')
        params = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "ERLM_STRT_DT": start_date,
            "ERLM_END_DT": end_date,
            "OVRS_EXCG_CD": "",
            "PDNO": symbol,
            "SLL_BUY_DVSN_CD": "02",
            "LOAN_DVSN_CD": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }

        logger.debug(f"{symbol} 매수 일자 조회 요청 URL: {URL}")
        logger.debug(f"{symbol} 매수 일자 조회 요청 파라미터: {params}")
        logger.debug(f"{symbol} 매수 일자 조회 요청 헤더: {headers}")

        try:
            response = self.session.get(URL, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"{symbol} 매수 일자 조회 응답 데이터: {json.dumps(data, ensure_ascii=False, indent=4)}")

            rt_cd = data.get('rt_cd')
            if rt_cd != '0':
                msg1 = data.get('msg1', 'No message provided.')
                logger.error(f"{symbol} 매수 일자 조회 실패: rt_cd={rt_cd}, msg1={msg1}")
                return None

            output1 = data.get('output1', [])
            if not output1:
                logger.info(f"{symbol}의 매수 거래 내역이 없습니다.")
                return None

            # 'trad_dt'와 'sll_buy_dvsn_cd'를 사용하여 매수 거래만 필터링
            buy_transactions = [
                item for item in output1
                if item.get('sll_buy_dvsn_cd') == '02'
            ]

            if not buy_transactions:
                logger.info(f"{symbol}의 매수 거래가 없습니다.")
                return None

            # 가장 최근 매수 거래의 'trad_dt'를 가져옴
            latest_buy = max(buy_transactions, key=lambda x: x.get('trad_dt', '00000000'))
            trad_dt_str = latest_buy.get('trad_dt')
            if not trad_dt_str:
                logger.error(f"{symbol}의 매수 거래 내역에 'trad_dt'가 없습니다.")
                return None

            try:
                trad_dt = datetime.datetime.strptime(trad_dt_str, '%Y%m%d').date()
                logger.info(f"{symbol}의 최근 매수 일자: {trad_dt}")
                return trad_dt
            except ValueError:
                logger.error(f"{symbol}의 'trad_dt' 형식 오류: {trad_dt_str}")
                return None

        except requests.HTTPError as http_err:
            logger.error(f"{symbol} 매수 일자 조회 HTTP 오류 발생: {http_err} - 응답 내용: {response.text}")
            return None
        except requests.RequestException as req_err:
            logger.error(f"{symbol} 매수 일자 조회 요청 오류 발생: {req_err}")
            return None
        except KeyError as key_err:
            logger.error(f"{symbol} 매수 일자 조회 응답 데이터에 필요한 키가 없습니다: {key_err}")
            return None
        except ValueError as val_err:
            logger.error(f"{symbol} 매수 일자 조회 데이터 변환 오류: {val_err}")
            return None
        except Exception as e:
            logger.error(f"{symbol} 매수 일자 조회 중 예상치 못한 오류 발생: {e}", exc_info=True)
            return None


    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        특정 종목의 현재가를 조회합니다. EXCD는 NAS, NYS, AMS 순으로 시도합니다.
        :param symbol: 주식 종목 코드 (SYMB)
        :return: 현재가 (float) 또는 None
        """
        exchange_order = ['NAS', 'NYS', 'AMS']
        for excd in exchange_order:
            PATH = "/uapi/overseas-price/v1/quotations/price"
            URL = f"{self.base_url}{PATH}"
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "authorization": f"Bearer {self.access_token}",
                "appkey": API_KEY,
                "appsecret": API_SECRET,
                "tr_id": "HHDFS00000300",
                "custtype": "P"
            }
            params = {
                "AUTH": "",
                "EXCD": excd,
                "SYMB": symbol
            }

            logger.debug(f"{symbol} 현재가 조회 요청 URL: {URL}")
            logger.debug(f"{symbol} 현재가 조회 요청 파라미터: {params}")
            logger.debug(f"{symbol} 현재가 조회 요청 헤더: {headers}")

            try:
                response = self.session.get(URL, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                logger.debug(f"{symbol} 현재가 조회 응답 데이터: {json.dumps(data, ensure_ascii=False, indent=4)}")

                rt_cd = data.get('rt_cd')
                if rt_cd != '0':
                    msg1 = data.get('msg1', 'No message provided.')
                    logger.error(f"{symbol} 현재가 조회 실패: rt_cd={rt_cd}, msg1={msg1}")
                    continue  # 다음 EXCD로 재시도

                output = data.get('output', {})
                if not output:
                    logger.error(f"{symbol} 현재가 상세 정보가 없습니다.")
                    continue

                last_price_str = output.get('last')
                if not last_price_str:
                    logger.error(f"{symbol} 현재가 정보가 응답에 없습니다.")
                    continue

                try:
                    last_price = float(last_price_str)
                    logger.info(f"{symbol} 현재가: {last_price} USD (EXCD: {excd})")
                    return last_price
                except ValueError:
                    logger.error(f"{symbol} 현재가 형식 오류: {last_price_str}")
                    continue  # 다음 EXCD로 재시도

            except requests.HTTPError as http_err:
                logger.error(f"{symbol} 현재가 조회 HTTP 오류 발생: {http_err} - 응답 내용: {response.text}")
                continue  # 다음 EXCD로 재시도
            except requests.RequestException as req_err:
                logger.error(f"{symbol} 현재가 조회 요청 오류 발생: {req_err}")
                continue  # 다음 EXCD로 재시도
            except KeyError as key_err:
                logger.error(f"{symbol} 현재가 조회 응답 데이터에 필요한 키가 없습니다: {key_err}")
                continue  # 다음 EXCD로 재시도
            except ValueError as val_err:
                logger.error(f"{symbol} 현재가 조회 데이터 변환 오류: {val_err}")
                continue  # 다음 EXCD로 재시도
            except Exception as e:
                logger.error(f"{symbol} 현재가 조회 중 예상치 못한 오류 발생: {e}", exc_info=True)
                continue  # 다음 EXCD로 재시도

        logger.error(f"{symbol}의 현재가를 모든 EXCD({exchange_order})에서 조회할 수 없습니다.")
        return None
    
    def get_asking_price_10(self, symbol: str, exchange_code: str = 'NAS') -> Tuple[Optional[List[Dict]], Optional[str]]:
        """
        해외주식 현재가 10호가를 조회합니다.
        :param symbol: 주식 종목 코드 (SYMB)
        :param exchange_code: 거래소 코드 (기본값: NAS)
        :return: 10호가 리스트 및 오류 메시지
        """
        PATH = "/uapi/overseas-price/v1/quotations/inquire-asking-price"
        URL = f"{self.base_url}{PATH}"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": API_KEY,
            "appsecret": API_SECRET,
            "tr_id": "HHDFS76200100",
            "custtype": "P",
        }
        params = {
            "AUTH": "",
            "EXCD": exchange_code,
            "SYMB": symbol.upper()
        }

        logger.debug(f"{symbol} 10호가 조회 요청 URL: {URL}")
        logger.debug(f"{symbol} 10호가 조회 요청 파라미터: {params}")
        logger.debug(f"{symbol} 10호가 조회 요청 헤더: {headers}")

        try:
            response = self.session.get(URL, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"{symbol} 10호가 조회 응답 데이터: {json.dumps(data, ensure_ascii=False, indent=4)}")

            rt_cd = data.get('rt_cd')
            if rt_cd != '0':
                msg1 = data.get('msg1', 'No message provided.')
                logger.error(f"{symbol} 10호가 조회 실패: rt_cd={rt_cd}, msg1={msg1}")
                return None, f"10호가 조회 실패: {msg1}"

            output2 = data.get('output2', {})
            if not output2:
                logger.error(f"{symbol}의 10호가 정보가 없습니다.")
                return None, "10호가 정보가 없습니다."

            asking_prices = []
            for i in range(1, 11):
                price_key = f'pask{i}'
                volume_key = f'vask{i}'
                price = output2.get(price_key)
                volume = output2.get(volume_key)
                if price and volume:
                    try:
                        asking_prices.append({
                            "price": float(price),
                            "volume": int(volume)
                        })
                    except ValueError:
                        logger.warning(f"{symbol}의 {price_key} 또는 {volume_key} 형식 오류: price={price}, volume={volume}")
                        continue

            if not asking_prices:
                logger.info(f"{symbol}의 10호가 정보가 없습니다.")
                return [], None

            # 가격 오름차순으로 정렬
            asking_prices.sort(key=lambda x: x['price'])
            logger.info(f"{symbol}의 10호가 조회 성공.")
            return asking_prices, None

        except requests.HTTPError as http_err:
            logger.error(f"{symbol} 10호가 조회 HTTP 오류 발생: {http_err} - 응답 내용: {response.text}")
            return None, f"10호가 조회 HTTP 오류 발생: {http_err} - 응답 내용: {response.text}"
        except requests.RequestException as req_err:
            logger.error(f"{symbol} 10호가 조회 요청 오류 발생: {req_err}")
            return None, f"10호가 조회 요청 오류 발생: {req_err}"
        except KeyError as key_err:
            logger.error(f"{symbol} 10호가 조회 응답 데이터에 필요한 키가 없습니다: {key_err}")
            return None, f"10호가 조회 응답 데이터 누락: {key_err}"
        except ValueError as val_err:
            logger.error(f"{symbol} 10호가 조회 데이터 변환 오류: {val_err}")
            return None, f"10호가 조회 데이터 변환 오류: {val_err}"
        except Exception as e:
            logger.error(f"{symbol} 10호가 조회 중 예상치 못한 오류 발생: {e}", exc_info=True)
            return None, f"10호가 조회 중 예상치 못한 오류 발생: {e}"
