# 마이그레이션

기능명세서 §6 데이터 모델의 스키마 이력이다.

```
uv run tasks.py migrate                                       # upgrade head + policies 시드
uv run alembic -c server/infra/db/alembic.ini upgrade head
uv run alembic -c server/infra/db/alembic.ini revision -m "설명"
```

- 접속 URL은 `alembic.ini` 가 아니라 환경변수 `AEGIS_DATABASE_URL`(`.env` 포함)에서 읽는다.
  자격증명을 레포에 커밋하지 않기 위해서다.
- **`alembic.ini` 에는 한글을 쓰지 않는다.** alembic이 OS 로캘 코덱으로 읽기 때문에
  한글 Windows(cp949)에서 UTF-8 바이트를 만나면 파싱이 깨진다. 설명은 이 파일에 적는다.
- `0001` 은 `CREATE EXTENSION IF NOT EXISTS vector` 를 먼저 실행한다.
  `events.embedding` 과 `normal_pool.embedding` 이 `halfvec(3072)` 이기 때문이다(FN-AI-01).
- `uv run tasks.py verify` 는 DB 없이 `upgrade head --sql`(오프라인 렌더링)로 정합만 확인한다.
