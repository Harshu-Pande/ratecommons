---
title: RateCommons API
emoji: 🩺
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: Query server behind ratecommons.org (API and MCP)
---

The query server behind [ratecommons.org](https://ratecommons.org): negotiated healthcare prices published under the
Transparency in Coverage rule, answered from the public data in the `ratecommons` Hugging Face organization.

- JSON tools: `POST /api/tool/<name>` (schemas at `GET /api/tools`)
- MCP (streamable HTTP): `POST /mcp`
- Source: https://github.com/Harshu-Pande/ratecommons (`cloud/api`, `cloud/server`). This Space builds the commit in the
  `RC_CODE_REF` variable.
