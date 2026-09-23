# Colab notebooks

- `00_environment_check.ipynb`: private GitHub repository download, pinned dependency installation, Drive mount, runtime metadata recording, smoke bundle integrity를 확인합니다. 학습은 수행하지 않습니다.
- `10_build_yaw_dataset.ipynb`: 검증된 Drive capture ID를 capture 단위 split으로 지정하고 immutable dataset과 manifest를 생성한 뒤 다시 검증합니다.

노트북은 위에서 아래로 새 런타임에서 실행할 수 있어야 합니다. API 키와 GitHub 토큰을 셀에 직접 입력하거나 출력에 남기지 않습니다.

다음 노트북은 아직 구현되지 않았습니다. 구현 순서와 산출물 계약은 [프로젝트 워크플로](../docs/project-workflow.md)를 따릅니다.

1. 기존 YOLO/CNN actuator-free baseline 평가
2. baseline 실패 범위에 한정한 yaw CNN 또는 YOLO 재학습
3. 후보 모델의 locked-test 및 artifact manifest 생성
