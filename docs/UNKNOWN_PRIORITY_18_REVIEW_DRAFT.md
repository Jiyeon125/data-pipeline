# UNKNOWN 우선검수 18개 사업 확정 결과

## 목적과 사용 제한

- 대상: `data/manual/unknown_priority_fiscal_instrument_review.xlsx`의 `사업검수` 18개 사업
- 목적: 공식 자료와 사람 검수로 확정한 분석범위·재정수단 판단을 기록
- 판정 기준: 최종 수혜자가 현금을 받는지가 아니라 중앙정부 예산의 **사업지원형태·집행 경로**를 우선함
- 상태: 18개 사업·66개 사업-연도 검수 완료, `--require-complete` 통과

## 확정 입력

| 행 | 소관 | 사업 | 분석범위 | 제외사유 | 적용 | 재정수단 후보 | 연도 동일 | 신뢰도 | 현재 상태 | 판단 근거 |
|---:|---|---|---|---|---|---|---|---|---|---|
| 5 | 행정안전부 | 보통교부세 | OUT_OF_SCOPE | OUTSIDE_TARGET_POLICY_SCOPE | NOT_APPLICABLE | - | YES | HIGH | CONFIRMED | 지방재정 부족분을 보전하기 위해 지방자치단체에 교부하는 재원 |
| 6 | 보건복지부 | 기초연금지급 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | CONFIRMED | 지자체 지급, 국비·지방비 분담 구조 |
| 7 | 고용노동부 | 구직급여 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | DIRECT | YES | HIGH | CONFIRMED | 2022~2025년 공식 사업설명자료에서 사업지원형태 `직접` 확인 |
| 8 | 중소벤처기업부 | 소상공인성장지원 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | CONFIRMED | 공식 사업설명자료의 사업지원형태가 보조이며 2022년 재난지원금 포함 |
| 9 | 보건복지부 | 의료급여 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | CONFIRMED | 공식 사업설명자료에서 사업지원형태 `보조`, 서울 50%·그 외 80% 확인 |
| 10 | 고용노동부 | 산재보험급여 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | DIRECT | YES | HIGH | CONFIRMED | 2022~2025년 공식 사업설명자료에서 사업지원형태 `직접` 확인 |
| 11 | 보건복지부 | 생계급여 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | CONFIRMED | 국고보조율을 적용하는 보조사업으로 공식 예산분석서에서 확인 |
| 12 | 행정안전부 | 부동산교부세 | OUT_OF_SCOPE | OUTSIDE_TARGET_POLICY_SCOPE | NOT_APPLICABLE | - | YES | HIGH | CONFIRMED | 부동산교부세 전액을 지방자치단체에 교부 |
| 13 | 행정안전부 | 민생회복 소비쿠폰 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | CONFIRMED | 2025년 지자체 공식 예산자료에서 국고보조사업과 국비·지방비 분담 확인 |
| 14 | 고용노동부 | 모성보호육아지원 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | DIRECT | YES | HIGH | CONFIRMED | 2022~2025년 공식 사업설명자료에서 사업지원형태 `직접` 확인 |
| 15 | 보건복지부 | 영유아보육료 지원 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | CONFIRMED | 공식 결산분석에서 국고보조 사업으로 확인 |
| 16 | 보건복지부 | 아동수당 지급 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | CONFIRMED | 지자체 지급과 국고보조율 구조 확인 |
| 17 | 보건복지부 | 장애인활동지원 | IN_SCOPE | NOT_APPLICABLE | REVIEW_REQUIRED | UNKNOWN | YES | HIGH | CONFIRMED | 공식 사업설명자료에서 사업지원형태 `직접`과 `보조`가 모두 체크되고 국고보조율 67%로 확인됨 |
| 18 | 중소벤처기업부 | 소상공인 손실보상 제도화 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | CONFIRMED | 공식 사업설명자료와 국회 예산분석에서 보조사업으로 확인 |
| 19 | 보건복지부 | 노인일자리 및 사회활동지원 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | CONFIRMED | 지자체 경상보조·민간 경상보조 및 국고보조율 확인 |
| 20 | 보건복지부 | 부모급여(영아수당) 지원 | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | SUBSIDY | YES | HIGH | CONFIRMED | 현금·바우처 급여이지만 지자체 집행과 국고보조율 구조 확인 |
| 21 | 과학기술정보통신부 | 지급이자와반환금 | OUT_OF_SCOPE | NON_POLICY_ADMINISTRATION | NOT_APPLICABLE | - | YES | HIGH | CONFIRMED | 우체국예금 원리금 지급 의무로 정책사업 순위와 다른 금융계정 의무지출 |
| 22 | 고용노동부 | 국민취업지원제도(일반) | IN_SCOPE | NOT_APPLICABLE | APPLICABLE | DIRECT | YES | HIGH | CONFIRMED | 서비스와 소득지원이 함께 있으나 2022~2025년 공식 사업설명자료의 사업지원형태는 모두 `직접` |

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
| 구직급여·산재보험급여·모성보호육아지원·국민취업지원제도 | 고용노동부 2022년 사업설명자료: https://www.moel.go.kr/info/financeInfo/openfiscal/busiExplanView.do?bbs_seq=20220300559 |
| 구직급여·산재보험급여·모성보호육아지원·국민취업지원제도 | 고용노동부 2023년 사업설명자료: https://www.moel.go.kr/info/financeInfo/openfiscal/busiExplanView.do?bbs_seq=20230200029 |
| 구직급여·산재보험급여·모성보호육아지원·국민취업지원제도 | 고용노동부 2024년 사업설명자료: https://www.moel.go.kr/info/financeInfo/openfiscal/busiExplanView.do?bbs_seq=20240101813 |
| 구직급여·산재보험급여·모성보호육아지원·국민취업지원제도 | 고용노동부 2025년 사업설명자료: https://www.moel.go.kr/info/financeInfo/openfiscal/busiExplanView.do?bbs_seq=20250100967 |
| 의료급여·장애인활동지원 | 보건복지부 2022년 사업설명자료: https://www.mohw.go.kr/board.es?act=view&bid=0037&list_depth=1&list_no=369977&mid=a10107010000 |

