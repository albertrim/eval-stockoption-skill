# ipo-eval 스킬 구현 계획

비상장 스타트업의 코스닥 상장 가능성·예상 시총·주당가를 추정하고, 보유 스톡옵션 가치를 계산해 Threads용 텍스트로 뽑아주는 LLM 스킬. **재미용이지만 숫자는 최근 3년 코스닥 직접공모 상장사 실데이터에서 나온다.**

## 0. 확정된 결정

| 항목 | 결정 |
|---|---|
| 패키징 | 단일 스킬 `ipo-eval`, 모드 2개 (`company`, `option`). **Claude Code 전용** — 입력은 AskUserQuestion 멀티턴, 다른 LLM 도구 호환은 목표 아님 |
| 기준 데이터 | 이 저장소의 `builder/`가 생성한 정적 JSON을 GitHub에 배포 |
| 데이터 범위 | 최근 3년 코스닥 **직접공모**만 (일반·기술특례·성장성·이익미실현). 스팩·스팩합병·리츠·코넥스 이전상장 제외 |
| 계산 | Python 스크립트(표준 라이브러리만)가 숫자 결정, LLM은 해석·서사 |
| 옵션 가치 | 3시나리오 **세후가치** + **현재가치**(코스닥 지수 실측 수익률로 시간 할인). 내재가치는 계산만 하고 출력 안 함. 확률가중·블랙숄즈 없음 |
| 출력 | Threads 메인 1개(≤500자) + 근거 답글 3~4개 |
| 업데이트 | 첫 실행 시 manifest 비교 → y/n → 데이터 + 스킬 코드 갱신 |
| 저장 | `~/.ipo-eval/` (프로필·데이터·마지막 체크 시각). 외부 전송 없음 |
| 심사 중 기업 | 38 청구 이력 전체(1999~)로 기준율 실측, 같은 업종·규모의 심사 중 회사 표시, 승인 후 예정 공모 밴드를 비교군에 포함 |
| 증권신고서 | DART `document.xml`에서 상장예정주식수·공모가 산정(유사회사·배수·할인율)·스톡옵션 현황 파싱. 실패는 null + 성공률 리포트 |

## 1. 저장소 구조

```
eval-stockoption-skill/
├── SKILL.md                  # 스킬 본문 (트리거·플로우·출력 규칙)
├── README.md                 # 설치(Claude Code)·면책·개인정보 방침
├── VERSION                   # 스킬 코드 버전 (manifest.skill_version과 비교)
├── scripts/
│   ├── ipo_eval.py           # 단일 CLI: update | validate | company | option | format
│   ├── lib/
│   │   ├── store.py          # ~/.ipo-eval/ 읽기·쓰기
│   │   ├── update.py         # manifest 체크·데이터 다운로드·git pull
│   │   ├── comps.py          # 비교기업 선정
│   │   ├── predict.py        # 상장 확률·예상 시점
│   │   ├── valuate.py        # 시총·주당가 3시나리오
│   │   ├── option_value.py   # 행사 가능 수량·세후가치·현재가치·희석 (내재가치는 내부 계산)
│   │   ├── tax.py            # 벤처기업 특례 세후 계산
│   │   └── threads.py        # Threads 포맷터 (`fmt_krw`: 만원/억+만원/억원 규칙, 500자 검사)
│   └── tests/
├── references/
│   ├── methodology.md        # 모델 근거 (LLM이 설명 요청 시 읽음)
│   └── kosdaq_listing_rules.md  # 상장요건 트랙별 수치 + 출처 URL
├── data/                     # 빌드 산출물 = 배포 데이터
│   ├── manifest.json         # data_version, skill_version, sha256, 건수, URL, 백테스트 MAPE
│   ├── kosdaq_ipo.json       # 회사별 factsheet + 주가 경로 + 신고서 파싱값
│   ├── pipeline.json         # 청구·승인·철회·상장 이력 + 현재 심사 중 기업
│   ├── base_rates.json       # pipeline.json에서 자동 계산 (승인율·소요기간 등)
│   └── tax_params.json       # 세율·한도 (수동, 기준일·출처 필수)
└── builder/                  # 데이터 빌더 (사용자 설치 불필요)
    ├── pyproject.toml        # uv, Python 3.12 고정 (FDR·pandas 호환)
    ├── fetch_listings.py
    ├── fetch_ipo_terms.py
    ├── fetch_financials.py
    ├── fetch_prices.py
    ├── fetch_pipeline.py     # 38 청구 이력 + 청구 상세(설립일)
    ├── fetch_sec_filing.py   # DART 증권신고서 파싱 (DART_API_KEY)
    ├── classify_sector.py
    ├── sector_overrides.csv
    ├── build.py
    └── backtest.py
```

