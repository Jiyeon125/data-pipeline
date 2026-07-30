# UNKNOWN 우선검수 18개 사업 1차 입력안

## 목적과 사용 제한

- 대상: `data/manual/unknown_priority_fiscal_instrument_review.xlsx`의 `사업검수` 18개 사업
- 목적: 사람 검수 전에 공식 자료를 모아 엑셀 입력 후보를 제시
- 판정 기준: 최종 수혜자가 현금을 받는지가 아니라 중앙정부 예산의 **사업지원형태·집행 경로**를 우선함
- 상태: LLM 보조 사전검토이며 사람 검수 완료가 아님. 엑셀의 `review_status=CONFIRMED`로 아직 반영하지 않음

## 1차 입력안

| 행 | 소관 | 사업 | 분석범위 | 제외사유 | 적용 | 재정수단 후보 | 연도 동일 | 신뢰도 | 현재 상태 | 판단 근거 |
|---:|---|---|---|---|---|---|---|---|---|---|
| 5 | 행정안전부 | 보통교부세 | OUT_OF_SCOPE | OUTSIDE_TARGET_POLICY_SCOPE | NOT_APPLICABLE | - | YES | HIGH | 사람 확인 대기 | 지방재정 부족분을 보전하기 위해 지방자치단체에 교부하는 재원 |
| 6 | 보건복지부 | 기초연금지급 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | 사람 확인 대기 | 지자체 지급, 국비·지방비 분담 구조 |
| 7 | 고용노동부 | 구직급여 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | DIRECT | REVIEW_REQUIRED | MEDIUM | 사업설명자료 필요 | 고용보험 급여 직접 지급 성격은 확인되나 연도별 사업지원형태 확인 필요 |
| 8 | 중소벤처기업부 | 소상공인성장지원 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | 사람 확인 대기 | 공식 사업설명자료의 사업지원형태가 보조이며 2022년 재난지원금 포함 |
| 9 | 보건복지부 | 의료급여 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | REVIEW_REQUIRED | MEDIUM | 사업설명자료 필요 | 의료급여기금 국비·지방비 분담 구조는 확인되나 전체 사업의 연도별 지원형태 직접 확인 필요 |
| 10 | 고용노동부 | 산재보험급여 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | DIRECT | REVIEW_REQUIRED | MEDIUM | 사업설명자료 필요 | 국가 운영 산재보험 급여 지급 성격은 확인되나 연도별 사업지원형태 확인 필요 |
| 11 | 보건복지부 | 생계급여 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | 사람 확인 대기 | 국고보조율을 적용하는 보조사업으로 공식 예산분석서에서 확인 |
| 12 | 행정안전부 | 부동산교부세 | OUT_OF_SCOPE | OUTSIDE_TARGET_POLICY_SCOPE | NOT_APPLICABLE | - | YES | HIGH | 사람 확인 대기 | 부동산교부세 전액을 지방자치단체에 교부 |
| 13 | 행정안전부 | 민생회복 소비쿠폰 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | MEDIUM | 사업설명자료 필요 | 지자체를 통해 카드·지역사랑상품권·선불카드로 지급하나 예산상 사업지원형태 직접 확인 필요 |
| 14 | 고용노동부 | 모성보호육아지원 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | DIRECT | REVIEW_REQUIRED | MEDIUM | 사업설명자료 필요 | 출산전후휴가·육아휴직 급여 지급 성격은 확인되나 연도별 사업지원형태 확인 필요 |
| 15 | 보건복지부 | 영유아보육료 지원 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | 사람 확인 대기 | 공식 결산분석에서 국고보조 사업으로 확인 |
| 16 | 보건복지부 | 아동수당 지급 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | 사람 확인 대기 | 지자체 지급과 국고보조율 구조 확인 |
| 17 | 보건복지부 | 장애인활동지원 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | REVIEW_REQUIRED | MEDIUM | 사업설명자료 필요 | 바우처·제공기관 집행 구조는 확인되나 예산상 지원형태 직접 확인 필요 |
| 18 | 중소벤처기업부 | 소상공인 손실보상 제도화 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | 사람 확인 대기 | 공식 사업설명자료와 국회 예산분석에서 보조사업으로 확인 |
| 19 | 보건복지부 | 노인일자리 및 사회활동지원 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | 사람 확인 대기 | 지자체 경상보조·민간 경상보조 및 국고보조율 확인 |
| 20 | 보건복지부 | 부모급여(영아수당) 지원 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | 사람 확인 대기 | 현금·바우처 급여이지만 지자체 집행과 국고보조율 구조 확인 |
| 21 | 과학기술정보통신부 | 지급이자와반환금 | OUT_OF_SCOPE | NON_POLICY_ADMINISTRATION | NOT_APPLICABLE | - | YES | HIGH | 사람 확인 대기 | 우체국예금 원리금 지급 의무로 정책사업 순위와 다른 금융계정 의무지출 |
| 22 | 고용노동부 | 국민취업지원제도(일반) | IN_SCOPE | NOT_APPLICABLE | REVIEW_REQUIRED | UNKNOWN | REVIEW_REQUIRED | MEDIUM | 사업설명자료 필요 | 구직촉진수당과 취업지원서비스가 혼합되어 단일 재정수단 확정 불가 |

## 공식 근거

