# LOT Traceability Flask

MS SQL 기반 LOT 추적성(상위/하위) 조회용 Flask 웹앱입니다.

## 기능
- DB 접속 정보(서버/포트/DB/계정/드라이버) .env 파일 입력
- LOT 번호 기준 상위 LOT 추적(원자재 방향)
- LOT 번호 기준 하위 LOT 추적(생산/출하 방향)
- 테이블명/컬럼명을 화면에서 입력하여 다양한 스키마에 대응

## 실행 방법
1. 폴더 이동
   - `cd LotTraceabilityFlask`
2. 가상환경 생성/활성화 (선택)
3. 환경파일 준비
   - `.env.example`를 참고해서 `.env` 값을 수정
4. 패키지 설치
   - `pip install -r requirements.txt`
5. 실행
   - `python app.py`
6. 브라우저 접속
   - `http://127.0.0.1:5002`

## .env 설정
필수 DB 설정:
- `DB_SERVER`
- `DB_PORT`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_DRIVER`

기본 추적 컬럼 설정(선택):
- `TRACE_TABLE_NAME`
- `TRACE_LOT_COLUMN`
- `TRACE_PARENT_COLUMN`
- `TRACE_PROCESS_COLUMN`
- `TRACE_ITEM_COLUMN`
- `TRACE_QTY_COLUMN`
- `TRACE_EVENT_TIME_COLUMN`
- `TRACE_MAX_DEPTH`

## 기본 컬럼 가정
기본값은 아래 구조를 가정합니다. 필요시 화면에서 변경하세요.
- 테이블: `lot_trace`
- LOT 컬럼: `lot_no`
- 부모 LOT 컬럼: `parent_lot_no`
- 공정 컬럼: `process_name`
- 품목 컬럼: `item_code`
- 수량 컬럼: `qty`
- 이력시간 컬럼: `event_time`

## 화면별 연결 테이블
현재 화면과 기능이 사용하는 주요 테이블은 아래와 같습니다.

| 화면 / 기능 | 연결 테이블 | 용도 |
| --- | --- | --- |
| 메인 목록 (`/`) | `QualityInspection` | 검사 목록 조회, 검색 조건 적용, 삭제 대상 조회 |
| 새 검사 입력 (`/inspection/new`) | `QualityInspection` | 검사 데이터 저장 |
| 검사 삭제 (`/inspection/delete/<id>`) | `QualityInspection` | 검사 데이터 삭제 |
| 업체 검색 팝업 | `Custinfo` | 업체코드 / 업체명 조회 |
| 품번 검색 팝업 | `MatlDanGa`, `PCodeinfo` | 업체별 품번 조회, 품명 매핑 |
| 품번/품명 표시 | `PCodeinfo` | 품번에 대한 품명 조회 |
| 화학성분 표시 | `Chemicalinfo` | Lot No 기준 화학성분 존재 여부 확인 |

참고:
- `QualityInspection`는 이 앱의 주 저장 테이블입니다.
- `Custinfo`, `PCodeinfo`, `Chemicalinfo`, `MatlDanGa`는 Yujin 참조 DB에서 조회합니다.

## 참고
- SQL 식별자(테이블/컬럼)는 서버측에서 영문/숫자/언더스코어 패턴으로 검증합니다.
- 접속 정보는 `.env`에서 읽습니다.
- SQL Server ODBC Driver는 OS에 설치되어 있어야 합니다.

## GitHub + Render 배포
이 폴더에는 Render 배포용 `Dockerfile`, `render.yaml`이 포함되어 있습니다.

1. GitHub 업로드
   - `git add LotTraceabilityFlask`
   - `git commit -m "Add Render deployment config for LotTraceabilityFlask"`
   - `git push`

2. Render에서 새 Web Service 생성
   - GitHub 저장소 연결
   - Blueprint 사용 시 `render.yaml` 인식
   - 수동 생성 시 Root Directory를 `LotTraceabilityFlask`로 설정

3. Render 환경변수 설정
   - `DB_SERVER`
   - `DB_PORT`
   - `DB_NAME`
   - `DB_USER`
   - `DB_PASSWORD`
   - `DB_DRIVER` (예: `ODBC Driver 18 for SQL Server`)
   - `YUJIN_DB_SERVER` (예: `ms0501.gabiadb.com`)
   - `YUJIN_DB_PORT`
   - `YUJIN_DB_NAME` 또는 `YUJIN_DB_DATABASE`
   - `YUJIN_DB_USER` 또는 `YUJIN_DB_USERNAME`
   - `YUJIN_DB_PASSWORD`
   - `YUJIN_DB_DRIVER`
   - `YUJIN_DB_ENCRYPT` (구버전 서버면 `no` 권장)
   - `YUJIN_DB_TRUST_SERVER_CERTIFICATE` (기본 `yes`)

4. 배포 확인
   - 배포 로그에서 컨테이너 시작 확인
   - `/` 경로 접속 후 조회 기능 테스트
