# 젯슨 이식 인수인계 (M9)

이 문서는 **젯슨 Orin Nano 위에서 작업하는 사람/에이전트**를 위한 것이다.
노트북 쪽에서 여기까지 만들어 두었고, 젯슨에서 이어서 해야 할 일을 적는다.

읽는 순서: 이 문서 → `edge/README.md` → `CLAUDE.md` 절대규칙.
`docs/` 명세서 전체를 읽지 마라. 필요한 절만 본다.

---

## 0. 먼저 알아야 할 것

**엣지는 판단하지 않는다.** 규칙에 걸리면 후보(candidate)만 서버로 올리고,
확정·경고·시정판정은 전부 서버가 한다(CLAUDE.md 절대규칙 3). 젯슨에서 이벤트를
만들거나 임계값으로 무언가를 결정하는 코드를 추가하지 마라.

**엣지는 서버로 밀어 넣는다. 젯슨에 FastAPI 를 올리지 않는다.**
젯슨은 서버의 `/ws/edge` 에 붙는 **WebSocket 클라이언트**다(`edge/client.py`).
서버가 젯슨에서 값을 가져가는 pull 구조가 아니다. 이미 양쪽 다 구현돼 있으므로
새로 만들 것이 없다 — 바꾸는 것은 주소뿐이다.

**영상은 중계하지 않는다.** 젯슨은 서브 스트림(640×360)만 받아 추론하고
**메타데이터만** 올린다. 라이브 화면과 녹화는 서버가 메인 스트림(1920×1080)으로
따로 처리한다. 젯슨이 멈춰도 관제 화면은 살아 있어야 한다.

**시스템 시계를 직접 읽지 않는다.** `aegis_vision.clock.Clock` 을 주입받는다.
시계를 직접 부르는 곳은 레포 전체에서 `clock.py` 하나뿐이고, 훅이 이것을 강제한다
(절대규칙 1). 테스트가 3초·10초·15초·30초·300초 타이머를 순간이동시켜야 하므로
이 규칙이 깨지면 검증 자체가 불가능해진다.

**임계값을 코드나 `config.yaml` 에 넣지 마라.** 판정 임계는 서버 DB `policies` 에
있고 엣지가 30초마다 `GET /policies` 로 읽는다. `config.yaml` 에는 **모델 경로와
하드웨어 설정만** 둔다(절대규칙 6).

---

## 1. 노트북에서 이미 끝난 것

| 항목 | 위치 | 상태 |
|---|---|---|
| 추론 파이프라인 (감지·추적·분류·게이지·후보) | `edge/` 전체 | 노트북 CPU 에서 **동작 확인됨** |
| 서버 연동 (WebSocket · 정책/구역/캘리브레이션 조회) | `edge/client.py` | 동작 확인됨 |
| TensorRT 백엔드 | `edge/session.py` `_TensorRTBackend` | **작성만 됨 · 미검증** |
| NVDEC 디코드 | `edge/main.py` `_gstreamer_pipeline` | **작성만 됨 · 미검증** |
| 엔진 빌드 스크립트 | `scripts/build_engines.py` | **작성만 됨 · 미검증** |

★ 아래 세 개는 젯슨 하드웨어가 없어 **한 번도 실행된 적이 없다.** 노트북의
`uv run tasks.py verify` 가 통과한 것은 백엔드 분기와 설정 처리까지이고, CUDA
메모리 관리나 `execute_async_v3` 호출이 맞는지는 **젯슨에서 처음 확인된다.**
통과했다고 동작한다고 읽지 마라.

---

## 2. 지금 가장 먼저 풀어야 할 문제 — 파이썬 버전

이 레포는 `requires-python = ">=3.13"` 이다. JetPack 6 는 Ubuntu 22.04 ·
Python 3.10 이다. 그리고 **젯슨의 `tensorrt` 파이썬 바인딩은 apt 로 깔리는
시스템 파이썬에 묶여 있다** — PyPI 에 aarch64 젯슨용 휠이 없다.

