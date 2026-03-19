# 질문게시판 독립 페이지 Design Document

> **Summary**: `/board` 독립 페이지 + 백엔드 API 확장의 상세 설계
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-03-19
> **Status**: Draft
> **Plan Reference**: `docs/01-plan/features/qna-board-page.plan.md`
> **Branch**: `feat/qna-board-page`

---

## 1. FR-06: 백엔드 API 확장 (구현 순서 1번)

### 1.1 변경 파일

| 파일 | 변경 유형 |
|------|----------|
| `api/index.py` | 수정 — 기존 `board_recent` 리팩터링 + 신규 엔드포인트 2개 |

### 1.2 API 상세 설계

#### 1.2.1 `GET /api/board/search` — 검색 + 필터 + 페이지네이션

기존 `GET /api/board/recent`를 확장하는 신규 엔드포인트. `board_recent`는 하위 호환을 위해 유지한다.

```python
@app.get("/api/board/search")
def board_search(
    q: str = "",
    category: str = "",
    page: int = 1,
    per_page: int = 15,
):
    """질문게시판 검색 — 키워드 + 카테고리 필터 + 페이지네이션"""
    sb = _get_supabase()
    per_page = min(per_page, 30)
    offset = (page - 1) * per_page

    query_builder = (
        sb.table("qa_conversations")
        .select("id, category, question_text, answer_text, created_at", count="exact")
    )

    # 카테고리 필터
    if category:
        query_builder = query_builder.eq("category", category)

    # 키워드 검색 (question_text ILIKE)
    if q:
        query_builder = query_builder.ilike("question_text", f"%{q}%")

    result = (
        query_builder
        .order("created_at", desc=True)
        .range(offset, offset + per_page - 1)
        .execute()
    )

    items = []
    for row in result.data or []:
        question = _anonymize(row.get("question_text", ""))
        answer = row.get("answer_text", "")
        answer_preview = answer[:300] + ("..." if len(answer) > 300 else "") if answer else ""
        items.append({
            "id": row["id"],
            "category": row.get("category", ""),
            "question": question,
            "answer_preview": _anonymize(answer_preview),
            "created_at": row.get("created_at", ""),
        })

    total = result.count or 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
        "has_more": offset + per_page < total,
    }
```

**`board_recent`와의 차이점**: `q` 파라미터(ILIKE 검색), `category` 파라미터(정확 일치 필터), `total_pages` 필드 추가.

#### 1.2.2 `GET /api/board/{item_id}` — 상세 조회

```python
@app.get("/api/board/{item_id}")
def board_detail(item_id: str):
    """질문게시판 상세 — 답변 전문 (비식별화)"""
    sb = _get_supabase()

    # UUID 형식 검증 (path traversal 방지)
    try:
        import uuid as _uuid
        _uuid.UUID(item_id)
    except ValueError:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": "Invalid ID"})

    result = (
        sb.table("qa_conversations")
        .select("id, category, question_text, answer_text, created_at")
        .eq("id", item_id)
        .single()
        .execute()
    )

    if not result.data:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "Not found"})

    row = result.data
    return {
        "id": row["id"],
        "category": row.get("category", ""),
        "question": _anonymize(row.get("question_text", "")),
        "answer": _anonymize(row.get("answer_text", "")),
        "created_at": row.get("created_at", ""),
    }
```

#### 1.2.3 `GET /api/board/categories` — 카테고리 목록

```python
@app.get("/api/board/categories")
def board_categories():
    """사용 가능한 카테고리 목록 (건수 포함)"""
    sb = _get_supabase()

    result = (
        sb.table("qa_conversations")
        .select("category", count="exact")
        .execute()
    )

    # 카테고리별 건수 집계
    counts = {}
    for row in result.data or []:
        cat = row.get("category", "일반상담")
        counts[cat] = counts.get(cat, 0) + 1

    categories = [
        {"name": cat, "count": count}
        for cat, count in sorted(counts.items(), key=lambda x: -x[1])
    ]

    return {"categories": categories, "total": result.count or 0}
```

---

## 2. FR-01 + FR-04: board.html 독립 페이지 + 답변 전문 보기

