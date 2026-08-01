# 전체 PDF 무인 절단·표 구조화·오류위험 설계

## 1. 결론

400~600쪽 전체 PDF를 외부 LLM에 보내지 않습니다. 현재 저장소의 PyMuPDF를
1차 처리기로 유지하고, 로컬 표 구조화가 실패한 **후보 페이지만** 오픈소스 OCR
표 파서에 보냅니다. 두 로컬 파서가 불일치하거나 코드 검증을 통과하지 못한
**표 영역 이미지와 계층 제목**만 외부 비전 LLM에 보냅니다.

2026-08-01 동일 18쪽 파일럿에서 OpenDataLoader PDF 2.5.0 fast mode가 지표명
12/12와 같은 행 수치 20/20을 복원했습니다. 그러나 24개 전체 PDF 확장에서는
ODL 구조 통과 계획서도 지표명 68.02%, 같은 행 필드 64.53%에 그쳐 기본 파서
자동 승인 결정을 철회했습니다. 구조 통과 보고서는 각각 98.44%, 96.25%였으므로
검증 후보로 유지하되 자동 확정하지 않습니다. 소표본 결과는
[로컬 PDF 파서 파일럿 결과](PERMISSIVE_LOCAL_PARSER_PILOT_RESULT.md), 전체 확장
결과는 [선택형 비전 dry-run 결과](SELECTIVE_VISION_PILOT_RESULT.md)를 따릅니다.

LLM이 반환한 `confidence=0.95`를 정확도 95%로 해석하지 않습니다. 정답 없이
현재 행이 실제로 맞는지 확정할 수는 없지만, 원문 존재·산식·파서 간 합의·OCR
인식점수·계층 충돌을 이용해 **오류 가능성이 큰 행을 선별**할 수 있습니다.
`예상 정확도 n%`를 표시하려면 기존 424지표를 문서 단위 홀드아웃으로 사용해
오류위험 모델을 사후 보정해야 합니다.

### 1.1 승자 선정 뒤 늘어나는 구성요소

운영 구조에 무거운 모델 두 개가 추가되는 것은 아닙니다.

1. 기존 경계 탐색·절단·규칙 검증기
2. 디지털 표용 OpenDataLoader fast 스택 한 개
3. 필드별 검증·보정 테이블 또는 작은 로지스틱 모형

3번은 OCR 모델이 아니라 파서 합의, 원문 존재, 열·단위·산식 충돌을 입력으로 받는
가벼운 코드와 소형 계수 파일입니다. 두 후보가 모두 근거 게이트를 통과하지 못하면
승자를 억지로 정하지 않습니다.

## 2. 현재 자료에서 확인한 전체본 구조

- `data/raw/performance_docs`에는 전체 PDF 38개, 총 12,450쪽이 있습니다.
- 현재 4개 부처 2022~2024년 무인 탐색은 이미 전체본 24개를 직접 읽습니다.
- 수기로 잘라 둔 별첨 분리본 28개를 사후 정답으로 비교했습니다.
- 별첨 시작 위치는 전체 PDF의 70.5~84.5% 지점입니다.
- 28개 중 27개는 마지막 PDF 쪽까지 별첨이며, 1개는 마지막 빈 1쪽만 제외합니다.
- 마지막 비어 있지 않은 쪽을 종료점으로 잡으면 28/28이 기존 분리 범위와
  정확히 일치했습니다.

골드 범위는 시작·종료 페이지 평가에만 사용하며 운영 탐색 입력에는 넣지 않습니다.

### 2.1 시작 페이지 탐색 기준선

전체 PDF 후반부에서 다음 복합 표제를 찾았습니다.

```text
계획서:
  프로그램 성과지표 현황
  AND 총괄현황

보고서:
  별첨1
  AND 회계·기금별 예·결산 현황
```

공백·문장부호를 제거한 텍스트 기준으로 계획서 15/16, 보고서 12/12에서 기존
분리본 시작 페이지와 정확히 일치했습니다. 유일한 실패는 PDF 글꼴 매핑이 깨진
2024년 보건복지부 계획서였습니다.

