# External AI Access Log

이 문서는 외부 AI 접근 실험 중 **확인된 ChatGPT/Codex와 Claude 결과만** 짧게 기록한다.
다른 AI 웹 실험 기록은 혼란을 줄이기 위해 여기서 제거했다.

## 결론

ChatGPT/Codex와 Claude는 KnowNet MCP에 붙었다.

확인된 것은 세 가지다.

1. Codex shell에서 Cloudflare Quick Tunnel을 통해 MCP JSON-RPC POST 호출 성공
2. ChatGPT PC Web에서 custom MCP connector를 통해 `knownet_start_here` 호출 성공
3. Claude 앱/Claude.ai 커넥터 등록 화면에서 MCP 주소를 넣어 `knownet_start_here`, `knownet_me`, `knownet_state_summary` 호출 성공

즉, KnowNet MCP HTTP bridge는 외부에서 접근 가능한 형태로 동작했다.

## 사용한 주소

테스트 당시 Quick Tunnel 주소:

```txt
https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
```

로컬 대상:

```txt
http://127.0.0.1:8010/mcp
```

주의:

```txt
Quick Tunnel 주소는 임시 테스트용이다.
운영용 주소가 아니다.
```

## ChatGPT/Codex 확인 결과

환경:

```txt
Codex shell
Cloudflare Quick Tunnel
KnowNet MCP HTTP bridge
```

성공한 호출:

```txt
initialize
tools/list
knownet_start_here
knownet_me
knownet_state_summary
knownet_ai_state
knownet_review_dry_run
```

결과:

```txt
MCP JSON-RPC POST 호출 성공
review dry-run 성공
실제 review submit은 하지 않음
```

진단:

```txt
server: knownet
version: 14.0
agent_token: ok
agent_scope_count: 6
token_warning: expires_soon
```

## ChatGPT PC Web 확인 결과

환경:

```txt
ChatGPT PC Web
Custom MCP connector
Cloudflare Quick Tunnel
```

설정:

```txt
URL: https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
Authentication: none
```

성공한 호출:

```txt
knownet_start_here
```

결과:

```txt
custom MCP connector가 붙은 ChatGPT PC Web 세션에서는 KnowNet 도구 호출 가능
connector가 없는 일반 웹 세션에서는 knownet_* 도구 직접 호출 불가
```

## Claude 확인 결과

성공한 방식:

```txt
Claude Desktop 앱 또는 Claude.ai의 Connectors / Integrations 화면에서
custom MCP server로 KnowNet MCP 주소를 등록
```

등록한 주소:

```txt
https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
```

인증:

```txt
No authentication
```

성공한 호출:

```txt
knownet_start_here
knownet_me
knownet_state_summary
```

결과:

```txt
Claude에서 KnowNet MCP 도구 호출 성공
세 API 모두 정상 응답
```

확인된 상태:

```txt
token_id: agent_55b5a5bf6896
role: agent_reviewer
scopes: citations/read, findings/read, graph/read, pages/read, reviews/read, reviews/create
phase: 14
pages: 64
reviews: 13
findings: 59
graph_nodes: 630
release_ready: false
```

주의:

```txt
Claude Desktop용 claude_desktop_config.json 파일 업로드 방식이 아니다.
Claude 앱/Claude.ai의 커넥터 등록 화면에서 MCP URL을 직접 추가해야 한다.
현재 성공 경로는 Cloudflare Quick Tunnel을 통한 원격 MCP 연결이다.
```

## 접근 방식 정리

MCP 가능한 클라이언트:

```txt
POST /mcp
JSON-RPC
tools/list
tools/call
knownet_* 도구 호출 가능
```

GET-only 클라이언트:

```txt
GET /mcp
GET /mcp?resource=agent:onboarding
GET /mcp?resource=agent:state-summary
도구 호출은 불가
읽기 미리보기만 가능
```

POST가 필요한 기능:

```txt
search
fetch
knownet_review_dry_run
knownet_submit_review
```

## 현재 판단

외부 AI 접근성 실험 1단계는 성공으로 본다.

다만 웹 AI를 계속 추가로 붙이는 실험은 여기서 멈춘다.
이제 중요한 작업은 운영 가능한 접근 표면을 다듬는 것이다.

다음 단계:

```txt
1. GET-only fallback을 필요한 만큼만 확장
2. Quick Tunnel 대신 named tunnel 준비
3. Cloudflare Access 같은 접근 제어 붙이기
4. 테스트용 agent token은 짧게 만들고 테스트 후 revoke
5. provider별 차이는 profile/config 문서에만 기록
6. MCP 도구 이름은 계속 knownet_* 하나로 유지
```

## Claude Desktop 참고

Claude Desktop에서 파일 업로드 방식은 성공 경로가 아니다.

성공한 방식:

```txt
Claude Desktop 앱 또는 Claude.ai 설정 화면
Connectors / Integrations
Custom MCP server 추가
MCP URL 직접 입력
```

실패한 방식:

```txt
claude_desktop_config.json 파일을 Claude 채팅에 업로드
일반 웹 대화에서 KnowNet 도구 호출 요청
```

정리:

```txt
Claude는 설정 파일을 읽는 방식보다, 현재 앱/웹의 커넥터 등록 화면에서 MCP URL을 넣는 방식이 확인된 성공 경로다.
```