### 2.1 파일 위치

| 파일 | 변경 유형 |
|------|----------|
| `public/board.html` | **신규** — 독립 게시판 페이지 |

### 2.2 HTML 구조

```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <!-- 메인페이지와 동일 폰트/CDN -->
  <title>질문게시판 — 노동OK</title>
  <link href="Noto Serif KR + Pretendard" />
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/dompurify/dist/purify.min.js"></script>
</head>
<body>
  <!-- HEADER: index.html과 동일 구조, "질문게시판" 링크 active 상태 -->
  <header id="site-header">...</header>

  <!-- HERO: 간소화된 히어로 -->
  <section id="board-hero">
    <h1>질문게시판</h1>
    <p>다른 분들이 물어본 질문과 답변을 검색해보세요</p>
    <div id="board-stats">총 <strong>0</strong>건의 질문</div>
  </section>

  <main>
    <!-- SEARCH BAR -->
    <section id="search-section">
      <input type="text" id="search-input" placeholder="검색어를 입력하세요 (예: 주휴수당, 퇴직금)" />
    </section>

    <!-- CATEGORY FILTER -->
    <section id="filter-section">
      <div id="category-chips">
        <button class="cat-chip active" data-cat="">전체</button>
        <!-- JS에서 동적 생성 -->
      </div>
    </section>

    <!-- BOARD LIST -->
    <section id="board-section">
      <div id="result-count"></div>
      <div id="board-list"></div>
    </section>

    <!-- PAGINATION -->
    <nav id="pagination" aria-label="페이지 탐색"></nav>
  </main>

  <footer>...</footer>
</body>
</html>
```

### 2.3 디자인 토큰 (index.html 계승)

```css
:root {
  /* index.html과 100% 동일한 CSS custom properties */
  --navy: #1B2A4A;
  --copper: #C08050;
  --cream: #F7F5F2;
  --font-display: 'Noto Serif KR', serif;
  --font-body: 'Pretendard', sans-serif;
  /* ... 나머지 동일 ... */
}

body {
  font-family: var(--font-body);
  background: var(--cream);
  color: var(--text);
  max-width: 800px;
  margin: 0 auto;
}
```

### 2.4 컴포넌트 상세 설계

#### 2.4.1 Board Hero (간소화)

```css
#board-hero {
  background: var(--navy);
  color: #fff;
  padding: 40px 24px 32px;
  border-radius: var(--radius-lg);
  text-align: center;
}
#board-hero h1 {
  font-family: var(--font-display);
  font-size: 32px;
  font-weight: 900;
}
#board-hero p {
  color: rgba(255,255,255,0.7);
  font-size: 15px;
  margin-top: 8px;
}
#board-stats {
  color: var(--copper-light);
  font-size: 14px;
  margin-top: 16px;
}
```

#### 2.4.2 Search Bar

```css
#search-section {
  padding: 24px 20px 0;
}
#search-input {
  width: 100%;
  padding: 14px 20px 14px 44px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--warm-white);
  font-size: 15px;
  font-family: var(--font-body);
  outline: none;
  transition: border-color 0.2s;
  /* 검색 아이콘: CSS background-image로 SVG 삽입 */
}
#search-input:focus {
  border-color: var(--copper);
}
```

**JS 동작**: `input` 이벤트 → 300ms 디바운스 → `loadBoard()` 호출 + URL 파라미터 갱신

#### 2.4.3 Category Filter Chips

```css
#filter-section {
  padding: 16px 20px 0;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
#category-chips {
  display: flex;
  gap: 8px;
  flex-wrap: nowrap;  /* 모바일: 가로 스크롤 */
}
.cat-chip {
  padding: 7px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: transparent;
  font-size: 13px;
  font-family: var(--font-body);
  color: var(--text-secondary);
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
  flex-shrink: 0;
}
.cat-chip:hover {
  border-color: var(--copper);
  color: var(--copper);
}
.cat-chip.active {
  background: var(--copper);
  color: #fff;
  border-color: var(--copper);
}
```

**JS 동작**: `/api/board/categories` → 동적으로 chip 생성. 클릭 시 `active` 토글 + `loadBoard()` 호출 + URL 파라미터 갱신.

