# 자동화 흐름

이 문서는 코드가 GitHub에서 검증되고, Raspberry Pi에서 수집한 데이터가 Drive와 Colab을 거쳐 versioned dataset이 되며, 이후 승인된 evaluation release가 Pi로 돌아가는 과정을 설명합니다. 파일 형식은 [데이터 계약](data-contract.md), 팀의 실험 판단 기준은 [프로젝트 워크플로](project-workflow.md), 계정과 연결 설정은 [GitHub·Colab·Pi 연결](github-colab-pi.md)이 기준입니다.

자동화의 목적은 반복 작업과 무결성 검사를 맡는 것입니다. 데이터 split, locked-test 개봉, 모델 선택, 물리 장비 실행은 자동 결정하지 않습니다.

이 문서는 자동화의 연결 관계와 handoff를 보여 주는 운영 지도입니다. 계정 연결, Pi OAuth, calibration, capture 조작과 파일 schema의 세부 절차를 대체하지 않습니다. 처음 시작하는 팀원은 먼저 [GitHub·Colab·Pi 연결](github-colab-pi.md)을 완료하고, Pi 작업자는 [Pi direct Drive upload](pi-drive-upload.md)와 [Yaw data collection](yaw-data-collection.md)을 따라야 합니다. 모든 repository 명령은 별도 표시가 없으면 checkout root와 활성화된 project venv에서 실행합니다.

## 1. 전체 구조

```text
code branch / pull request
  └─ GitHub Actions CI
       ├─ Ruff
       ├─ CPU tests
       └─ notebook structure check

Raspberry Pi camera
  └─ 사람이 표적을 정렬하고 Space로 capture
       └─ capture bundle + manifest
            └─ upload script
                 ├─ local hash verification
                 ├─ Drive payload upload
                 ├─ remote consistency check
                 └─ manifest published last
                      ↓
Google Drive / pi-upload/raw/<capture-id>
  └─ Colab dataset builder
       ├─ source capture 재검증
       ├─ capture 단위 split 확인
       ├─ human-aligned frame만 복사
       └─ labels.csv + dataset_manifest.json
            ↓
Google Drive / processed/<dataset-id>
  └─ baseline / training / model promotion       [아직 미구현]
       ↓
GitHub model candidate + Drive run artifacts     [아직 미구현]
  └─ manual evaluation deployment
       └─ GitHub Actions → Tailscale → Pi release directory
```

Drive와 rclone 경로는 같은 위치를 다음처럼 표현합니다.

```text
Google Drive: rubber-band-gun-ai-data/
├── pi-upload/
│   ├── raw/<capture-id>/       == Pi rclone project-drive:raw/<capture-id>/
│   └── smoke/<capture-id>/     == Pi rclone project-drive:smoke/<capture-id>/
├── processed/<dataset-id>/     == Colab workspace.processed/<dataset-id>/
└── runs/<run-id>/              == Colab workspace.runs/<run-id>/
```

## 2. 자동화 상태

| 구간 | 시작 방식 | 자동 처리 | 사람이 결정하는 것 | 현재 상태 |
| --- | --- | --- | --- | --- |
| 코드 CI | PR 또는 `main` push | 설치, Ruff, tests, notebook 검사 | PR 내용과 merge | 구현됨 |
| Pi camera preview | Pi에서 명령 실행 | 공통 회전·crop 화면 표시 | 카메라 위치와 crop 적합성 | 구현됨·실기 확인 필요 |
| yaw capture | Pi에서 motion mode 실행 | settle 차단, 이미지·각도·manifest 저장 | 보정값, 정렬, capture 시점 | 구현됨·하드웨어 검증 필요 |
| Pi → Drive upload | Pi에서 bundle별 명령 실행 | 해시 검사, immutable upload, 원격 대조 | 어떤 완료 bundle을 올릴지 | 구현·smoke 검증됨 |
| Colab 환경 확인 | 사용자가 Run all | GitHub `main` 다운로드, 의존성 설치, Drive mount, smoke 검증 | 계정 승인과 smoke ID | 구현·smoke 검증됨 |
| Dataset 생성 | 사용자가 ID와 split 입력 후 Run all | capture 재검증, 이미지 복사, labels/manifest 생성, 결과 재검증 | dataset ID와 capture별 split | 구현·합성 데이터 검증됨 |
| Baseline 평가 | 향후 notebook 실행 | 지표·실패 사례·run manifest 생성 예정 | threshold와 통과 여부 | 미구현 |
| 재학습 | baseline 실패 후 향후 notebook 실행 | checkpoint·metrics·run manifest 생성 예정 | 재학습 필요성, 모델 종류 | 미구현 |
| 모델 승격 | 향후 model candidate PR | manifest·hash·CPU 호환성 검사 예정 | 모델 승인과 locked-test 개봉 | 미구현 |
| Pi evaluation 배포 | GitHub Actions 수동 실행 | CI 재실행, Tailscale 연결, SHA별 release 동기화 | 팀 확인과 실행 시점 | 코드 준비·비활성화 |
| Pi 추론/물리 시험 | 향후 로컬 실행 | recorded-frame inference와 로그 기록 예정 | 장비 arm, 단발 실행, hit 판정 | 미구현 |

