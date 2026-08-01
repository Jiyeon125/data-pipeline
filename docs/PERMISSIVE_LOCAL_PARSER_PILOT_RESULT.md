# 로컬 PDF 표 파서 파일럿 결과

> 2026-08-01 최종 정정: 최초 라이선스 게이트는 내부 사용과 외부 배포 의무를
> 혼동해 OpenDataLoader를 과도하게 제외했습니다. Java를 격리 설치하고 같은
> 18쪽에 OpenDataLoader PDF 2.5.0 fast mode를 추가 실행했습니다.
>
> 2026-08-01 전체 PDF 확장 정정: 이 문서의 12/12·20/20은 18쪽 소표본 결과입니다.
> 24개 전체 PDF에서 계획서 정확도가 유지되지 않아 기본 파서 자동 승인 결정을
> 철회했습니다. 운영 판단은
> [전체 PDF 선택형 비전 결과](SELECTIVE_VISION_PILOT_RESULT.md)를 우선합니다.

## 결론

**동일 18쪽 비교의 구조 파서 승자는 OpenDataLoader PDF 2.5.0 fast mode입니다.**
다만 전체 문서 자동 승인 파서는 아니며, 무인 파서 전체 승자는 아직 없습니다.

- 정상·복잡표·저텍스트 계층에서는 현재 페이지 연결 골드 12개 지표명과 20개
  수치 필드를 모두 복원했습니다.
- `OCR_REQUIRED` 계층은 페이지 연결 골드가 0개여서 정확도를 숫자로 주장할 수
  없습니다.
- 회전 페이지 `p09`와 OCR 필요 페이지 `p12`를 육안 대조한 결과, 읽기 순서가
  섞이거나 여러 지표가 한 셀에 합쳐졌습니다. 이 두 유형은 자동 승인하지 않습니다.
- 따라서 운영안은 `OpenDataLoader fast → 구조 검증 → 실패 crop만 선택적 비전
  LLM 또는 사람 검수`입니다. PaddleOCR를 기본 fallback으로 두지 않습니다.

## 동일 18쪽 비교

| 항목 | OpenDataLoader 2.5.0 fast | Docling 2.117.0 | PaddleOCR 3.7.0 | Tesseract PSM 11 |
|---|---:|---:|---:|---:|
| 처리 결과 | 18/18 | 18/18 | 18/18 | 18/18 |
| 총 실행시간 | 10.950초 | 74.522초 | 406.601초 | 63.776초 |
| 페이지당 시간 | 0.608초(배치 평균) | 4.157초(중앙값) | 20.244초(중앙값) | 3.543초(평균) |
| 지표명 완전복원 | 12/12 | 10/12 | 6/12 | 4/12 |
| 지표명 유사도 0.8 이상 | 12/12 | 11/12 | 6/12 | 5/12 |
| 같은 행 기대 수치 | 20/20 | 13/20 | 과거 6/20 | 미측정 |
| 측정 peak RAM | 489.473 MB | 1,588.312 MB | 1,466.902 MB | 508.664 MB |
| 외부 LLM/API | 0회 | 0회 | 0회 | 0회 |

OpenDataLoader는 18쪽에서 표 27개를 만들었고 16쪽에 표 객체가 존재했습니다.
2,741개 구조 노드 중 2,602개가 좌표를 가졌습니다. 좌표가 없는 139개는 내용이
아닌 `table row` 컨테이너였으며, 실제 텍스트·셀 내용 노드 2,602개는 모두 좌표를
가졌습니다.

### 채점기 정정

최초 채점기는 지표명이 본문과 표에 반복될 때 첫 번째 유사 행 하나만 골라 수치를
확인했습니다. 그 결과 Docling의 같은 행 복원을 7/20으로 과소평가했습니다.
모든 지표명 일치 행 중 어느 하나라도 기대 수치를 포함하는지 확인하도록 공통
채점기를 고친 뒤 Docling은 13/20, OpenDataLoader는 20/20이었습니다.

OpenDataLoader JSON은 병합 셀의 `row span`을 제공합니다. 지표명 셀을 해당 연도별
목표·실적·달성률 행에 상속해 행을 펼쳤습니다. 이 복구에는 골드 값을 사용하지
않았으며 골드는 추출 완료 뒤 사후 채점에만 사용했습니다.

## 승자 게이트

| 게이트 | OpenDataLoader 판단 | 해석 |
|---|---|---|
| 18쪽 실행·원본 해시 | 통과 | 입력 18/18, 원본 18/18 해시 일치 |
| 디지털 표 지표명·수치 | 통과 | 페이지 연결 골드 12개·20필드 기준 |
| 내용 좌표 | 통과 | 내용 노드 2,602/2,602 좌표 보존 |
| OCR_REQUIRED | 미통과 | 골드 0개이며 p09·p12 시각 QA 실패 |
| 최종 KPI 비근거 non-null | 산정 전 | 아직 최종 KPI 스키마를 생산하지 않음 |
| 프로그램 계층 귀속 | 산정 전 | 이 페이지 파일럿은 계층 귀속을 만들지 않음 |