사용자 PC 요구사항: `python3` (3.10+) 표준 라이브러리만. pandas·FDR은 `builder/` 전용.

## 2. 데이터셋

### 2.1 `kosdaq_ipo.json` 레코드

| 그룹 | 필드 | 출처 (0단계에서 확인) |
|---|---|---|
| 식별 | code, name, sector_tag, listing_date, listing_track(소속부 `기술성장기업부`=특례, 그 외 일반), industry_krx, industry_naver | 38 상세(종목코드·시장), FDR `KRX-DESC`(ListingDate·Sector·Industry), 네이버 업종명 |
| 공모 | band_low, band_high, ipo_price, band_position, inst_demand_ratio, retail_sub_ratio, lockup_commit_pct, offer_shares, new_shares, old_shares, offer_amount, underwriter | 38 상세 페이지 (`/html/fund/?o=v&no=`) |
| 재무 | 최근 3개 회계연도 revenue, operating_income, net_income, eps, bps (억원) + 38 요약(예심 청구 시점 매출·순이익) | 네이버 `item/main.naver` 기업실적분석, 38 상세 |
| 주식수 | shares_at_ipo(신고서 상장예정주식수, 없으면 shares_now로 대체하고 `shares_source` 표기), shares_now, marcap_now → ipo_market_cap = ipo_price × shares_at_ipo | DART 증권신고서, FDR `KOSDAQ` |
| 산정 | valuation_method(PER/PSR/EV-EBITDA/DCF 혼합), peer_names[], applied_multiple, discount_low, discount_high (평가액 대비 희망밴드 할인율) | DART 증권신고서 「인수인의 의견 - 공모가격 산정」 |
| 옵션 | options_outstanding, option_exercise_price_wavg, option_to_ipo_ratio (= 행사가 ÷ 공모가) | DART 증권신고서 「주식매수선택권 부여현황」 |
| 주가 | day1_open, day1_close, close_1m/3m/6m/12m, latest_close | FDR `DataReader(code, listing_date)` |
| 밸류 | ipo_per, ipo_psr (공모시총 ÷ 상장 직전 연도 실적) | 계산 |
| 설립 | founded_year | 38 청구 상세(`설립일자`), 없으면 DART 기업개황 `est_dt` |
| 메타 | source_urls, fetched_at | 빌더 |

금액 필드는 전부 **정수 원**(`_krw` 접미사)으로 통일한다. 38(백만원)·네이버(억원) 단위는 빌더가 변환하고, 표시 단위(만원·억원)는 `threads.py`만 다룬다.

검증 항등식: `ipo_price × shares_at_ipo ≈ ipo_market_cap` (±2%), `new_shares + old_shares = 공모주식수`. 어긋나면 레코드에 `warnings[]` 기록하고 빌드 리포트에 출력 — 조용히 통과 금지.

`sector_tag` 값: `it_saas`, `ai_data`, `bio_health`, `beauty`, `ecommerce_platform`, `fintech`, `content_game`, `hardware_semi`, `other`. 네이버 업종 → 태그 자동 매핑 후 `sector_overrides.csv`로 수동 교정.

### 2.2 `pipeline.json` — 청구 이력 (0단계에서 확인)

38 `ipo.htm?o=&key=0&page=1..84` (1999년~, ≈2,500건). 행: 청구일, 기업명, 상태(`심사중`/`승인`/`철회`/`상장`), 자본금, 매출, 순이익, 주간사, 주업종, 시장. 청구 상세(`ipo.htm?o=v&key=2&no=`)에서 설립일자·승인일·주요제품 보강. 상장 건은 종목코드로 `kosdaq_ipo.json`과 조인.

