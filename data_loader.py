# data_loader.py

import oracledb
from config import mydb
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

def get_actions() -> List[Dict]:
    """
    C_EXISTING_ACTIONS_HIS 테이블에서 
    '가장 최근 EXPECTED_increase_date'의 매매 신호를 전부 불러옵니다.
    (PREDICTED_ACTION 필터 제거)
    """
    if mydb is None:
        logger.error("데이터베이스 연결이 설정되지 않았습니다.")
        return []
    try:
        cursor = mydb.cursor()

        # 가장 최근의 EXPECTED_increase_date 구하기
        query_max_date = """
            SELECT MAX(EXPECTED_increase_date) AS MAX_DATE
            FROM C_EXISTING_ACTIONS_HIS
        """
        cursor.execute(query_max_date)
        max_date_result = cursor.fetchone()

        if not max_date_result or not max_date_result[0]:
            logger.info("데이터가 없습니다. (EXPECTED_increase_date가 존재하지 않음)")
            cursor.close()
            return []

        max_expected_increase_date = max_date_result[0]  # datetime.date 객체

        # 가장 최근 날짜의 매매 신호 가져오기 (PREDICTED_ACTION 필터 없음)
        query = """
            SELECT SYMBOL, EXPECTED_increase_date, PREDICTED_ACTION
              FROM C_EXISTING_ACTIONS_HIS
             WHERE EXPECTED_increase_date = :max_date
        """
        cursor.execute(query, {"max_date": max_expected_increase_date})
        actions = cursor.fetchall()
        cursor.close()

        action_list = []
        for action in actions:
            symbol, expected_increase_date, predicted_action = action
            action_list.append({
                "symbol": symbol,
                "expected_increase_date": expected_increase_date,
                "predicted_action": predicted_action
            })

        logger.info(f"{max_expected_increase_date}에 대한 {len(action_list)}개의 매매 신호를 가져왔습니다.")
        return action_list

    except oracledb.DatabaseError as e:
        logger.error(f"데이터베이스 오류 (get_actions): {e}")
        return []
    except Exception as e:
        logger.error(f"예상치 못한 오류 (get_actions): {e}")
        return []