uv 로 3.13 을 따로 깔면 `import tensorrt` 가 되지 않는다. 이것부터 정해야 나머지가
의미가 있다.

**선택지 A — 엣지만 시스템 파이썬에 맞춘다 (권장)**
`edge/pyproject.toml` 의 `requires-python` 을 낮추고 apt 의 tensorrt 를 쓴다.
엣지는 `package = false` 이고 의존성이 7개뿐이라 현실적이다. 서버·프론트와
파이썬 버전이 갈리지만 어차피 다른 기계다.
할 일: 3.13 전용 문법을 쓰는지 확인하고 걷어낸다.

**선택지 B — NVIDIA L4T 컨테이너**
파이썬과 TensorRT 가 맞춰진 이미지를 쓴다. 버전 충돌은 사라지지만 카메라·네트워크
설정이 한 겹 늘어난다.

어느 쪽이든 **결정한 뒤에** 3장으로 간다.

---

## 3. 환경 확인

```bash
cat /etc/nv_tegra_release
```

```bash
python3 --version
```

```bash
python3 -c "import tensorrt; print(tensorrt.__version__)"
```

```bash
sudo nvpmodel -q
```

```bash
python3 -c "import cv2; print(cv2.getBuildInformation())" | grep -i gstreamer
```

마지막 명령이 중요하다. **`GStreamer: YES` 가 나와야 NVDEC 가 된다.**
PyPI 의 `opencv-python-headless` 는 GStreamer 없이 빌드돼 있어서 그것을 깔면
NVDEC 경로가 열리지 않는다. 젯슨에서는 **JetPack 이 딸려 주는 OpenCV** 를 써야 한다.
`edge/main.py` 의 `_require_gstreamer()` 가 이 상황을 잡아 에러로 알린다 —
조용히 CPU 디코딩으로 되돌아가지 않는다.

전원 모드는 최대로 올린다. 안 그러면 처리율 실측이 의미가 없다.

```bash
sudo nvpmodel -m 0
```

```bash
sudo jetson_clocks
```

---

## 4. 카메라가 아직 없다 — 노트북에서 가짜 RTSP 를 받는다

**실물 카메라는 아직 도착하지 않았다.** 그동안 젯슨은 **노트북이 송출하는 가짜
RTSP** 를 본다. 관제 화면도 지금처럼 노트북에서 띄운다.

```
노트북                                   젯슨
  mediamtx (:8554)  ──── RTSP sub ───▶  edge (추론)
  서버 (:8000)      ◀─── /ws/edge ────  edge (후보 업로드)
  프론트 (:5173)
```

노트북에서:

```bash
uv run tasks.py cams --source media/lego_sample_1.mp4
```

젯슨의 `edge/config.yaml` 에서 주소 **세 군데**를 노트북 LAN IP 로 바꾼다.
`127.0.0.1` 로 두면 젯슨 자기 자신을 가리켜 아무것도 안 온다.

```yaml
streams:
  - cam_id: 1
    rtsp_sub: rtsp://<노트북IP>:8554/cam1/sub    # 127.0.0.1 아님

server:
  ws_url:   ws://<노트북IP>:8000/ws/edge
  rest_url: http://<노트북IP>:8000/api/v1
```

노트북 서버도 외부에서 닿게 띄워야 한다. 지금은 `--host 127.0.0.1` 이라 젯슨에서
접속되지 않는다.

```bash
uv run uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```

방화벽에서 8000 · 8554 를 열어야 할 수 있다. 먼저 젯슨에서 이것부터 확인해라 —
이게 안 되면 뒤의 어떤 것도 서버에 올라가지 않는다.

```bash
curl http://<노트북IP>:8000/api/v1/system/status
```

