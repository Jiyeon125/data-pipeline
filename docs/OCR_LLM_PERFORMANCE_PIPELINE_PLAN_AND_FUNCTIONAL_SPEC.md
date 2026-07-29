# OCR+LLM 성과문서 검수 파이프라인 기획·기능명세

> 작성일: 2026-07-28  
> 상태: 오프라인 대조·사람 검수 UI 구현, 외부 LLM 호출부 미구현
> 범위: 성과계획서·성과보고서 PDF의 성과지표 구조화와 원문 검수  
> 주의: 이 문서를 작성하면서 외부 OCR·LLM API는 호출하지 않았습니다.

## 1. 결론

현재 필요한 것은 PDF 전체를 고성능 LLM에 반복 전송하는 파이프라인이 아닙니다.

권장안은 다음과 같습니다.

1. 기존 `performance_pipeline.pdf_reconciliation`이 PDF 텍스트·표·페이지 후보를 로컬에서 먼저 찾습니다.
2. 텍스트가 없거나 표가 깨진 페이지만 로컬 Tesseract OCR을 수행합니다.
3. 규칙으로 확정되지 않은 행만 관련 1~4쪽과 수기 행을 묶은 `evidence bundle`로 만듭니다.
4. 저가 모델이 구조화 추출하고, 불일치·저신뢰 행만 상위 모델이 재검수합니다.
5. LLM 결과는 `CONFIRMED`가 아닌 원시 후보로 저장하고, 산식·원문·사람 검수를 통과한 값만 분석값으로 채택합니다.

이 방식이면 현재 3개 부처 전체를 사람처럼 두 번 검수하는 보수적 실험도 대략
`US$5~15` 범위에서 시작할 수 있습니다. 반면 PDF 전체를 행마다 다시 전송하면
중복 토큰 때문에 비용과 오류가 함께 커집니다.

## 2. 목적과 비목적

### 2.1 목적

- 성과계획서의 프로그램·성과지표·목표치와 성과보고서의 최종 목표·실적·공식
  달성률을 원문 근거와 함께 구조화합니다.
- 현재 수기 구조화 엑셀을 골드셋이자 검수 입력으로 사용하여 수정량을 줄입니다.
- 추출 실패, 문서 불일치, 지표 변경을 조용히 버리지 않고 검토 큐로 보냅니다.
- 호출별 토큰·비용·모델·프롬프트 버전을 기록하여 재현성과 비용 상한을 보장합니다.

### 2.2 비목적

- LLM이 정책 성과, 낭비, 삭감·폐지 대상을 판정하지 않습니다.
- 프로그램 성과지표를 세부사업 성과로 귀속하지 않습니다.
- 문서에 없는 값을 추정하거나 계획 목표로 보고서 목표를 대체하지 않습니다.
- LLM 결과만으로 최종 점수나 점검 우선순위를 확정하지 않습니다.
- 원본 PDF를 수정하거나 Git에 올리지 않습니다.

## 3. 현재 기준선

현재 로컬 원문 대조 결과는 다음과 같습니다.

| 항목 | 현재 값 |
|---|---:|
| 대상 부처 | `019` 고용노동부, `075` 보건복지부, `162` 과학기술정보통신부 |
| PDF | 21개 |
| 페이지 | 1,750쪽 |
| 수기 성과지표 행 | 361행 |
| `EXACT_MATCH` | 54행 |
| `MATCH_AFTER_CHANGE` | 106행 |
| 그 밖의 검수·추출 대상 | 201행 |

현재 저장소의 로컬 파이프라인은 이미 문서 인벤토리, 페이지 텍스트·표 추출,
수기값 대조, 근거 페이지와 상태 저장을 수행합니다. 외부 LLM 단계는 이 결과를
대체하는 별도 파서가 아니라 `201행` 중 해결되지 않은 증거 묶음에만 붙여야 합니다.

이전 별도 체크아웃의 PDF-first 실험에서는 API 호출 없이 858개 통합 레코드를
생성하고 수기 골드셋 필드 392/448(87.5%)를 맞춘 기준선이 있었습니다. 이 수치는
현재 저장소의 검증 결과가 아니므로 재현 전에는 성능 보장치로 사용하지 않습니다.

## 4. 비용 산정

### 4.1 산정 가정

문서 전체 토큰 수가 아니라 실제 호출 단위를 다음처럼 고정합니다.

