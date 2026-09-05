# ipo-eval

**우리 회사가 코스닥에 상장하면 내 스톡옵션은 얼마일까** — 최근 5년 코스닥 상장 실데이터로
계산해 Threads에 바로 올릴 글로 만들어 주는 Claude Code 스킬.

> 재미로 보는 계산기입니다. 투자·세무·법률 자문이 아닙니다.
> 옵션 행사, 주식 매매, 이직 판단에 쓰지 마세요.

## 무엇을 하나

회사 질문 여덟 개, 스톡옵션 질문 일곱 개. 답하고 나면 이런 글이 나옵니다.

```
🏢 우리 회사가 코스닥 가면?
· 상장 가능성 64% · 거래소 예비심사 청구
· 예상 상장 2027년 상반기
· 예상 시총 1,496억원
· 주당 25,582원

내 스톡옵션 5,000주 중 상장 시점 행사 가능 2,500주 (행사가 3,000원)
· 세후 손에 쥐는 돈 5,633만원
· 오늘 기준으로 당기면 5,573만원
· 지분 0.04%

⚠️ 재미로 보는 추정. 최근 코스닥 상장 IT·소프트웨어 20곳 기준.
#스톡옵션 #코스닥 #IPO
```

**메인 글의 숫자는 기준 시나리오 하나입니다.** 폭은 첫 답글에 들어갑니다.

```
[범위] 위 숫자는 기준 시나리오 하나입니다. 시총 374억원~3,117억원,
주당 6,395원~53,310원까지 벌어집니다(비교기업 배수 하위 10%~상위 90%).
최악·최선이 아닙니다.
같은 폭으로 세후 가치는 846만원~1억2,551만원입니다.
```

답글은 5개입니다(회사만 계산하면 4개). 비교기업 목록(업종 포함), 범위와 가정, 세금·할인·
모델 오차, 상장 가능성의 근거, 행사 비용과 6개월 뒤 시나리오. 답글도 500자 안에 들어갑니다.

## 설치

Claude Code 플러그인입니다. 대화창에서 두 줄이면 됩니다.

```
/plugin marketplace add albertrim/eval-stockoption-skill
/plugin install ipo-eval
```

`python3` 3.10 이상만 있으면 됩니다. 설치할 패키지는 없습니다.

| 이렇게 치면 | 무엇이 시작되나 |
|---|---|
| `/ipo-eval:company` | 회사 모드 — 질문 8개 |
| `/ipo-eval:option` | 옵션 모드 — 질문 7개 |
| `/ipo-eval:company 회사이름` | 회사 이름까지 한 번에. 질문 1번을 건너뜁니다 |
| "우리 회사 코스닥 가면 얼마야" | 회사 모드 |
| "내 스톡옵션 얼마야" | 옵션 모드 |

옵션 모드는 회사 모드 결과 위에서 돌아갑니다. 저장된 회사가 없으면 회사 모드부터 하자고
알려줍니다.

### DART 자동 조회 (선택)

회사 이름을 넣으면 DART 전자공시에서 **설립연도·매출·영업손익·발행주식수**를 찾아 자동으로
채웁니다. 그만큼 질문이 줄어듭니다. 감사보고서나 사업보고서를 내는 회사면 대개 잡힙니다.

