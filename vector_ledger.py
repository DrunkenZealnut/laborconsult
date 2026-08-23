#!/usr/bin/env python3
"""업로드 벡터 ID 원장 — 고아 벡터 정리의 단일 출처.

**왜 원장이 필요한가.** `upsert`는 덮어쓸 뿐 지우지 않는다. 재실행에서 어떤
문서의 청크 수가 **줄면**(청킹 규칙 변경·OCR 정정으로 섹션 병합·임베딩 대상
섹션 조정) 이전 실행의 남는 벡터가 그대로 남아 검색 결과에 계속 섞인다.
Pinecone Serverless는 메타데이터 필터 삭제를 지원하지 않으므로, **이 원장이
그 벡터를 지울 수 있는 유일한 수단이다.**

**왜 공용 모듈인가.** 이 구현은 `pinecone_upload_textbook.py`에만 있었고
`pinecone_upload_court_precedents.py`에는 없었다(외부감사 2026-08-23 H3).
같은 사이클에서 M1이 "업로드 스크립트 간 유틸 복사"가 3.5개월짜리 드리프트를
만든 것을 확인했으므로(legal의 NFD 픽스가 contextual에 전파되지 않음),
복사하지 않고 출처를 하나로 둔다.

**그룹 키 선택이 안전성을 좌우한다.** prune은 "이번에 올린 것"과 "원장에 있던
것"의 차집합을 지운다. 그룹을 넓게 잡으면 **부분 실행이 나머지를 고아로
오판한다** — court는 `--limit`이 있어 코퍼스 전체를 한 그룹으로 두면
`--limit 20` 실행이 나머지 수천 건을 삭제 대상으로 계산한다. 그래서 그룹은
"한 번의 실행이 항상 통째로 다루는 단위"여야 한다:
  · textbook → `book_id` (`--book` 단위로 전량 재청킹)
  · court    → 사건번호 (파일 하나가 자기 청크를 전부 다시 만든다)
"""

from __future__ import annotations

import os
import re
import sys
import json
from typing import Callable


