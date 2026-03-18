# Design: 챗봇 메인페이지 제작

> Feature: `chatbot-main-page`
> Plan: `docs/01-plan/features/chatbot-main-page.plan.md`
> Created: 2026-03-18
> Level: Dynamic

---

## 1. Overview

현재 채팅 전용 `public/index.html`을 스크롤 기반 다기능 메인페이지로 리디자인.
기존 채팅 JS 로직 100% 보존하면서 5개 섹션 추가.

### 1.1 Page Layout

```
┌─────────────────────────────────────────────┐
│  Header (sticky)                            │
│  [로고] AI 노동상담 챗봇  [저장] [흐름도]     │
├─────────────────────────────────────────────┤
│                                             │
│  SEC-01: Hero — 챗봇 채팅창                  │
│  (min-height: 70vh, 스크롤 가능)             │
│                                             │
├─────────────────────────────────────────────┤
│  SEC-02: 많이 하는 질문 (FAQ)                │
│  [임금/수당] [퇴직/해고] [근로계약] ...       │
│  ┌─────┐ ┌─────┐ ┌─────┐                   │
│  │ Q1  │ │ Q2  │ │ Q3  │                   │
│  └─────┘ └─────┘ └─────┘                   │
├─────────────────────────────────────────────┤
│  SEC-03: 임금 계산기                         │
│  ┌───┐ ┌───┐ ┌───┐ ┌───┐                   │
│  │💰│ │📊│ │🏖│ │⚖│                   │
│  │주휴│ │퇴직│ │연차│ │최저│                   │
│  └───┘ └───┘ └───┘ └───┘                   │
│  ┌───┐ ┌───┐ ┌───┐ ┌───┐                   │
│  │📋│ │🏥│ │💼│ │🚫│                   │
│  │실업│ │4대│ │연장│ │해고│                   │
│  └───┘ └───┘ └───┘ └───┘                   │
│         [전체 계산기 보기 →]                  │
├─────────────────────────────────────────────┤
│  SEC-04: 질문게시판                          │
│  ┌─ Q: 주휴수당 미지급... ─────── 3시간 전 ─┐│
│  │  A: 근로기준법 제55조에 따라...           ││
│  └───────────────────────────────────────┘│
│  ┌─ Q: 퇴직금 계산... ──────── 5시간 전 ─┐  │
│  └───────────────────────────────────────┘│
│  [더 보기]                                  │
├─────────────────────────────────────────────┤
│  SEC-05: Footer                             │
│  청년노동자인권센터                           │
│  서울시 종로구 성균관로12 5층                  │
│  admin@younglabor.kr                        │
│  ⚠ 면책고지 | © 2026                        │
└─────────────────────────────────────────────┘
```

---

## 2. HTML Structure

### 2.1 전체 구조 변경

**현재**: `body = header + #chat + #input-wrapper + .disclaimer`
**변경**: `body = header + main(scrollable) > [#chat-section, #faq-section, #calc-section, #board-section] + footer`

```html
<body>
  <header> ... (기존 유지) </header>

  <main id="main-content">
    <!-- SEC-01: 챗봇 채팅창 -->
    <section id="chat-section">
      <div id="chat"> ... (기존 채팅 메시지 영역) </div>
      <div id="input-wrapper"> ... (기존 입력 영역) </div>
    </section>

    <!-- SEC-02: 많이 하는 질문 -->
    <section id="faq-section">
      <h2 class="section-title">많이 하는 질문</h2>
      <div id="faq-tabs"> ... </div>
      <div id="faq-list"> ... </div>
    </section>

    <!-- SEC-03: 임금 계산기 -->
    <section id="calc-section">
      <h2 class="section-title">임금 계산기</h2>
      <div id="calc-grid"> ... </div>
      <a href="/calculators" class="section-link">전체 계산기 보기 →</a>
    </section>

    <!-- SEC-04: 질문게시판 -->
    <section id="board-section">
      <h2 class="section-title">질문게시판</h2>
      <div id="board-list"> ... </div>
      <button id="board-more">더 보기</button>
    </section>
  </main>

  <!-- SEC-05: Footer -->
  <footer id="site-footer"> ... </footer>

  <div id="drop-overlay">파일을 여기에 놓으세요</div>
</body>
```

