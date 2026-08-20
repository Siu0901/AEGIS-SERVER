# ESP32 경고 장치 인수인계

경광등·부저를 제어하는 ESP32 펌웨어를 만드는 사람을 위한 문서다.

**이 문서는 원본이 아니다.** 규격의 원천은 `docs/AEGIS_API명세서.md` §3 이고,
페이로드 스키마는 `packages/contracts/src/aegis_contracts/mqtt.py` 다. 둘과 어긋나면
그쪽이 맞다. 여기서는 펌웨어를 짜는 데 필요한 것만 모아 다시 적는다.

**서버 쪽은 이미 다 되어 있다**(`docs/INDEX.md` FN-ALM-02 ✅). 지금은
`sim/mcu_sim/` 이 그 자리에 붙어 있고, **실물 ESP32 는 그것을 그대로 대체한다** —
서버 입장에서 둘은 구분되지 않는다. 동작을 확인하고 싶으면 시뮬레이터를 켜서
서버가 무엇을 보내는지 먼저 보면 된다.

```bash
uv run tasks.py mcu
```

---

## 0. 한눈에

```
                    aegis/alert  (QoS 1)
   서버  ──────────────────────────────▶  ESP32   경광등 + 부저
         ◀──────────────────────────────
                aegis/device/status  (10초 주기)
```

| | |
|---|---|
| 브로커 | Mosquitto · 서버와 같은 기계 |
| 포트 | **1883** (MQTT) · 9001 (WebSocket, 브라우저용이라 ESP32 는 안 쓴다) |
| 인증 | 없음 (`allow_anonymous true`) — 현장 내부망 전용 |
| 구독할 토픽 | `aegis/alert` |
| 발행할 토픽 | `aegis/device/status` |

---

## 1. 받는 것 — `aegis/alert`

서버가 경고를 발동할 때 발행한다. **QoS 1** 이다.