#### 2.4.4 Board Item (아코디언)

```css
.board-item {
  background: var(--warm-white);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  margin-bottom: 8px;
  overflow: hidden;
  transition: all 0.2s;
}
.board-item:hover {
  border-color: var(--copper);
  box-shadow: var(--shadow-sm);
}
/* 질문 행 */
.board-q {
  padding: 14px 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
}
/* 답변 영역 (접힌 상태) */
.board-a {
  display: none;
  padding: 0 18px 18px;
  border-top: 1px solid var(--border-light);
}
.board-item.open .board-a {
  display: block;
}
/* 마크다운 렌더링 영역 */
.board-a .md-content {
  font-size: 14px;
  line-height: 1.8;
  color: var(--text);
}
.board-a .md-content h2 { font-size: 16px; margin: 16px 0 8px; }
.board-a .md-content h3 { font-size: 15px; margin: 12px 0 6px; }
.board-a .md-content table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 12px 0; }
.board-a .md-content th, .board-a .md-content td { border: 1px solid var(--border); padding: 8px 10px; text-align: left; }
.board-a .md-content th { background: var(--cream); font-weight: 600; }
.board-a .md-content blockquote { border-left: 3px solid var(--copper); padding-left: 12px; color: var(--text-secondary); margin: 12px 0; }
.board-a .md-content strong { color: var(--navy); }
```

**JS 동작**: 질문 클릭 → `board-item.open` 토글. 최초 오픈 시 `/api/board/{id}` 호출 → `marked.parse()` + `DOMPurify.sanitize()` → `.md-content`에 삽입. 이후 캐시.

#### 2.4.5 Pagination

```css
#pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 4px;
  padding: 32px 20px 48px;
}
.page-btn {
  min-width: 36px; height: 36px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--warm-white);
  font-size: 14px;
  font-family: var(--font-body);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}
.page-btn:hover { border-color: var(--copper); color: var(--copper); }
.page-btn.active { background: var(--copper); color: #fff; border-color: var(--copper); }
.page-btn:disabled { opacity: 0.4; cursor: default; }
.page-btn.arrow { font-size: 12px; }
```

**JS 로직**: 최대 7개 페이지 버튼 표시. 현재 페이지 중심으로 양쪽 3개씩. 이전/다음 화살표.

```javascript
function renderPagination(page, totalPages) {
  var nav = document.getElementById('pagination');
  nav.innerHTML = '';
  if (totalPages <= 1) return;

  // 이전 버튼
  var prev = createPageBtn('◀', page - 1, page <= 1);
  nav.appendChild(prev);

  // 페이지 번호들 (최대 7개)
  var start = Math.max(1, page - 3);
  var end = Math.min(totalPages, start + 6);
  start = Math.max(1, end - 6);

  for (var i = start; i <= end; i++) {
    var btn = createPageBtn(i, i, false);
    if (i === page) btn.classList.add('active');
    nav.appendChild(btn);
  }

  // 다음 버튼
  var next = createPageBtn('▶', page + 1, page >= totalPages);
  nav.appendChild(next);
}
```

---

## 3. FR-02 + FR-03: 카테고리 필터 + 키워드 검색

### 3.1 URL 파라미터 동기화

```javascript
// 상태 관리
var boardState = { page: 1, q: '', category: '' };

// URL → 상태 복원 (페이지 로드 시)
function parseUrlParams() {
  var params = new URLSearchParams(window.location.search);
  boardState.page = parseInt(params.get('page')) || 1;
  boardState.q = params.get('q') || '';
  boardState.category = params.get('category') || '';
}

// 상태 → URL 갱신 (검색/필터/페이지 변경 시)
function updateUrl() {
  var params = new URLSearchParams();
  if (boardState.q) params.set('q', boardState.q);
  if (boardState.category) params.set('category', boardState.category);
  if (boardState.page > 1) params.set('page', boardState.page);
  var qs = params.toString();
  history.replaceState(null, '', qs ? '?' + qs : location.pathname);
}
```

### 3.2 검색 디바운스

