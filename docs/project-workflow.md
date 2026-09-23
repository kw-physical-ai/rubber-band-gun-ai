# 프로젝트 워크플로

이 문서는 네 명의 팀원이 같은 저장소와 데이터로 작업할 때 코드, 데이터, 학습 결과가 어떻게 이동하는지 설명합니다. 실제 접속 주소와 개인 자격 증명은 저장소 밖에서 관리합니다.

## 1. 네 시스템의 역할

| 시스템 | 역할 | 저장하면 안 되는 것 |
| --- | --- | --- |
| GitHub | 코드, 노트북 소스, 설정 예제, 모델 manifest, 승인된 모델 | raw 데이터, 토큰, 개인 장비 정보 |
| Raspberry Pi | 카메라 수집, 보정된 yaw/pitch 명령, 향후 recorded-frame 평가 | 개인 GitHub 토큰, 임의 수정된 완료 bundle |
| Google Drive | raw capture, processed dataset, 학습 run과 checkpoint | GitHub 작업 이력의 대체물 |
| Google Colab | 데이터 검증, 전처리, 평가, 필요할 때 학습 | 셀에 직접 쓴 토큰, 재현 정보 없는 결과물 |

Drive의 공용 구조는 다음과 같습니다.

```text
rubber-band-gun-ai-data/
├── pi-upload/
│   ├── raw/<capture-id>/
│   └── smoke/<capture-id>/
├── processed/<dataset-id>/
└── runs/<run-id>/
```

Pi는 `pi-upload/`만 작성하고, Colab은 이를 읽어 `processed/`와 `runs/`를 작성합니다. 팀원은 공유 Drive 폴더 권한을 받되 Pi의 OAuth/rclone token을 복사하지 않습니다.

## 2. GitHub 협업

모든 팀원은 organization member이자 repository `Write` 권한 사용자로 참여합니다. 개인별 GitHub·Colab credential을 사용하고 서로 공유하지 않습니다.

일반 작업 순서:

1. Issue에 목적, 완료 조건, 관련 capture/run ID, 작업자 한 명과 검토자 한 명을 적는다. 역할은 Issue마다 바꾸며 고정된 상하 권한을 만들지 않는다.
2. `feat/...`, `fix/...`, `exp/...`, `docs/...` 중 하나의 짧은 branch를 만든다.
3. 코드와 문서를 함께 수정하고 로컬 검증을 실행한다.
4. pull request에 변경 이유, 검증 결과, 하드웨어에서 하지 않은 검증을 적는다.
5. `python` CI가 성공한 뒤 다른 팀원이 검토하고 merge한다.

```bash
pytest
ruff check .
python scripts/check-notebooks.py
```

하드웨어 실험 Issue에는 최소한 다음을 기록합니다.

- Git commit
- 하드웨어·카메라·calibration ID
- capture ID 또는 dataset ID
- model hash 또는 run ID
- 거리·조명·표적 조건
- 지표와 실패 사례
- 다음 결정

데이터 annotation은 작성자와 검토자를 분리합니다. 하드웨어 run은 가능하면 장비 조작자와 결과 기록자를 분리합니다. 모델 후보 PR 작성자는 자신의 결과를 정리할 수 있지만, merge와 locked-test 개봉 결정에는 다른 팀원의 검토가 필요합니다.

## 3. 데이터 수집

### 연결 확인 데이터

Smoke bundle은 Pi → Drive → Colab 연결만 증명합니다. 학습이나 모델 평가에 사용하지 않습니다. [data-flow smoke test](data-flow-smoke-test.md)를 따릅니다.

### yaw 데이터

Yaw capture는 사람이 고정된 조준 기준에 표적을 맞춘 뒤 카메라 프레임과 yaw/pitch 명령값을 함께 저장합니다. 센서가 측정한 물리 각도가 아니라 서보에 보낸 명령값이라는 점에 주의합니다.

각 session은 `capture-YYYYMMDDTHHMMSSZ` 디렉터리 하나로 완료되며 이미지, `data_angles.csv`, `manifest.json`을 포함합니다. Pi와 Colab 양쪽에서 `scripts/check-yaw-capture.py`가 통과해야 분석 후보가 됩니다. 자세한 조작 방법은 [yaw data collection](yaw-data-collection.md), 필드 정의는 [data contract](data-contract.md)를 따릅니다.