현재 `심사중`·`승인` 상태 기업은 별도 배열 `in_review[]`로 두고, 승인 후 증권신고서가 나온 기업은 밴드·산정 방식을 붙여 `expected_ipo: true` 비교군 후보로 사용.

### 2.3 `base_rates.json` — `pipeline.json`에서 자동 계산

수동 입력 없음. 빌드마다 재계산하고 표본 수를 함께 기록.

- 청구 → 승인율, 승인 → 상장 완료율, 철회율 (최근 3년·5년, 코스닥, 업종 대분류별)
- 청구 → 승인, 승인 → 상장 소요 개월 (중앙값·사분위)
- 설립 → 청구 연수 분포 (업종별 중앙값)
- 트랙별 비중 (소속부 기준, `kosdaq_ipo.json`에서)
- 할인율 `discount_rate`: 코스닥 지수(FDR `KQ11`) 최근 3년 연환산 수익률. 음수면 5년 → 10년으로 기간을 늘려 첫 양수 값, 그래도 음수면 빌드 실패. 값·기간·기준일 기록
- 단계 0~2(청구 전)의 기준율은 실측 불가 → 청구 단계 기준율에 `methodology.md`의 고정 계수를 곱하고 "추정"으로 표기

### 2.4 `tax_params.json` (수동 관리)

- 벤처기업 스톡옵션 행사이익 비과세 한도 (연·누적), 적용 요건 요약
- 근로소득세 누진세율표 + 지방소득세
- 코스닥 증권거래세율
- 스톡옵션 행사주식 보호예수 기간 (코스닥 상장규정)
- 행사 최소 재직 기간 (상법·벤처기업법상 부여 후 2년 — 출처 확인 후 기록. 일정이 이보다 빠르면 경고)
- 각 값에 `as_of`, `source_url`. **2026년 기준으로 빌드 시점에 재확인** — 현재 기억하는 수치를 그대로 넣지 않음.

### 2.5 빌더 파이프라인 (`builder/build.py`)

1. `fetch_listings` — 38 신규상장 목록(`index.htm?o=nw&page=N`, 3년 ≈ 16페이지) → 스팩 이름 필터 → 상세에서 종목코드·시장 확보 → 코스닥만. 공모 기반 목록이라 스팩합병·이전상장은 자연 제외. KIND `searchListingTypeSub`(세션 필요)로 상장유형=신규상장 교차검증(선택)
2. `fetch_ipo_terms` — 38 상세 파싱 (`spike.py`의 `detail_38` 승격). 요청 간 0.5s 대기
3. `fetch_financials` — 네이버 기업실적분석 연간 3년 + 38 요약. 상장 직전 연도가 네이버 3년 창 밖(2023년 하반기 상장)이면 38 요약으로 대체하고 `fin_source` 표기
4. `fetch_prices` — FDR 상장일 기준 시점별 종가
4a. `fetch_pipeline` — 38 청구 이력 84페이지 + 상장·심사중 건의 청구 상세. 이력은 변하지 않으므로 캐시하고 최근 2년치만 재수집
4b. `fetch_sec_filing` — DART `list.json`(corp_code, `증권신고서(지분증권)` 최신 [발행조건확정] 우선) → `document.xml` → 텍스트화 후 regex: `상장예정주식수(보통주) N주`, 「할인율」 표(평가액·희망가·할인율), 「주식매수선택권 부여현황」 표. 회사당 1건, 실패 항목은 null. 신고서가 없는 회사(구주매출 없는 소액공모 등)는 건너뜀
5. `classify_sector` — 네이버 업종명 + KRX Industry → 태그, `sector_overrides.csv`로 교정
6. `build` — 병합·항등식 검증·`kosdaq_ipo.json` + `pipeline.json` + `base_rates.json` + `manifest.json`, 리포트(건수·결측률·신고서 파싱 성공률·warnings). 추가 항등식: `shares_at_ipo × ipo_price` vs 38 공모시총, 신고서 할인율 범위 내에 확정공모가 위치
7. `backtest` — §3.4

