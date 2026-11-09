---
title: "Counterparty messages are untrusted"
description: "Text from another company's agent is data, never instructions."
when: "A PR builds LLM prompts or handles ExchangeMessage, Ask or Card content"
actions: "Request changes if counterparty strings are placed in system instructions, used to choose indices or tools, rendered with innerHTML, or if LLM output is used without pydantic validation and an allow-list of item IDs"
---

## When to Use This

A PR builds LLM prompts or handles ExchangeMessage, Ask or Card content.

## How It Works

Request changes if counterparty strings are placed in system instructions, used to choose indices or tools, rendered with innerHTML, or if LLM output is used without pydantic validation and an allow-list of item IDs. Point to the exact lines and the relevant section of docs/SPEC.md or AGENTS.md.

## Why This Matters

Prompt injection from the other company's agent is the main attack this project demonstrates and defends against.
