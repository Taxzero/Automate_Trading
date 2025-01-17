#config.py

import os
from dotenv import load_dotenv
import oracledb
import sys

# 환경 변수 로드
load_dotenv()

# Oracle Client 초기화 (Thick 모드)
try:
    oracledb.init_oracle_client(lib_dir=r"오라클url")
except Exception as err:
    print("Oracle Client 라이브러리 초기화 오류: ", err)
    sys.exit(1)

# Oracle DB 설정
ORACLE_HOST = os.getenv('ORACLE_HOST', 'localhost')
ORACLE_PORT = os.getenv('ORACLE_PORT', '1521')
ORACLE_SERVICE_NAME = os.getenv('ORACLE_SERVICE_NAME', 'XE')
ORACLE_USER = os.getenv('ORACLE_USER', 'username')
ORACLE_PASSWORD = os.getenv('ORACLE_PASSWORD', 'password')

# DSN 생성
DSN = oracledb.makedsn(ORACLE_HOST, ORACLE_PORT, service_name=ORACLE_SERVICE_NAME)

# Oracle DB 연결
try:
    mydb = oracledb.connect(
        user=ORACLE_USER,
        password=ORACLE_PASSWORD,
        dsn=DSN
    )
    print("Oracle DB 연결 성공")
except oracledb.DatabaseError as e:
    error, = e.args
    print(f"Oracle DB 연결 실패: {error.code} - {error.message}")
    mydb = None

# API 설정
BASE_URL = os.getenv('BASE_URL', 'https://openapi.koreainvestment.com:9443')
ACCOUNT_NO = os.getenv('ACCOUNT_NO', '계좌번호')
ACNT_PRDT_CD = os.getenv('ACNT_PRDT_CD', '01')  # 예: '01'
CUST_TYPE = os.getenv('CUST_TYPE', 'P')  # 'P' 개인, 'C' 법인
API_KEY = os.getenv('API_KEY', 'your_app_key')
API_SECRET = os.getenv('API_SECRET', 'your_app_secret')

# 로깅 디렉토리 설정
LOG_DIR = os.getenv('LOG_DIR', './logs')

# 기타 설정
DISCORD_WEBHOOK_URL= os.getenv("DISCORD_WEBHOOK_URL","웹훅url")