실행: `cd builder && DART_API_KEY=… uv run python build.py`. 키가 없으면 4b만 건너뛰고 `shares_source=now`로 빌드. 초기엔 수동 실행, 안정화 후 GitHub Actions 월 1회 (선택).

## 3. 계산 모델

### 3.1 입력 (mode `company`)

필수: 회사명, 주요 비즈니스 서술(`business_description`, 자유 텍스트) → LLM이 `sector_tag` 분류 후 사용자 확인, 설립연도, 최근 연매출(+전년 매출 → 성장률 계산), 영업이익(흑자/적자), 현재 단계
선택: 전년 매출, 발행주식수(또는 최근 라운드 포스트머니·주당가). 주관사 선정·기술평가 통과는 단계(1·2)로 대신한다

수집 순서와 질문 방식은 §4.1.

단계 값: `0 없음 → 1 주관사 선정 → 2 기술평가 통과 → 3 예심 청구 → 4 예심 승인 → 5 공모 진행`

### 3.2 상장 가능성 (`predict.py`)

1. **트랙 판정** — 입력은 매출·영업이익뿐이므로 `kosdaq_listing_rules.md`의 이익·매출 요건만 본다: 흑자 ∧ 매출 요건 충족 → 일반 트랙 후보, 적자 → 특례 트랙(기술특례·성장성·이익미실현) 가정. 자기자본·시총 요건은 "미확인"으로 표기
2. **기준율** — `base_rates.json` 실측치. 예심 청구 단계면 승인율 × 완료율, 승인 단계면 완료율. 청구 전 단계는 청구 기준율 × 고정 계수(추정 표기)
3. **보정** — 업종 트랙 비중, 흑자 여부, 매출 성장률 분위, 설립 경과년수 vs 업종 중앙값. 보정 계수는 `methodology.md`에 표로 고정 (LLM 임의 조정 금지)
4. **예상 시점** — 단계별 실측 소요 개월 합산 (청구 전이면 설립→청구 업종 중앙값 사용) → `expected_ipo_date`(YYYY-MM). 현재가치의 n과 만료 검사가 이 값을 쓴다
5. **심사 중 유사 회사** — `in_review[]`에서 같은 업종 태그 ∧ 매출 log 스케일 ±1 구간 최대 3곳 (실명·매출·순이익·청구일)
6. 출력: `probability`, `expected_ipo_date`, `track`, `reasons[]`, `peers_in_review[]`

### 3.3 예상 시총·주당가 (`comps.py`, `valuate.py`)

**비교기업 선정**: 같은 `sector_tag` ∧ 매출 규모 log 스케일 ±1 구간 ∧ 흑자/적자 일치. 5개 미만이면 조건을 순서대로 완화하고 완화 내역을 출력에 명시.

**배수 선택**:
- 흑자 → 공모가 기준 PER 분포
- 적자·매출 있음 → PSR 분포
- 바이오·매출 미미 → 공모시총 절대값 분포

**주관사 방식 재현** (신고서 파싱값이 있는 비교기업이 5개 이상일 때): 평가액 = 비교기업 `applied_multiple` 중앙값 × 입력 실적, 희망밴드 = 평가액 × (1 − discount_high) ~ (1 − discount_low). 결과에 "주관사 방식" 줄을 따로 표시해 배수 분포 방식과 나란히 보여줌.

비교군에는 `expected_ipo: true`(승인 후 신고서 제출, 상장 전) 기업을 포함하되 주가 경로 통계(6M 수익률 등)에서는 제외.

**3시나리오** = 비교기업 25/50/75 백분위 배수 × 입력 실적 → 공모가 기준 시총. 별도로 "상장 6개월 후" = 공모시총 × 비교기업 6M 수익률 중앙값.