### 2.2 핵심 변경점

| 항목 | 현재 | 변경 |
|------|------|------|
| body layout | `flex-column, overflow:hidden` | `flex-column, overflow:visible` |
| #chat | `flex:1, overflow-y:auto` | `min-height:60vh` (section 내) |
| #input-wrapper | body 하단 고정 | `position:sticky; bottom:0` (chat-section 내) |
| .disclaimer | body 하단 고정 | footer로 이동 |
| 스크롤 | #chat 내부 스크롤 | main 전체 스크롤 + #chat 내부 스크롤 |

---

## 3. Section Detail Design

### 3.1 SEC-01: 챗봇 채팅창

**레이아웃**: 기존 채팅 UI를 `<section id="chat-section">`으로 감쌈.

```html
<section id="chat-section">
  <div id="chat">
    <!-- 기존 인사말 메시지 -->
    <div class="msg-wrapper assistant-side">
      <div class="msg assistant">
        안녕하세요! 한국 노동법 관련 질문에 답변해 드립니다.<br>
        임금계산, 퇴직금, 4대보험 등 무엇이든 물어보세요.
      </div>
    </div>
  </div>
  <div id="input-wrapper">
    <!-- 기존 파일 프리뷰 + 입력 영역 100% 보존 -->
  </div>
</section>
```

**CSS**:
```css
#chat-section {
  min-height: 70vh;
  display: flex;
  flex-direction: column;
  position: relative;
}
#chat {
  flex: 1;
  overflow-y: auto;
  max-height: 60vh;      /* 스크롤 영역 제한 */
  padding: 16px 20px;
}
#input-wrapper {
  position: sticky;
  bottom: 0;
  z-index: 10;
}
```

**JS 변경사항**: 없음 (기존 로직 100% 보존)

### 3.2 SEC-02: 많이 하는 질문 (FAQ)

**데이터**: 프론트엔드 하드코딩 (API 불필요, 성능 최적)

```javascript
const FAQ_DATA = {
  "임금/수당": {
    icon: "💰",
    questions: [
      "시급 10,000원인데 주휴수당은 얼마인가요?",
      "연장근로수당은 어떻게 계산하나요?",
      "야간수당과 휴일수당을 동시에 받을 수 있나요?",
      "2026년 최저임금은 얼마인가요?",
    ]
  },
  "퇴직/해고": {
    icon: "📋",
    questions: [
      "1년 6개월 근무 후 퇴직금은 얼마인가요?",
      "해고예고수당은 어떻게 계산하나요?",
      "권고사직도 퇴직금을 받을 수 있나요?",
      "부당해고 구제 신청은 어떻게 하나요?",
    ]
  },
  "근로계약": {
    icon: "📝",
    questions: [
      "근로계약서를 안 쓰면 어떻게 되나요?",
      "수습기간에도 최저임금을 받아야 하나요?",
      "계약직 갱신 거절은 부당해고인가요?",
    ]
  },
  "4대보험": {
    icon: "🏥",
    questions: [
      "4대보험 가입 기준이 어떻게 되나요?",
      "4대보험료는 얼마나 내나요?",
      "일용직도 4대보험에 가입해야 하나요?",
    ]
  },
  "직장 내 괴롭힘": {
    icon: "🚫",
    questions: [
      "직장 내 괴롭힘 판단 기준이 뭔가요?",
      "괴롭힘 신고는 어디에 하나요?",
      "괴롭힘 증거는 어떻게 모으나요?",
    ]
  },
  "출산/육아": {
    icon: "👶",
    questions: [
      "출산휴가 급여는 얼마인가요?",
      "육아휴직 급여는 어떻게 계산하나요?",
      "배우자 출산휴가는 며칠인가요?",
    ]
  }
};
```