해당 문서는 전체 456쪽을 OCR하지 않고 첫 15쪽만 150dpi로 OCR했습니다. 목차
7쪽에서 `별첨 1 프로그램 성과지표 현황 356`을 찾았습니다. PDF 앞표지 오프셋을
고려해 예상 위치 주변만 OCR하면 364쪽 시작 표제를 찾을 수 있습니다.

## 3. 권장 처리 흐름

```text
원본 PDF SHA-256·페이지 수 기록
  ↓
PyMuPDF로 전 페이지 저비용 텍스트·폰트·표·이미지 특성 수집
  ↓
후반부 복합 표제로 별첨 시작 탐색
  ├─ 성공: 시작 페이지 확정
  └─ 실패: 앞 15쪽 목차만 150dpi OCR
             → 목차 쪽번호 주변만 OCR해 시작 표제 확인
  ↓
마지막 비어 있지 않은 페이지를 종료점으로 확정
  ↓
PyMuPDF로 별첨 파생 PDF 생성, 원본은 변경하지 않음
  ↓
기존 1차 표 파서
  ├─ 근거 완전: LOCAL_CONFIRMED
  └─ 실패 페이지만 OpenDataLoader fast에 전달
       ├─ 구조·코드검증 통과: LOCAL_CONFIRMED 후보
       └─ 회전·셀병합·연도/산식 검증 실패: 표 crop + 계층 제목만 비전 LLM
            ├─ 근거검증 통과: CALIBRATED_AUTO_ACCEPT 후보
            └─ 실패/OOD: HUMAN_REVIEW_REQUIRED
```

LLM 입력은 다음으로 제한합니다.

- 표 전체 페이지가 아니라 표 bounding box crop
- 프로그램목표 번호·프로그램명 제목 crop 1개
- 회계연도 머리글 crop 1개
- 문서명, 원본 PDF 페이지, 인쇄 페이지
- 허용 JSON Schema

원본 PDF, 전체 별첨 PDF, 수기 정답, 다른 프로그램 행은 전송하지 않습니다.

## 4. 오픈소스 후보 비교

| 후보 | 역할 | 장점 | 한계 | 결정 |
|---|---|---|---|---|
| 기존 PyMuPDF | 전체본 탐색·절단·디지털 표 | 이미 설치, 빠름, 원본 좌표 보존 | AGPL/상용 이중 라이선스, 깨진 글꼴·스캔 표 한계 | 연구 기준선만 유지, 배포 경로는 pypdf로 교체 |
| PaddleOCR PP-StructureV3 | OCR·레이아웃·표 셀 구조 | Korean PP-OCRv5, 셀 좌표·텍스트·인식점수·HTML 제공 | 동일 표본 지표명 6/12·같은 행 수치 6/20 | 운영 fallback 미채택 |
| Docling | PDF 파싱·OCR·표 구조 통합 | 페이지 범위, Windows, 여러 OCR 엔진 | 동일 표본 지표명 11/12·같은 행 수치 13/20, 무거운 환경 | 비교 기준선 |
| OpenDataLoader fast | Java 디지털 구조 파서 | 동일 18쪽 지표명 12/12·같은 행 수치 20/20, 전체 구조 통과 보고서 98.44%·96.25% | 전체 구조 통과 계획서 68.02%·64.53%, 회전·연속표 실패, Java·제3자 고지 필요 | 보고서 검증 후보, 계획서 자동 승인 금지 |
| OpenDataLoader hybrid | Docling+EasyOCR 라우팅 | 스캔·복합 문서 fallback 제공 | 기존 비교 후보와 의존성 중복, 이번 실측 범위 아님 | 현 단계 미도입 |
| pypdf | 원본 해시·페이지 수·별첨 절단 | BSD-3-Clause, 순수 Python | 표 구조·좌표 복원용이 아님 | 정부 배포용 PyMuPDF 경계 기능 대체 후보 |
| OCRmyPDF | 깨진/스캔 PDF에 검색 텍스트층 추가 | 선택 페이지 OCR, deskew·rotate 지원 | 표 셀 구조를 복원하지 않음 | 필요 시 전처리만 |
| Camelot | 디지털 PDF 표 추출 | 텍스트 PDF 표에 간단 | 공식 문서상 스캔 PDF 미지원, 긴 PDF 일괄처리 메모리 증가 | 현 단계 미도입 |

