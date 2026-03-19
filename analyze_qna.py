#!/usr/bin/env python3
"""
노동OK Q&A 질문 분석기
- output_qna/ 마크다운 파일을 Claude Haiku로 분석
- 5개씩 배치 처리 (API 비용 절감)
- analysis_qna.jsonl에 중간 저장 (재개 가능)
- 예상 비용: 10,000개 × ~1,000토큰 ≈ 1,000만 토큰 → Haiku 기준 약 $4

사용법:
  python3 analyze_qna.py              # 전체 분석
  python3 analyze_qna.py --limit 100  # 샘플 100개만
  python3 analyze_qna.py --dry-run    # API 미사용, 파일 목록만 출력
"""

import os
import re
import json
import time
import argparse
from pathlib import Path
import anthropic
from dotenv import load_dotenv

load_dotenv()

_PROJECT_DIR = Path(__file__).parent
DEFAULT_INPUT_DIR    = str(_PROJECT_DIR / "output_qna")
DEFAULT_OUTPUT_JSONL = str(_PROJECT_DIR / "analysis_qna.jsonl")
MODEL        = "claude-haiku-4-5-20251001"
BATCH_SIZE   = 5
MAX_CONTENT_CHARS = 2000  # 질문 본문 최대 길이 (토큰 절감)

ANALYSIS_SYSTEM = """당신은 한국 노동법 Q&A 데이터 분석 전문가입니다.
주어진 질문들을 분석하여 정확한 JSON 형식으로 반환하세요.
반드시 유효한 JSON 배열만 출력하고, 추가 설명은 하지 마세요."""

ANALYSIS_PROMPT_TEMPLATE = """다음 {n}개의 노동법 Q&A 질문을 분석하여 JSON 배열로 반환하세요.

각 항목 형식:
{{
  "file_id": "파일 ID",
  "question_type": "주요 법적 이슈 (예: 퇴직금, 해고, 임금, 연차, 주휴수당, 산재, 실업급여, 근로계약, 직장내괴롭힘, 기타)",
  "sub_type": "세부 유형 (예: 퇴직금 계산, 연차 발생, 해고 적법성 등)",
  "provided_info": {{
    "근무기간": "값 또는 null",
    "임금형태": "월급/시급/연봉 또는 null",
    "임금액": "금액 또는 null",
    "근무형태": "정규직/계약직/파트타임 등 또는 null",
    "사업장규모": "인원 또는 null",
    "퇴직사유": "자발/해고/계약만료 등 또는 null"
  }},
  "missing_info": ["계산에 필요하지만 없는 정보 목록"],
  "final_question": "핵심 질문 한 문장 요약",
  "requires_calculation": true 또는 false,
  "calculation_type": "계산기 유형 (퇴직금/연차수당/연장수당/주휴수당/최저임금/해고예고수당/실업급여/육아휴직급여/해당없음)"
}}

분석할 질문들:
{questions}

JSON 배열만 출력하세요 (```json 코드블록 없이)."""


def load_analyzed_ids(jsonl_path: str) -> set:
    """이미 분석된 파일 ID 목록"""
    analyzed = set()
    if not os.path.exists(jsonl_path):
        return analyzed
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if 'file_id' in obj:
                    analyzed.add(obj['file_id'])
            except json.JSONDecodeError:
                pass
    return analyzed


def get_md_files(input_dir: str) -> list[dict]:
    """output_qna/에서 마크다운 파일 목록 수집"""
    files = []
    if not os.path.exists(input_dir):
        print(f"[오류] 디렉터리 없음: {input_dir}")
        print("  먼저 crawl_qna.py를 실행하세요.")
        return files

    for fname in sorted(os.listdir(input_dir)):
        if not fname.endswith('.md') or fname == 'index.md':
            continue
        m = re.match(r'^(\d+)_', fname)
        if not m:
            continue
        files.append({
            'file_id': m.group(1),
            'filename': fname,
            'path': os.path.join(input_dir, fname),
        })

    return files