| 사업 | 공식 근거 |
|---|---|
| 보통교부세·부동산교부세 | 행정안전부 지방교부세 안내: https://www.mois.go.kr/frt/sub/a06/b07/localSharedTax/screen.do |
| 기초연금지급 | 국가법령정보센터 기초연금법 지급 규정: https://www.law.go.kr/lsLinkCommonInfo.do?lsJoLnkSeq=1031319703 |
| 기초연금지급 | 국회예산정책처 국비·지방비 분담 자료: https://www.nabo.go.kr/board/file/down.do?fid=33314449 |
| 소상공인성장지원 | 중소벤처기업부 2024년 사업설명자료: https://www.mss.go.kr/common/board/Download.do?bcIdx=1047721&cbIdx=128&streFileNm=b8fe4698-d9a9-4066-97ab-5e171dcf0e6d.pdf |
| 소상공인성장지원·손실보상 | 중소벤처기업부 2022년 사업설명자료: https://www.mss.go.kr/common/board/Download.do?bcIdx=1031706&cbIdx=128&streFileNm=5ba526a3-6863-407a-a388-9131123e5dcd.pdf |
| 소상공인성장지원·손실보상 | 국회예산정책처 추경 보조사업 분석: https://nabo.go.kr/board/file/bulkDown.do?bid=19&idx=8184 |
| 의료급여·생계급여 | 국회예산정책처 2024년도 예산안 분석: https://www.nabo.go.kr/board/file/down.do?fid=33317752 |
| 산재보험급여 | 고용노동부 산재보험 정책안내: https://www.moel.go.kr/policyitrd/policyItrdView.do?policy_itrd_sn=540 |
| 민생회복 소비쿠폰 | 행정안전부 사업안내: https://www.mois.go.kr/frt/bbs/type010/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000008&nttId=118705 |
| 모성보호육아지원 | 고용노동부 모성보호 급여 안내: https://www.moel.go.kr/info/policyBiz/realPolicyView.do?bbs_seq=1385093021718 |
| 영유아보육료 지원 | 국회예산정책처 2023회계연도 결산분석: https://nabo.go.kr/board/file/down.do?fid=33318084 |
| 아동수당 지급 | 보건복지부 아동수당 안내: https://www.mohw.go.kr/menu.es?mid=a10711030100 |
| 아동수당 지급 | 국회예산정책처 국고보조율 자료: https://www.nabo.go.kr/board/file/down.do?fid=33314816 |
| 장애인활동지원 | 보건복지부 장애인활동지원 안내: https://www.mohw.go.kr/menu.es?mid=a10710040800 |
| 노인일자리 | 보건복지부 노인일자리 안내: https://www.mohw.go.kr/menu.es?mid=a10712020100 |
| 노인일자리 | 정부 정책브리핑 보조방식 설명: https://www.korea.kr/briefing/actuallyView.do?newsId=148906078 |
| 부모급여 | 보건복지부 부모급여 안내: https://www.mohw.go.kr/menu.es?mid=a10711030600 |
| 부모급여 | 국회예산정책처 국고보조율 자료: https://www.nabo.go.kr/board/file/down.do?fid=33317533 |
| 지급이자와반환금 | 국가법령정보센터 우체국예금·보험법: https://www.law.go.kr/LSW/lsPdfPrint.do?ancYnChk=0&bylChaChk=N&efGubun=Y&efYd=20240209&joAllCheck=Y&joEfOutPutYn=on&lsiSeq=253313&mokChaChk=N |
| 국민취업지원제도 | 고용노동부 사업안내: https://www.moel.go.kr/news/enews/report/enewsView.do?news_seq=14584 |

## 추가 원문이 필요한 범위

큰 성과계획서·성과보고서 PDF 전체는 필요하지 않습니다. 아래 **예산·기금운용계획 사업설명자료의 해당 사업 페이지만** 있으면 됩니다.
이 자료는 Codex가 먼저 각 부처·국회예산정책처 등 공식 공개처에서 찾아 확인합니다.
사용자가 직접 찾아서 제출할 목록이 아니며, 공식 공개본을 찾지 못한 항목만 마지막에 별도로 요청합니다.

1. 고용노동부 2022~2025년 사업설명자료
   - 구직급여: `1280-350`
   - 산재보험급여: `4051-350`
   - 모성보호육아지원: `1345-358`
   - 국민취업지원제도(일반): `1234-300`
2. 행정안전부 2025년 추경 사업설명자료
   - 민생회복 소비쿠폰
3. 보건복지부 2022~2025년 사업설명자료
   - 의료급여: `1132-302`
   - 장애인활동지원: `1535-304`

중소벤처기업부는 현재 확보한 2022·2024년 공식 사업설명자료로 1차 분류가 가능하므로 더 큰 PDF가 당장 필요하지 않습니다.

## 다음 반영 순서

1. Codex가 위 7개 사업의 공식 사업설명자료를 추가 탐색
2. 공식 공개본을 찾지 못한 항목만 사용자에게 원문 보유 여부 확인
3. 후보 판정과 근거를 사용자에게 짧게 제시해 최종 사람 검수
4. Excel의 `S:AD`에 입력하고 `reviewer`, `reviewed_at`, `review_status` 기록
5. `validate-unknown-priority-review --require-complete` 통과 확인
6. UNKNOWN 오버레이와 순위 민감도 재산출
