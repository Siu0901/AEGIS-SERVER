# 젯슨 패치 — 진단용 마스크 윤곽 (`overlay_mask`)

젯슨에서 `git pull` 을 할 수 없는 상황을 전제로, **손으로 적용할 수 있게** 정리한 문서다.
pull 이 가능해지면 이 문서는 버리고 그냥 pull 하면 된다.

---

## 0. 먼저 — 이건 선택이 아니다

**서버를 새 코드로 올리면, 이 패치를 적용하지 않은 젯슨은 죽는다.**

계약 모델의 베이스가 `extra="forbid"` 다.

```python
# packages/contracts/src/aegis_contracts/_base.py
model_config = ConfigDict(extra="forbid")
```

> `extra="forbid"` 는 의도적이다. 스키마는 `packages/contracts` 에만 정의하므로
> 명세서에 없는 필드가 실려 오면 그것은 계약 위반이며 조용히 통과시키면 안 된다.

엣지는 30초마다 `GET /policies` 를 읽어 `Policies.model_validate()` 로 검증한다
(`edge/client.py`). 서버가 새로 추가된 `overlay_mask` 를 응답에 싣는데 젯슨 쪽 모델에
그 필드가 없으면 **ValidationError 로 엣지가 멈춘다.**

### 배포 순서

```
① 젯슨에 이 패치 적용  →  ② 엣지 재기동  →  ③ 서버를 새 코드로 올림
```

**젯슨이 먼저다.** 반대로 하면 그 사이에 엣지가 죽는다. 젯슨을 못 만지는 동안에는
**서버도 새 코드로 올리지 마라.**

---

## 1. 무엇을 하는 기능인가

감지 모델이 seg 라 마스크가 이미 있고(`edge/detect.py`, 48점), 지금까지는 접지점·최근접
거리·자세 계산에만 쓰고 버렸다(API명세서 §2.1 — 「결과값만 전송한다」).

감지가 형태를 제대로 잡는지 **화면으로 확인할 수 없어서**, 진단용으로만 윤곽을 실어
보내는 경로를 열었다.

| | |
|---|---|
| 기본값 | `false` — 적용해도 아무 동작이 달라지지 않는다 |
| 켜는 곳 | **서버.** 엣지가 정책을 주기적으로 읽으므로 젯슨 재기동이 필요 없다 |
| 전송 점수 | 내부 48점 중 **24점**으로 균등 솎기 |
| 판정 영향 | **없다.** 거리·자세 계산은 48점 원본을 그대로 쓴다 |

```bash
# 켜기 (서버에서)
curl -X PATCH http://<서버>:8000/api/v1/policies \
  -H 'content-type: application/json' -d '{"overlay_mask": true}'
```

★ **상시로 켜두는 값이 아니다.** 객체당 좌표 24쌍이 매 프레임 더 나간다 — 카메라 2대에
객체 5개면 초당 수천 개다. 확인이 끝나면 되돌린다.

---

## 2. 고칠 파일 넷

젯슨에서 필요한 것만 추렸다. `ws.py`·서버·프론트 변경은 젯슨과 무관하다.

| 파일 | 무엇 |
|---|---|
| `packages/contracts/src/aegis_contracts/_base.py` | `Contour` 타입 추가 |
| `packages/contracts/src/aegis_contracts/policies.py` | `overlay_mask` 필드 (**이것이 없으면 엣지가 죽는다**) |
| `packages/contracts/src/aegis_contracts/edge.py` | `DetectedPerson`·`DetectedVehicle` 에 `contour` |
| `edge/pipeline.py` | 정책이 켜졌을 때만 24점으로 솎아 싣기 |

---

## 3. 패치 적용

같이 보낸 `jetson.patch` 를 쓰면 한 번에 끝난다.

```bash
cd ~/AEGIS-SERVER
git apply --check jetson.patch    # 먼저 확인만
git apply jetson.patch
```