실물 카메라가 오면 `rtsp_sub` 만 실제 카메라 주소로 바꾼다(예:
`rtsp://192.168.0.10:554/Streaming/Channels/102`). **서브 스트림은 640×360(16:9)**
이어야 한다 — 메인 1920×1080 과 화면비가 같아야 정규화 좌표가 대응된다.
640×640 같은 정사각 설정은 쓰지 않는다. 로더가 막는다.

---

## 5. 엔진 빌드

ONNX 3개를 젯슨으로 복사한 뒤(`models/weights/` — git 제외라 직접 날라야 한다):

```bash
uv run python -m scripts.build_engines --list
```

```bash
uv run python -m scripts.build_engines
```

`trtexec --fp16` 으로 빌드하고, 같은 자리에 **클래스 이름 사이드카**를 남긴다.

★ **사이드카가 왜 필요한가.** `trtexec` 로 만든 엔진은 ONNX 의 `names` 메타데이터를
물고 가지 않는다. 그대로 두면 `Session.class_names()` 가 빈 표를 돌려주고 감지가
0건이 된다. 스크립트가 `<이름>.names.json` 을 함께 쓰므로 **엔진만 따로 복사하지
마라.** 사이드카가 없으면 로그에 「클래스 이름을 찾지 못했다」가 뜬다 —
인덱스로 때우지 않는다(절대규칙 9).

★ **엔진은 빌드한 GPU · TensorRT 버전에 종속된다.** 노트북에서 만들 수 없고,
JetPack 을 올리면 다시 빌드해야 한다.

★ **FP16 을 쓴다.** INT8 은 0.8ms 빠른 대신 mAP 가 0.480 → 0.449 로 떨어진다.
속도 여유가 있으므로 정확도를 택한다(기능명세서 §3). 실측에서 부족할 때만 검토.

---

## 6. 설정 전환

```yaml
runtime:
  backend: tensorrt          # onnx → tensorrt

decode:
  backend: nvdec             # cpu → nvdec
  target_fps: 8
```

`runtime.providers` 와 `intra_op_threads` 는 onnxruntime 전용이라 TensorRT 에서는
무시된다. 남겨 두어도 되고, 노트북으로 되돌릴 때 필요하다.

모르는 값을 넣으면 **조용히 넘어가지 않고 죽는다** — `backend: tensorRT` 같은
대소문자 오타로 CPU 추론을 돌면 처리율이 안 나오는 이유를 한참 찾게 되기 때문이다.

---

## 7. 실행과 확인

```bash
uv run tasks.py edge --cam 1
```

확인할 것을 순서대로 적는다. 앞의 것이 안 되면 뒤는 볼 필요 없다.

1. **스트림이 붙는가** — 로그에 `스트림 연결 — rtsp://...`
2. **서버에 붙는가** — 로그에 `서버 연결 — ws://...`
3. **모델이 열리는가** — 감지·분류 모델의 클래스 표가 로그에 찍힌다.
   `['toy_truck', 'toy_person']` 처럼 나와야 한다. 비어 있으면 사이드카 문제다
4. **거부 메시지가 0인가** — `GET /system/status` 의 `edge.msg_rejected_total`.
   0이 아니면 스키마가 어긋난 것이다. 서버 로그에 원본 페이로드가 남는다(FN-SYS-06)
5. **처리율** — 같은 응답의 `cameras[].fps`. **목표는 카메라당 8fps 이상**이다.
   노트북에서는 0.2~1.2fps 였다(CPU). 젯슨에서 8 이 안 나오면 그때 파고든다
6. **확정 이벤트가 나오는가** — 8fps 가 나오면 3초 확정을 채울 수 있다.
   `GET /api/v1/events` 에 `confirmed` 가 뜨고, 그래야 시정률 숫자가 처음 나온다

노트북에서는 처리율이 낮아 이벤트가 전부 `dropped`(확정 전 트랙 소실)였다.
**젯슨에서 이것이 풀리는지가 이번 이식의 핵심이다.**

