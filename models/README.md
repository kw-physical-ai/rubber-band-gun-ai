# Promoted models

이 디렉터리에는 검증 후 팀이 승인한 모델만 Git LFS로 저장합니다.

강의 자료의 `yolo_target.pt`와 `best_yaw_cnn.pth`는 baseline 평가가 끝날 때까지 `physical-ai/`에 유지하고 커밋하지 않습니다. 승격할 때는 모델 파일 옆에 `<artifact-name>.json` manifest를 추가합니다. 예를 들어 `yaw-v1.pth`에는 `yaw-v1.pth.json`이 필요합니다.

- model SHA-256
- source commit
- training run/data manifest ID
- input/preprocessing schema
- yaw range 또는 class names
- validation 및 locked-test metrics
- compatible Ultralytics/PyTorch versions

`python scripts/check-model-manifest.py models/<artifact>.json`이 파일과 manifest를 검증합니다. CI는 모든 tracked `.pt`/`.pth`가 Git LFS pointer이고 paired manifest가 있는지 검사합니다.

모델 후보 생성, 비교, 승인 절차는 [프로젝트 워크플로](../docs/project-workflow.md)를 따릅니다. 현재 승격된 모델은 없습니다.