def atomic_write_json(path: str, data, *, indent: int = 1) -> None:
    """JSON을 원자적으로 쓴다 — 쓰기 중 죽어도 기존 파일이 손상되지 않는다.

    직접 `open(path, "w")`로 쓰면 truncate 직후 중단됐을 때 **빈 파일**이 남고,
    읽는 쪽은 대개 그것을 '최초 실행'으로 해석해 상태를 통째로 잃는다
    (외부감사 2026-08-23 M8). 상태·진행상황·원장처럼 **잃으면 복구가 어려운
    파일**에 쓴다. 원본에서 언제든 재생성되는 산출물에는 굳이 필요 없다.
    """
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class VectorLedger:
    """그룹 단위 벡터 ID 원장.

    Args:
        path: 원장 JSON 경로. **코퍼스마다 달라야 한다** — 그룹 키 공간이
            겹치지 않더라도 한 파일을 공유하면 한쪽의 손상 격리가 다른 쪽의
            롤백 기록까지 묶어 중단시킨다.
        group_re: 그룹 ID 형식 검증용. 이 값들이 `index.delete()`로 들어가므로
            형태가 어긋나면 엉뚱한 벡터를 지운다 — 삭제는 되돌릴 수 없다.
        id_re_for: 그룹 ID → 그 그룹의 벡터 ID 정규식. 접두사만 검사하면
            규격 위반 ID(`textbook_win_x_y` 등)가 통과한다.
    """

    def __init__(self, path: str, group_re: re.Pattern,
                 id_re_for: Callable[[str], re.Pattern]) -> None:
        self.path = path
        self._group_re = group_re
        self._id_re_for = id_re_for

    # ── 저수준 I/O ────────────────────────────────────────────────────────

    def read(self) -> dict[str, list[str]]:
        """원장 로드. 손상 시엔 백업 후 중단한다.

        조용히 {}로 시작하면 **다른 그룹의 롤백 기록이 통째로 사라진다** —
        이 목록이 유일한 복구 수단이다. 빈 파일은 정상(최초 실행)으로 본다.
        """
        backup = self.path + ".bak"

        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            # .bak만 남아 있다는 건 직전 실행이 손상을 감지하고 격리했다는 뜻이다.
            # 여기서 {}를 반환하면 이전 ID를 잃고 기존 고아 벡터를 영영 정리하지
            # 못한다 — 사람이 복구하거나 명시적으로 초기화할 때까지 막는다.
            if os.path.exists(backup):
                sys.exit(f"[오류] 손상 격리된 롤백 기록이 있습니다: {backup}\n"
                         f"       내용을 확인해 {self.path}로 복구하거나, "
                         f"의도적 초기화라면 .bak을 삭제한 뒤 재실행하세요.")
            return {}

        def _abort(reason: str):
            os.replace(self.path, backup)
            sys.exit(f"[오류] 롤백 기록이 올바르지 않습니다 ({reason}). "
                     f"원본을 {backup}로 보존했습니다 — 확인 후 재실행하세요.")

        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            _abort(str(e))

        # 스키마 검증 — 이 값은 index.delete()로 들어간다.
        if not isinstance(data, dict):
            _abort(f"최상위가 dict가 아님: {type(data).__name__}")
        for group_id, ids in data.items():
            if not self._group_re.match(str(group_id)):
                _abort(f"그룹 ID 형식 위반: {group_id!r}")
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                _abort(f"'{group_id}' 항목이 문자열 리스트가 아님")
            id_re = self._id_re_for(group_id)
            bad = [i for i in ids if not id_re.match(i)]
            if bad:
                _abort(f"'{group_id}' 항목에 벡터 ID 규격 위반 {len(bad)}건 "
                       f"(예: {bad[:2]})")
        return data

    def write(self, data: dict[str, list[str]]) -> None:
        """원자적 교체로 기록 — 쓰기 중 죽어도 원장이 비지 않는다.

        truncate 후 쓰는 방식은 중단 시 빈 파일을 남기고, read()가 그것을
        '최초 실행'으로 읽어 **이전 ID를 통째로 잃는다**. 그러면 기존 고아
        벡터를 영영 정리할 수 없다.
        """
        atomic_write_json(self.path, data)

    # ── 기록 ──────────────────────────────────────────────────────────────

    def record(self, groups: dict[str, list[str]]) -> dict[str, set[str]]:
        """업로드 예정 벡터 ID를 기록하고 **이전 기록**을 돌려준다.

        **upsert보다 먼저** 호출한다 — 업로드 도중 죽으면 이미 적재된 벡터가
        기록 없이 남고 복구 수단이 사라진다. 존재하지 않는 ID의 delete는
        무해하므로 기록은 실제 적재분의 **상위집합**이어야 안전하다.

        같은 이유로 기존 기록과 **합집합**을 취한다. 청킹이 바뀌어 ID가 줄면
        교체 방식은 이전 실행의 고아 벡터를 추적 대상에서 지워버린다.

        여러 그룹을 한 번에 받는 것은 파일 I/O 때문이다 — 그룹마다 읽고 쓰면
        court처럼 그룹이 수천 개인 코퍼스에서 원장 쓰기가 병목이 된다.
        """
        data = self.read()
        previous = {g: set(data.get(g, [])) for g in groups}
        for group_id, ids in groups.items():
            data[group_id] = sorted(previous[group_id] | set(ids))
        self.write(data)
        return previous

    def finalize(self, groups: dict[str, list[str]]) -> None:
        """업로드·정리가 모두 성공한 뒤 원장을 현재 집합으로 확정한다.

        이걸 하지 않으면 원장이 합집합으로 남아 다음 실행이 **이미 삭제한 ID를
        또 stale로 계산**한다. 삭제 자체는 멱등이라 무해하지만, 대량 삭제 가드가
        한 번 걸리면 원장이 그대로라 이후 실행이 매번 같은 지점에서 멈춘다.
        """
        data = self.read()
        for group_id, ids in groups.items():
            data[group_id] = sorted(ids)
        self.write(data)

    # ── 정리 ──────────────────────────────────────────────────────────────

    def prune(self, groups: dict[str, list[str]], previous: dict[str, set[str]],
              index, namespace: str, *, batch_size: int = 100,
              allow_large: bool = False, label: str = "") -> int:
        """이번 업로드에 없는 이전 벡터를 삭제하고 원장을 확정한다.

        업로드가 전부 성공한 뒤에만 호출한다 — 중간 실패 시 삭제하면 아직
        올리지 못한 벡터를 지울 수 있다.

        대량 삭제 가드는 **전체 합계**로 판정한다. 그룹별로 걸면 청크가 1개인
        그룹에서 1건만 줄어도 50%를 넘어 상시 발동하고, 경고가 일상이 되면
        아무도 읽지 않는다.

        Returns: 삭제한 벡터 수.
        """
        stale: list[str] = []
        for group_id, ids in groups.items():
            stale.extend(sorted(previous.get(group_id, set()) - set(ids)))
        stale.sort()

        if not stale:
            self.finalize(groups)
            return 0

        total_current = sum(len(v) for v in groups.values())
        # 대량 삭제는 ID 규격이 통째로 바뀐 신호다. 조용히 지우면 되돌릴 수 없다.
        # 탈출구를 '원장 비우기'로 두면 안 된다 — previous가 사라져 stale이 0이
        # 되고 고아 벡터가 영구히 남는다. 명시 플래그로만 통과시킨다.
        if not allow_large and len(stale) > total_current * 0.5:
            sys.exit(
                f"[오류] {label or '대상'} 고아 벡터가 {len(stale)}건으로 현재 "
                f"청크({total_current})의 50%를 넘습니다 — 벡터 ID 규격이 바뀌었을 "
                f"수 있습니다. 의도한 변경이면 --allow-large-prune 으로 재실행하세요 "
                f"(원장을 직접 비우면 삭제 대상을 잃어 고아가 영구히 남습니다)."
            )

        for i in range(0, len(stale), batch_size):
            index.delete(ids=stale[i:i + batch_size], namespace=namespace)
        print(f"  고아 벡터 {len(stale)}건 삭제 (예: {stale[:2]})")
        self.finalize(groups)
        return len(stale)