portable Java와 파서별 Python 환경은 `.pilot_envs/`에 격리했습니다. 시스템 Java와
안정 `.venv`는 변경하지 않았습니다.

OpenDataLoader가 공개한 200문서 벤치마크에서는 hybrid 표 점수가 0.928로 가장
높지만, 프로젝트 제작자가 운영하는 벤치마크이고 한국어 정부 성과표 포함 여부가
명시되지 않았습니다. 따라서 이 수치를 채택 근거로 쓰지 않고, 현재 4개 부처의
정상 텍스트·깨진 글꼴·스캔·다단 머리글 표본에서 다시 측정합니다.

## 5. 정답 없이 오류를 찾을 수 있는 범위

### 5.1 직접 틀렸다고 판정 가능한 경우

- 반환한 값이나 지표명이 근거 crop/OCR 결과 어디에도 없음
- 회계연도 머리글과 선택한 값 열이 다름
- 프로그램목표 번호가 페이지 제목과 다름
- 같은 원문 crop을 서로 다른 프로그램에 중복 사용
- 달성률과 `실적 ÷ 목표 × 100`이 허용 오차 밖에서 불일치
- 단위와 값 형식이 충돌
- 변경 전·변경 후 목표를 뒤바꿈
- 두 로컬 파서가 서로 다른 숫자나 계층을 반환

이 검사는 정답지 없이도 가능한 **반증 검사**입니다. 모든 검사를 통과했다고 실제
정답임이 증명되는 것은 아닙니다.

### 5.2 `예상 정확도 n%`를 만들기 위한 보정

예측 단위는 행 전체가 아니라 필드별로 둡니다.

```text
indicator_name_correct_probability
unit_correct_probability
planned_target_correct_probability
actual_value_correct_probability
achievement_rate_correct_probability
source_page_correct_probability
```

기존 424지표·848 문서행을 무작위 행 분할하지 않고
`부처 × 연도 × 문서유형` 그룹으로 홀드아웃합니다. 같은 표의 인접 행이
학습과 평가에 동시에 들어가는 누수를 막기 위해서입니다.

신규 여부를 표 이미지나 표 ID의 완전 일치로 정의하지 않습니다. 그렇게 하면 실제
운영 문서가 거의 모두 `UNSEEN_LAYOUT`이 된다는 지적이 맞습니다. 대신 다음과 같은
**의미·품질 조건군**으로 레이아웃 계열을 정의합니다.

- 계획서/보고서, 성과표/목표변경표 등 문서 역할
- `성과지표·단위·목표·실적·달성률·연도` 헤더 역할과 헤더 층수
- 병합 셀, 열 수, 가로/세로 표, 반복 머리글 구조
- 정상 텍스트층, 깨진 글꼴, 이미지 표 등 입력 품질
- 파서 간 필드 합의, 원문 근거 존재, 열·단위·산식 검증 결과

필드별 확률은 다음 계층으로 보정합니다.

1. 같은 문서 역할·헤더 구조·품질 조건군의 표본이 충분하면 해당 경험정확도를 사용
2. 세부 계열 표본이 부족하면 문서유형·입력품질의 더 넓은 집단으로 후퇴하고 구간을 넓힘
3. 헤더 역할을 해석하지 못하거나 근거·파서가 크게 충돌한 진짜 OOD는 숫자를 숨기고 사람 검수

따라서 처음 보는 **표 파일**이어도 익숙한 조건군이면 예상 정확도를 표시할 수
있습니다. 반대로 근거 표본이 부족한 필드에는 억지로 숫자를 만들지 않습니다.

오류위험 입력 후보는 다음과 같습니다.