**HTML**:
```html
<section id="faq-section" class="page-section">
  <h2 class="section-title">많이 하는 질문</h2>
  <div id="faq-tabs" role="tablist">
    <!-- JS로 카테고리 탭 생성 -->
  </div>
  <div id="faq-list" role="tabpanel">
    <!-- JS로 질문 버튼 목록 생성 -->
  </div>
</section>
```

**CSS**:
```css
.page-section {
  padding: 40px 20px;
  max-width: 900px;
  margin: 0 auto;
}
.section-title {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 20px;
  text-align: center;
}

/* FAQ 탭 */
#faq-tabs {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 12px;
  justify-content: center;
  flex-wrap: wrap;
}
.faq-tab {
  padding: 8px 16px;
  border: 1px solid var(--border);
  border-radius: 20px;
  background: var(--card);
  cursor: pointer;
  font-size: 14px;
  white-space: nowrap;
  transition: all 0.15s;
}
.faq-tab:hover { border-color: var(--primary); color: var(--primary); }
.faq-tab.active {
  background: var(--primary);
  color: white;
  border-color: var(--primary);
}

/* FAQ 질문 목록 */
#faq-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.faq-item {
  padding: 12px 16px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  cursor: pointer;
  font-size: 14px;
  text-align: left;
  transition: all 0.15s;
  display: flex;
  align-items: center;
  gap: 8px;
}
.faq-item:hover {
  border-color: var(--primary);
  background: var(--co-legal-bg);
}
.faq-item::before {
  content: "💬";
  font-size: 16px;
  flex-shrink: 0;
}
```

**JS 인터랙션**:
```javascript
function initFAQ() {
  const tabs = document.getElementById('faq-tabs');
  const list = document.getElementById('faq-list');
  const categories = Object.keys(FAQ_DATA);

  // 탭 생성
  categories.forEach((cat, i) => {
    const tab = document.createElement('button');
    tab.className = 'faq-tab' + (i === 0 ? ' active' : '');
    tab.textContent = FAQ_DATA[cat].icon + ' ' + cat;
    tab.onclick = () => selectFaqTab(cat, tab);
    tabs.appendChild(tab);
  });

  // 첫 카테고리 표시
  renderFaqList(categories[0]);
}

function selectFaqTab(cat, tabEl) {
  document.querySelectorAll('.faq-tab').forEach(t => t.classList.remove('active'));
  tabEl.classList.add('active');
  renderFaqList(cat);
}

function renderFaqList(cat) {
  const list = document.getElementById('faq-list');
  list.innerHTML = '';
  FAQ_DATA[cat].questions.forEach(q => {
    const item = document.createElement('button');
    item.className = 'faq-item';
    item.textContent = q;
    item.onclick = () => askQuestion(q);
    list.appendChild(item);
  });
}

function askQuestion(text) {
  // 채팅 섹션으로 스크롤
  document.getElementById('chat-section').scrollIntoView({ behavior: 'smooth' });
  // 입력창에 텍스트 설정 후 전송
  msgInput.value = text;
  msgInput.dispatchEvent(new Event('input'));
  setTimeout(() => send(), 300);
}
```

### 3.3 SEC-03: 임금 계산기 바로가기

**데이터**: 프론트엔드 하드코딩

```javascript
const CALC_SHORTCUTS = [
  { icon: "💰", name: "주휴수당", desc: "주 15시간 이상 근무 시", query: "시급 10,000원, 주 40시간 근무할 때 주휴수당은 얼마인가요?" },
  { icon: "📊", name: "퇴직금", desc: "1년 이상 근무 시", query: "월급 300만원, 3년 근무 후 퇴직금은 얼마인가요?" },
  { icon: "🏖️", name: "연차수당", desc: "미사용 연차 정산", query: "월급 250만원, 미사용 연차 5일의 연차수당은?" },
  { icon: "⚖️", name: "최저임금 검증", desc: "2026년 기준 확인", query: "시급 10,030원이 최저임금 이상인지 확인해주세요" },
  { icon: "📋", name: "실업급여", desc: "수급 자격/금액", query: "월급 280만원, 2년 근무 후 실업급여는 얼마인가요?" },
  { icon: "🏥", name: "4대보험료", desc: "근로자/사업주 부담", query: "월급 300만원일 때 4대보험료는 각각 얼마인가요?" },
  { icon: "💼", name: "연장/야간/휴일수당", desc: "할증률 적용 계산", query: "시급 12,000원, 연장근로 10시간의 수당은 얼마인가요?" },
  { icon: "🚫", name: "해고예고수당", desc: "30일분 통상임금", query: "월급 250만원일 때 해고예고수당은 얼마인가요?" },
];
```

