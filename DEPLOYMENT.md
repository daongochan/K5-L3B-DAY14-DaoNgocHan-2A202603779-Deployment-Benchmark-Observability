# Deployment Information

## Public URL
https://agent-production-143225b4.up.railway.app

## Platform
Railway (`DOCKERFILE` multi-stage runtime + managed Railway `Redis` service)

## Test Commands

### 1. CP6 Self-Check (HTTP Status Verification)
```bash
export BASE="https://agent-production-143225b4.up.railway.app"
export AGENT_API_KEY="<YOUR_AGENT_API_KEY>"

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # Expected: 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # Expected: 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'                                  # Expected: 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'                                  # Expected: 200
```

### 2. Health & Readiness Checks
```bash
curl https://agent-production-143225b4.up.railway.app/health
# Expected: {"status":"ok","uptime_seconds":...,"environment":"production","timestamp":"..."}

curl https://agent-production-143225b4.up.railway.app/ready
# Expected: {"status":"ready","redis":"ok"}
```

### 3. API Test (with Authentication)
```bash
curl -X POST https://agent-production-143225b4.up.railway.app/ask \
  -H "X-API-Key: <YOUR_AGENT_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

## Environment Variables Set
- `PORT` (`8000`)
- `ENVIRONMENT` (`production`)
- `LOG_LEVEL` (`INFO`)
- `REDIS_URL` (`${{Redis.REDIS_URL}}` — linked to Railway Redis service)
- `AGENT_API_KEY` *(secret configured on Railway, not stored in repository)*
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`1.0`)
- `MONTHLY_BUDGET_USD` (`10.0`)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