**주당가** = 시총 ÷ 상장 후 총주식수. 총주식수 = 현재 발행주식수 × (1 + 데이터셋 신주비율 중앙값 — `new_shares ÷ (shares_at_ipo − new_shares)`). 발행주식수 미입력 시 포스트머니 ÷ 최근 라운드 주당가로 추정하고 "추정" 표기. 둘 다 없으면 시총까지만 출력하고 주당가·옵션 계산은 건너뛴다(옵션 모드 진입 시 발행주식수를 다시 묻는다). 주당가가 데이터셋 공모가 분포(대부분 1만~5만 원) 밖이면 액면분할/병합 배수 제안.

### 3.4 백테스트 (`builder/backtest.py`)

데이터셋의 회사 하나를 "비상장인 척" 입력해 §3.3 모델로 공모시총을 추정 → 실제와 비교. 전체 leave-one-out 오차 중앙값(MAPE)을 `manifest.json`에 기록하고 Threads 근거 답글에 "이 모델의 과거 적중 오차 ±xx%"로 표시. 근거의 신뢰도를 사용자가 직접 보게 하는 장치.

### 3.5 스톡옵션 (`option_value.py`, `tax.py`)

입력: 수량, 행사가, 부여일, 행사 가능 일정(`vest_schedule[{after_months, cumulative_pct}]` — "2년 뒤 50%, 4년 뒤 100%" 같은 계단식과 월 단위 모두 이 형태로), 행사기간 만료일, 현재 발행주식수. 선택: 연봉(세율 구간용, 미입력 시 "다른 근로소득 없음" 가정 표기)

계산:
- 시나리오별 내재가치 = (예상 주당가 − 행사가) × 수량 — 계산용, 출력하지 않음. 수량은 전량 / 오늘 행사 가능분 / 예상 상장 시점 행사 가능분
- 가격 기준: 세후가치·현재가치는 **공모가 기준 주당가**(3시나리오)로 계산한다. "상장 6개월 후" 가격은 참고 줄로만 보여준다
- **만료 검사**: `expected_ipo_date`가 행사기간 만료 이후면 "상장 전 만료" 경고 — 현실에서 가장 흔한 0원 케이스
- 지분율 = 수량 ÷ 상장 후 총주식수
- **세후가치**(출력) = 내재가치 − 세금(비과세 한도 적용 → 초과분 근로소득 누진세 → 매도 시 증권거래세). 보호예수 기간 표기
- **현재가치**(출력) = 세후가치 ÷ (1 + r)^n. r = `base_rates.discount_rate`(§2.3), n = 오늘 → 예상 상장 시점 + 보호예수 종료까지 년수. 상장 확률은 곱하지 않고 별도 줄로만
- 행사가 > 예상 주당가인 시나리오는 0원 (음수 금지)
- **행사가 위치**: 사용자 행사가 ÷ 예상 주당가(기준)를 데이터셋 `option_to_ipo_ratio` 분포(신고서 파싱)와 비교해 백분위 표시 — "최근 상장사 스톡옵션 행사가는 공모가의 중앙값 xx%, 당신은 yy%"

## 4. SKILL.md 플로우

```
트리거
  /ipo-eval            → 모드 선택(AskUserQuestion: 회사 / 옵션)
  /ipo-eval company    → 회사 모드 바로
  /ipo-eval option     → 옵션 모드 바로
  자연어: "우리 회사 상장하면 얼마" → 회사, "내 스톡옵션 얼마" → 옵션

1. 업데이트 체크  python3 scripts/ipo_eval.py update check
   - ~/.ipo-eval/last_check 가 24h 이내면 스킵
   - manifest 3초 타임아웃, 실패 시 조용히 넘어감
   - 차이 있으면 "데이터 vX→vY, 스킬 vA→vB 업데이트할까요? (y/n)"
   - y: update apply --data (JSON 교체) / --skill (.git 있으면 git pull, 없으면 수동 안내)
2. 모드 확정  인자·자연어로 정해졌으면 건너뜀. option은 회사 프로필·결과 없으면 company부터
3. 입력 수집  §4.1 멀티턴 질문. 기존 프로필(~/.ipo-eval/profiles/<slug>.json) 있으면 재사용 여부 확인
4. 실행  ipo_eval.py company --profile <slug>  → JSON (결과는 프로필에 캐시)
         ipo_eval.py option  --profile <slug> --option <n>  → JSON (캐시된 company 결과 사용)
5. LLM 해석  JSON을 근거로 서사 작성. 숫자는 JSON 값 그대로, 새로 계산 금지
6. 출력  ipo_eval.py format --threads → 메인+답글 텍스트. macOS면 pbcopy 제안
```