`구현됨`은 코드 경로가 존재하고 자동 테스트가 있다는 뜻입니다. 카메라·서보·표적과 관련된 성능을 실제 장비에서 검증했다는 뜻은 아닙니다.

## 3. 현재 가능한 golden path

현재 운영 가능한 자동화는 dataset 생성에서 끝납니다. 이후 baseline, training, model promotion과 Pi inference는 구현 전입니다.

| 순서 | 담당 역할 | 실행 | 성공 증거 | 다음 handoff |
| --- | --- | --- | --- | --- |
| 1 | 코드 작업자 | branch에서 변경 후 PR | `python` CI 성공 URL | 다른 팀원 review |
| 2 | Pi operator | preview와 calibration 확인 후 yaw capture | `scripts/check-yaw-capture.py`의 `status: passed`와 capture ID | data steward에게 capture ID 전달 |
| 3 | Pi operator | `upload-drive-bundle.sh` 실행 | terminal의 `Drive upload verified`와 Drive의 완료 manifest | Colab operator에게 capture ID 전달 |
| 4 | Colab operator | `00_environment_check.ipynb` Run all | `runs/data-flow-smoke/<smoke-id>.json`의 `status: passed` | 연결 준비 완료 기록 |
| 5 | data steward | capture 목록과 split 제안 | Issue에 capture ID, 조건과 split 근거 | 다른 팀원 확인 |
| 6 | Colab operator | `10_build_yaw_dataset.ipynb` Run all | dataset verifier의 `status: passed`, dataset ID와 manifest hash | 향후 baseline 작업 입력 |

역할은 고정 직급이 아니라 작업 단위 책임입니다. 네 명이 순환해서 맡을 수 있지만, locked-test 개봉과 모델 승격은 제안자 외 다른 팀원이 확인합니다. GitHub/Drive 관리자, Pi operator, data steward, Colab/model operator의 구체적인 배정은 Issue에 남깁니다.

각 성공 신호가 증명하는 범위도 다릅니다.

| 성공 신호 | 증명하는 것 | 증명하지 않는 것 |
| --- | --- | --- |
| CI 성공 | commit의 lint, CPU tests, notebook 저장 구조 | 하드웨어·카메라·모델 성능 |
| Smoke 성공 | Pi bundle이 Drive와 Colab까지 같은 bytes로 이동 | 데이터 의미, label, 학습 가능성 |
| Capture verifier 성공 | bundle 구조, 해시, 각도 계약과 이미지 geometry | 사람이 정확히 정렬했는지 |
| Dataset verifier 성공 | source lineage, split 구조, image-label 대응과 해시 | sample 수의 충분성, 모델 정확도 |
| Release hash 성공 | Git tracked release가 Pi에 같은 bytes로 복사됨 | service 적용, latency, 실제 장비 성능 |

## 4. 코드 변경 자동화

### 입력과 트리거

- 입력: Git에 커밋된 코드, 노트북, 설정 예제와 테스트
- 트리거: 모든 pull request와 `main` push
- 정의: `.github/workflows/ci.yml`

### 자동 단계