**HTML**:
```html
<section id="calc-section" class="page-section">
  <h2 class="section-title">임금 계산기</h2>
  <p class="section-desc">궁금한 계산기를 선택하면 바로 상담이 시작됩니다</p>
  <div id="calc-grid">
    <!-- JS로 카드 생성 -->
  </div>
  <div class="section-link-wrap">
    <a href="/calculators" class="section-link">전체 25개 계산기 보기 →</a>
  </div>
</section>
```

**CSS**:
```css
#calc-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
@media (max-width: 768px) {
  #calc-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 400px) {
  #calc-grid { grid-template-columns: repeat(2, 1fr); gap: 8px; }
}

.calc-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  text-align: center;
  cursor: pointer;
  transition: all 0.15s;
}
.calc-card:hover {
  border-color: var(--primary);
  box-shadow: 0 2px 8px rgba(37,99,235,0.1);
  transform: translateY(-2px);
}
.calc-card .calc-icon { font-size: 28px; margin-bottom: 8px; }
.calc-card .calc-name { font-size: 14px; font-weight: 600; }
.calc-card .calc-desc { font-size: 11px; color: var(--muted); margin-top: 4px; }

.section-desc {
  text-align: center;
  color: var(--muted);
  font-size: 14px;
  margin-bottom: 20px;
}
.section-link-wrap { text-align: center; margin-top: 16px; }
.section-link {
  color: var(--primary);
  text-decoration: none;
  font-size: 14px;
  font-weight: 600;
}
.section-link:hover { text-decoration: underline; }
```

**JS**:
```javascript
function initCalcGrid() {
  const grid = document.getElementById('calc-grid');
  CALC_SHORTCUTS.forEach(calc => {
    const card = document.createElement('div');
    card.className = 'calc-card';
    card.innerHTML = `
      <div class="calc-icon">${calc.icon}</div>
      <div class="calc-name">${calc.name}</div>
      <div class="calc-desc">${calc.desc}</div>
    `;
    card.onclick = () => askQuestion(calc.query);
    grid.appendChild(card);
  });
}
```

### 3.4 SEC-04: 질문게시판

**API 설계**: 새 엔드포인트 `/api/board/recent` (인증 불필요)

```python
# api/index.py에 추가

@app.get("/api/board/recent")
def board_recent(page: int = 1, per_page: int = 10):
    """최근 공개 질문/답변 — 비식별화 처리"""
    sb = _get_supabase()
    per_page = min(per_page, 20)
    offset = (page - 1) * per_page

    result = (
        sb.table("qa_conversations")
        .select("id, category, question_text, answer_text, created_at", count="exact")
        .order("created_at", desc=True)
        .range(offset, offset + per_page - 1)
        .execute()
    )

    items = []
    for row in result.data or []:
        q = _anonymize(row.get("question_text", ""))
        a = row.get("answer_text", "")
        # 답변은 300자까지 미리보기
        a_preview = a[:300] + ("..." if len(a) > 300 else "") if a else ""
        items.append({
            "id": row["id"],
            "category": row.get("category", ""),
            "question": q,
            "answer_preview": _anonymize(a_preview),
            "created_at": row.get("created_at", ""),
        })

    total = result.count or 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": offset + per_page < total,
    }
```

**비식별화 함수**:
```python
import re

_ANON_PATTERNS = [
    (re.compile(r'[가-힣]{2,4}(?=\s*(?:씨|님|사장|대표|과장|부장|팀장|차장|이사))'), 'OOO'),
    (re.compile(r'(?:주\s*\)?\s*|㈜\s*|(?:주식)?회사\s+)[가-힣A-Za-z]+'), '(주)OOO'),
    (re.compile(r'\d{2,3}[-.\s]?\d{3,4}[-.\s]?\d{4}'), '***-****-****'),
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), '***@***.***'),
]

def _anonymize(text: str) -> str:
    """개인정보 비식별화"""
    for pattern, replacement in _ANON_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
```