```text
호출 단위: 성과지표 1행 + 관련 원문 1~4쪽 + JSON 스키마
평균 입력: 6,000 tokens/행
평균 출력: 500 tokens/행
현재 미해결: 201행
현재 전체: 361행
환산 가정: US$1 = 1,480원
```

따라서 현재 미해결 201행은 입력 1.206M, 출력 0.1005M tokens이고, 전체
361행은 입력 2.166M, 출력 0.1805M tokens입니다. 실제 비용은 PDF 이미지
토큰화, 공급자별 토크나이저, 재시도와 캐시 적중률에 따라 달라집니다.

### 4.2 201행 1회 검수 비용

2026-07-28 공개 단가를 적용한 추정치입니다.

| 모델 | 입력/출력 US$/1M | 일반 호출 | Batch |
|---|---:|---:|---:|
| OpenAI GPT-5.4 nano | 0.20 / 1.25 | $0.37 (약 500원) | $0.18 |
| OpenAI GPT-5.4 mini | 0.75 / 4.50 | $1.36 (약 2,000원) | $0.68 |
| OpenAI GPT-5.6 Luna | 1.00 / 6.00 | $1.81 (약 2,700원) | $0.90 |
| Claude Sonnet 5, 2026-08-31까지 | 2.00 / 10.00 | $3.42 (약 5,100원) | $1.71 |
| Claude Sonnet 5, 2026-09-01부터 | 3.00 / 15.00 | $5.13 (약 7,600원) | $2.56 |
| OpenAI GPT-5.6 Terra | 2.50 / 15.00 | $4.52 (약 6,700원) | $2.26 |
| OpenAI GPT-5.6 Sol | 5.00 / 30.00 | $9.05 (약 13,400원) | $4.52 |

공식 단가 출처:

