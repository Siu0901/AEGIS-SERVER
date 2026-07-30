"""`packages/contracts` → 프론트 TypeScript 타입 생성기.

    uv run tasks.py types            # front/src/types/contracts.ts 를 쓴다
    uv run tasks.py types --check    # 생성물이 최신인지만 본다 (verify 가 쓴다)

**왜 필요한가.** 스키마의 원본은 `packages/contracts` 하나다(CLAUDE.md 절대규칙 5).
그런데 프론트는 파이썬을 읽을 수 없어 그동안 §4.6 · §5.3 을 **손으로 옮겨** 두고 있었고,
그 사본은 계약이 바뀌어도 아무도 잡아주지 않았다. 필드 하나가 `null` 이 될 수 있게
넓어졌는데 프론트가 모르면 화면은 그 값을 그냥 그리다 깨진다.

**경로**: Pydantic 모델 → JSON Schema → TypeScript.
중간에 JSON Schema 를 두는 이유는 Pydantic 이 별칭(`class` · `from`)·nullable·기본값을
이미 해석해 주기 때문이다. 파이썬 타입 힌트를 직접 읽으면 그 해석을 다시 구현해야 한다.

**생성 대상은 계약이 내보내는 SpecModel 전량**이다. 화면이 쓰는 것만 고르지 않는다 —
고르기 시작하면 무엇이 빠졌는지 아무도 모르고, 다음 화면을 만들 때 손으로 옮기는
관행이 되살아난다.

**JSON Schema 는 `serialization` 모드로 뽑는다.** 두 모드는 **기본값이 있는 필드**에서
갈린다 — `validation` 은 "안 보내도 된다"고 보아 옵셔널로 내고, `serialization` 은
"항상 실려 나간다"고 보아 필수로 낸다.

응답 기준이 맞다. `Policies` 는 모든 필드에 기본값이 있는데 `GET /policies` 는 언제나
전량을 돌려준다. 그것을 옵셔널로 내면 프론트가 `overlay_stale_ms ?? 1000` 처럼
**값을 코드에 적어 메우게 되고**, 그게 바로 절대규칙 6 이 금지하는 것이다.

그래서 **모든 필드를 필수로 낸다.** `serialization` 모드의 `required` 목록도 기본값이
있는 필드를 빼놓으므로 그것을 믿지 않는다 — `model_dump()` 는 `exclude_unset` 없이는
선언된 필드를 전부 내보내고, 서버는 어디서도 그 옵션을 쓰지 않는다.

대가: 요청 모델(`EventPatchRequest` · `MuteAlertRequest.minutes` 등)도 필수로 나온다.
일부만 보내려는 자리에서는 프론트가 `Partial<EventPatchRequest>` 로 좁히면 된다 —
TypeScript 가 이미 그 도구를 갖고 있으므로 생성기가 모델을 골라 다르게 다룰 이유가 없다.

별칭(`class` · `from`)은 두 모드에서 같다 — `Field(alias=...)` 가 양방향에 걸린다.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any, get_args

from pydantic.json_schema import models_json_schema

import aegis_contracts as contracts
from aegis_contracts import enums
from aegis_contracts._base import SpecModel

if isinstance(sys.stdout, io.TextIOWrapper):
    # `tasks.py` 가 자식으로 돌리면 출력이 파이프가 되고, 그때 한글 Windows 는 cp949 를
    # 쓴다 — '—' 하나에 죽어 **생성이 끝났는데 실패로 보고된다.**
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 생성물 경로. `front/src/types/` 안에 두어 손으로 쓴 헬퍼(`system.ts`)와 나란히 산다.
OUTPUT = Path(__file__).resolve().parent.parent / "front" / "src" / "types" / "contracts.ts"

#: 파일 첫머리. **손으로 고치지 말라는 말을 코드 첫 줄에 둔다.**
HEADER = """/**
 * 자동 생성 파일 — 손으로 고치지 마라.
 *
 *     uv run tasks.py types
 *
 * 원본은 `packages/contracts` 이고 그 원본은 `docs/AEGIS_API명세서.md` 다
 * (CLAUDE.md 절대규칙 5). 이 파일을 고치면 다음 생성에서 지워진다.
 *
 * `uv run tasks.py verify` 가 재생성해 이 파일과 대조하므로, 계약이 바뀌었는데
 * 여기가 낡아 있으면 검증이 실패한다.
 *
 * 각 타입의 주석은 계약 모델 docstring 의 **첫 단락**이다. 전문은 파이썬 쪽에 있다.
 */

