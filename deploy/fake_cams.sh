#!/usr/bin/env bash
# 가짜 IP 카메라 2대를 mediamtx 로 무한 루프 송출한다.
#
#   ./deploy/fake_cams.sh                          # 컬러바 테스트 패턴
#   ./deploy/fake_cams.sh a.mp4                    # 카메라 1·2 모두 a.mp4
#   ./deploy/fake_cams.sh a.mp4 b.mp4              # 카메라별 다른 영상
#
# 카메라 1대당 ffmpeg 1개를 띄우고, 그 안에서 main/sub 두 출력을 동시에 낸다.
# 코덱·해상도·fps 는 실제 IP 카메라와 같게 맞춘다 — 여기서 어긋나면 엣지 추론
# 예산(§5)과 오버레이 정합(±100ms) 실측이 의미를 잃는다.
#
#   main  1920x1080  H.264  서버용 (라이브 · 7일 녹화 · 클립 원본)
#   sub    640x360   H.264  엣지용 (추론)
#
# Ctrl+C 로 전부 정리된다.

set -euo pipefail

RTSP_BASE="${RTSP_BASE:-rtsp://localhost:8554}"
MAIN_SIZE="${MAIN_SIZE:-1920x1080}"
SUB_SIZE="${SUB_SIZE:-640x360}"
FPS="${FPS:-15}"
MAIN_BITRATE="${MAIN_BITRATE:-4000k}"
SUB_BITRATE="${SUB_BITRATE:-600k}"

# GOP 2초. 링버퍼에서 클립을 잘라낼 때 키프레임 간격이 곧 절단 정밀도가 된다(FN-REC-03).
GOP=$(( FPS * 2 ))

command -v ffmpeg >/dev/null 2>&1 || { echo "ffmpeg 가 필요하다" >&2; exit 1; }

PIDS=()
cleanup() {
  trap - INT TERM EXIT
  echo ""
  echo "[fake_cams] 종료 중..."
  for pid in "${PIDS[@]:-}"; do
    [[ -n "${pid}" ]] && kill "${pid}" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# 입력 인자를 만든다. 파일이 주어지면 무한 루프 재생, 없으면 컬러바 + 타임코드.
input_args() {
  local cam="$1" file="${2:-}"
  if [[ -n "${file}" ]]; then
    [[ -f "${file}" ]] || { echo "영상 파일을 찾을 수 없다: ${file}" >&2; exit 1; }
    printf '%s\0' -stream_loop -1 -re -i "${file}"
  else
    # smptebars + 흐르는 타임코드. 오버레이 시간 정합을 눈으로 확인할 때 쓴다.
    printf '%s\0' -re -f lavfi -i \
      "smptebars=size=${MAIN_SIZE}:rate=${FPS},drawtext=text='CAM${cam} %{pts\\:hms}':fontcolor=white:fontsize=48:x=40:y=40"
  fi
}

publish_camera() {
  local cam="$1" file="${2:-}"
  local -a in_args=()
  mapfile -d '' -t in_args < <(input_args "${cam}" "${file}")

  echo "[fake_cams] cam${cam}  main=${RTSP_BASE}/cam${cam}/main (${MAIN_SIZE}@${FPS})  sub=${RTSP_BASE}/cam${cam}/sub (${SUB_SIZE}@${FPS})"

  ffmpeg -hide_banner -loglevel warning -nostdin \
    "${in_args[@]}" \
    -filter_complex "[0:v]split=2[main][sub];[main]scale=${MAIN_SIZE},fps=${FPS}[mainout];[sub]scale=${SUB_SIZE},fps=${FPS}[subout]" \
    -map "[mainout]" -c:v libx264 -preset veryfast -tune zerolatency -profile:v main \
      -pix_fmt yuv420p -b:v "${MAIN_BITRATE}" -g "${GOP}" -keyint_min "${GOP}" -sc_threshold 0 \
      -f rtsp -rtsp_transport tcp "${RTSP_BASE}/cam${cam}/main" \
    -map "[subout]" -c:v libx264 -preset veryfast -tune zerolatency -profile:v baseline \
      -pix_fmt yuv420p -b:v "${SUB_BITRATE}" -g "${GOP}" -keyint_min "${GOP}" -sc_threshold 0 \
      -f rtsp -rtsp_transport tcp "${RTSP_BASE}/cam${cam}/sub" &

  PIDS+=("$!")
}

CAM1_FILE="${1:-}"
CAM2_FILE="${2:-${CAM1_FILE}}"

if [[ -z "${CAM1_FILE}" ]]; then
  echo "[fake_cams] 영상 파일 인자가 없다 — 컬러바 테스트 패턴을 송출한다"
fi

publish_camera 1 "${CAM1_FILE}"
publish_camera 2 "${CAM2_FILE}"

echo "[fake_cams] 송출 중. Ctrl+C 로 종료한다."
wait
