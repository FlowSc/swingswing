# KOSPI Swing Bot

KOSPI 스윙 자동매매 봇 프로젝트입니다.

현재 구조는 **FastAPI 백엔드 + React 프론트엔드 + Supabase DB/Auth + KIS Open API 모의투자** 기준입니다.

실전투자는 아직 막아두었고, 현재는 **KIS 모의투자 주문만 처리**하도록 설계되어 있습니다.

## 프로젝트 구조

```text
kospi/
  backend/      FastAPI 백엔드 서버 및 자동매매 스케줄러
  frontend/     React 프론트엔드, 회원가입/로그인/봇 제어 화면
  supabase/     Supabase 테이블 스키마
  legacy_local/ 예전 로컬 실행용 파일 보관
```

## 주요 기능

- Supabase Auth 기반 회원가입/로그인
- 회원별 KIS 앱키, 시크릿, 계좌번호 저장
- 텔레그램 봇 토큰과 Chat ID는 백엔드 환경변수에서 고정 관리
- KIS 시크릿은 백엔드에서 암호화 후 Supabase에 저장
- KOSPI 스윙 후보 종목 스캔
- 장중 감시 및 조건 충족 시 KIS 모의투자 주문
- 텔레그램 알림 발송
- 시그널, 포지션, 매매 로그 조회

## 전략 개요

현재 스윙 전략은 아래 조건을 조합합니다.

기본 조건:

- RSI(14) 30 이상 56 미만
- 일목균형표 전환선이 기준선 위로 돌파
- 볼린저 밴드 폭이 수축 중이 아님
- 당일 거래량이 전일 기준 5일 평균 거래량 이상
- 거래량 120% 이상은 추가 점수

추가 조건:

- KOSPI 지수가 5일선 위
- KOSPI 시가총액 1000위 이내 또는 KOSDAQ150 구성 종목

추가 리스크 필터:

- 20일 평균 거래량 최소 기준 통과
- 1,000원 미만 저가주 제외
- 20일 평균 거래대금 3억 원 미만 제외
- 우선주, 스팩, 리츠성 종목 제외
- 손절폭이 과도하게 넓은 종목 제외

점수 가산:

- 최근 5일 내 전환선/기준선 골든크로스
- 볼린저 밴드 폭 5% 이상 확대
- 거래량 120% 이상
- 거래량 150% 이상

장중 자동매매 진입 필터:

- 현재가가 스캔 기준 Entry의 -0.5% 이상
- 현재가가 스캔 기준 Entry의 +2.0% 이하
- 현재가가 일목균형표 기준선 이상
- 현재가가 볼린저 밴드 상단 이하
- 현재가가 당일 고점 대비 3% 이상 밀리지 않음

기본 운용 흐름:

```text
14:00  오늘의 KOSPI 스윙 후보 스캔
09:00  장중 감시 시작
14:30-15:20  신규 진입 허용
09:00-15:20  보유 포지션 관리
매 1분  보유 포지션 웹소켓 실시간 매도 감시
5분마다  watcher tick 실행
```

## 필요한 외부 서비스

- Supabase
- Railway
- KIS Open API 모의투자 계정
- Telegram Bot, 선택사항
- 프론트엔드 배포 서비스, 예: Railway, Vercel, Netlify

## Supabase 세팅

1. Supabase 프로젝트를 만듭니다.
2. `Authentication > Providers`에서 Email 로그인을 활성화합니다.
3. Supabase SQL Editor에서 [supabase/schema.sql](supabase/schema.sql)을 실행합니다.
4. Supabase에서 아래 값을 확인합니다.

```text
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
```

주의:

- `SUPABASE_ANON_KEY`는 프론트엔드에서 사용해도 됩니다.
- `SUPABASE_SERVICE_ROLE_KEY`는 백엔드에서만 사용해야 합니다.
- `SUPABASE_SERVICE_ROLE_KEY`를 React 프론트엔드에 넣으면 안 됩니다.

## 백엔드 로컬 실행

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

백엔드 `.env` 예시:

```text
ENVIRONMENT=local
TZ=Asia/Seoul
TIMEZONE=Asia/Seoul
SCHEDULER_ENABLED=false

SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
BROKER_ENCRYPTION_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

`BROKER_ENCRYPTION_KEY` 생성:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

주의:

- `BROKER_ENCRYPTION_KEY`는 서버 전체에서 쓰는 암호화 키입니다.
- 이 값으로 회원별 KIS app key, app secret을 암호화합니다.
- 중간에 바꾸면 기존에 DB에 저장된 KIS 정보를 복호화할 수 없습니다.
- React 프론트엔드에는 절대 넣으면 안 됩니다.

## 프론트엔드 로컬 실행

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

프론트엔드 `.env` 예시:

```text
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
VITE_API_BASE_URL=http://localhost:8000
```

프론트엔드에 넣으면 안 되는 값:

- `SUPABASE_SERVICE_ROLE_KEY`
- `BROKER_ENCRYPTION_KEY`
- KIS app secret
- Telegram bot token

## API 구조

인증이 필요한 API는 Supabase access token을 사용합니다.

```text
Authorization: Bearer <Supabase access token>
```

주요 API:

```text
GET  /health
GET  /broker/kis/status
POST /broker/kis
POST /bot/control
POST /bot/scan
POST /bot/watch-tick
GET  /signals/today
GET  /positions
GET  /trade-logs
```

## 프론트 화면에서 가능한 작업

- 회원가입
- 로그인
- KIS 앱키/시크릿/계좌번호 저장
- 백엔드에 고정된 텔레그램 설정 사용
- 자동매매 ON/OFF
- 오늘 시그널 스캔
- KIS 연결 테스트
- KIS 계좌 조회
- 오늘 시그널 조회
- 포지션 조회
- 매매 로그 조회

## Railway 백엔드 배포

GitHub 저장소는 하나로 유지하고, Railway 백엔드 서비스의 root directory를 아래처럼 설정합니다.

```text
backend
```

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Railway 백엔드 환경변수:

```text
ENVIRONMENT=production
TZ=Asia/Seoul
TIMEZONE=Asia/Seoul
SCHEDULER_ENABLED=true

SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
BROKER_ENCRYPTION_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

## 프론트엔드 배포

프론트엔드 서비스의 root directory:

```text
frontend
```

Build command:

```bash
npm run build
```

Output directory:

```text
dist
```

프론트엔드 배포 환경변수:

```text
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
VITE_API_BASE_URL=https://배포된-백엔드-주소
```

Supabase Auth 설정에서 프론트엔드 배포 URL도 허용해야 합니다.

예:

```text
http://localhost:5173
https://your-frontend-domain.com
```

## 보안 주의사항

- KIS app secret은 DB에 원문 저장하지 않습니다.
- 백엔드에서 `BROKER_ENCRYPTION_KEY`로 암호화해서 저장합니다.
- React 프론트엔드는 Supabase anon key와 access token만 사용합니다.
- 실전투자는 현재 백엔드 코드에서 막아두었습니다.
- 예전에 노출된 KIS 키, Telegram bot token은 운영 전 재발급하는 것이 좋습니다.

## Git에 올리면 안 되는 것

```text
.env
kis_config.local.env
.venv-*
node_modules
output
dist
*.app
*.zip
```

## Git에 올려야 하는 것

```text
.env.example
backend/requirements.txt
frontend/package-lock.json
supabase/schema.sql
```

## Supabase 추가 SQL

기존 DB에 `backtest_trades` 테이블이 이미 있다면 아래 컬럼을 한 번 추가해야 합니다.

```sql
alter table backtest_trades
  add column if not exists tp1_done boolean not null default false,
  add column if not exists tp2_done boolean not null default false,
  add column if not exists remaining_qty_ratio numeric;
```

## 현재 상태

- Git 저장소 초기화 완료
- 백엔드 FastAPI 구조 생성 완료
- 프론트 React 로그인/회원가입 화면 생성 완료
- Supabase 스키마 작성 완료
- 프론트 production build 통과
- 백엔드 문법 검사 통과

아직 필요한 것:

- Supabase 실제 프로젝트 값 입력
- Railway 백엔드 배포
- 프론트엔드 배포
- Supabase Auth redirect URL 설정
- 운영 전 노출된 키 재발급