`--check` 에서 실패하면 로컬에 다른 수정이 있다는 뜻이다. 그때는 아래 4절을 보고
손으로 넣어라.

적용 뒤 확인:

```bash
python3 -c "
from aegis_contracts.policies import Policies
from aegis_contracts.edge import DetectedPerson
print('overlay_mask:', Policies().overlay_mask)
print('contour 필드:', 'contour' in DetectedPerson.model_fields)
"
```

```
overlay_mask: False
contour 필드: True
```

둘 다 나오면 됐다. 엣지를 다시 띄운다.

---

## 4. 손으로 넣기

### 4-1. `_base.py`

`__all__` 에 `"Contour"` 를 넣고, `PointPx` 정의 **뒤에** 추가한다.

```python
__all__ = ["Bbox", "Contour", "Homography", "PointM", "PointPx", "SpecModel"]
```

```python
PointPx = tuple[float, float]

#: 진단용 마스크 윤곽 — 정규화 픽셀 좌표의 점 목록 (API명세서 §2.1).
#:
#: ★ **판정에 쓰지 않는다.** 감지 결과를 눈으로 확인하기 위한 값이고, 거리·자세·접지점은
#:   전부 엣지가 원본 마스크로 계산해 결과값만 싣는다. 서버는 이 값을 읽지 않고 통과시킨다.
#:
#: ★ **기본은 아예 싣지 않는다.** 정책 `overlay_mask` 가 켜졌을 때만 채운다 — 점 하나가
#:   좌표 두 개이므로 켜두면 오버레이 메시지가 몇 배로 커진다.
Contour = list[PointPx]
```

### 4-2. `policies.py` — 이것이 핵심이다

`class Policies` 안, `# --- 오버레이 시간 정합 (FN-UI-02) ---` 주석 **앞에** 넣는다.

```python
    # --- 진단 표시 ---
    overlay_mask: bool = False
    """마스크 윤곽(`contour`)을 `frame`·`overlay` 에 싣는다(API명세서 §2.1 · §4.5).

    ★ **기본은 꺼짐이다.** 켜면 객체마다 좌표 24쌍이 매 프레임 더 나간다.

    ★ **판정에는 쓰이지 않는다.** 이 값이 켜지든 꺼지든 확정·해소·거리 판정은 동일하다.
      엣지가 정책을 주기적으로 읽으므로 **엣지를 재시작하지 않고** 토글된다.
    """
```

그리고 아래쪽 `class PolicyPatch` 안 `overlay_buffer_webrtc_ms` 줄 **앞에**:

```python
    overlay_mask: bool | None = None
```

### 4-3. `edge.py`

임포트 줄에 `Contour` 를 넣는다.

```python
from ._base import Bbox, Contour, PointM, PointPx, SpecModel
```

`class DetectedPerson` 의 마지막 필드(`nearby: list[FrameNearby]`) 뒤, 그리고
`class DetectedVehicle` 의 마지막 필드(`danger_radius_m: float`) 뒤에 **각각** 넣는다.

```python
    contour: Contour | None = None
    """진단용 마스크 윤곽 (API명세서 §2.1). 정책 `overlay_mask` 가 켜졌을 때만 채운다.

    ★ **판정에 쓰지 않는다.** 없으면 필드를 생략한다 — `null` 을 싣지 않는다.
    """
```

### 4-4. `edge/pipeline.py`

**파일 맨 끝**에 헬퍼를 추가한다.