따라서 OpenDataLoader를 **디지털 표 구조화 승자**로 선택하되, OCR_REQUIRED와
계층 귀속까지 자동 승인하는 승자로 확대 해석하지 않습니다.

## 표본과 해석 범위

- 한 행: 원본 PDF 한 쪽
- 표본: 18쪽, 원본 11개 PDF
- 부처: 고용노동부 4쪽, 보건복지부 4쪽, 중소벤처기업부 4쪽,
  과학기술정보통신부 6쪽
- 계층: 정상 8쪽, `OCR_REQUIRED` 4쪽, 복잡표 4쪽, 저텍스트 2쪽
- 선정: 골드 값을 보지 않고 기존 `page_audit.csv` 상태·표 수·레코드 수와
  PDF 텍스트량으로 결정
- 평가 골드: 지표명 12개, 같은 행 수치 20개

계층별 페이지 연결 골드는 `NORMAL` 7개, `COMPLEX_TABLE` 4개, `LOW_TEXT` 1개,
`OCR_REQUIRED` 0개입니다. 12개 지표에서 100%였다는 결과를 4개 부처 전체나
스캔 문서의 정확도로 일반화하지 않습니다.

## 실행환경과 라이선스

안정 `.venv`와 시스템 `PATH`·`JAVA_HOME`은 변경하지 않았습니다.

| 구성 | 격리 경로 | 설치크기 | 라이선스 판단 |
|---|---|---:|---|
| Eclipse Temurin JRE 21.0.12+8 | `.pilot_envs/java/` | 144.5 MB | 배포 시 포함 NOTICE·legal 보존 |
| OpenDataLoader PDF 2.5.0 | `.pilot_envs/opendataloader/` | 34.1 MB | 본체 Apache-2.0, 제3자 고지 보존 |

OpenDataLoader wheel에는 `LICENSE`, `NOTICE`, `THIRD_PARTY` 자료가 포함되어 있으며
veraPDF 일부는 MPL-2.0으로 배포됩니다. 이는 내부 사용 금지가 아니라 설치 패키지를
외부에 전달할 때 해당 고지와 적용 소스 제공 범위를 확인할 조건입니다. 법률 자문은
아니며 실제 정부 배포 전 라이선스 검토가 필요합니다.

```text
Temurin archive SHA-256
B8AA18FEF5EDB69BEE8618F99677D66D0873D22CB40D974C15AC9FFCDECF73BA

라이선스 인벤토리
data/interim/parser_pilot/licenses/opendataloader/minimal_license_inventory.csv
```

## 재현 산출물

```text
data/interim/parser_pilot/manifest.csv
data/interim/parser_pilot/opendataloader/parser_results.csv
data/interim/parser_pilot/opendataloader/run_summary.json
data/interim/parser_pilot/opendataloader/evaluation_summary.json
data/interim/parser_pilot/opendataloader/raw/*.json
data/interim/parser_pilot/opendataloader/raw/*.md
```

재현 명령:

```powershell
.venv\Scripts\python.exe scripts\permissive_local_parser_pilot.py manifest --root . --output-dir data\interim\parser_pilot
.venv\Scripts\python.exe scripts\permissive_local_parser_pilot.py run-opendataloader --root . --output-dir data\interim\parser_pilot
.venv\Scripts\python.exe scripts\permissive_local_parser_pilot.py evaluate-parser --root . --output-dir data\interim\parser_pilot --parser opendataloader
```

## 품질검증

- OpenDataLoader 배치 반환코드 0, 18/18 결과 생성
- 동결 1쪽 입력과 원본 PDF 해시 각각 18/18 일치
- 외부 LLM/API 호출 0회, 원본 PDF 수정 0건
- portable Java 버전 확인, 두 Python 환경 `pip check` 통과
- 공통 채점기의 반복 지표 행과 병합 셀 row-span 회귀검사 추가
- p09·p12·p14를 원본 이미지와 원출력으로 시각 대조

## 권장 다음 단계

1. OpenDataLoader를 디지털 표 기본 파서로 고정합니다.
2. 회전, 지표 다중 병합, 연도·단위·달성률 불일치를 구조 실패 신호로 만듭니다.
3. 실패한 표 crop과 계층 제목만 선택적 비전 LLM 또는 사람 검수로 보냅니다.
4. OCR_REQUIRED 홀드아웃 골드를 확보하기 전에는 해당 유형 예상 정확도를 표시하지
   않습니다.

## 공식 근거

- [OpenDataLoader PDF GitHub](https://github.com/opendataloader-project/opendataloader-pdf)
- [OpenDataLoader 라이선스 안내](https://opendataloader.org/docs/license)
- [OpenDataLoader hybrid mode](https://opendataloader.org/docs/hybrid-mode)
- [OpenDataLoader 제3자 라이선스](https://github.com/opendataloader-project/opendataloader-pdf/blob/main/THIRD_PARTY/THIRD_PARTY_LICENSES.md)
- [Eclipse Temurin](https://adoptium.net/temurin/)
