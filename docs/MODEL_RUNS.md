# Model Runs

이 문서는 KnowNet이 외부 모델을 호출하는 방식의 운영 기록이다.

외부 웹 AI가 KnowNet에 직접 붙는 MCP 실험은
[EXTERNAL_AI_ACCESS_LOG.md](EXTERNAL_AI_ACCESS_LOG.md)에 기록한다.
Gemini는 그 방식이 아니다.

## Gemini 방향

Gemini 웹 채팅은 KnowNet 통합 대상이 아니다.

KnowNet의 Gemini 경로는 다음 방향이다.

```txt
KnowNet
→ safe context 생성
→ Gemini API 호출
→ structured JSON 응답 수신
→ review Markdown 변환
→ dry-run
→ 운영자 확인 후 import
```

즉:

```txt
Gemini가 KnowNet에 접속하는 방식 아님
KnowNet이 Gemini API를 호출하는 방식
```

## 현재 상태

2026-05-03 기준:

```txt
status: implemented_mocked
provider: gemini
real_api: not_enabled
real_adapter: not_implemented
mock_adapter: working
operator_import_required: true
```

## 확인한 Mock Run

실행한 endpoint:

```txt
POST /api/model-runs/gemini/reviews
```

요청 성격:

```txt
mock: true
max_pages: 8
prompt_profile: gemini_external_reviewer_v1
```

결과:

```txt
run_id: modelrun_8627bc8d86ed
status: dry_run_ready
provider: gemini
model: gemini-2.5-pro
input_tokens: 6489
output_tokens: 266
finding_count: 2
parser_errors: none
```

의미:

```txt
safe context builder 정상
secret/path guard 통과
Gemini mock adapter 정상
model JSON → review Markdown 변환 정상
review dry-run parser 정상
collaboration record는 아직 생성하지 않음
```

## Non-Mock Safety Check

실행한 요청:

```txt
POST /api/model-runs/gemini/reviews
mock: false
```

현재 결과:

```txt
blocked: true
status: 503
code: gemini_disabled
message: Gemini runner is disabled. Use mock=true until a real provider is enabled.
```

의미:

```txt
GEMINI_API_KEY 없이 실제 Gemini 호출은 나가지 않음
GEMINI_RUNNER_ENABLED=false 상태에서는 비용 발생/API 호출 없음
실제 Gemini 연동은 명시적으로 켠 뒤에만 가능
```

## 필요한 설정

실제 Gemini API 테스트 전 필요한 값:

```txt
GEMINI_API_KEY
GEMINI_RUNNER_ENABLED=true
GEMINI_MODEL
```

현재 환경 확인:

```txt
GEMINI_API_KEY: missing
GEMINI_RUNNER_ENABLED: disabled
```

## 다음 단계

실제 Gemini API로 넘어가기 전 할 일:

```txt
1. Gemini API key 준비
2. 실제 adapter 구현
3. token counter를 Gemini API 기준으로 보강
4. 비용/쿼터/timeout 기록
5. 실제 호출은 한 번만 수동 테스트
6. 결과는 바로 import하지 말고 dry-run 상태에서 운영자가 확인
```

## 원칙

```txt
모델 결과는 자동으로 KnowNet에 import하지 않는다.
항상 dry-run-ready 상태를 거친다.
운영자가 명시적으로 import해야 collaboration_reviews/findings에 들어간다.
```
