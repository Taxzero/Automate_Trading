# utils.py

import requests
import json
import os
from config import API_KEY, API_SECRET, BASE_URL, LOG_DIR
import logging
from typing import Optional, Dict
import datetime

logger = logging.getLogger(__name__)

def get_access_token() -> Optional[str]:
    """OAuth2 인증을 통해 접근 토큰을 발급받거나 캐시된 토큰을 반환합니다."""
    token_file = os.path.join(LOG_DIR, 'access_token.json')
    now = datetime.datetime.now()

    # 캐시된 토큰이 존재하는지 확인
    if os.path.exists(token_file):
        try:
            with open(token_file, 'r') as f:
                token_data = json.load(f)
            access_token = token_data.get('access_token')
            timestamp_str = token_data.get('timestamp')
            if access_token and timestamp_str:
                token_time = datetime.datetime.fromisoformat(timestamp_str)
                # 토큰 유효기간(24시간) 내인지 확인
                if now - token_time < datetime.timedelta(hours=24):
                    logger.info("캐시된 접근 토큰을 사용합니다.")
                    return access_token
                else:
                    logger.info("접근 토큰이 만료되었습니다. 토큰 파일을 삭제합니다.")
                    os.remove(token_file)
                    logger.info("토큰 파일을 삭제했습니다.")
            else:
                logger.warning("토큰 파일에 필요한 정보가 없습니다. 토큰 파일을 삭제합니다.")
                os.remove(token_file)
                logger.info("토큰 파일을 삭제했습니다.")
        except Exception as e:
            logger.error(f"토큰 파일을 읽는 중 오류 발생: {e}")
            try:
                os.remove(token_file)
                logger.info("토큰 파일을 삭제했습니다.")
            except Exception as delete_error:
                logger.error(f"토큰 파일 삭제 중 오류 발생: {delete_error}")

    # 새로운 접근 토큰 발급
    url = f"{BASE_URL}/oauth2/tokenP"
    headers = {'Content-Type': 'application/json'}
    data = {
        "grant_type": "client_credentials",
        "appkey": API_KEY,
        "appsecret": API_SECRET
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
        response.raise_for_status()
        response_data = response.json()
        access_token = response_data.get('access_token')
        if access_token:
            logger.info("새로운 접근 토큰을 발급받았습니다.")
            # 토큰과 발급 시간을 캐시 파일에 저장
            token_data = {
                'access_token': access_token,
                'timestamp': now.isoformat()
            }
            # LOG_DIR가 존재하지 않으면 생성
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(token_file, 'w') as f:
                json.dump(token_data, f)
            return access_token
        else:
            logger.error("응답에 'access_token'이 포함되지 않았습니다.")
            return None
    except requests.RequestException as e:
        logger.error(f"접근 토큰 발급 요청 실패: {e}")
        return None
    except Exception as e:
        logger.error(f"예상치 못한 오류 발생: {e}")
        return None

def get_hashkey(data: Dict) -> Optional[str]:
    """해시 키를 생성합니다."""
    url = f"{BASE_URL}/uapi/hashkey"
    headers = {
        'Content-Type': 'application/json',
        'appkey': API_KEY,
        'appsecret': API_SECRET
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
        response.raise_for_status()
        hashkey = response.json().get('HASH')
        if hashkey:
            logger.info("해시 키 생성 성공.")
            return hashkey
        else:
            logger.error("해시 키 응답 없음.")
            return None
    except requests.RequestException as e:
        logger.error(f"해시 키 생성 실패: {e}")
        return None
    except Exception as e:
        logger.error(f"예상치 못한 오류 발생: {e}")
        return None
