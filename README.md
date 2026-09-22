# Rubber Band Gun AI

라즈베리파이 카메라 영상으로 표적을 탐지하고 yaw 보정값을 평가하는 Physical AI 수업 프로젝트입니다.

최종 연결 목표는 다음과 같습니다.

```text
GitHub repository -> Google Colab -> model candidate PR -> GitHub Actions -> Raspberry Pi evaluation release
```

현재 스캐폴드는 GitHub/Colab 환경 확인, CPU CI, Pi 환경 조사, 수동 evaluation 릴리스까지 제공합니다. 모델 학습·후보 PR·Pi 추론은 하드웨어 진단 후 필요한 범위만 구현합니다.

하드웨어 검증 전에는 카메라와 모델 평가만 수행합니다. 자동 배포는 모터 또는 발사 장치를 구동하지 않습니다.

Pi → Drive → Colab 데이터 연결은 [data-flow smoke test](docs/data-flow-smoke-test.md)로 확인합니다. Tailscale은 Pi 원격 접속에 사용하고, 데이터는 Pi에서 Drive로 직접 업로드합니다. 이 테스트의 이미지는 연결 검증 전용이며 학습 데이터로 사용하지 않습니다.

## Colab 시작

[![Open environment check in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/kw-physical-ai/rubber-band-gun-ai/blob/main/notebooks/00_environment_check.ipynb)

저장소가 비공개이므로 Colab에서 GitHub 접근 권한과 `GITHUB_TOKEN` Secret이 필요합니다. 자세한 과정은 [GitHub-Colab-Pi 연결 가이드](docs/github-colab-pi.md)를 따릅니다.

## 로컬 확인

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
python scripts/check-notebooks.py
```

## 디렉터리

```text
notebooks/       Colab 진입점
src/             공용 Python 패키지
tests/           하드웨어 없는 테스트
models/          검증 후 승격된 Git LFS 모델만 저장
requirements/    Colab/Pi 환경별 의존성
scripts/         Pi 조사와 배포 도구
docs/            설정·실험·의사결정 문서
```

강의 원본 자료와 로컬 데이터는 `physical-ai/`, `data/`, `runs/`에 둘 수 있지만 Git에는 포함하지 않습니다.

## 현재 게이트

1. Colab 환경 노트북을 깨끗한 런타임에서 실행한다.
2. Pi 환경 조사 결과를 기록한다.
3. 모터 없는 evaluation 모드를 구현한다.
4. 기존 YOLO/CNN 모델을 소량의 독립 진단 데이터로 평가한다.
5. 결과에 따라 기존 모델 유지, 보정 또는 선택적 재학습을 결정한다.
