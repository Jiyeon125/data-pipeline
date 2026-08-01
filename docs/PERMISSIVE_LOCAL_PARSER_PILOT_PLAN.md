# Permissive 로컬 PDF 파서 파일럿 계획

> 2026-08-01 실제 실행 결과는
> [PERMISSIVE_LOCAL_PARSER_PILOT_RESULT.md](PERMISSIVE_LOCAL_PARSER_PILOT_RESULT.md)에
> 기록했습니다. 최초 permissive-only 게이트는 정부 사용 가능성과 라이선스 고지
> 의무를 혼동한 과잉 기준이어서 철회했습니다. 세 후보를 같은 18쪽에서 실측한
> 결과, OpenDataLoader PDF 2.5.0 fast mode를 디지털 표 기본 파서로 선택했습니다.
> 회전·OCR 필요 페이지는 시각 QA를 통과하지 못해 선택 검수 대상으로 남겼습니다.

## 1. 결정

정부부처 내부·외부 배포 가능성을 고려하되, 사용 금지와 배포 의무를 구분합니다.

```text
즉시 허용: Apache-2.0, MIT, BSD, ISC, CDLA-Permissive
조건부 허용: MPL-2.0, LGPL (고지·소스 위치·재링크 조건 등 배포 준수사항 기록)
별도 검토: GPL, AGPL (결합·배포·서비스 형태 확인)
제외: 비상업, 연구전용, 용도제한 라이선스
```

MPL/LGPL 전이 의존성이 있다는 사실만으로 내부 파일럿과 정부 이용을 금지하지
않습니다. 외부 조직에 설치 패키지를 전달할 때는 SBOM·LICENSE/NOTICE·해당 소스
위치를 함께 제공하고, 수정·결합 방식에 따른 의무를 별도로 확인합니다.

동일 표본 비교 후보와 최종 판정은 다음과 같습니다.

1. `OpenDataLoader PDF 2.5.0 fast mode`: 디지털 표 승자
2. `Docling standard pipeline + Tesseract CLI(kor+eng)`: 비교 기준선
3. `PaddleOCR PP-StructureV3 + Korean PP-OCRv5`: 운영 fallback 미채택

초기 검토안의 EasyOCR과 PaddleOCR에는 LGPL 전이 의존성이 있지만, 이는 사용 금지가
아니라 배포 준수사항입니다. 실제 후보 비교에서는 해당 의존성을 숨기지 않고
SBOM에 남긴 채 실행합니다. Apache-2.0 Tesseract와 공식 `tessdata` 최소 스택도
비교 기준선으로 유지합니다.

OpenDataLoader PDF 2.0+ 본체는 Apache-2.0입니다. 포함된 MPL 제3자 구성요소는
사용 금지가 아니라 외부 배포 시 고지·소스 제공 범위를 관리할 조건이므로 내부
파일럿 제외 사유로 사용하지 않습니다. 현재 PyMuPDF 1.28.0은 AGPL 또는 상용 이중
라이선스이므로 성능 기준선으로만 관찰하고, 정부 배포 경로에서는 BSD-3-Clause인
`pypdf`로 경계 탐색·페이지 절단을 교체합니다.

## 2. 분석 질문

파일럿은 일반적인 PDF 벤치마크 1등을 고르는 작업이 아닙니다.

> 현재 4개 부처 성과계획서·성과보고서에서 PyMuPDF 로컬 탐색이 놓친 한국어
> 성과표를, 원문 근거와 좌표를 보존하면서 가장 정확하고 단순하게 복원하는
> permissive 스택은 무엇인가?

파일럿으로 다음을 결정하지 않습니다.

- 최종 정책 우선순위
- 성과와 세부사업의 임의 귀속
- 외부 LLM 모델 선택
- 신규 문서의 무조건 자동 승인

## 3. 환경 분리와 라이선스 게이트

현재 안정 `.venv`는 변경하지 않습니다. 저장소 안의 Git 제외 경로에 파서별 환경을
따로 만듭니다.

```text
.pilot_envs/paddle/
.pilot_envs/docling/
.pilot_envs/opendataloader/
.pilot_envs/java/
.pilot_cache/models/
data/interim/parser_pilot/
```

현재 환경은 Anaconda Python 3.13.9입니다. 파서별 표준 `venv`와 `pip`를 사용했고,
OpenDataLoader에는 portable Eclipse Temurin JRE 21을 저장소의 Git 제외 경로에
설치했습니다. 시스템 `PATH`·`JAVA_HOME`과 안정 `.venv`는 변경하지 않았습니다.

설치 후 모델을 실행하기 전에 다음 게이트를 통과해야 합니다.

1. 설치된 모든 패키지의 이름·버전·라이선스 메타데이터를 CSV로 저장합니다.
2. 비상업·연구전용·용도제한 라이선스가 있으면 실행을 중단합니다. GPL·AGPL은
   결합·배포 형태를 확인하기 전까지 운영 후보 승격을 중단합니다.