- 텍스트층 한글 비율, PUA/비정상 글리프 수, 추출 문자 수
- 별첨 시작 표제 일치 여부와 목차 fallback 사용 여부
- 기존 PyMuPDF 추출과 OpenDataLoader 필드의 원문 존재·구조 일치 여부
- OCR 단어·셀 인식점수의 최솟값·중앙값
- JSON Schema, 원문 존재, 연도 열, 단위, 계층, 중복 검증 결과
- 달성률 산식 오차와 목표변경표 충돌 여부
- 문서 레이아웃이 보정 표본 범위 밖인지 여부

첫 버전은 설명 가능한 정규화 로지스틱 회귀 또는 충분한 표본을 가진 위험구간별
경험오류율 중 실제 홀드아웃 보정이 더 나은 하나로 시작합니다. 모델의 자기신뢰도는
입력에서 제외하거나 보조 신호로만 둡니다. 최소 지지 표본 수와 허용 보정오차는
파일럿 전에 임의 확정하지 않고 민감도 결과로 정합니다. 표본이 부족한 필드는 숫자
확률을 표시하지 않고 `NOT_CALIBRATED`로 둡니다.

### 5.3 UI 표시안

```text
예상 정확도: 97% (성과보고서·2단 헤더·정상 텍스트층, 홀드아웃 n=84)
판정: 사람 검수 권장
이유:
  - OCR 셀 최소 인식점수 낮음
  - PyMuPDF와 PaddleOCR 목표치 불일치
  - 달성률 산식 7.3%p 불일치
근거: 원본 PDF 364쪽, 표 crop 바로가기
```

정확도 점추정치만 보여주지 않고 표본 수, 보정 범위, 위험 사유를 함께 표시합니다.
새 부처라는 이유만으로 자동 `UNSEEN_LAYOUT` 처리하지 않습니다. 위 조건군에서
지원되는지 먼저 확인하고, 지원되지 않는 의미 구조·품질 조합만 `UNSEEN_LAYOUT`으로
사람에게 보냅니다.

## 6. 파일럿 판정 기준

임계값은 파일럿 결과를 보기 전에 확정하지 않습니다. 다음을 같이 비교합니다.

- 별첨 시작·종료 페이지 정확도
- 지표명·단위·목표·실적·달성률 필드 정확도
- 원문에 없는 비null 값 비율
- 자동 승인률과 사람 검수 잔여율
- 오류위험 상위 구간의 실제 오류 포착률
- 확률구간별 관측 정확도와 calibration error
- 문서당 로컬 처리시간, GPU 메모리, LLM 페이지·토큰·비용

비교 표본은 정상 텍스트, 이미지 표, 글꼴 매핑 오류, 복수 연도 열, 동명 지표를
모두 포함해야 합니다. 한 부처에서 조정한 뒤 다른 부처·연도로 홀드아웃 검증합니다.

## 7. 구현 순서

1. 전체본 별첨 시작·종료 탐색과 파생 PDF 절단을 현재 PyMuPDF로 구현합니다.
2. 실패 문서에서 골드 사전노출 없이 후보 페이지 manifest를 만듭니다.
3. OpenDataLoader fast는 보고서 검증 후보로 사용하고 계획서는 구조 통과만으로 승인하지 않습니다.
4. 회전·셀병합·연도·단위·산식 구조 검증을 실패 라우팅 게이트로 구현합니다.
5. pypdf가 별첨 경계 28/28을 재현하는지 확인해 PyMuPDF 배포 경로를 교체합니다.
6. 로컬 불일치 페이지만 비전 LLM 요청으로 생성하고 예상 비용을 계산합니다.
7. 424지표 그룹 홀드아웃으로 필드별 오류위험을 계층 보정합니다.
8. 위험도·근거·사유를 대시보드 검수 큐에 표시합니다.

## 8. 라이선스와 정부 환경 배포

아래는 법률 자문이 아니라 공식 저장소·모델 카드에 기반한 기술 검토입니다.

