# 데이터분석 업그레이드 요약

## 추가된 검증

- 생산 등급 계약 감사에 이어 동일 236행을 생산 판정식으로 shadow 재현했습니다.
- 고정 CSV에서 안전하게 재계산 가능한 4개 수치 임계값을 OAT 6개 변형으로 점검했습니다.
- execution, reported_performance, budget_performance_mismatch, repetition을 한 계열씩 제거해
  점검등급의 신호 의존성을 분리했습니다.
- H와 identity·comparability·결측 상태는 고정했고 생산 코드·CSV·등급은 변경하지 않았습니다.

## 핵심 결과

- shadow 기준 재현 불일치: 0/236행
- A~D 등급 유지율: 0.938~1.000
- A+B Jaccard: 0.882~1.000
- 신호 제거별 등급 변경: execution 20, reported_performance 56, budget_performance_mismatch 50, repetition 24

## 분석적으로 달라진 점

현재 등급을 단일 결과로 제시하는 데서 그치지 않고, 어떤 수치 경계와 신호 계열에서
등급이 유지되거나 이동하는지 프로그램-연도별로 추적할 수 있게 됐습니다. 결과는 임계값
튜닝이나 성과판정이 아니라 검토범위 압축과 경계 사례 확인에만 사용합니다.
