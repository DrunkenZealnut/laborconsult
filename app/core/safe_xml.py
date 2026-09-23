"""원격 XML 파싱 단일 창구.

이 저장소가 파싱하는 XML 은 전부 **원격 HTTP 응답**이다(법제처 API 16곳, 게시판 첨부
HWPX). 그런데 stdlib `xml.etree.ElementTree` 는 내부 엔티티를 확장하므로, 1KB 짜리
문서가 파싱 중에 수 GB 로 부풀 수 있다("billion laughs"). `legal_api.py` 의 8곳은
**상담 요청 경로**에 있어 그 확장이 곧 서비스 정지가 된다.

한 곳만 막으면 나머지가 그대로 남아 "막았다"는 오해만 만든다. 그래서 파싱 진입점을
여기 하나로 모은다 — 새 XML 호출부를 만들 때도 여기를 거칠 것.

**2중 방어**:
  1. DTD·엔티티 선언이 있으면 아예 파싱하지 않는다. 우리가 받는 법제처 응답과 HWPX
     section XML 은 DOCTYPE 을 쓰지 않으므로 정상 문서를 잃지 않는다.
  2. `defusedxml` 이 설치돼 있으면 그쪽으로 파싱한다(외부 엔티티 참조·이차 폭발까지 커버).
     없어도 1번이 남으므로 **조용히 안전하지 않은 상태가 되지 않는다** — 그게 폴백을
     두면서도 stdlib 로 그냥 넘기지 않는 이유다.

`UnsafeXML` 은 `ET.ParseError` 의 하위 클래스다. 기존 호출부가 `except ET.ParseError`
또는 광범위 `except Exception` 으로 받아 폴백하므로, 거부가 곧 우아한 성능저하가 된다.
"""
from __future__ import annotations

import codecs
import re
from xml.etree import ElementTree as ET

try:
    from defusedxml.ElementTree import fromstring as _defused_fromstring
except ImportError:      # 선택 의존성 — 없으면 아래 DTD 거부가 단독으로 막는다
    _defused_fromstring = None

# 루트 요소가 시작하는 지점. XML 규격상 DTD 는 **반드시 루트 요소 앞(prolog)** 에 온다.
# 바이트 상한(4KB)으로 자르면 prolog 에 긴 주석·처리지시문을 채워 선언을 뒤로 밀 수 있다
# (실측: 5KB 주석 뒤의 DOCTYPE 이 검사를 통과해 엔티티가 확장됐다). 그래서 상한이 아니라
# **prolog 끝**에서 자른다 — 길이에 무관하고, 본문(CDATA·문자데이터)은 애초에 포함되지
# 않아 "판례 본문에 우연히 들어간 문자열" 오탐도 생기지 않는다.
_ROOT_START = re.compile(r"<[A-Za-z_:]")

# BOM → 인코딩. **바이트로 검사하면 UTF-16 에서 통째로 빗나간다** — `<!DOCTYPE` 이
# `<\x00!\x00D\x00…` 로 들어가 b"<!DOCTYPE" 이 매치되지 않는다(실측: UTF-16·UTF-16-BE
# 에서 엔티티가 그대로 확장됐다). 파서는 BOM 을 보고 디코드하므로, 검사도 같은 눈으로
# 봐야 한다. UTF-32 를 UTF-16 보다 먼저 본다 — UTF-32-LE BOM 은 UTF-16-LE BOM 으로 시작한다.
_BOMS = ((codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
         (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be"),
         (codecs.BOM_UTF8, "utf-8"))


def _as_text(raw: bytes) -> str:
    """검사용 문자열. 파서가 해석할 인코딩과 같은 눈으로 본다."""
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            return raw[len(bom):].decode(encoding, "ignore")
    # BOM 이 없는데 앞머리에 널바이트가 있으면 UTF-16 계열이다(규격상 BOM 이 있어야 하지만
    # 없는 문서도 돌아다닌다). ASCII 호환 인코딩은 latin-1 로 바이트를 보존해 훑는다.
    if b"\x00" in raw[:64]:
        return raw.decode("utf-16", "ignore") + raw.decode("utf-16-be", "ignore")
    return raw.decode("latin-1", "ignore")


class UnsafeXML(ET.ParseError):
    """DTD·엔티티 선언이 있는 XML — 파싱하지 않는다."""


def fromstring(data: bytes | str) -> ET.Element:
    """원격 XML 을 파싱한다. DTD·엔티티 선언이 있으면 `UnsafeXML` 을 던진다."""
    raw = data if isinstance(data, bytes) else data.encode("utf-8", "ignore")
    text = _as_text(raw)
    root_at = _ROOT_START.search(text)
    prolog = text[:root_at.start()] if root_at else text
    if "<!DOCTYPE" in prolog or "<!ENTITY" in prolog:
        # ParseError 는 SyntaxError 하위라 2번째 인자가 4-튜플이어야 한다. ElementTree
        # 자신도 메시지만 넘기고 position 은 나중에 붙이므로 같은 방식을 쓴다.
        error = UnsafeXML("DTD/엔티티 선언이 있는 XML 은 파싱하지 않습니다")
        error.position = (1, 0)
        raise error
    if _defused_fromstring is not None:
        return _defused_fromstring(raw)
    return ET.fromstring(raw)