완료된 capture는 수정하지 않습니다. 라벨을 고쳐야 한다면 원본을 덮어쓰지 말고 새로운 dataset version에서 수정 이력과 근거를 기록합니다.

전송과 장애 복구는 [Pi direct Drive upload](pi-drive-upload.md)를 따릅니다. 업로더는 로컬 manifest와 payload를 확인하고 원격 `manifest.json`을 마지막에 게시합니다. Colab은 업로드된 사본을 다시 검증하며, 완료 manifest가 없는 중단된 업로드는 데이터셋에 포함하지 않습니다.

## 4. 학습 여부를 결정하는 순서

학습은 기본 동작이 아니라 baseline 평가 실패에 대한 대응입니다.

### 4.1 먼저 준비할 진단 데이터

- 여러 capture session
- 지원 yaw 범위의 위치
- 가까운 거리와 먼 거리
- 서로 다른 조명과 배경
- 표적이 없는 장면
- baseline 판단과 학습에 사용하지 않을 locked-test session

같은 burst의 인접 프레임은 매우 비슷하므로 이미지 단위 random split을 하지 않습니다. capture ID 전체를 train, validation, locked test 중 하나에 배정합니다. 기존 모델의 문제를 찾고 재학습 여부를 결정할 때는 validation 역할의 진단 session만 사용합니다. Locked-test session은 최종 후보와 threshold를 고정할 때까지 열지 않습니다. 가능하면 날짜, 표적 위치, 거리, 조명과 정렬 담당자도 split 사이에서 분리합니다.

### 4.2 기존 모델을 분리 평가

1. YOLO: 사람이 검토한 독립 annotation을 정답으로 사용해 target recall, no-target false-positive rate, 잘못된 박스 사례를 평가합니다. 기존 YOLO가 만든 pseudo-label을 같은 모델의 평가 정답으로 사용하지 않습니다.
2. Yaw CNN: 표적 검출 결과가 정상인 프레임에서 yaw MAE와 위치별 bias를 평가합니다.
3. Recorded-frame pipeline: 수집 때와 같은 전처리로 `detect → mask → yaw prediction` 전체 결과를 기록합니다.

평가 threshold는 실제 servo resolution, 목표 거리에서 허용할 수 있는 오차, 표적 크기를 바탕으로 validation 결과를 보기 전에 정합니다. 기존 강의 checkpoint의 학습 지표만으로 통과 처리하지 않습니다. Locked-test label을 만드는 사람은 가능하면 후보 모델의 예측을 보지 않고 annotation이나 정렬값을 확정합니다.

현재 하드웨어가 완성되지 않아 숫자 threshold는 아직 정해지지 않았습니다. Calibration이 끝나면 별도 평가 Issue에 metric별 통과값과 `invalid` 조건을 먼저 기록하고, 후보 commit·model hash·threshold가 고정되었다는 검토자의 확인 후에만 locked test를 실행합니다.

### 4.3 결과별 처리

| 결과 | 처리 |
| --- | --- |
| YOLO와 yaw 모두 통과 | 재학습하지 않고 calibration/config만 확정 |
| YOLO 통과, yaw가 일정하게 치우침 | barrel alignment 또는 center calibration 수정 후 재평가 |
| YOLO 통과, yaw 오차가 위치·session마다 달라짐 | yaw capture를 보강하고 yaw CNN만 재학습 |
| YOLO recall/false positive 실패 | 표적 annotation을 만들고 YOLO 재학습 후 yaw 재평가 |

## 5. Dataset version

학습 전에 Colab이 검증된 capture를 읽어 `processed/<dataset-id>/`를 만들어야 합니다. dataset version에는 다음 정보가 필요합니다.

- source capture ID와 각 manifest SHA-256
- `rbg-camera-preprocessing/v1` 전체 설정
- train/validation/locked-test의 capture ID 목록
- 포함·제외된 label status와 제외 사유
- 생성에 사용한 Git commit과 패키지 버전
- 파일 수, yaw 분포와 누락/거부 통계