**HTML**:
```html
<section id="board-section" class="page-section">
  <h2 class="section-title">질문게시판</h2>
  <p class="section-desc">다른 분들이 최근에 물어본 질문들입니다</p>
  <div id="board-list">
    <!-- JS로 동적 생성 -->
  </div>
  <div class="section-link-wrap">
    <button id="board-more" class="section-link" style="border:none;background:none;cursor:pointer;">
      더 보기 ↓
    </button>
  </div>
</section>
```

**CSS**:
```css
.board-item {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin-bottom: 8px;
  overflow: hidden;
  transition: border-color 0.15s;
}
.board-item:hover { border-color: var(--primary); }

.board-q {
  padding: 12px 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
}
.board-q .board-cat {
  background: var(--co-legal-bg);
  color: var(--primary);
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
  white-space: nowrap;
  flex-shrink: 0;
}
.board-q .board-text { flex: 1; }
.board-q .board-time {
  color: var(--muted);
  font-size: 12px;
  white-space: nowrap;
  flex-shrink: 0;
}
.board-q .board-chevron {
  color: var(--muted);
  transition: transform 0.2s;
  flex-shrink: 0;
}
.board-item.open .board-chevron { transform: rotate(180deg); }

.board-a {
  display: none;
  padding: 0 16px 12px;
  font-size: 13px;
  color: var(--muted);
  line-height: 1.6;
  border-top: 1px solid var(--border);
  margin-top: 0;
  padding-top: 12px;
}
.board-item.open .board-a { display: block; }

.board-ask-btn {
  display: inline-block;
  margin-top: 8px;
  color: var(--primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  background: none;
  border: none;
}
```

**JS**:
```javascript
let boardPage = 1;
let boardLoading = false;

async function loadBoard(append = false) {
  if (boardLoading) return;
  boardLoading = true;

  const moreBtn = document.getElementById('board-more');
  moreBtn.textContent = '불러오는 중...';

  try {
    const resp = await fetch(API_BASE + '/api/board/recent?page=' + boardPage + '&per_page=10');
    if (!resp.ok) throw new Error('API 오류');
    const data = await resp.json();

    const list = document.getElementById('board-list');
    if (!append) list.innerHTML = '';

    data.items.forEach(item => {
      const el = createBoardItem(item);
      list.appendChild(el);
    });

    moreBtn.style.display = data.has_more ? '' : 'none';
    moreBtn.textContent = '더 보기 ↓';
  } catch (e) {
    console.error('Board load error:', e);
    if (!append) {
      document.getElementById('board-list').innerHTML =
        '<p style="text-align:center;color:var(--muted);padding:20px;">질문을 불러올 수 없습니다.</p>';
    }
    moreBtn.style.display = 'none';
  } finally {
    boardLoading = false;
  }
}

function createBoardItem(item) {
  const div = document.createElement('div');
  div.className = 'board-item';
  const timeAgo = getTimeAgo(item.created_at);
  div.innerHTML = `
    <div class="board-q" onclick="this.parentElement.classList.toggle('open')">
      <span class="board-cat">${item.category || '일반'}</span>
      <span class="board-text">${escHtml(item.question)}</span>
      <span class="board-time">${timeAgo}</span>
      <span class="board-chevron">▼</span>
    </div>
    <div class="board-a">
      ${escHtml(item.answer_preview)}
      <br>
      <button class="board-ask-btn" onclick="askQuestion('${escAttr(item.question)}')">
        비슷한 질문하기 →
      </button>
    </div>
  `;
  return div;
}

function getTimeAgo(isoStr) {
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return mins + '분 전';
  const hours = Math.floor(mins / 60);
  if (hours < 24) return hours + '시간 전';
  const days = Math.floor(hours / 24);
  if (days < 30) return days + '일 전';
  return new Date(isoStr).toLocaleDateString('ko-KR');
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function escAttr(str) {
  return str.replace(/'/g,"\\'").replace(/"/g,'&quot;');
}

document.getElementById('board-more').addEventListener('click', () => {
  boardPage++;
  loadBoard(true);
});
```