### 4.1 입력 수집 — 멀티턴 질문 (Claude Code 전용)

한 턴에 질문 하나. 선택지가 정해진 것은 AskUserQuestion, 서술·숫자는 일반 채팅으로 받는다. 어느 턴이든 "모름"·"건너뜀"이 가능하고, 그 항목은 스크립트가 채우거나 null로 두고 결과에 "추정" 표시.

**회사 모드**

| 턴 | 질문 | 방식 | 저장 필드 |
|---|---|---|---|
| 1 | 회사명 | 채팅. 같은 이름 프로필이 있으면 AskUserQuestion으로 "그대로 사용 / 일부 수정 / 새로 입력" | `name` |
| 2 | **주요 비즈니스** — "무엇을 누구에게 팔아서 매출이 나는지 자유롭게, 자세히 적어주세요. 매출 비중이 큰 순서로, 과금 방식(구독·수수료·제품 판매 등)도 함께" | 채팅, 자유 서술. LLM이 `sector_tag` 후보 1~2개와 이유를 제시 → AskUserQuestion으로 확정(후보 + "기타") | `business_description`(원문 그대로), `sector_tag` |
| 3 | 설립연도 | 채팅 | `founded_year` |
| 4 | 최근 연매출과 그 전년 매출 ("85억, 그 전년 60억") | 채팅. 단위 자유("85억", "8,500,000,000") | `revenue_krw`, `revenue_prev_krw` → `revenue_growth` 계산 |
| 5 | 영업이익 (흑자/적자와 금액) | 채팅 | `operating_income_krw` |
| 6 | 상장 단계 0~5 | AskUserQuestion. 각 단계 설명 포함. 3 이상이면 같은 턴에서 청구일(·승인일)을 이어서 묻는다 | `stage`, `stage_date` |
| 7 | 발행주식수 — 모르면 최근 투자 라운드의 포스트머니와 주당 가격 | 채팅 | `shares_outstanding` 또는 `last_round{post_money_krw, price_per_share_krw}` |
| 8 | 확인 — 입력 전체를 표로 보여주고 "저장하고 계산 / 수정" | AskUserQuestion | 프로필 JSON 저장 |

**옵션 모드**

| 턴 | 질문 | 방식 | 저장 필드 |
|---|---|---|---|
| 1 | 어느 회사 프로필인지 | AskUserQuestion(프로필 목록). 없으면 회사 모드로 유도 | `company` |
| 2 | 수량과 행사가 | 채팅 | `quantity`, `strike_krw` |
| 3 | 부여일과 **행사 가능 일정** — "계약서에 '부여일로부터 2년 뒤 50%, 4년 뒤 100%'처럼 적힌 부분" ("클리프·베스팅" 용어 쓰지 않음) | 채팅. LLM이 `vest_schedule`로 정규화하고 날짜로 바꿔 되풀이 확인 ("2025-03 50% → 2027-03 100%, 맞나요?") | `grant_date`, `vest_schedule[]` |
| 4 | 행사 기간 만료일 | 채팅 | `expiry_date` |
| 5 | 연봉 (선택, 건너뛰기 가능) | 채팅 | `salary_krw` |
| 6 | 확인 — 표 + "저장하고 계산 / 수정" | AskUserQuestion | 프로필 JSON `options[]`에 추가 |

**`~/.ipo-eval/` 구성**

```
~/.ipo-eval/
├── data/            # manifest.json, kosdaq_ipo.json, pipeline.json, base_rates.json, tax_params.json
├── profiles/
│   └── 예시테크.json  # {name, business_description, sector_tag, founded_year, revenue_krw, revenue_prev_krw,
│                      #  operating_income_krw, stage, stage_date, shares_outstanding, last_round{},
│                      #  estimated[], options[{quantity, strike_krw, grant_date, vest_schedule[], expiry_date, salary_krw}],
│                      #  result{company: …, options: […]}, updated_at}
└── last_check       # 업데이트 확인 시각
```