/* eslint-disable */
"""


def exported_models() -> list[type[SpecModel]]:
    """계약이 `__all__` 로 내보내는 `SpecModel` 전량. 이름 순."""
    found = [
        value
        for name in contracts.__all__
        if isinstance(value := getattr(contracts, name), type)
        and issubclass(value, SpecModel)
        and value is not SpecModel
    ]
    return sorted(found, key=lambda model: model.__name__)


def schema_defs(models: list[type[SpecModel]]) -> dict[str, Any]:
    """모델 전량을 한 번에 뽑아 `$defs` 를 공유하게 만든다.

    모델마다 따로 뽑으면 같은 하위 모델(`NearbySnapshot` 등)이 여러 파일에 중복
    정의되고, 그중 하나만 갱신되는 상황이 생긴다.
    """
    _, top = models_json_schema(
        [(model, "serialization") for model in models],
        ref_template="#/$defs/{model}",
    )
    defs: dict[str, Any] = top.get("$defs", {})
    return defs


# ---------------------------------------------------------------------------
# JSON Schema → TypeScript
# ---------------------------------------------------------------------------


def ts_type(schema: Any) -> str:
    """JSON Schema 조각 하나를 TypeScript 타입 문자열로.

    **모르는 모양을 조용히 `any` 로 넘기지 않는다.** `unknown` 을 내면 그 자리를 쓰는
    코드가 컴파일되지 않아 사람이 알아채고, `any` 면 틀린 필드가 조용히 통과한다.
    """
    if not isinstance(schema, dict):
        return "unknown"

    if (ref := schema.get("$ref")) is not None:
        return str(ref).rsplit("/", 1)[-1]

    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False).replace('"', "'")

    if (enum := schema.get("enum")) is not None:
        return " | ".join(json.dumps(item, ensure_ascii=False).replace('"', "'") for item in enum)

    for key in ("anyOf", "oneOf"):
        if (options := schema.get(key)) is not None:
            return " | ".join(dict.fromkeys(ts_type(option) for option in options))

    if (parts := schema.get("allOf")) is not None:
        return " & ".join(ts_type(part) for part in parts)

    kind = schema.get("type")
    if isinstance(kind, list):
        return " | ".join(ts_type({**schema, "type": item}) for item in kind)

    match kind:
        case "string":
            return "string"
        case "integer" | "number":
            return "number"
        case "boolean":
            return "boolean"
        case "null":
            return "null"
        case "array":
            return _ts_array(schema)
        case "object":
            return _ts_object(schema)
        case _:
            # 타입이 없는 스키마다 (`Any` 필드 등). `unknown` 이 정직한 표현이다.
            return "unknown"


def _ts_array(schema: dict[str, Any]) -> str:
    if (prefix := schema.get("prefixItems")) is not None:
        # 고정 길이 튜플 — `bbox`(4) · `foot_point`(2) · `depth_band_m`(2) 가 이것이다.
        # `number[]` 로 넓히면 길이가 계약인 필드에서 그 사실이 사라진다.
        return "[" + ", ".join(ts_type(item) for item in prefix) + "]"
    items = schema.get("items")
    if items is None:
        return "unknown[]"
    inner = ts_type(items)
    return f"({inner})[]" if (" " in inner) else f"{inner}[]"


def _ts_object(schema: dict[str, Any]) -> str:
    """익명 객체. 스키마의 `required` 를 보지 않는 이유는 `render_definition` 과 같다."""
    properties: dict[str, Any] = schema.get("properties") or {}
    if not properties:
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            return f"Record<string, {ts_type(extra)}>"
        return "Record<string, unknown>"
    fields = [f"{_key(name)}: {ts_type(body)}" for name, body in properties.items()]
    return "{ " + "; ".join(fields) + " }"


def _key(name: str) -> str:
    """JS 식별자로 쓸 수 없는 키는 따옴표로 감싼다."""
    if name.isidentifier():
        return name
    return json.dumps(name, ensure_ascii=False)


def _doc(schema: dict[str, Any], indent: str = "") -> str:
    """모델 설명의 **첫 단락**을 JSDoc 으로. 전문은 파이썬 쪽에 있다."""
    description = str(schema.get("description") or "").strip()
    if not description:
        return ""
    lines: list[str] = []
    for line in description.splitlines():
        if not line.strip() and lines:
            break
        lines.append(line.strip())
    if not lines:
        return ""
    body = "\n".join(f"{indent} * {line}".rstrip() for line in lines)
    return f"{indent}/**\n{body}\n{indent} */\n"


def render_definition(name: str, schema: dict[str, Any]) -> str:
    """`$defs` 항목 하나를 `export type` 또는 `export interface` 로."""
    doc = _doc(schema)
    if "properties" in schema:
        properties: dict[str, Any] = schema["properties"]
        # **`?` 를 붙이지 않는다.** `serialization` 모드에서도 스키마의 `required` 는
        # 기본값이 있는 필드를 빼놓지만, 직렬화는 그 필드도 항상 내보낸다. 옵셔널로
        # 내면 `Policies.overlay_stale_ms` 가 `number | undefined` 가 되어 프론트가
        # 값을 코드에 적어 메우게 된다(절대규칙 6 위반). nullable 은 `| null` 로
        # 이미 구분되므로 "없을 수 있다"는 정보는 잃지 않는다.
        lines = [f"{doc}export interface {name} {{"]
        for field, body in properties.items():
            field_doc = _doc(body, indent="  ")
            if field_doc:
                lines.append(field_doc.rstrip("\n"))
            lines.append(f"  {_key(field)}: {ts_type(body)}")
        lines.append("}")
        return "\n".join(lines)
    return f"{doc}export type {name} = {ts_type(schema)}"


def literal_aliases(defs: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    """`aegis_contracts.enums` 의 `Literal[...]` 별칭들.

    `EventStatus` · `ViolationType` 처럼 `Enum` 으로 만든 것은 JSON Schema 가 `$defs`
    로 뽑아 주지만, `AlertState = Literal["candidate", ...]` 같은 별칭은 **쓰이는 자리에
    값 목록으로 펼쳐진다.** 그러면 프론트가 `AlertState` 라는 이름을 쓸 수 없어 결국
    손으로 다시 적게 되고, 그것이 이 생성기를 만든 이유였다.

    이름이 이미 `$defs` 에 있으면 건너뛴다 — 같은 이름을 두 번 선언하면 컴파일되지 않는다.
    """
    found: dict[str, tuple[Any, ...]] = {}
    for name in enums.__all__:
        if name in defs:
            continue
        alias = getattr(enums, name)
        args = get_args(alias)
        if args and all(isinstance(arg, str | int | bool | float) for arg in args):
            found[name] = args
    return found


def render_alias(name: str, values: tuple[Any, ...]) -> str:
    body = " | ".join(json.dumps(value, ensure_ascii=False).replace('"', "'") for value in values)
    return f"export type {name} = {body}"


def render(defs: dict[str, Any]) -> str:
    aliases = literal_aliases(defs)
    blocks = [render_alias(name, aliases[name]) for name in sorted(aliases)]
    blocks += [render_definition(name, defs[name]) for name in sorted(defs)]
    return HEADER + "\n" + "\n\n".join(blocks) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def generate() -> str:
    return render(schema_defs(exported_models()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="contracts → front TypeScript 타입 생성")
    parser.add_argument(
        "--check",
        action="store_true",
        help="쓰지 않고 생성물이 최신인지만 확인한다 (다르면 종료코드 1)",
    )
    args = parser.parse_args(argv)

    generated = generate()
    models = exported_models()

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current == generated:
            print(f"타입 생성물이 최신이다 — {OUTPUT.name} (모델 {len(models)}종)")
            return 0
        # 조용히 통과시키지 않는다(절대규칙 9). 계약이 바뀌었는데 프론트 타입이 낡은
        # 상태는 "손으로 옮긴 사본" 시절과 같은 위험이다.
        reason = "파일이 없다" if not current else "내용이 다르다"
        print(f"타입 생성물이 낡았다 ({reason}): {OUTPUT}")
        print("  uv run tasks.py types 로 다시 생성하고 커밋해라.")
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # 개행을 LF 로 못박는다. Windows 기본(CRLF)으로 쓰면 `--check` 가 리눅스에서
    # 항상 실패한다 — 젯슨에서도 같은 명령이 돌아야 한다.
    OUTPUT.write_text(generated, encoding="utf-8", newline="\n")
    print(f"타입 생성 완료 — {OUTPUT} (모델 {len(models)}종 · {len(generated.splitlines())}줄)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