3. MPL·LGPL은 실행을 허용하되 패키지·파일·수정 여부·외부 배포 시 준수사항을
   기록합니다. `UNKNOWN` 또는 복수 라이선스는 원문 LICENSE를 확인합니다.
4. 모델 저장소·revision·파일 SHA-256·모델 카드 라이선스를 별도 manifest에 남깁니다.
5. 설치가 끝난 뒤 자동 다운로드를 끄고 고정된 로컬 모델 파일만 사용합니다.

비상업·연구전용·용도제한이 확인되거나 GPL·AGPL 배포 검토가 해결되지 않으면
라이선스가 허용되는 부분만 억지로 떼어 쓰지 않고 운영 후보 승격을 보류합니다.

## 4. 표본 구성

골드 값을 보고 페이지를 고르지 않습니다. 기존 로컬 라우팅 결과만 사용해 아래
계층을 먼저 채운 뒤 manifest와 PDF SHA-256을 동결합니다.

| 계층 | 페이지 수 | 선정 기준 |
|---|---:|---|
| 정상 디지털 표 | 4 | 4개 부처 각 1쪽, `LOCAL_CONFIRMED` |
| 다단 연도·병합 헤더 | 4 | 계획/보고·복수 연도 열 포함 |
| 글꼴 매핑 오류 | 4 | `OCR_REQUIRED`, 보건복지부 2024 포함 |
| 이미지·저텍스트 표 | 4 | 낮은 한글 비율 또는 이미지 중심 페이지 |
| 계층·중복 난이도 | 2~4 | 동명 지표, 목표변경, 프로그램목표 경계 |

총 18~20쪽을 권장합니다. 해당 계층의 실제 페이지가 부족하면 다른 계층으로 수를
임의 대체하지 않고 부족 사유를 기록합니다.

적응용 smoke 페이지 1쪽은 별도로 두고 평가에서 제외합니다. 평가 페이지는 두
파서 모두 같은 렌더링·같은 입력을 사용합니다. 기존 424지표·848 문서행은 추출이
끝난 뒤 사후 채점에만 사용합니다.

## 5. 공통 출력계약

파서 원출력은 보존하고 다음 필드로 정규화합니다.

```text
parser_name
parser_version
model_revision
document_id
source_pdf_sha256
source_page
table_bbox
cell_bbox
program_goal_number_raw
program_name_raw
indicator_name_raw
unit_raw
fiscal_year_raw
planned_target_raw
actual_value_raw
achievement_rate_raw
ocr_confidence_raw
evidence_text
elapsed_seconds
peak_ram_mb
peak_vram_mb
```

값을 찾지 못하면 `null`로 두고 다른 행이나 골드 값으로 보정하지 않습니다. 필드별
원문과 페이지·좌표가 없으면 자동 승인 후보가 될 수 없습니다.

## 6. 실행 순서

### 단계 A. 설치 전 라이선스 고정

- 후보별 직접·전이 의존성 목록을 해석합니다.
- 허용 라이선스만 남은 버전 조합을 lock 파일로 저장합니다.
- 패키지와 모델의 LICENSE·NOTICE·모델 카드를 보존합니다.

### 단계 B. CPU smoke test

- 각 후보를 정상 페이지 1쪽과 글꼴 오류 페이지 1쪽에 실행합니다.
- import, 모델 로드, 한국어 출력, JSON 직렬화, API 0회를 확인합니다.
- 한 후보가 실행되지 않으면 안정 `.venv`를 고치지 않고 해당 격리 환경만 수정합니다.

### 단계 C. 동결 표본 실행

- 동일 18~20쪽을 후보별 한 번씩 실행합니다.
- 파서별 원출력·정규화 출력·실행로그·자원사용량을 보존합니다.
- 네트워크 요청, 외부 LLM, 골드 조회를 차단합니다.

### 단계 D. 사후 채점

다음 값을 필드별·문서유형별·입력품질별로 계산합니다.

- 발견 커버리지와 미발견 수
- 지표명·단위·목표·실적·달성률 의미동등 정확도
- 원문에 없는 비null 값 수와 비율
- 근거 페이지·표·셀 좌표의 정확성
- 프로그램목표·연도 열 오연결 수
- 중복 행과 다른 프로그램 값 혼입 수
- 페이지당 시간, peak RAM·VRAM, 모델·환경 크기

두 후보는 같은 페이지의 대응 필드로 비교하고, 차이와 부트스트랩 구간을 함께
제시합니다. 일반 표 구조 점수 하나로 한국어 필드 정확도를 대체하지 않습니다.

## 7. 승자 결정 규칙

가중합 점수를 만들지 않고 아래 게이트를 순서대로 적용합니다.

1. **라이선스 게이트:** 사용 제한 또는 해결되지 않은 배포 의무가 있으면 운영 승격 보류
2. **근거 게이트:** 원문에 없는 비null 값이 있으면 자동승인 경로에서는 탈락
3. **계층 게이트:** 프로그램목표·연도 열 오연결이 반복되면 탈락
4. **정확도·커버리지:** 필드별 결과와 입력품질별 약점을 독립적으로 비교
5. **동률 처리:** 차이가 불확실하면 설치·운영·속도가 단순한 후보를 선택