## 추가 원문 필요 여부

- 사용자가 추가로 제출할 원문은 없습니다.
- 고용노동부 4개 사업은 2022~2025년 공식 사업설명자료에서 `직접`으로 확인했습니다.
- 의료급여는 보건복지부 공식 사업설명자료에서 `보조`로 확인했습니다.
- 민생회복 소비쿠폰은 2025년 지자체 공식 예산자료에서 국고보조사업으로 확인했습니다.
- 장애인활동지원은 원문 부족이 아니라 공식 사업설명자료 자체가 `직접+보조` 복합으로 표시됩니다.

## 복합수단 처리 결정

장애인활동지원은 하나의 재정수단으로 강제 분류하지 않습니다. 현재 검수 지침에 따라
`fiscal_instrument_applicability=REVIEW_REQUIRED`,
`fiscal_instrument=UNKNOWN`으로 유지합니다.

현행 분류체계를 유지하고 일반 재정분석에는 포함하되 재정수단 내부 순위에서만
제한하기로 결정했습니다. 향후 내역사업 단위 자료가 확보될 때만 `MULTIPLE` 또는
내역사업별 재정수단 도입을 재검토합니다.

## 반영 결과

1. Excel `S:AD` 입력과 검수자·검수일·상태 기록 완료
2. 사업 18개·연도 66행 `--require-complete` 통과
3. 범위 제외 3개 사업·12행을 전체 순위 모집단에서 제외
4. 복합수단 1개 사업·4행은 일반 분석에 유지하고 재정수단별 순위에서 제한
5. M3와 3개 부처 시나리오 순위 재산출 완료
