# server/infra/clip

이벤트 클립 · 키프레임 추출(FN-REC-03). **클립은 확정 즉시가 아니라 `confirmed_at + clip_post_roll_s + margin` 시점에 예약 실행**한다. M3에서 작업한다.