```javascript
var searchTimer = null;
document.getElementById('search-input').addEventListener('input', function(e) {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(function() {
    boardState.q = e.target.value.trim();
    boardState.page = 1;
    loadBoard();
    updateUrl();
  }, 300);
});
```

### 3.3 카테고리 칩 동적 생성

```javascript
async function loadCategories() {
  var resp = await fetch(API_BASE + '/api/board/categories');
  var data = await resp.json();

  var container = document.getElementById('category-chips');
  // "전체" 칩은 HTML에 이미 존재
  data.categories.forEach(function(cat) {
    var btn = document.createElement('button');
    btn.className = 'cat-chip';
    btn.dataset.cat = cat.name;
    btn.textContent = cat.name + ' ' + cat.count;
    btn.addEventListener('click', function() {
      document.querySelectorAll('.cat-chip').forEach(function(c) { c.classList.remove('active'); });
      btn.classList.add('active');
      boardState.category = cat.name;
      boardState.page = 1;
      loadBoard();
      updateUrl();
    });
    container.appendChild(btn);
  });
}
```

---

## 4. FR-05: 페이지네이션

Section 2.4.5에서 상세 설계 완료. 핵심:
- 최대 7개 페이지 버튼
- 이전/다음 화살표 (첫/마지막 페이지 비활성화)
- `boardState.page` 갱신 → `loadBoard()` + `updateUrl()`

---

## 5. FR-07: 메인페이지 연결

### 5.1 변경 파일

| 파일 | 변경 유형 |
|------|----------|
| `public/index.html` | 수정 — 게시판 섹션에 "전체 보기" 링크, 헤더에 "게시판" 링크 |

### 5.2 변경 내용

#### 헤더 네비게이션에 "게시판" 링크 추가

```html
<!-- header-nav 내 기존 링크들 뒤에 추가 -->
<a href="/board">게시판</a>
```

#### 게시판 섹션에 "전체 보기" 링크 추가

```html
<!-- #board-more-btn 옆 또는 대체 -->
<div class="section-link-wrap">
  <a href="/board" class="board-view-all">전체 보기 →</a>
</div>
```

---

## 6. FR-08: Vercel 라우팅

### 6.1 변경 파일

| 파일 | 변경 유형 |
|------|----------|
| `vercel.json` | 수정 — `/board` 라우트 추가 |

### 6.2 변경 내용

`routes` 배열에서 `/(.*\\..*)`(파일 확장자 매칭) 라우트 **앞에** 추가:

```json
{ "src": "/board", "dest": "/public/board.html" }
```

위치: `/admin`, `/calculators` 라우트와 같은 레벨.

---

## 7. 구현 순서 및 의존성

```
Phase 1: FR-06 (API)
    ↓
Phase 2: FR-01 + FR-04 (board.html 기본 + 마크다운 렌더링)
    ↓
Phase 3: FR-02 + FR-03 (카테고리 + 검색)
    ↓
Phase 4: FR-05 (페이지네이션)
    ↓
Phase 5: FR-07 + FR-08 (메인 연결 + Vercel 라우팅)
```

---

## 8. 보안 체크리스트

| 항목 | 설계 대응 |
|------|----------|
| XSS | `DOMPurify.sanitize(marked.parse(answer))` — 마크다운 렌더링 후 sanitize |
| 개인정보 | 모든 API 출력에 `_anonymize()` 적용 (이름, 회사명, 전화번호, 이메일) |
| Path traversal | `board_detail`에서 UUID 형식 검증 (`uuid.UUID(item_id)`) |
| SQL injection | Supabase Python SDK가 파라미터화 쿼리 사용 — 직접 SQL 없음 |
| Rate limiting | Vercel serverless 기본 제한 + per_page 상한 (max 30) |

---

## 9. 변경 영향도 요약

| 파일 | 변경 유형 | 예상 줄 수 |
|------|----------|:----------:|
| `api/index.py` | 수정 | +80줄 |
| `public/board.html` | **신규** | ~500줄 |
| `public/index.html` | 수정 | +5줄 |
| `vercel.json` | 수정 | +1줄 |

**총계**: 신규 1개 + 수정 3개. ~586줄.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-19 | Initial design — 8 FRs detailed | Claude |