검증은 스크립트가 한다(`ipo_eval.py validate --profile`): 매출 음수, 단계 범위 밖, 만료일 < 부여일, 행사가 ≤ 0 등은 항목·이유를 돌려주고 해당 턴만 다시 묻는다. `business_description`은 계산에 쓰지 않고 LLM이 비교기업을 설명할 때와 다음 실행 때 분류 근거로만 쓴다. Threads 출력에는 넣지 않는다.

LLM 규칙 (SKILL.md에 명시): 숫자 재계산 금지, 비교기업 이름은 JSON에 있는 것만, 매 출력에 "재미로 보는 추정, 투자 판단 근거 아님" 한 줄, "사라/팔아라" 식 표현 금지.

## 5. Threads 출력 예시

```
[메인 ≤500자]
🏢 우리 회사가 코스닥 가면?
· 상장 가능성 61% (예심 청구 단계)
· 예상 상장 2027년 상반기
· 예상 시총 보수 340억원 / 기준 550억원 / 낙관 850억원
· 주당 5,600원 / 9,000원 / 13,900원

내 스톡옵션 5,000주 (행사가 3,000원)
· 세후가치 1,290만원 / 2,990만원 / 5,440만원
· 현재가치 1,140만원 / 2,640만원 / 4,800만원
· 지분 0.08%

⚠️ 재미로 보는 추정. 최근 3년 코스닥 상장 SaaS 11곳 기준.
#스톡옵션 #코스닥 #IPO

[답글 1] 비교기업 11곳: A, B, C … (적자 SaaS, 매출 30~250억원). PSR 25/50/75 = 4.0/6.5/10.0배. 주관사 방식이면 평가액 690억원 × 할인 20~35% → 450~550억원
[답글 2] 가정: 신주비율 22%(610만 주), 6개월 후 −8%, 비과세 한도 안이라 거래세만 차감. 현재가치는 연 12% 할인(코스닥 지수 3년 연환산) × 1.1년. 모델 과거 오차 ±31%
[답글 3] 상장 가능성 근거: 최근 3년 코스닥 청구 N건 중 승인 72%, 승인 후 상장 85%, 청구→상장 중앙값 7개월. 비슷한 규모로 지금 심사 중: 라이드플럭스(매출 40억원, 8월 청구)
[답글 4] 행사 가능: 오늘 3,750주(75%), 2027-03부터 전량. 만료 2030-03, 상장 예상 2027 → 여유 3년. 행사가는 최근 상장사 중앙값(공모가의 xx%)보다 낮은 편. 보호예수 N개월
```

(숫자는 매뉴얼 §6과 같은 설명용 예시)

규칙: 마크다운 없음, 500자(한글 기준) 초과 시 포맷터가 실패 반환, 이모지 줄당 1개 이하. **금액은 항상 '원'까지 붙인다**: 1억 미만 → 만원 단위(1,300만원), 1억 이상 → 억+만원(1억2,500만원), 100억 이상 → 억원 정수(550억원). 주당가는 원 단위 정수(9,000원).

## 6. 단계별 일정

| 단계 | 산출물 | 검증 |
|---|---|---|
| 0. 스파이크 ✅ | `builder/spike.py` 3곳 end-to-end | §8 |
| 1. 빌더 | `kosdaq_ipo.json` v1 (3년치) + `pipeline.json`(1999~) + `base_rates.json` 자동 생성, 빌드 리포트 | 건수 ≈ 38 비스팩 코스닥 건수, 항등식 통과율, 결측률 필드별, 신고서 파싱 성공률(주식수·할인율·옵션 각각) |
| 2. 계산 엔진 | `lib/*.py` + pytest, `backtest.py` | 알려진 회사 재현 테스트, 백테스트 MAPE 기록, 만료·적자·주식수 미입력 경로 테스트 |
| 3. 스킬 | SKILL.md(§4.1 멀티턴 입력 포함), `ipo_eval.py`, Threads 포맷터, 업데이트 체크 | 새 셸에서 clone→실행→y/n→출력까지 수동 시나리오 |
| 4. 배포 | README, 면책, 개인정보 방침, VERSION·manifest 태그, 첫 릴리즈 | 새 Claude Code 환경에서 clone→설치→실행 확인 |
| 5. (선택) | GitHub Actions 월간 빌드 | 빌드 실패 시 이전 데이터 유지 |