**Lazy Loading**: IntersectionObserver로 스크롤 도달 시 로드
```javascript
const boardObserver = new IntersectionObserver(entries => {
  if (entries[0].isIntersecting && !boardLoading) {
    loadBoard();
    boardObserver.disconnect();
  }
}, { rootMargin: '200px' });

boardObserver.observe(document.getElementById('board-section'));
```

### 3.5 SEC-05: Footer

**HTML**:
```html
<footer id="site-footer">
  <div class="footer-inner">
    <div class="footer-org">
      <strong>청년노동자인권센터</strong>
      <span>서울시 종로구 성균관로12 5층</span>
      <a href="mailto:admin@younglabor.kr">admin@younglabor.kr</a>
    </div>
    <div class="footer-links">
      <a href="#">개인정보처리방침</a>
      <span>|</span>
      <a href="#">이용약관</a>
    </div>
    <div class="footer-disclaimer">
      본 답변은 참고용이며 법적 효력이 없습니다.
      정확한 판단은 고용노동부(1350) 또는 노무사에게 문의하세요.
    </div>
    <div class="footer-copyright">
      © 2026 청년노동자인권센터. AI 노동상담 챗봇.
    </div>
  </div>
</footer>
```

**CSS**:
```css
#site-footer {
  background: var(--text);
  color: #94a3b8;
  padding: 40px 20px 24px;
  font-size: 13px;
  line-height: 1.6;
}
.footer-inner {
  max-width: 900px;
  margin: 0 auto;
  text-align: center;
}
.footer-org {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 16px;
}
.footer-org strong {
  color: #e2e8f0;
  font-size: 15px;
}
.footer-org a {
  color: var(--primary);
  text-decoration: none;
}
.footer-links {
  margin-bottom: 16px;
  display: flex;
  gap: 8px;
  justify-content: center;
}
.footer-links a {
  color: #94a3b8;
  text-decoration: none;
}
.footer-links a:hover { color: #e2e8f0; }
.footer-disclaimer {
  color: #64748b;
  font-size: 12px;
  margin-bottom: 8px;
}
.footer-copyright {
  color: #475569;
  font-size: 11px;
}
```

---

## 4. API Design

### 4.1 새 엔드포인트

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/board/recent` | None | 최근 질문/답변 목록 (비식별화) |

#### `GET /api/board/recent`

**Query Params**:
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| page | int | 1 | 페이지 번호 |
| per_page | int | 10 | 페이지당 건수 (max: 20) |

**Response** (`200 OK`):
```json
{
  "items": [
    {
      "id": "uuid",
      "category": "임금/수당",
      "question": "주휴수당 미지급 시 어떻게...",
      "answer_preview": "근로기준법 제55조에 따라...",
      "created_at": "2026-03-18T10:30:00Z"
    }
  ],
  "total": 150,
  "page": 1,
  "per_page": 10,
  "has_more": true
}
```

### 4.2 비식별화 규칙

| 패턴 | 치환 | 예시 |
|------|------|------|
| 한글 이름 + 호칭 | `OOO` | "김철수 사장" → "OOO 사장" |
| 회사명 | `(주)OOO` | "주)삼성전자" → "(주)OOO" |
| 전화번호 | `***-****-****` | "010-1234-5678" → "***-****-****" |
| 이메일 | `***@***.***` | "test@gmail.com" → "***@***.***" |

---

## 5. CSS Design System

### 5.1 기존 CSS Variables 활용 (변경 없음)

```css
:root {
  --primary: #2563eb;
  --bg: #f8fafc;
  --card: #ffffff;
  --text: #1e293b;
  --muted: #64748b;
  --border: #e2e8f0;
  /* 기존 callout 색상 그대로 활용 */
}
```

### 5.2 추가 CSS

```css
/* ── 섹션 구분선 ── */
.page-section {
  padding: 48px 20px;
  max-width: 900px;
  margin: 0 auto;
  border-top: 1px solid var(--border);
}
.page-section:first-of-type { border-top: none; }