쓰려면 [opendart.fss.or.kr](https://opendart.fss.or.kr)에서 키를 무료로 발급받아 넣으세요.

```bash
echo "발급받은키" > ~/.ipo-eval/dart_key
```

키가 없거나, DART에 그 회사가 없거나, 보고서에서 숫자를 못 읽으면 **아무 말 없이 원래대로
직접 물어봅니다.** 못 믿을 값은 버리고 묻습니다 — 표 단위를 잘못 읽었거나(매출 1억 미만),
당기와 전년이 같은 값이거나, 영업손익이 매출의 3배를 넘는 경우입니다.

사명이 바뀐 회사도 찾습니다. DART 등록명이 옛 이름이어도, 새 이름으로 넣으면 잡습니다.

직접 확인해 보려면:

```bash
python3 scripts/ipo_eval.py dart --name 회사이름   # 저장소 폴더에서
```

## 내 정보는 어디로 가나

입력한 회사·옵션 정보는 **`~/.ipo-eval/`에만 저장됩니다.** 바깥으로 나가는 요청은 둘뿐이고,
둘 다 읽기만 합니다.

| 어디로 | 무엇을 | 언제 |
|---|---|---|
| GitHub raw | 공개 데이터 파일, `VERSION` | 업데이트 확인·적용 |
| DART 오픈API | 회사 이름으로 공시 조회 | DART 키를 넣었을 때만 |

DART 조회는 **회사 이름만** 보냅니다. 매출·옵션 수량 같은 입력값은 보내지 않습니다.

지우려면 `rm -rf ~/.ipo-eval` 하면 됩니다.

## 숫자는 어디서 오나

| 데이터 | 내용 | 출처 |
|---|---|---|
| 상장사 339곳 | 최근 5년 코스닥 직접공모. 공모가·경쟁률·재무·주가 경로 | 38커뮤니케이션, 네이버 금융, KRX, DART 증권신고서 |
| 청구 이력 2,108건 | 1999년부터의 예비심사 청구·승인·철회·상장 | 38커뮤니케이션 |
| 세율·한도 | 비과세 한도, 소득세율, 증권거래세, 기준금리 | 국세청, 법제처, 한국은행 |

**과거 상장사 336곳에 이 모델을 거꾸로 적용하면 시총 오차 중앙값이 51%입니다.** 절반은 50%
이상 틀립니다. 그 숫자를 결과에 같이 찍습니다. 계산 방법과 한계는
[`references/methodology.md`](references/methodology.md)에 적어뒀습니다.

## 구조

```
.claude-plugin/
  plugin.json       플러그인 이름·버전
  marketplace.json  이 저장소를 마켓플레이스로 쓰기 위한 정의
commands/
  company.md        /ipo-eval:company
  option.md         /ipo-eval:option
skills/ipo-eval/
  SKILL.md          스킬 본문 — 질문 순서, 출력 규칙
scripts/
  ipo_eval.py       CLI (표준 라이브러리만)
  lib/              계산 엔진 — 비교기업·확률·밸류·옵션·세금·포맷·DART
  tests/test_all.py python3 scripts/tests/test_all.py
data/               배포 데이터 (JSON)
references/         계산 방법, 코스닥 상장요건
builder/            데이터 수집기 (사용자는 실행할 일 없음)
CHANGELOG.md        버전별 변경 이력
```

데이터를 직접 다시 만들려면:

```bash
cd builder && uv sync
DART_API_KEY=... uv run python build.py --years 5
uv run python backtest.py
```

## 새 버전 내보내기 (관리자용)

사용자 쪽은 세션에서 처음 스킬을 부를 때 `update check`를 돌립니다(24시간에 한 번).
무엇이 새 버전인지는 두 값으로 각각 판정합니다.

| 무엇 | 사용자가 가진 값 | 저장소에서 읽는 값 |
|---|---|---|
| 스킬 코드 | 설치 폴더의 `VERSION` | `main` 브랜치의 `VERSION` |
| 비교 데이터 | `manifest.json`의 `data_version` | `data/manifest.json`의 `data_version` |

**코드만 고쳤으면 `VERSION` 한 줄만 올려 push하면 됩니다.** 사용자에게 바로 잡힙니다.
`data/manifest.json`을 다시 만들 필요는 없습니다.

```bash
echo "0.7.0" > VERSION        # plugin.json, marketplace.json의 version도 같이
git commit -am "..." && git push
```

데이터를 새로 뽑았으면 빌더가 `manifest.json`의 `data_version`을 갱신하므로, 그것까지
같이 push하면 됩니다.

**스킬 코드가 새 버전이면 스크립트는 아무것도 바꾸지 않고 `/plugin update ipo-eval`을 안내합니다.**
플러그인은 `~/.claude/plugins/cache/`에 복사본으로 들어오므로 `git pull`이 되지 않습니다.
플러그인 업데이트는 코드와 동봉 데이터를 함께 가져옵니다. 데이터만 새 버전이면 사용자가 `y`를
눌렀을 때 `update apply --data`로 `~/.ipo-eval/data/`에 내려받습니다. 내려받은 데이터가 동봉
데이터보다 오래되면 동봉 데이터를 씁니다. 어느 쪽이든 `~/.ipo-eval/`의 프로필은 건드리지 않습니다.
(git clone으로 쓰는 개발용 폴더에서는 `update apply --skill`이 `git pull --ff-only`를 합니다.)

`.claude-plugin/plugin.json`과 `marketplace.json`의 `version`도 `VERSION`과 같이 올려주세요.
**`version`이 그대로면 `/plugin update`가 새 코드를 받지 않습니다.** 플러그인 관리 화면에
보이는 값이기도 합니다.

## 버전

현재 0.7.0. 버전별로 바뀐 내용은 [`CHANGELOG.md`](CHANGELOG.md)에 있습니다.

## 라이선스

MIT. 데이터 출처는 각 사이트의 이용약관을 따릅니다.