`notebooks/10_build_yaw_dataset.ipynb`와 `scripts/build-yaw-dataset.py`가 이 계약을 구현합니다. Builder는 source bundle을 다시 검증하고 `human-aligned` 프레임만 복사하며, 한 capture가 여러 split에 들어가거나 전처리 설정이 섞이면 중단합니다. 결과는 `labels.csv`와 `dataset_manifest.json`을 포함한 immutable directory로 게시됩니다.

따라서 현재 자동화 흐름은 `Pi capture → Drive upload → Colab bundle 검증 → versioned dataset`까지 이어집니다. 기존 모델 baseline 평가와 학습 run 생성부터는 아직 문서 계약만 있고 실행 코드는 없습니다.

## 6. Colab 학습 run

각 학습은 `runs/<run-id>/` 아래에 독립적으로 저장합니다.

```text
runs/<run-id>/
├── run_manifest.json
├── metrics.json
├── checkpoints/
├── plots/
└── evaluation/
```

`run_manifest.json`에는 최소한 다음을 기록합니다.

- Git commit
- dataset ID와 dataset manifest hash
- 모델 종류와 초기 weight hash
- 전처리 schema
- hyperparameters와 random seed
- Python, PyTorch, Ultralytics 버전
- validation 및 locked-test 지표
- 생성된 artifact SHA-256

Locked test는 최종 후보에 한 번 사용합니다. 기존 모델이 validation 기준을 통과해 최종 후보가 되면 그때 처음 locked test를 실행합니다. 결과를 보고 hyperparameter나 threshold를 바꿨다면 기존 결과는 더 이상 locked test가 아니므로 새 모델 버전과 새로운 독립 test session이 필요합니다.

## 7. 모델 후보와 승격

모델 후보 PR에는 다음을 포함합니다.

- 학습·평가 코드 또는 노트북 변경
- 선택된 모델의 Git LFS pointer
- model manifest
- dataset ID와 run ID
- 기존 baseline과 후보 지표 비교
- 실패 사례와 알려진 제한
- Pi recorded-frame 평가 결과

원본 데이터, 전체 checkpoint 모음, 큰 plot/output은 Drive에 두고 Git에는 넣지 않습니다. `models/`에는 팀이 승인한 최종 artifact와 manifest만 둡니다.

CI는 코드와 manifest의 구조를 확인할 수 있지만 실제 카메라 성능이나 명중률을 대신 검증하지 못합니다. Pi evaluation release는 코드와 모델을 복사하고 hash를 확인하는 단계이며 모터를 자동으로 시작하거나 발사하지 않습니다.

## 8. 실제 명중 시험

Yaw 라벨 정확도와 실제 명중 여부는 다릅니다. 하드웨어와 안전 절차가 완성된 뒤에만 별도의 controlled shot run을 수행합니다.

- 시험 전에 hit 영역과 `invalid` 조건을 정의합니다.
- 각 shot은 pre-shot frame, 모델 예측, 명령 각도, 거리, model/calibration version에 연결합니다.
- `hit/miss/invalid`는 모델 예측이 아니라 표적의 사후 증거로 판정합니다.
- locked shot 결과를 보고 모델을 조정했다면 새 모델과 새 locked run으로 다시 평가합니다.

현재 저장소는 `shot_results.csv`의 행 형식만 제공하며 발사를 구동하는 코드는 포함하지 않습니다. 실제 시험 전에는 model hash, calibration ID, preprocessing schema, target coordinate system과 증거 파일 hash를 묶는 shot-run manifest를 추가해야 합니다.

## 9. 현재 작업 경계

현재 바로 할 수 있는 작업:

- 팀원별 clone, branch, PR, CI
- Colab 환경 확인과 공유 Drive mount
- Pi → Drive → Colab smoke test
- preview-only 카메라 확인
- 하드웨어 보정 후 발사 없는 yaw capture 생성과 검증

다음으로 구현할 작업:

1. actuator-free 기존 모델 evaluator와 Colab baseline notebook
2. baseline 결과가 요구할 경우에만 yaw CNN 또는 YOLO training notebook
3. model manifest validator와 recorded-frame Pi evaluator

실제 발사와 movement-capable inference는 위 작업 및 하드웨어 안전 검증 이후의 별도 단계입니다.