## 7. 리스크

- **스크래핑 소스 변경** (38·네이버·KIND) — 빌더만 영향, 사용자는 정적 JSON. 빌드 리포트에 소스별 성공률 출력
- **세법·상장규정 수치** — 2026년 기준 재확인 전엔 배포 금지. `as_of` 없는 값은 빌드 실패
- **표본 부족** — 업종·규모 교집합 5개 미만 빈번 예상. 완화 내역을 숨기지 않고 출력
- **Python 3.14 환경** — 빌더는 uv로 3.12 고정. 사용자 스크립트는 표준 라이브러리만이라 무관
- **스킬 자기 갱신** — git clone 설치만 자동. 복사 설치는 안내만
- **증권신고서 서식 편차** — 주관사마다 표 구조가 달라 regex 실패 예상. 실패는 null, 성공률 70% 미만이면 해당 필드를 모델에서 빼고 표시만
- **DART 키** — 빌더 실행자만 필요. 키 없이도 빌드는 되지만 `shares_source=now`·산정 정보 없음

## 8. 0단계 스파이크 결과 (2026-09-05)

`builder/spike.py <표본 상장사 3곳>` → `builder/spike_out/*.json`

| 소스 | 결과 |
|---|---|
| FDR `KRX-DESC` | ListingDate 제공. 3년 코스닥 신규상장 310건(스팩 70 포함), 소속부로 특례 구분 가능 |
| 38커뮤니케이션 | **https 핸드셰이크 실패 → http 사용**, euc-kr. 목록 304건(3년, 코스피·스팩 포함), 비스팩 218건. 상세에 밴드·공모가·기관/청약 경쟁률·확약·신주/구주·공모금액·청구시점 재무 전부 있음. `기업구분`은 전부 "중소일반"이라 무의미, 설립일 없음, EPS/PER 연도표는 4/15만 존재 |
| KIND | `searchListingTypeSub`는 세션 쿠키 없으면 빈 응답. 세션 붙이면 상장유형·업종·주선인 반환 |
| 네이버 기업실적분석 | utf-8. 연간 3년 매출·영업이익·순이익·EPS·BPS(억원) + 상장주식수 + 업종명. 2023년 하반기 상장사는 직전 연도가 창 밖 |
| FnGuide | 구 URL 폐쇄(`wcomp.fnguide.com`으로 이전). 사용 안 함 |
| 38 청구 이력 | `ipo.htm?o=&key=0&page=1..84` 1999-12~현재, 상태 `''(심사중)/승인/철회/상장`, 자본금·매출·순이익·주간사·업종. 청구 상세에 설립일자·승인일·기업구분·시장구분·주요제품 |
| DART 증권신고서 | `list.json` → `document.xml`(zip/xml) 정상. 표본 신고서 23만 자: 상장예정주식수 5,771,485주, 유사회사 PER 44배·추정순이익 현재가치·할인율 표, 주식매수선택권 60회 언급, 보호예수·유통가능 물량 |
| DART 재무 API | `fnlttSinglAcnt` 심사 중 기업·상장 직전 연도 모두 "조회된 데이타가 없습니다" → 재무는 38·네이버 |
| DART 기업개황 | `company.json` 설립일·업종코드 정상 (라이드플럭스 2018-05-02) |
| 검증 | 공모가×공모주식수=공모금액 3/3 일치. 상장일 38↔FDR 165/165 일치. 이름 매칭은 `(구.OOO)`·`(유가)` 접미사 때문에 53건 실패 → **조인 키는 상세 페이지의 종목코드** |

미확정: 2026년 세율·비과세 한도·보호예수 기간 → `tax_params.json` 작성 시 출처와 함께 확정. 신고서 regex 성공률은 1단계에서 측정.