두 후보 모두 근거 게이트를 통과하지 못하면 승자를 억지로 정하지 않습니다. 현재
로컬 파서를 유지하고 실패 crop만 외부 LLM에 보내는 선택형 경로로 갑니다.

## 8. 파일럿 이후

### 8.1 승자 통합

- 승자 하나만 `unattended_pdf` 공통 출력계약 뒤에 연결합니다.
- 다른 후보 환경과 모델은 운영 의존성에서 제거합니다.
- 기존 규칙 검증은 파서 전후 공통 단계로 재사용합니다.

### 8.2 AGPL 제거 경로

- PDF SHA-256·페이지 수·분할은 `pypdf`로 교체합니다.
- 기존 별첨 경계 28개에서 시작·종료와 파생 PDF 페이지가 28/28 같은지 확인합니다.
- 텍스트 경계 탐색이 약해진 문서는 목차·후보 위치의 선택 OCR로만 보완합니다.
- 동등성이 확인되기 전에는 현재 PyMuPDF 코드를 삭제하지 않고 연구 기준선으로
  격리합니다.

### 8.3 오류위험 보정

- `부처 × 연도 × 문서유형` 그룹 홀드아웃을 유지합니다.
- 표 ID가 아니라 문서 역할·헤더 구조·입력품질·근거검증 조건군으로 필드별
  경험정확도를 계산합니다.
- 표본 부족 또는 진짜 OOD는 확률을 만들지 않고 사람 검수로 보냅니다.

### 8.4 선택적 외부 LLM

- 로컬 미발견·파서 충돌·근거 실패 표 crop만 요청합니다.
- 전체 PDF와 전체 별첨은 보내지 않습니다.
- API 실행 전 요청 수·이미지 수·토큰·최대 비용을 산출하고 사용자 승인을 받습니다.
- LLM 결과도 원문·연도 열·단위·산식 검증을 통과해야만 승격합니다.

### 8.5 대시보드와 배포

- `LOCAL_CONFIRMED`, `LLM_REVIEW_REQUIRED`, `HUMAN_REVIEW_REQUIRED`,
  `NOT_CALIBRATED`를 분리 표시합니다.
- 필드별 예상 정확도, 동종 조건 표본 수, 위험 사유와 원문 crop을 함께 보여줍니다.
- 최종 패키지에는 lock, SBOM, 모델 manifest, LICENSE, NOTICE를 포함합니다.

## 9. 권장 일정

| 시점 | 완료 기준 |
|---|---|
| 8월 1일 | 계획·표본 규칙·라이선스 allowlist 동결 |
| 8월 2일 오전 | 격리 환경·라이선스 게이트·CPU smoke 완료 |
| 8월 2일 오후 | 동일 표본 실행·사후 채점·승자 또는 무승자 결정 |
| 8월 3일 오전 | 승자 어댑터와 공통 검증 연결, 실제 PDF 재실행 |
| 8월 3일 오후 | 오류위험 보정·선택적 LLM 요청 패키지·대시보드 큐 검증 |

GPU 최적화는 CPU 파일럿 승자에게만 적용합니다. 발표 일정 전에 라이선스와 분석
정확도가 확인되지 않은 기능은 운영 경로에 넣지 않습니다.

## 10. 공식 근거

- [PaddleOCR GitHub](https://github.com/PaddlePaddle/PaddleOCR)
- [PaddleOCR PyPI](https://pypi.org/project/paddleocr/)
- [PaddlePaddle PyPI](https://pypi.org/project/paddlepaddle/)
- [PP-StructureV3 모델 모음](https://huggingface.co/collections/PaddlePaddle/pp-structurev3)
- [Docling GitHub](https://github.com/docling-project/docling)
- [Docling 설치 문서](https://docling-project.github.io/docling/getting_started/installation/)
- [Docling 모델 묶음](https://huggingface.co/docling-project/docling-models)
- [Docling Tesseract CLI 설정](https://docling-project.github.io/docling/reference/pipeline_options/)
- [Tesseract GitHub와 Apache-2.0 LICENSE](https://github.com/tesseract-ocr/tesseract)
- [Tesseract 공식 언어모델과 Apache-2.0 LICENSE](https://github.com/tesseract-ocr/tessdata)
- [EasyOCR 전이 의존성 python-bidi의 LGPL 메타데이터](https://pypi.org/project/python-bidi/)
- [pypdf GitHub와 BSD-3-Clause LICENSE](https://github.com/py-pdf/pypdf/blob/main/LICENSE)
- [OpenDataLoader PDF GitHub](https://github.com/opendataloader-project/opendataloader-pdf)
- [OpenDataLoader 라이선스 안내](https://opendataloader.org/docs/license)
- [OpenDataLoader 제3자 라이선스](https://github.com/opendataloader-project/opendataloader-pdf/blob/main/THIRD_PARTY/THIRD_PARTY_LICENSES.md)
- [PyMuPDF 공식 라이선스 안내](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)