1. Python 3.11 환경에서 개발 의존성을 설치합니다.
2. `ruff check .`로 정적 검사를 실행합니다.
3. `pytest`로 하드웨어 없는 테스트를 실행합니다.
4. `python scripts/check-notebooks.py`로 저장된 output과 execution count가 없는지 검사합니다.

CI 성공은 코드와 데이터 계약의 정적·CPU 검증만 의미합니다. 카메라 영상 품질, servo 방향, 실제 latency, 표적 탐지 성능과 명중 여부는 증명하지 않습니다. 팀원은 CI 결과와 다른 팀원의 review를 확인한 뒤 merge합니다.

## 5. Pi 데이터 수집 자동화

### 5.1 Preview

```bash
python scripts/pi/collect-yaw-data.py --config configs/pi.toml
```

Preview-only에서는 카메라 frame에 공통 회전·crop을 적용해 보여줍니다. Motor driver를 import하지 않고 labeled capture도 만들지 않습니다. 사람이 화면을 보고 crop 방향과 표적 영역을 확인해야 합니다.

### 5.2 Yaw capture

```bash
python scripts/pi/collect-yaw-data.py \
  --config configs/pi.toml \
  --output-root "$HOME/captures" \
  --enable-motion
```

Motion mode는 `calibrated=true`, 실제 calibration ID, aiming reference, 유효한 servo 범위가 없으면 시작을 거부합니다. 사람은 WASD로 정렬하고 안정화 표시가 사라진 뒤 Space를 누릅니다. 프로그램은 다음을 자동으로 수행합니다.

- 공통 전처리로 canonical JPEG 저장
- commanded yaw/pitch와 yaw offset 기록
- 한 session을 `capture-<UTC>` ID로 묶기
- 이미지 크기, 파일 크기와 SHA-256을 manifest에 기록
- 완성 전에는 hidden `.partial` directory 사용
- 완료 시 directory rename

이 단계에는 발사 명령이 없습니다. 자세한 조작과 calibration 절차는 [Yaw data collection](yaw-data-collection.md)을 따릅니다.

## 6. Pi → Drive 업로드 자동화

```bash
bash "$HOME/upload-drive-bundle.sh" \
  "$HOME/captures/<capture-id>" \
  project-drive:raw
```

업로더는 다음 순서로 동작합니다.

1. 목적지가 `project-drive:raw` 또는 `project-drive:smoke`인지 확인합니다.
2. bundle 이름과 manifest의 capture ID가 같은지 확인합니다.
3. 선언된 모든 파일의 크기와 SHA-256을 검사하고 추가 파일·symlink·특수 파일을 거부합니다.
4. 로컬 bundle의 write bit를 제거하고 manifest snapshot을 만듭니다.
5. payload를 Drive에 `--immutable`로 전송하고 `rclone check`를 실행합니다.
6. 로컬 bundle을 다시 확인합니다.
7. 완료 표식인 `manifest.json`을 마지막에 올리고 다시 대조합니다.

중간에 멈춘 원격 directory에는 완료 manifest가 없으므로 Colab dataset 후보가 아닙니다. 복구와 OAuth 범위는 [Pi direct Drive upload](pi-drive-upload.md)가 기준입니다.

같은 capture ID를 여러 사람이 동시에 업로드하지 않습니다. `--immutable` 충돌은 자동으로 덮어쓸 대상이 아니라, 원격 directory와 완료 manifest를 확인해야 한다는 신호입니다. 로컬 write bit 제거는 공유 Linux 계정 안에서의 실수 방지일 뿐이며, Drive Editor나 같은 Pi 계정 사용자의 변경을 막는 보안 경계는 아닙니다.

## 7. Colab 환경 자동화

`notebooks/00_environment_check.ipynb`는 새 runtime마다 다음을 수행합니다.

1. 사용자의 `GITHUB_TOKEN`으로 GitHub API에서 현재 `main` SHA를 조회합니다.
2. 그 SHA의 repository archive를 `/content/rubber-band-gun-ai`에 받습니다.
3. Colab 의존성을 설치하고 실행 환경 정보를 출력합니다.
4. 각 사용자의 Google Drive를 mount합니다.
5. 공용 workspace 경로를 확인합니다.
6. 입력받은 smoke ID의 모든 파일과 해시를 검증하고 `runs/data-flow-smoke/`에 report를 씁니다.