```python
#: 진단용으로 내보낼 윤곽 점 수 (API명세서 §2.1).
#:
#: 내부 계산은 48점(`edge/detect._MAX_CONTOUR_POINTS`)을 쓰지만 화면에 그릴 때는 그 절반이면
#: 형태가 충분히 드러난다. **점 하나가 좌표 두 개**라 매 프레임·매 객체마다 나가는 양이고,
#: 이 값을 그대로 두면 오버레이 메시지가 몇 배가 된다.
#:
#: ★ **내부 계산에 쓰는 윤곽을 줄이지 않는다.** 여기서 솎는 것은 전송용 사본뿐이다 —
#:   `nearest_pair_m`·PCA 주축은 48점 그대로 본다.
_CONTOUR_SEND_POINTS = 24


def _contour_for_send(contour: tuple[PointPx, ...]) -> list[list[float]] | None:
    """전송용 윤곽. 균등 솎기로 24점까지 줄이고 소수점 3자리로 자른다.

    `approxPolyDP` 로 꼭짓점만 남기지 않는 이유는 `edge/detect.py` 와 같다 — 꼭짓점만
    남기면 형태가 각져 사람으로 보이지 않는다. 균등 간격이 화면에서도 자연스럽다.
    """
    if not contour:
        return None
    points = list(contour)
    if len(points) > _CONTOUR_SEND_POINTS:
        step = len(points) / _CONTOUR_SEND_POINTS
        points = [points[int(index * step)] for index in range(_CONTOUR_SEND_POINTS)]
    return [[round(float(x), 3), round(float(y), 3)] for x, y in points]
```

**차량** — `DetectedVehicle.model_validate({...})` 안, `"danger_radius_m"` 줄 뒤:

```python
                    "danger_radius_m": self._danger_radius_m,
                    # 진단용. 정책이 꺼져 있으면 **키 자체를 넣지 않는다**(§2.1).
                    **(
                        {"contour": _contour_for_send(detection.contour)}
                        if self._policies.overlay_mask
                        else {}
                    ),
```

**사람** — `if helmet is not None:` 줄 **바로 앞**:

```python
            if self._policies.overlay_mask:
                # 진단용 윤곽(§2.1). 정책이 꺼져 있으면 **키 자체를 넣지 않는다** —
                # `null` 을 실으면 "마스크를 못 만들었다"로 읽히는데 그건 다른 뜻이다.
                body["contour"] = _contour_for_send(detection.contour)
            if helmet is not None:
```

---

## 5. 확인

엣지를 띄우고 서버에서 정책을 켠 다음, 관제 화면에서 박스 안에 실루엣이 그려지면 된다.

```bash
# 서버에서 — 브로커 대신 대시보드 WS 를 직접 들여다봐도 된다
curl -X PATCH http://<서버>:8000/api/v1/policies \
  -H 'content-type: application/json' -d '{"overlay_mask": true}'
```

30초 안에 반영된다(엣지의 정책 폴링 주기). 되돌릴 때는 `false` 로 같은 요청을 보낸다.

---

## 6. 같이 확인해 줬으면 하는 것 — `buffer_frames`

패치와 무관하지만 지금 값이 위험해 보인다.

```yaml
# edge/config.yaml
track:
  buffer_frames: 34
```

**이 값은 초가 아니라 프레임 수다**(`edge/track.py` 의 `state.misses` 가 프레임마다 오른다).
그래서 처리율이 바뀌면 뜻하는 시간이 같이 바뀐다.

`confirm_duration_s` 가 3초이므로 **이 값이 3초보다 짧으면 확정에 도달할 수 없다.**
감지가 잠깐만 끊겨도 트랙이 죽고, 다시 잡히면 새 번호를 받아 이벤트가 처음부터 시작한다.

| 실측 처리율 | 3초에 해당하는 값 |
|---|---|
| 10 fps | 30 |
| 15 fps | 45 |
| **30 fps** | **90** |

노트북에서 이 값이 어긋났을 때 실측으로 **이벤트 96건 중 확정 1건**, 정지된 장면인데
9분 만에 트랙 ID 가 500번대까지 올라갔다. 젯슨 실측 fps 를 확인하고 다시 잡아 달라.

---

*원본: `docs/AEGIS_API명세서.md` §2.1 · §4.5 · §5.1 · 참고: `edge/JETSON.md` §8*
