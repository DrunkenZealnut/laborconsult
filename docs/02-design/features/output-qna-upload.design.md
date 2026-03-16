# output-qna-upload Design

## 1. 개요

output_qna(9,809건) + output_qna_2(9,807건)를 Pinecone `qa` 네임스페이스에 업로드.
출처를 `source=nodongok`으로 메타데이터에 저장하여 추적 가능하게 한다.

## 2. 데이터 구조

### 2.1 파일 형식 (동일)

```markdown
# {제목}

| 항목 | 내용 |
| --- | --- |
| 작성일 | 2021.10.17 |
| 조회수 | 619 |
| 원문 | [https://www.nodong.kr/qna/2253007](...) |

### 작성자 정보
| 성별 | 여성 |
| 지역 | 상담소 |

---

## 질문
{질문 본문}

## 답변
### 답변 1
{답변 본문}
```

### 2.2 메타데이터 추출

| 필드 | 추출 위치 | 예시 |
|------|----------|------|
| `title` | `# 제목` | "시간제 근무 후 계약만료 시 이직확인서" |
| `post_id` | 파일명 앞 숫자 | "2253007" |
| `date` | 메타 테이블 `작성일` | "2021.10.17" |
| `url` | 메타 테이블 `원문` | "https://www.nodong.kr/qna/2253007" |
| `source` | 고정값 | `"nodongok"` |
| `source_type` | 고정값 | `"qa"` |

## 3. 구현 설계

### 3.1 pinecone_upload_contextual.py 수정

#### SOURCES 추가

```python
{
    "directory": "output_qna",
    "namespace": "qa",
    "source_type": "qa",
    "label": "Q&A 상담 (1차)",
    "source": "nodongok",
},
```

기존 `output_qna_2` 항목에도 `"source": "nodongok"` 추가.

#### process_source() 메타데이터 수정

벡터 메타데이터에 `source` 필드 추가:

```python
"metadata": {
    "source_type": source_type,
    "source": source_config.get("source", ""),  # NEW: 출처
    "title": title[:200],
    "category": category[:50],
    "date": date_str,
    "url": url,
    "section": chunk["section"][:100],
    "chunk_index": chunk["chunk_index"],
    "chunk_text": chunk["chunk_text"][:900],
    "text": chunk["chunk_text"][:900],    # rag.py 호환
}
```

### 3.2 rag.py 수정

`NAMESPACES`에 `"qa"` 추가:

```python
NAMESPACES = ["laborlaw-v2", "counsel", "qa"]
```

`format_pinecone_hits()`에 qa 라벨 추가:

```python
"qa": "상담 Q&A",
```

### 3.3 중복 처리

- output_qna와 output_qna_2에서 동일 post_id 12건 → chunk_id가 같으므로 자동 덮어쓰기 (문제 없음)

### 3.4 답변 없는 글 처리

output_qna_2의 일부 파일은 답변이 없음 (댓글 작성 권한 없음 텍스트만 존재).
본문 길이 < 50자인 경우 스킵.

## 4. 파일 변경 목록

| 파일 | 변경 | 내용 |
|------|------|------|
| `pinecone_upload_contextual.py` | MODIFY | SOURCES에 output_qna 추가, metadata에 source 필드 |
| `app/core/rag.py` | MODIFY | NAMESPACES에 "qa" 추가, qa 라벨 |

## 5. 실행 명령

```bash
python3 pinecone_upload_contextual.py --source "Q&A" --skip-context
```
