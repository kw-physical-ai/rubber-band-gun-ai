# Rubber Band Gun AI

라즈베리파이 카메라 영상에서 표적을 탐지하고 yaw 보정값을 예측하는 Physical AI 수업 프로젝트입니다. 네 명의 팀원이 GitHub, Google Drive, Colab, Raspberry Pi를 하나의 재현 가능한 흐름으로 사용하도록 구성합니다.

현재 저장소는 발사 없는 데이터 연결과 yaw 수집 기반을 제공합니다. 자동 발사 코드는 포함하지 않으며, 하드웨어 보정 전에는 모터도 움직이지 않습니다.

## 전체 흐름

```text
Raspberry Pi
  └─ camera + 사람이 정렬한 yaw 명령값
       ↓ 검증된 capture bundle
Google Drive / pi-upload/raw
       ↓ Colab에서 무결성 확인 및 capture 단위 분할
baseline 평가
       ├─ 통과: 기존 모델 + 보정값 유지
       ├─ YOLO만 실패: 표적 탐지 데이터 보강 및 YOLO 재학습
       └─ yaw만 실패: yaw capture 보강 및 CNN 재학습
       ↓
Drive / runs + model candidate PR
       ↓ 팀 리뷰와 GitHub Actions
승격된 모델과 코드의 Raspberry Pi evaluation release
```

원칙은 “먼저 기존 모델을 독립 데이터로 평가하고, 실패한 부분만 재학습”입니다. 수집한 데이터를 곧바로 학습에 넣지 않으며, 명중 여부는 하드웨어 완성 후 별도의 실제 시험으로 검증합니다.

## 현재 구현 상태

| 영역 | 상태 | 제공 기능 |
| --- | --- | --- |
| GitHub/Colab 연결 | 준비됨 | 비공개 저장소 다운로드, 의존성 설치, Drive mount, 런타임 기록 |
| Pi → Drive → Colab | 검증됨 | 카메라 smoke bundle 생성·업로드·해시 검증 |
| yaw 데이터 수집 | 코드 준비·실기 미검증 | 공통 전처리, 보정 설정, 발사 없는 yaw/pitch 수집, bundle 검증 |
| 데이터 계약 | 준비됨 | capture manifest, CSV, 전처리 버전, 향후 shot result 형식 |
| CI | 준비됨 | Ruff, CPU 테스트, 노트북 구조 검증 |
| 학습 데이터셋 생성 | 미구현 | capture 단위 split과 dataset manifest 코드가 다음 단계 |
| 기존 모델 baseline 평가 | 미구현 | actuator-free YOLO/CNN 평가 코드가 다음 단계 |
| 재학습 | 미구현 | baseline 결과에 따라 YOLO 또는 yaw CNN만 구현 |
| Pi 추론/실제 발사 평가 | 미구현 | 하드웨어와 안전 절차 완성 후 진행 |

강의 자료의 모델과 노트북은 참고 자료이며 현재 프로젝트의 검증된 결과물이 아닙니다. 특히 강의 수집·학습·추론 코드의 카메라 crop 방식이 서로 달라 그대로 배포하지 않습니다.

## 팀원이 시작하는 방법

### 1. 저장소 작업

```bash
git clone git@github.com:kw-physical-ai/rubber-band-gun-ai.git
cd rubber-band-gun-ai
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
python scripts/check-notebooks.py
```

각 팀원은 짧은 branch에서 작업하고 `main`으로 pull request를 엽니다. `python` CI가 성공한 뒤 누구든 리뷰하고 merge할 수 있습니다. 개인 토큰, SSH 키, Pi 주소, 로컬 설정, 원본 데이터는 커밋하지 않습니다.

### 2. Colab 확인

[![Open environment check in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/kw-physical-ai/rubber-band-gun-ai/blob/main/notebooks/00_environment_check.ipynb)

비공개 저장소이므로 각 팀원이 자신의 repository-scoped `GITHUB_TOKEN`을 Colab Secret에 등록합니다. 토큰을 공유하거나 셀에 직접 적지 않습니다. 자세한 절차는 [GitHub·Colab·Pi 연결](docs/github-colab-pi.md)을 따릅니다.

### 3. Pi 작업

- 연결만 검사: [Pi → Drive → Colab smoke test](docs/data-flow-smoke-test.md)
- Drive 최초 설정: [Pi direct Drive upload](docs/pi-drive-upload.md)
- 카메라 preview와 yaw 수집: [Yaw data collection](docs/yaw-data-collection.md)

표적과 하드웨어가 준비되지 않았다면 preview-only까지만 실행합니다. `configs/pi.toml`에 실제 한계값과 조준 기준을 기록하고 `calibrated=true`로 바꾸기 전에는 motion mode가 거부됩니다.

## 데이터와 학습 원칙

- `pi-upload/raw/`: Pi만 쓰는 원본 capture ingress. 완료된 bundle은 수정하지 않습니다.
- `processed/`: 검증된 capture를 특정 dataset version으로 조합한 결과입니다.
- `runs/`: 학습 설정, 지표, 로그, checkpoint와 run manifest를 저장합니다.
- `models/`: 팀이 승인한 최종 모델과 manifest만 Git LFS로 저장합니다.
- train/validation/locked-test는 개별 이미지가 아니라 capture ID 단위로 분리합니다.
- baseline 진단과 모델·threshold 선택에는 validation만 사용하고, locked test는 최종 후보를 고정한 뒤 한 번만 엽니다.
- `diagnostic` 프레임과 실제 shot 결과는 명시적으로 승격하기 전까지 학습 데이터가 아닙니다.

전체 협업·학습·모델 승격 절차는 [프로젝트 워크플로](docs/project-workflow.md), 파일 형식은 [데이터 계약](docs/data-contract.md)에 설명되어 있습니다.

## 저장소 구조

```text
configs/        커밋 가능한 예제 설정만 저장
docs/           팀 운영, 데이터, Pi/Drive 절차
models/         검증 후 승격된 Git LFS 모델과 manifest
notebooks/      Colab 진입점과 향후 학습 노트북
requirements/   공통·Colab·Pi 의존성
scripts/        검증, 배포, Pi 실행 도구
src/            수집·전처리·검증 공용 Python 패키지
tests/          하드웨어 없는 자동 테스트
```

`physical-ai/`, `configs/pi.toml`, `data/`, `captures/`, `runs/`는 로컬 또는 외부 저장소 전용이며 Git에서 제외됩니다.

## 다음 구현 순서

1. 표적이 준비되면 actuator-free baseline 진단용 capture와 아직 열지 않을 locked-test capture를 분리해 만든다.
2. capture 검증과 dataset manifest/split 생성을 Colab 코드로 구현한다.
3. 기존 YOLO와 yaw CNN을 각각 평가한다.
4. 실패 원인에 따라 보정, yaw CNN 재학습, YOLO 재학습 중 하나만 선택한다.
5. 승인된 모델 manifest와 recorded-frame 평가를 거쳐 Pi evaluation release를 만든다.

상세한 장기 계획과 안전 경계는 [development setup plan](docs/setup-plan.md)에 있습니다.
