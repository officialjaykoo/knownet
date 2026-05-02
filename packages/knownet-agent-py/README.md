# KnowNet Agent Python SDK

Small HTTP client for scoped KnowNet agent tokens.

```python
from knownet_agent import KnowNetClient

client = KnowNetClient.from_env()
print(client.me().data)
```

Required environment:

```txt
KNOWNET_AGENT_TOKEN=<token shown once by the operator dashboard>
KNOWNET_BASE_URL=http://127.0.0.1:8000
```

The SDK does not read KnowNet's SQLite database and does not implement a second
auth model. Writes go through the existing KnowNet API.