Notebook source는 GitHub에 있지만 runtime, `GITHUB_TOKEN`, Drive 승인은 사용자별입니다. 한 사람의 runtime이나 Secret이 다른 팀원에게 전달되지는 않습니다.

Notebook은 실행 시작 시점의 `main` SHA를 먼저 조회하고 그 exact SHA의 archive를 받습니다. 실행 중 `main`이 바뀌어도 해당 runtime의 `commit_sha`는 바뀌지 않으며 dataset manifest에 전달됩니다. 현재 notebook은 feature branch나 임의 SHA 선택을 지원하지 않으므로, 공유 dataset은 review를 거쳐 `main`에 들어간 코드로 만듭니다.

## 8. Dataset 생성 자동화

`notebooks/10_build_yaw_dataset.ipynb`에서 사람이 다음 값만 지정합니다.

```python
dataset_id = "dataset-baseline-v1"
train_ids = []
validation_ids = ["capture-<UTC>"]
locked_test_ids = []
```

Builder는 각 capture를 정확히 한 split에만 허용하고 다음을 자동으로 수행합니다.

1. 각 raw capture를 복사 전후에 검증합니다.
2. 전처리 schema가 다른 capture의 혼합을 거부합니다.
3. `human-aligned` frame만 포함하고 `diagnostic` frame 수를 기록합니다.
4. 복사된 이미지 hash를 source manifest와 비교합니다.
5. 전역적으로 고유한 이미지 이름과 `labels.csv`를 만듭니다.
6. source capture hash, calibration, split, Git commit, 파일 hash와 yaw 통계를 `dataset_manifest.json`에 기록합니다.
7. 완성된 dataset을 독립 verifier로 다시 검사합니다.
8. 기존 dataset ID가 있으면 덮어쓰지 않고 중단합니다.

결과는 다음 위치에 저장됩니다.

```text
rubber-band-gun-ai-data/processed/<dataset-id>/
```

현재 baseline evaluator가 없으므로, 첫 실제 dataset은 기존 모델 진단용 `validation` capture만으로 만들 수 있습니다. `locked_test_ids`는 후보 모델과 threshold를 고정하고 다른 팀원이 승인하기 전까지 비워둡니다.

`locked-test`는 Drive 권한으로 숨겨진 데이터가 아니라 팀 절차상의 상태입니다. Drive Editor는 raw capture를 열 수 있으므로, 후보 commit·model hash·threshold와 승인자를 Issue에 먼저 기록하고 개봉 시점과 결과를 남겨야 합니다. 결과를 보고 후보나 threshold를 바꾸면 해당 결과는 더 이상 locked test가 아니며 새로운 독립 capture가 필요합니다.

Capture 단위 split은 인접 frame 누수를 막지만, 같은 정렬자·조명·거리·배경이 모든 split에 반복되는 편향까지 제거하지는 않습니다. 가능한 범위에서 수집 조건과 정렬 담당자를 분리하고, 최종 성능 주장은 모델 예측과 독립적으로 기록한 물리 시험 결과로 확인합니다.

Dataset ID는 한 번 게시하면 재사용하지 않습니다. 같은 dataset ID를 여러 Colab runtime에서 동시에 build하지 않습니다. 일반 예외는 staging을 정리하지만 runtime 강제 종료로 `.<dataset-id>.partial`이 남으면 source와 오류를 확인한 뒤 그 exact partial만 정리합니다. 완료 directory가 있으면 새 version ID를 사용합니다.

CLI로 같은 작업을 할 때는 다음 형식을 사용합니다.

```bash
python scripts/build-yaw-dataset.py \
  --output-root /path/to/processed \
  --dataset-id dataset-baseline-v1 \
  --validation /path/to/raw/capture-<UTC>

python scripts/check-yaw-dataset.py \
  /path/to/processed/dataset-baseline-v1
```

## 9. 모델 학습과 결과 반환의 예정 경계

Dataset 이후 단계는 아직 자동화되지 않았습니다. 구현할 때도 notebook 파일 자체를 Pi로 보내지 않습니다.

