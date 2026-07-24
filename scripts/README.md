# Scripts

일회성 점검이나 배치 실행 래퍼만 둡니다. 재사용되는 변환·조인·분석 로직은
반드시 `src/` 패키지에 구현합니다.

- `test_api.ps1`: OpenAPI 연결 점검
- `work_tracker_hook.py`: 로컬 Codex 작업 트래커용이며 Git에서 제외됩니다.