/* ── 섹션 사이 간격 ── */
#chat-section + .page-section { margin-top: 0; }

/* ── main 스크롤 ── */
#main-content {
  flex: 1;
  overflow-y: auto;
}
```

### 5.3 모바일 반응형 (추가)

```css
@media (max-width: 600px) {
  .page-section { padding: 32px 16px; }
  .section-title { font-size: 18px; }
  #faq-tabs { justify-content: flex-start; flex-wrap: nowrap; }
  #calc-grid { grid-template-columns: repeat(2, 1fr); }
  .footer-org { font-size: 12px; }
}
```

---

## 6. Implementation Order

```
Phase 1 (P0): 구조 변경 + Footer
  ├─ 1.1 body 레이아웃 변경 (flex → scroll)
  ├─ 1.2 <main> 래퍼 + <section> 구조화
  ├─ 1.3 Footer HTML/CSS
  ├─ 1.4 기존 .disclaimer 제거 → Footer로 이동
  └─ 1.5 기존 채팅 기능 테스트 (회귀 확인)

Phase 2 (P1): FAQ + 계산기
  ├─ 2.1 FAQ_DATA 하드코딩
  ├─ 2.2 FAQ 섹션 HTML/CSS/JS
  ├─ 2.3 CALC_SHORTCUTS 하드코딩
  ├─ 2.4 계산기 카드 그리드 HTML/CSS/JS
  ├─ 2.5 askQuestion() 함수 (스크롤 + 자동전송)
  └─ 2.6 모바일 반응형 테스트

Phase 3 (P2): 질문게시판
  ├─ 3.1 _anonymize() 비식별화 함수 (api/index.py)
  ├─ 3.2 /api/board/recent 엔드포인트
  ├─ 3.3 질문게시판 HTML/CSS/JS
  ├─ 3.4 IntersectionObserver lazy loading
  ├─ 3.5 "더 보기" 페이지네이션
  └─ 3.6 에러 상태 처리 (API 실패 시 fallback)
```

---

## 7. File Changes

| File | Action | Description |
|------|--------|-------------|
| `public/index.html` | **Modify** | 전체 리디자인 (HTML 구조 + CSS + JS) |
| `api/index.py` | **Modify** | `/api/board/recent` 엔드포인트 + `_anonymize()` 추가 |

**신규 파일 없음** — 기존 2개 파일만 수정.

---

## 8. Testing Checklist

### 8.1 기능 테스트
- [ ] 기존 채팅 SSE 스트리밍 정상 동작
- [ ] 파일 첨부 기능 정상 동작
- [ ] 마크다운 렌더링 정상 동작
- [ ] 대화 저장 (export) 기능 정상 동작
- [ ] FAQ 탭 전환 정상 동작
- [ ] FAQ 질문 클릭 → 챗봇 자동 질문
- [ ] 계산기 카드 클릭 → 챗봇 자동 질문
- [ ] "전체 계산기 보기" 링크 정상
- [ ] 질문게시판 로드 정상
- [ ] 질문게시판 펼침/접기 동작
- [ ] "비슷한 질문하기" 클릭 동작
- [ ] "더 보기" 페이지네이션 동작
- [ ] Footer 이메일 링크 동작

### 8.2 반응형 테스트
- [ ] Desktop (1440px)
- [ ] Tablet (768px)
- [ ] Mobile (375px)
- [ ] Small Mobile (320px)

### 8.3 성능 테스트
- [ ] Lighthouse 성능 90+
- [ ] 질문게시판 API 응답 1초 이내
- [ ] 페이지 초기 로드 3초 이내 (3G)

### 8.4 보안 테스트
- [ ] 질문게시판 개인정보 비식별화 확인
- [ ] 비식별화 우회 불가능 확인
- [ ] XSS 방지 (escHtml 적용)