```text
processed/<dataset-id>
  ↓ baseline 또는 training notebook
runs/<run-id>/{run_manifest, metrics, checkpoints, plots}
  ↓ 선택된 후보만 PR
models/<model-version> + model manifest
  ↓ CI + 팀 승인
Pi evaluation release
```

Drive에는 전체 run과 checkpoint를 보관하고, Git에는 승인된 모델과 manifest만 둡니다. Training notebook은 `train`과 `validation`만 읽고, locked test는 후보와 threshold가 고정된 뒤 별도 평가 단계에서 한 번 엽니다.

## 10. Pi evaluation 배포 자동화

`.github/workflows/deploy-eval.yml`은 push 자동 배포가 아니라 `workflow_dispatch`로 시작하는 수동 workflow입니다. 현재 `PI_DEPLOY_ENABLED=false`이므로 실행되지 않습니다.

수동 실행 시 사용자가 임의 commit을 고르는 방식이 아니라, job이 시작될 때의 `main`을 checkout하고 그 SHA를 release ID로 사용합니다. 따라서 후보 코드와 모델은 먼저 review를 거쳐 `main`에 merge되어야 합니다. Git LFS checkout 후 실제 worktree content가 release에 포함되고, Git tracked file만 전송됩니다.

활성화 후의 자동 단계:

1. 항상 최신 `main`을 checkout합니다.
2. Ruff, 전체 CPU tests, notebook 검사와 Git LFS 검사를 다시 실행합니다.
3. GitHub-hosted runner를 제한된 Tailscale identity로 tailnet에 연결합니다.
4. deploy 전용 SSH key와 known hosts를 준비합니다.
5. Git tracked file만 `<release-root>/releases/<commit-sha>`에 복사합니다.
6. Pi에서 전체 SHA-256 manifest를 검사합니다.
7. 검증 성공 후 `<release-root>/current` symlink를 새 release로 전환합니다.

Workflow는 service를 시작하거나 motor·발사 명령을 실행하지 않습니다. 현재 비공개 저장소의 요금제에서는 required environment reviewer를 배포의 강제 gate로 사용할 수 없으므로, workflow 활성화 전까지는 PR review와 수동 dispatch를 팀 규칙으로 사용합니다. Repository variables, secrets, 이 권한 제약과 활성화 절차는 [GitHub·Colab·Pi 연결](github-colab-pi.md)에 있습니다.

다음 조건을 모두 충족하기 전에는 `PI_DEPLOY_ENABLED`를 바꾸지 않습니다.

- baseline/model manifest와 Pi recorded-frame evaluator가 구현되어 있다.
- deploy 전용 계정, release root owner와 권한이 확정되어 있다.
- 한 commit을 수동 배포하고 hash 검증한 기록이 있다.
- `current`를 직전 release로 되돌리는 rollback 명령을 실제로 시험했다.
- 배포 후 service를 자동 시작하지 않는 현재 경계를 팀이 이해한다.
- release 보존과 disk 정리 책임자를 정했다.

## 11. 실패 지점과 재시도

| 실패 위치 | 남는 상태 | 재시도 기준 |
| --- | --- | --- |
| Pi capture 중단 | local hidden `.partial` | 업로드하지 않고 새 capture 시작 |
| Drive payload upload 중단 | manifest 없는 remote directory | 원본이 동일하면 재실행, 충돌 시 upload 문서의 복구 절차 사용 |
| Colab runtime 종료 | `/content` 작업 소실 가능, Drive 완료 결과는 유지 | 같은 commit과 ID를 확인하고 다시 실행 |
| Dataset build 예외 | 일반 예외는 staging 정리, 강제 종료는 `.partial` 가능 | 원인을 고친 뒤 exact partial만 정리하고 같은 ID 또는 새 version 사용 |
| CI 실패 | merge되지 않은 commit과 log | 실패 원인을 수정해 push |
| Pi deploy 검증 실패 | SHA release directory가 남을 수 있으나 `current`는 전환되지 않음 | 네트워크 등 일시 실패는 같은 workflow 재실행, 코드·artifact 오류는 새 commit으로 수정 |

자동화가 성공해도 다음 단계의 입력으로 사용할지는 사람이 승인합니다. 특히 smoke 성공은 연결만, dataset verifier 성공은 구조와 provenance만, CI 성공은 코드 검증만 증명합니다.
