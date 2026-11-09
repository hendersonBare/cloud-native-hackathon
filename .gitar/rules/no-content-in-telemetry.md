---
title: "No content in telemetry or logs"
description: "Spans, metrics and logs carry IDs, counts, decisions and rule IDs only."
when: "A PR adds span attributes, metric attributes or log statements"
actions: "Request changes if memory text, prompts, LLM responses, asks, briefs, CV text, emails or API keys could reach a span, metric or log line"
---

## When to Use This

A PR adds span attributes, metric attributes or log statements.

## How It Works

Request changes if memory text, prompts, LLM responses, asks, briefs, CV text, emails or API keys could reach a span, metric or log line. Point to the exact lines and the relevant section of docs/SPEC.md or AGENTS.md.

## Why This Matters

Telemetry goes to a third-party backend and must never carry personal or confidential data.
