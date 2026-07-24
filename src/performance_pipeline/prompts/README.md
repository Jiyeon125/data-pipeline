# Prompt versions

프롬프트는 버전별 파일로 추가하고 `configs/llm.yaml`의 `prompt_version`과
일치시킵니다. 문서에 없는 값은 생성하지 않고 `null`과 검토 상태를 반환해야 합니다.