```json
{
  "event_id": "EV-20260814-0231",
  "type": "no_helmet",
  "level": 2,
  "zone_id": "forklift_lane",
  "duration_s": 5,
  "repeat": false
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `event_id` | string | 자동 경고는 `EV-YYYYMMDD-NNNN`, 수동 방송은 `MANUAL-cam{N}-{ISO8601}`. **중복 수신 판별에 쓴다** |
| `type` | string | **점멸 패턴 선택자.** `no_helmet` / `zone_intrusion` / `proximity` / `fall` / `manual` |
| `level` | int | **`1` · `2` · `3` 만 온다.** 1=주의(부저 없음) · 2=경고 · 3=긴급(연속 부저) |
| `zone_id` | string·null | 구역 ID. 없으면 `null`. 표시용이며 패턴에 쓰지 않아도 된다 |
| `duration_s` | int | 경광등·부저를 켜 둘 시간(초). 기본 5 |
| `repeat` | bool | 재경고. `true` 면 **패턴을 달리해** 상습 상황을 구분한다 |

### 반드시 지킬 것 넷

**① `level` 3 은 반드시 연속 부저다.**
`fall`(쓰러짐)은 서버가 등급 3 미만으로 내리는 것을 API 단에서 거부한다. 대상자가
스스로 시정할 수 없는 유일한 유형이라서다. 펌웨어에서도 3을 부저 없이 처리하면 안 된다.

**② `type` 을 모르면 무시하지 말고 기본 패턴으로 켠다.**
위반 유형이 나중에 늘어날 수 있다. 모르는 값이 왔다고 조용히 넘기면 **경고가 사라진다.**
`level` 은 항상 유효하므로 그것으로 켜라.

**③ `manual` 은 일반 주의 환기 패턴이다.**
수동 방송에는 위반 유형이 없어서 쓰는 값이다. **다른 위반 유형의 패턴을 빌려 쓰지 마라** —
실제 위반이 감지된 것처럼 보인다.

**④ 같은 `event_id` 가 두 번 와도 문제없게 만든다.**
QoS 1 이라 중복 수신이 가능하다. 서버 주석에 이유가 적혀 있다:

> 경고가 한 번 더 울리는 것(중복 수신)보다 **울리지 않는 것**이 나쁘다

같은 `event_id` 면 **패턴을 처음부터 다시 시작하지 말고 이어서 켜라.** 새로 시작하면
중복 수신 때마다 경고가 끊겼다 켜진다.

### `type` 별 패턴 (제안)

패턴 자체는 명세가 정하지 않는다. 아래는 시작점이고, 현장에서 조정해도 된다.
**구분이 되는 것**이 목적이다 — 관리자가 소리만 듣고 무엇이 일어났는지 알아야 한다.

| `type` | 기본 `level` | 제안 패턴 |
|---|---|---|
| `fall` | **3** | 적색 연속 점등 + **연속 부저** |
| `proximity` | 2 | 적색 빠른 점멸(200ms) + 단속 부저 |
| `zone_intrusion` | 2 | 황색 점멸(500ms) + 단속 부저 |
| `no_helmet` | 2 | 황색 느린 점멸(1s) + 짧은 부저 1회 |
| `manual` | 2 | 백색/황색 느린 점멸, 부저 없음 |
| (모르는 값) | 온 대로 | `level` 기준 기본 패턴 |

`repeat: true` 면 위 패턴에 **점멸 속도를 올리거나 부저를 한 번 더** 넣는 식으로 구분한다.

---

## 2. 보내는 것 — `aegis/device/status`

**10초 주기**로 발행한다.

```json
{
  "device": "esp32-01",
  "online": true,
  "uptime_s": 84210,
  "last_alert": "2026-08-14T05:37:03Z"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `device` | string | 장치 ID. 여러 대면 서로 달라야 한다 |
| `online` | bool | 항상 `true` (살아 있으니 보내는 것이다) |
| `uptime_s` | int | 부팅 후 경과 초 |
| `last_alert` | string·null | 마지막으로 경고를 울린 시각. **ISO 8601 UTC**. 없으면 `null` |

### 주기를 바꾸면 서버도 바꿔야 한다

서버는 **30초** 동안 상태 보고가 없으면 오프라인으로 본다
(`DEFAULT_MCU_STALE_AFTER_S`, 10초 주기의 3회 연속 누락). 발행 주기를 바꾸려면
서버 설정 `mcu_stale_after_s` 도 함께 바꿔야 한다. 알려주면 맞춰 준다.

### `last_alert` 의 시각

ESP32 에 RTC 가 없으면 정확한 벽시계를 모른다. 두 가지 중 하나로 하면 된다.

- **NTP 로 시각을 맞춘다** (권장). 서버도 NTP 로 맞추고 있어 정합이 된다
- 못 맞추겠으면 **`null` 을 보낸다.** 틀린 시각을 보내지 마라 — 서버는 그 값을
  「마지막 경고 시각」으로 화면에 띄운다

---

## 3. 연결 관리

**재연결은 펌웨어가 책임진다.** 서버는 ESP32 를 찾아 나서지 않는다.

- 브로커 연결이 끊기면 **지수 백오프로 재시도**한다 (1s → 2s → 4s … 상한 30s 정도)
- 재연결되면 `aegis/alert` 을 **다시 구독**한다. 구독은 세션과 함께 사라진다
- `clean_session` 은 `true` 로 둬도 된다. 끊긴 동안의 경고를 나중에 몰아서 울리는 것은
  오히려 위험하다 — **지난 경고를 뒤늦게 울리지 마라**

### LWT (Last Will) — 넣어주면 좋다

브로커에 연결할 때 유언을 등록해 두면, 전원이 나가도 서버가 즉시 안다.
없으면 30초 타임아웃까지 기다려야 한다.

```
토픽    aegis/device/status
페이로드 {"device":"esp32-01","online":false,"uptime_s":0,"last_alert":null}
QoS     1
retain  false
```

---

## 4. 확인 방법

서버·브로커를 띄운 상태에서 브로커를 직접 들여다보면 된다.

```bash
mosquitto_sub -h <서버IP> -t 'aegis/#' -v
```

경고를 강제로 한 번 내보내려면 관제 화면의 **수동 방송** 버튼을 쓰거나:

```bash
curl -X POST http://<서버IP>:8000/api/v1/alerts/manual \
  -H 'content-type: application/json' -d '{"cam_id": 1}'
```

장치가 붙었는지는 관제 화면 좌하단과 `GET /system/status` 의 `mcu` 로 확인한다.

```bash
curl -s http://<서버IP>:8000/api/v1/system/status | grep -o '"mcu":{[^}]*}'
```

---

## 5. 넘겨받을 때 확인할 것

- [ ] 브로커 IP·포트를 펌웨어에 넣었다 (**1883**)
- [ ] `aegis/alert` 구독, 재연결 시 재구독한다
- [ ] `level` 3 이 연속 부저로 동작한다
- [ ] 모르는 `type` 이 와도 `level` 기준으로 켜진다
- [ ] 같은 `event_id` 중복 수신에 패턴이 재시작되지 않는다
- [ ] `aegis/device/status` 를 10초마다 발행한다
- [ ] `last_alert` 가 정확하거나, 자신 없으면 `null` 이다
- [ ] LWT 를 등록했다

---

*원본: `docs/AEGIS_API명세서.md` §3 · `packages/contracts/mqtt.py` · 참고 구현: `sim/mcu_sim/`*