---

## 8. 8fps 가 나온 다음에 할 일

처리율이 올라가면 노트북 제약에 맞춰 두었던 것들이 맞지 않게 된다.
`edge/README.md` 「M9 에서 손봐야 할 것」에 적혀 있고, 요약하면:

- **추적기에 칼만 필터가 없다.** `track.py` 는 ByteTrack 의 2단계 연결은 구현하지만
  위치 예측이 등속 근사다. 노트북 2~3fps 에서는 프레임 간격이 예측 정밀도보다
  지배적이라 문제가 안 됐다. 8fps 이상이면 ultralytics 의 ByteTrack 으로 교체하는
  것이 맞다
- **`track.buffer_frames` 는 프레임 수다.** 처리율이 바뀌면 같은 **시간**이 되도록
  다시 잡아야 한다 (노트북 2~3fps 에서 8프레임 ≈ 3초)
- **시계 오차를 측정하지 않는다.** `heartbeat.clock.synced` 를 `false` 로 보낸다.
  측정하지 않은 값을 0으로 보고하면 동기화된 적 없는 엣지가 완벽해 보인다.
  젯슨에서 NTP 를 맞추고 실제 오차를 실어야 한다(§2.4)
- **뎁스 모델이 꺼져 있다.** `config.yaml` 의 `depth.onnx` 가 주석 처리돼 있다.
  노트북에서 프레임당 875ms 가 붙어 확정에 도달하지 못했기 때문이다. 젯슨에서는
  GPU 가 맡으므로 켜고 실측한다. 켜면 `depth_verified` 가 살아난다(FN-DET-11)

---

## 9. 하지 말아야 할 것

- **`uv run tasks.py verify` 를 건너뛰지 마라.** 명령을 못 찾아 건너뛴 것을 통과로
  간주하지 않는다. 실행할 수 없으면 통과가 아니라 오류다(절대규칙 9)
- **`docs/` 의 명세서 3종을 직접 고치지 마라.** 훅(`scripts/hooks/protect_specs.py`)이
  막는다. 고쳐야 한다고 판단되면 코드보다 사람에게 먼저 보고한다(절대규칙 8).
  `docs/INDEX.md` 는 진척표라 자유롭게 갱신한다
- **최상위 디렉토리를 새로 만들지 마라**(절대규칙 7)
- **`git push` 하지 마라.** 푸시는 사람이 한다
- **`models/` · `media/` · `.env` 를 커밋하지 마라**
- **제로샷/오픈보캐블러리 감지를 쓰지 마라.** 클래스는 `person` · `vehicle` 2종
  고정이다. 가중치가 YOLOE 계열이어도 `set_classes()` 를 부르지 않는다(절대규칙 11)

---

## 10. 막혔을 때 볼 곳

| 증상 | 먼저 볼 것 |
|---|---|
| 엔진이 안 열린다 (`deserialize_cuda_engine` 이 None) | 다른 GPU/TRT 버전에서 빌드한 엔진이다. 젯슨에서 다시 빌드 |
| 클래스 표가 비어 있다 | 사이드카 `<이름>.names.json` 이 엔진 옆에 있는가 |
| NVDEC 가 안 열린다 | OpenCV 에 GStreamer 지원이 있는가 (3장 마지막 명령) |
| 서버에 아무것도 안 올라간다 | `curl` 로 `/api/v1/system/status` 부터. 방화벽·`--host 0.0.0.0` |
| 거부 메시지가 쌓인다 | 서버 로그에 원본 페이로드가 남는다. 스키마는 `packages/contracts` 가 원천 |
| 좌표가 영상보다 뒤처진다 | 최신 프레임만 쓰는가 (`_LatestFrame` · 파이프라인 `drop=true`) |
| 거리 수치가 이상하다 | 캘리브레이션 단위. **미니어처 시연은 cm 다**(기능명세서 §4.7 FN-CFG-01) |
