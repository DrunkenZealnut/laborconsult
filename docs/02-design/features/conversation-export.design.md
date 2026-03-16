# conversation-export Design

## 1. 개요

채팅 대화 내용 전체를 마크다운 파일로 다운로드하는 프론트엔드 기능.

## 2. UI 설계

### 2.1 저장 버튼 위치

헤더 오른쪽에 "저장" 버튼 추가:

```html
<header>
  <h1>AI 노동상담 챗봇</h1>
  <span>nodong.kr BEST Q&A 기반</span>
  <button id="export-btn" title="대화 저장 (마크다운)">📥 저장</button>
</header>
```

### 2.2 버튼 스타일

```css
#export-btn {
  margin-left: auto;
  background: none;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 12px;
  cursor: pointer;
  color: var(--muted);
  font-size: 13px;
}
#export-btn:hover { border-color: var(--primary); color: var(--primary); }
```

## 3. 마크다운 내보내기 로직

### 3.1 데이터 수집

DOM에서 `.msg-wrapper` 순회:
- `.msg.user` → `innerText` (사용자 질문 원문)
- `.msg.assistant` → `dataset.md` (원본 마크다운) 또는 `innerText` 폴백
- `.msg.status`, 인사말 → 제외

### 3.2 마크다운 포맷

```markdown
# 노동OK 상담 기록

> 날짜: 2026-03-16 14:30
> 출처: nodong.kr AI 노동상담 챗봇

---

## 질문 1

{사용자 질문}

## 답변 1

{AI 답변 마크다운 원본}

---

## 질문 2
...

---

> 본 상담 기록은 AI가 제공한 참고 정보이며, 법적 효력이 없습니다.
> 정확한 사항은 고용노동부(☎ 1350) 또는 공인노무사에게 확인하시기 바랍니다.
```

### 3.3 파일 다운로드

```javascript
function exportChatMarkdown() {
    // 1. DOM 순회 → 마크다운 조합
    // 2. new Blob([md], {type: 'text/markdown'})
    // 3. URL.createObjectURL(blob)
    // 4. <a download="노동OK_상담_YYYYMMDD_HHMMSS.md"> 트리거
    // 5. URL.revokeObjectURL
}
```

## 4. 파일 변경

| 파일 | 변경 |
|------|------|
| `public/index.html` | CSS + 버튼 + `exportChatMarkdown()` 함수 |