- [OpenAI GPT-5.4 nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano)
- [OpenAI GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
- [OpenAI 모델 가격표](https://developers.openai.com/api/docs/models)
- [OpenAI GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [OpenAI GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
- [OpenAI Batch API](https://platform.openai.com/docs/api-reference/batch/object?api-mode=responses)
- [Claude Sonnet 5 가격 안내](https://platform.claude.com/docs/en/about-claude/models/whats-new-sonnet-5)
- [Anthropic Batch 가격](https://platform.claude.com/docs/en/about-claude/pricing)

### 4.3 OCR 비용

로컬 PyMuPDF와 Tesseract를 우선하면 API 비용은 `0원`입니다. 현재 1,750쪽을
전부 클라우드에 보내는 경우의 대략적인 비용은 다음과 같습니다.

| OCR 방식 | 공개 단가 | 1,750쪽 추정 |
|---|---:|---:|
| Google Document AI Enterprise OCR | $1.50/1,000쪽 | $2.63 |
| Google Document AI Layout Parser | $10/1,000쪽 | $17.50 |
| AWS Textract Detect Document Text | $1.50/1,000쪽 | $2.63 |
| AWS Textract Tables | $15/1,000쪽 | $26.25 |

출처:

- [Google Document AI 가격](https://cloud.google.com/document-ai/pricing)
- [AWS Textract 가격](https://aws.amazon.com/textract/pricing/)

모든 페이지에 표 OCR을 적용할 이유는 없습니다. `text_quality_status`가 낮은 후보
페이지만 보내는 것이 비용과 오탐 모두에 유리합니다.

### 4.4 실제 예산안

| 운용안 | 현재 201행 예상 | 용도 |
|---|---:|---|
| 최소 | $1~3 | 로컬 OCR + 저가 모델 1회 + 소량 재시도 |
| 권장 파일럿 | $5~15 | 저가 추출 + 상위 모델 교차검수 + 약 20% 재시도 |
| 매우 보수적 | $15~30 | 상위 모델 중심 이중 검수, 프롬프트 튜닝 포함 |

5개 부처를 약 2,400쪽·500행으로 가정하면 Sonnet 5 1회는 현재 프로모션 단가로
약 $8.50, Batch는 약 $4.25입니다. 이중 검수와 20% 재시도를 포함하면 약
$10~20 수준입니다. 행과 페이지 수가 확정되지 않은 부처가 있으므로 이는 예산
상한을 잡기 위한 추정치일 뿐입니다.

권장 초기 상한은 `US$25`입니다. 상한의 80%에 도달하면 신규 호출을 중단하고
사람 검수 큐만 생성합니다.

## 5. 처리 구조

```text
원본 PDF(읽기 전용)
  → 기존 로컬 텍스트·표 추출
  → 페이지 품질 판정
  → 필요한 페이지만 로컬 OCR
  → 지표별 evidence bundle 생성
  → 규칙 기반 대조
     ├─ 확정 가능: 기존 결과 유지
     └─ 미해결: 저가 LLM 구조화
          ├─ 스키마·산식·근거 검증 통과: 사람 검수 큐
          └─ 불일치/저신뢰: 상위 LLM 재검수
  → 사람 승인
  → analysis-ready 채택
```

### 5.1 단계별 기능

1. **문서 등록**
   - 부처 코드, 회계연도, 문서유형, 원본 경로, SHA-256, 페이지 수를 저장합니다.
   - 동일 해시 결과가 있으면 재사용합니다.
2. **로컬 추출**
   - PyMuPDF의 페이지 텍스트와 표를 먼저 사용합니다.
   - 추출 문자 수, 한글 비율, 표 셀 수로 품질 상태를 남깁니다.
3. **선택 OCR**
   - 텍스트가 비었거나 깨진 페이지만 Tesseract로 재추출합니다.
   - 원문 텍스트와 OCR 텍스트를 덮어쓰지 않고 나란히 보존합니다.
4. **후보 페이지 검색**
   - 프로그램명, 지표명, 표 머리글을 이용해 관련 페이지를 좁힙니다.
   - 후보를 못 찾으면 PDF 전체를 LLM에 보내지 않고 `PAGE_NOT_FOUND`로 보냅니다.
5. **증거 묶음**
   - 수기 행, 후보 페이지 번호, 페이지 텍스트/표, 앞뒤 한 쪽, 문서 메타데이터만
     포함합니다.
6. **LLM 구조화**
   - JSON Schema 강제 출력, temperature 0, 값 추정 금지로 호출합니다.
7. **결정적 검증**
   - 코드·연도·문서유형, 숫자 파싱, 단위, 근거 문장 존재, 달성률 산식 비교를
     코드로 검사합니다.
8. **사람 검수**
   - LLM이 확정하지 않고 승인·수정·보류할 수 있는 엑셀/CSV 큐를 만듭니다.
9. **분석값 채택**
   - 사람 승인과 검증을 통과한 필드만 `analysis_ready_*`에 채택합니다.

## 6. 입력·출력 계약

### 6.1 입력 한 행

분석 단위는 다음과 같습니다.

```text
부처 × 프로그램 × 성과지표 × 회계연도 × 문서유형
```

필수 입력:

```text
ministry_code: string
ministry_name: string
fiscal_year: integer
document_type: PLAN | REPORT
source_file: string
source_sha256: string
manual_row_id: string | null
manual_program_name: string | null
manual_indicator_name: string | null
candidate_pages: integer[]
evidence_text: string
evidence_tables: object[]
```

부처 코드는 `019`, `075`, `162`처럼 문자열과 앞자리 0을 보존합니다.

### 6.2 LLM 구조화 출력

```json
{
  "ministry_code": "019",
  "fiscal_year": 2024,
  "document_type": "REPORT",
  "program_name_raw": null,
  "indicator_name_raw": null,
  "target_raw": null,
  "actual_raw": null,
  "achievement_rate_raw": null,
  "unit_raw": null,
  "calculation_formula_raw": null,
  "indicator_change_raw": null,
  "source_page": null,
  "evidence_quote": null,
  "field_status": {
    "program_name": "FOUND|NOT_FOUND|AMBIGUOUS",
    "indicator_name": "FOUND|NOT_FOUND|AMBIGUOUS",
    "target": "FOUND|NOT_FOUND|AMBIGUOUS",
    "actual": "FOUND|NOT_FOUND|AMBIGUOUS",
    "achievement_rate": "FOUND|NOT_FOUND|AMBIGUOUS"
  },
  "review_reason": null
}
```

`null`은 실패가 아니라 문서에서 확인하지 못했다는 정상 상태입니다. 숫자 정규화,
달성률 재계산과 수기값 비교는 LLM이 아니라 후처리 코드가 수행합니다.

### 6.3 호출 감사 로그

```text
request_id
source_sha256
evidence_bundle_sha256
provider
model
prompt_version
schema_version
started_at
finished_at
input_tokens
output_tokens
cached_input_tokens
cost_usd
retry_count
api_status
validation_status
error_type
```

프롬프트 원문에는 API 키나 사용자 개인정보를 넣지 않습니다.

## 7. 프롬프트 계약

시스템 지시는 최소한 다음 내용을 포함해야 합니다.

```text
당신은 대한민국 재정 성과문서의 값 추출기다.
제공된 증거에 실제로 적힌 값만 JSON Schema에 맞춰 반환한다.
값을 추정, 계산, 보간, 번역하거나 상식으로 채우지 않는다.
계획 목표와 보고서 최종 목표를 서로 대체하지 않는다.
성과지표를 세부사업에 귀속하지 않는다.
확인할 수 없는 값은 null과 NOT_FOUND를 반환한다.
각 FOUND 값은 같은 페이지의 짧은 근거 문장과 페이지 번호를 가진다.
문서와 수기값이 다르면 문서값을 그대로 반환하고 불일치 사유를 적는다.
```

사용자 입력에는 한 행과 제한된 증거 묶음만 포함합니다. “이 사업이 실패했는가”,
“삭감해야 하는가” 같은 정책판단 질문은 같은 호출에 넣지 않습니다.

## 8. 모델 라우팅

모델은 공급자 이름이 아니라 역할로 설정합니다.

| 단계 | 기본 역할 | 상위 모델로 보내는 조건 |
|---|---|---|
| 1차 구조화 | 저가·구조화 출력 모델 | JSON 실패, 근거 누락, 복수 후보 |
| 2차 검수 | 중급 추론 모델 | 수기값·원문 충돌, 변경 지표, 표 구조 붕괴 |
| 사람 검수 | 최종 확정 | 정책 판단, 근거 없음, 두 모델 불일치 |

초기 권장값:

```text
extractor: GPT-5.4 nano 또는 GPT-5.4 mini
reviewer: Claude Sonnet 5 또는 GPT-5.6 Luna/Terra
batch: true
temperature: 0
max_retries: 2
budget_cap_usd: 25
```

모델명을 코드에 흩뿌리지 않고 기존 `configs/llm.yaml` 한 곳에서 관리합니다.

## 9. 상태와 검증 규칙

### 9.1 처리 상태

```text
LOCAL_CONFIRMED
OCR_REQUIRED
LLM_PENDING
LLM_EXTRACTED
LLM_REVIEW_REQUIRED
HUMAN_REVIEW_REQUIRED
CONFIRMED
REJECTED
PAGE_NOT_FOUND
API_FAILED
BUDGET_STOPPED
```

### 9.2 자동 확정 금지 조건

- 근거 페이지 또는 근거 문장이 없습니다.
- 원문에서 같은 값이 둘 이상 발견됩니다.
- 보고서 목표와 계획 목표를 구분할 수 없습니다.
- 달성률 산식과 공식 달성률이 크게 다릅니다.
- 지표명이 깨졌거나 프로그램과의 계층 관계가 불명확합니다.
- LLM 두 모델이 핵심 필드에서 다릅니다.

### 9.3 값 검증

- 원본 문자열과 정규화 숫자를 모두 보존합니다.
- `%`, 명, 건, 억 원 등 단위를 분리합니다.
- 분모가 0이거나 증감형·역지표이면 일반 달성률 산식 비교를 제한합니다.
- 공식 달성률을 재계산값으로 덮어쓰지 않습니다.
- 수정·삭제·추가된 지표를 같은 지표로 자동 확정하지 않습니다.

## 10. 재시도·캐시·비용 통제

- `source_sha256 + evidence_bundle_sha256 + prompt_version + model`을 캐시 키로 씁니다.
- 같은 입력의 성공 응답은 다시 호출하지 않습니다.
- 네트워크/429/5xx만 지수 백오프로 최대 2회 재시도합니다.
- 스키마 오류는 같은 모델 1회 교정 후 상위 모델 또는 사람 검수로 보냅니다.
- 일별·실행별·전체 누적 비용을 호출 전에 계산합니다.
- 예상 비용이 남은 상한을 넘으면 호출하지 않고 `BUDGET_STOPPED`로 기록합니다.
- 대량 추출은 Batch를 기본으로 하고, 대화형 재검수만 일반 호출을 사용합니다.

## 11. 저장 경계

```text
data/raw/performance_docs/                 원본 PDF, 읽기 전용
data/interim/performance/ocr/              페이지 OCR 원문
data/interim/llm_extractions/              LLM 원시 응답·호출 로그
data/processed/performance/pdf_reconciliation/  결정적 대조 결과
data/manual/                               사람 검수 입력
data/processed/performance/analysis_ready/ 검수 확정 분석값
```

모든 데이터·OCR·LLM 응답·검수 엑셀은 `.gitignore` 대상입니다. Git에는 코드,
빈 스키마·설정 예시, 문서와 발표용 비식별 시각화만 올립니다.

## 12. 필요한 명령과 기능

구현 시 기존 `fiscal-performance` CLI에 다음 두 명령만 추가하면 충분합니다.

```text
fiscal-performance prepare-llm-review <ministry_code> [--year YEAR] [--overwrite]
fiscal-performance run-llm-review <ministry_code> [--year YEAR]
  --provider PROVIDER --model MODEL --budget-cap-usd 25 --batch
```

`prepare-llm-review`는 외부 호출 없이 evidence bundle과 예상 토큰·비용만 만듭니다.
`run-llm-review`는 다음 조건을 모두 만족할 때만 호출합니다.

```text
사용자의 외부 API 호출 명시 승인
AND 환경변수에 API 키 존재
AND dry-run 예상비용이 상한 이하
AND 입력이 Git 비추적 경로
```

별도 웹 서비스, 작업 큐 서버, 데이터베이스는 초기 구현 범위에서 제외합니다.
현재 규모에서는 파일 기반 Batch JSONL과 Parquet/CSV 감사 로그면 충분합니다.

## 13. 수용 기준

### 13.1 기능

- 동일 입력 재실행 시 외부 호출과 중복 행이 생기지 않습니다.
- 입력·출력 행 수, 실패 행, 토큰과 비용이 모두 집계됩니다.
- 원문 파일 해시와 근거 페이지로 모든 필드를 추적할 수 있습니다.
- JSON Schema 위반과 근거 없는 값이 분석값으로 넘어가지 않습니다.
- 앞자리 0 부처 코드가 보존됩니다.

### 13.2 품질

첫 파일럿은 중기부 수기 골드셋으로 평가합니다.

```text
필드 정확도: 프로그램명·지표명·목표·실적·달성률 각각 측정
근거 정확도: 페이지 번호와 근거 문장 일치율
환각률: 원문에 없는 비null 값 비율
검토 절감률: 사람이 수정하지 않고 승인한 행 비율
실패 투명성: 실패·결측·미매칭 100% 목록화
```

권장 통과선:

- 원문에 없는 값 생성률 `0%`
- 핵심 필드 정확도 `95% 이상`
- 근거 페이지 정확도 `98% 이상`
- 전체 행 보존 `100%`
- 비용 상한 초과 `0건`

정확도가 통과선을 못 넘으면 모델을 무조건 키우기 전에 후보 페이지 검색, OCR,
표 복원과 프롬프트를 먼저 고칩니다.

## 14. 구현 순서

1. **오프라인 준비기**: 기존 대조 결과에서 201개 evidence bundle과 dry-run
   비용표를 만듭니다.
2. **중기부 파일럿**: 확정된 수기 골드셋 일부를 가리고 추출·근거 정확도를
   측정합니다.
3. **라우팅 검증**: 저가 모델 단독, 저가+상위 재검수, 상위 모델 단독을 같은
   표본에서 비교합니다.
4. **3개 부처 확대**: 오류 유형별 검토량과 실제 비용을 확인합니다.
5. **나머지 부처 확대**: 원본 별첨과 수기 행이 확보된 뒤 같은 명령으로 실행합니다.

현재 바로 구현할 것은 1단계까지입니다. 외부 API 호출과 모델 선정은 사용자의
명시 승인, API 키, 파일럿 예산 상한이 준비된 다음 진행합니다.

## 15. 비에이전트형 LLM 실행 방식

이 작업은 LLM이 다음 행동을 스스로 계획하고 도구를 연쇄 호출하는 에이전트형
작업으로 만들 필요가 없습니다. 재현성과 비용 통제를 위해 호출 순서를 코드가
고정하는 비에이전트형 배치가 적합합니다.

```text
코드가 evidence bundle 고정
→ 1차 LLM이 문서값만 JSON 추출
→ 코드가 스키마·근거·숫자·산식 검증
→ 실패 유형이 정해진 행만 2차 LLM에 같은 증거로 재검수
→ 두 결과와 원문을 사람 화면에 함께 표시
→ 사람이 승인·수정·해결불가 기록
```

LLM의 자기평가 `confidence`는 최종 신뢰도로 쓰지 않습니다. 신뢰도는 다음
관측 가능한 항목으로 계산합니다.

- JSON Schema 통과 여부
- 반환값이 근거 문장에 실제로 존재하는지
- 근거 페이지가 evidence bundle 안에 있는지
- 수기값·규칙 추출값·2차 LLM 결과의 일치 여부
- 목표·실적·달성률의 문서 내 역할 구분 여부
- 사람의 최종 수정 여부

## 16. 실행·판정 추적 단위

나중에 같은 오류가 들어왔을 때 단순 재실행하지 않도록 다음 다섯 단위를
분리해 기록합니다.

| 추적 단위 | 기본키 | 기록 목적 |
|---|---|---|
| 문서 | `source_sha256` | 같은 PDF 재처리 방지 |
| 증거 묶음 | `evidence_bundle_sha256` | 후보 페이지·OCR·수기행 변경 감지 |
| LLM 시도 | `request_id` | 모델·프롬프트·토큰·비용·오류 재현 |
| 필드 판정 | `request_id + field_name` | 어떤 값이 어떤 근거로 채택·기각됐는지 확인 |
| 사람 검수 | `source_indicator_id + reviewed_at` | 최종 승인·수정·해결불가와 검수자 기록 |

필드 판정에는 `candidate_value_raw`, `evidence_quote`, `source_page`,
`deterministic_validation_status`, `second_model_agreement`,
`human_decision`, `final_value_raw`, `correction_reason`을 보존합니다.
프롬프트의 내부 추론문은 저장 대상이 아니며, 입력·출력·근거·검증 결과만
감사 대상으로 남깁니다.

## 17. 휴먼인더루프 UI 적용

`src/fiscal_dashboard/app.py`의 `성과 원문 검수` 탭에서 다음 작업을 수행합니다.

1. 부처와 미검수 여부로 361행 검수 큐를 좁힙니다.
2. 수기값과 PDF 자동 추출값을 같은 표에서 비교합니다.
3. 계획서·보고서·변경표의 특정 페이지를 바로 렌더링합니다.
4. 자동 판정, 검수 사유, 추출 텍스트를 확인합니다.
5. `PENDING`, `CONFIRMED`, `CORRECTED`, `NOT_RESOLVABLE`과 검수 메모를
   `data/manual/performance/pdf_reconciliation_manual_confirmations.csv`에
   기록합니다.

저장 동작은 원본 PDF·자동 추출값·판정 라벨을 수정하지 않습니다. 검수 결과는
별도 축으로 병합되며, 다음 원문 대조 재실행에도 유지됩니다. 현재 UI의
`CORRECTED` 값은 검수 메모에 기록하는 1차 버전입니다. 외부 LLM 출력이 실제
분석값 후보로 들어오는 단계에서는 필드별 수정값 컬럼을 추가해야 하며, 그 전에는
수정 메모를 자동 분석값으로 승격하지 않습니다.

## 18. 파일럿 평가와 자동화 기준

모델 비교는 행을 무작위로 섞지 않고 문서·연도 단위로 분리합니다. 같은 표의
인접행이 학습용 예시와 평가용에 동시에 들어가면 표 구조를 외워 정확도가
과대평가되기 때문입니다.

```text
개발셋: 중기부 사람 확정행 일부
검증셋: 중기부의 다른 연도 또는 다른 문서
확장셋: 019·075·162 중 문서구조가 다른 부처
```

비교할 운용안은 `저가 모델 단독`, `저가 모델 + 실패행 상위 모델`,
`상위 모델 단독` 세 가지입니다. 모델별로 필드 정확도뿐 아니라 원문에 없는
비null 값 비율, 근거 페이지 정확도, 사람 수정률, 평균 검수시간, 행당 비용을
함께 기록합니다.

자동화는 오류 유형별로 결정합니다.

- 같은 원인·같은 수정이 반복되고 원문 규칙이 안정적이면 코드 규칙으로 승격합니다.
- 표 구조만 달라 규칙이 불안정하지만 근거 페이지가 좁혀지면 LLM 추출 대상으로 둡니다.
- 정책 판단, 복수 후보, 원문 부재는 계속 사람 검수로 남깁니다.
- 사람 수정 로그가 쌓여도 바로 프롬프트 예시로 넣지 않고 문서 단위 홀드아웃 성능이
  개선되는지 확인한 뒤 반영합니다.