| 구성요소 | 코드/가중치 라이선스 | 정부 내부 사용 | 배포 시 핵심 확인 |
|---|---|---|---|
| PyMuPDF 1.28.0 | AGPL-3.0 또는 상용 | 사용 형태별 법무 검토 필요 | 폐쇄형 배포가 AGPL 의무와 충돌하면 상용 라이선스 또는 교체 필요 |
| PaddleOCR 코드 | Apache-2.0 | 허용 | LICENSE·NOTICE·변경고지 보존 |
| Korean PP-OCRv5, SLANeXt, PP-DocLayout 대표 가중치 | 각 모델 카드상 Apache-2.0 | 허용 | 실제 고정한 모든 모델 카드·revision을 개별 기록 |
| Docling 코드 | MIT | 허용 | 저작권·라이선스 고지 보존 |
| docling-models | Apache-2.0 + CDLA-Permissive-2.0 표기 | 허용 가능 | 선택 모델·데이터별 원 라이선스와 고지 확인 |
| EasyOCR/Tesseract | Apache-2.0 | 허용 | 선택 OCR 가중치까지 manifest에 기록 |
| OpenDataLoader PDF 2.0+ | Apache-2.0 | 허용 | LICENSE·NOTICE·THIRD_PARTY를 함께 보존 |
| OpenDataLoader 포함 veraPDF 구성요소 | MPL-2.0 선택 배포 | 내부 사용 가능 | 외부 배포·수정 시 MPL 대상 파일의 소스 제공·고지 검토 |
| OpenDataLoader 2.0 미만 | MPL-2.0 | 내부 사용 가능 | 2.0+로 버전 고정하지 않으면 파일 단위 copyleft 검토 필요 |
| OCRmyPDF | MPL-2.0 | 내부 사용 가능 | 외부 배포한 수정 대상 파일의 소스·고지 제공 |

정부부처용 설치 패키지를 만들 때는 다음을 필수 산출물로 둡니다.

- 정확한 패키지 버전, Git commit, 모델 revision과 SHA-256을 고정한 SBOM
- `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES`와 모델 카드 사본
- 운영 중 Hugging Face·GitHub 자동 다운로드 금지, 승인된 아티팩트만 내부 반입
- 파서 코드와 모델 가중치의 라이선스를 별도 열로 기록
- PyMuPDF를 유지한다면 AGPL 준수 방식 또는 상용 라이선스 여부를 배포 전에 결정

## 9. 공식 참고자료

- [PaddleOCR PP-StructureV3](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PP-StructureV3.html)
- [PaddleOCR 한국어 PP-OCRv5](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html)
- [PaddleOCR GitHub](https://github.com/PaddlePaddle/PaddleOCR)
- [PaddleOCR PP-StructureV3 모델 모음](https://huggingface.co/collections/PaddlePaddle/pp-structurev3)
- [Docling CLI와 OCR·표 옵션](https://docling-project.github.io/docling/reference/cli/)
- [Docling confidence scores](https://docling-project.github.io/docling/concepts/confidence_scores/)
- [Docling GitHub](https://github.com/docling-project/docling)
- [Docling 모델 묶음](https://huggingface.co/docling-project/docling-models)
- [OpenDataLoader PDF GitHub](https://github.com/opendataloader-project/opendataloader-pdf)
- [OpenDataLoader PDF PyPI](https://pypi.org/project/opendataloader-pdf/)
- [OpenDataLoader 재현 가능 벤치마크](https://github.com/opendataloader-project/opendataloader-bench)
- [OpenDataLoader 제3자 라이선스 목록](https://github.com/opendataloader-project/opendataloader-pdf/blob/main/THIRD_PARTY/THIRD_PARTY_LICENSES.md)
- [PyMuPDF 공식 라이선스 안내](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)
- [OCRmyPDF API의 선택 페이지 OCR](https://ocrmypdf.readthedocs.io/en/stable/apiref.html)
- [Camelot 스캔 PDF 제한](https://camelot-py.readthedocs.io/en/latest/user/faq.html)
- [LLM conformal abstention 연구](https://arxiv.org/abs/2405.01563)