def extract_question_text(filepath: str) -> tuple[str, str]:
    """마크다운 파일에서 제목 + 질문 본문 추출"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return '', ''

    # 제목 추출 (첫 번째 # 헤딩)
    title_m = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else ''

    # 카테고리 추출
    cat_m = re.search(r'\|\s*카테고리\s*\|\s*([^|]+)\|', content)
    category = cat_m.group(1).strip() if cat_m else ''

    # 질문 섹션 추출
    q_m = re.search(r'## 질문\s*\n+(.*?)(?=\n## |\Z)', content, re.DOTALL)
    if q_m:
        question_body = q_m.group(1).strip()
    else:
        # 질문 섹션이 없으면 본문 전체 사용
        question_body = re.sub(r'^#.*$', '', content, flags=re.MULTILINE)
        question_body = re.sub(r'\|.*\|', '', question_body)
        question_body = question_body.strip()

    # 최대 길이 제한
    if len(question_body) > MAX_CONTENT_CHARS:
        question_body = question_body[:MAX_CONTENT_CHARS] + '...'

    header = f"[카테고리: {category}] " if category else ""
    return title, header + question_body


def parse_json_response(text: str, expected_count: int) -> list[dict]:
    """Claude 응답에서 JSON 배열 추출 및 파싱"""
    text = text.strip()

    # 코드블록 제거
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()

    # JSON 배열 찾기
    # 전체가 배열인 경우
    if text.startswith('['):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # 부분 추출 시도
    m = re.search(r'\[.*\]', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # 개별 JSON 객체 추출
    objects = []
    for m in re.finditer(r'\{[^{}]*\}', text, re.DOTALL):
        try:
            obj = json.loads(m.group(0))
            if 'question_type' in obj or 'file_id' in obj:
                objects.append(obj)
        except json.JSONDecodeError:
            pass

    return objects


def analyze_batch(client: anthropic.Anthropic, batch: list[dict]) -> list[dict]:
    """배치(5개) 분석 - Claude Haiku 호출"""
    # 질문 텍스트 구성
    question_blocks = []
    for item in batch:
        title, body = extract_question_text(item['path'])
        block = f"--- ID: {item['file_id']} ---\n제목: {title}\n{body}"
        question_blocks.append(block)

    questions_text = "\n\n".join(question_blocks)
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        n=len(batch),
        questions=questions_text,
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text
    except Exception as e:
        print(f"    [API 오류] {e}")
        return []

    parsed = parse_json_response(raw_text, len(batch))

    # file_id 매핑: 파싱된 결과에 file_id가 없으면 순서대로 할당
    results = []
    for i, item in enumerate(batch):
        if i < len(parsed):
            obj = parsed[i]
            obj['file_id'] = item['file_id']
            obj['filename'] = item['filename']
            results.append(obj)
        else:
            # 파싱 실패한 항목 → 빈 결과
            results.append({
                'file_id': item['file_id'],
                'filename': item['filename'],
                'question_type': '분석실패',
                'sub_type': '',
                'provided_info': {},
                'missing_info': [],
                'final_question': '',
                'requires_calculation': False,
                'calculation_type': '해당없음',
            })

    return results


def main():
    parser = argparse.ArgumentParser(description="Q&A 질문 분석기")
    parser.add_argument('--limit', type=int, default=0, help="분석할 최대 파일 수 (0=전체)")
    parser.add_argument('--dry-run', action='store_true', help="API 호출 없이 파일 목록만 출력")
    parser.add_argument('--input-dir', type=str, default=DEFAULT_INPUT_DIR, help=f"입력 디렉터리 (기본: {DEFAULT_INPUT_DIR})")
    parser.add_argument('--output-jsonl', type=str, default=DEFAULT_OUTPUT_JSONL, help=f"출력 JSONL 파일 (기본: {DEFAULT_OUTPUT_JSONL})")
    args = parser.parse_args()

    INPUT_DIR = args.input_dir
    OUTPUT_JSONL = args.output_jsonl

    # API 키 확인
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key and not args.dry_run:
        print("[오류] ANTHROPIC_API_KEY가 .env에 없습니다.")
        return

    # 파일 목록 수집
    all_files = get_md_files(INPUT_DIR)
    if not all_files:
        return

    print(f"=== 노동OK Q&A 분석기 시작 ===\n")
    print(f"입력 디렉터리: {INPUT_DIR}")
    print(f"출력 파일: {OUTPUT_JSONL}")
    print(f"전체 파일: {len(all_files)}개")

    # 이미 분석된 항목 건너뜀
    analyzed_ids = load_analyzed_ids(OUTPUT_JSONL)
    pending = [f for f in all_files if f['file_id'] not in analyzed_ids]

    print(f"이미 분석됨: {len(analyzed_ids)}개")
    print(f"분석 대상:  {len(pending)}개")

    if args.limit > 0:
        pending = pending[:args.limit]
        print(f"--limit 적용: {len(pending)}개만 처리\n")

    if args.dry_run:
        print("\n[dry-run] API 호출 없이 종료합니다.")
        for f in pending[:20]:
            print(f"  {f['filename']}")
        if len(pending) > 20:
            print(f"  ... 외 {len(pending) - 20}개")
        return

    if not pending:
        print("\n분석할 파일이 없습니다.")
        return

    client = anthropic.Anthropic(api_key=api_key)

    # 배치 처리
    total_batches = (len(pending) + BATCH_SIZE - 1) // BATCH_SIZE
    success_count = 0
    fail_count = 0

    with open(OUTPUT_JSONL, 'a', encoding='utf-8') as out_f:
        for batch_idx in range(0, len(pending), BATCH_SIZE):
            batch = pending[batch_idx:batch_idx + BATCH_SIZE]
            batch_num = batch_idx // BATCH_SIZE + 1

            ids_str = ', '.join(f['file_id'] for f in batch)
            print(f"[배치 {batch_num}/{total_batches}] ID: {ids_str}", end=' ... ', flush=True)

            results = analyze_batch(client, batch)

            if results:
                for obj in results:
                    out_f.write(json.dumps(obj, ensure_ascii=False) + '\n')
                out_f.flush()
                success_count += len(results)
                print(f"완료 ({len(results)}개)")
            else:
                fail_count += len(batch)
                print("실패")

            # API 속도 제한 방지 (배치 간 1초)
            time.sleep(1.0)

    print(f"\n=== 완료 ===")
    print(f"성공: {success_count}개 / 실패: {fail_count}개")
    print(f"결과 파일: {OUTPUT_JSONL}")
    print(f"\n다음 단계: python3 summarize_analysis.py")


if __name__ == '__main__':
    main()
