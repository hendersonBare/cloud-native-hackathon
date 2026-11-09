---
title: "Memory records carry org_id and share_level"
description: "Every Elasticsearch write goes through rapport_common.models.MemoryRecord and names.index_for()."
when: "A PR adds or changes code that writes documents to Elasticsearch"
actions: "Request changes if a write bypasses MemoryRecord validation or index_for(), hard-codes an index name, or omits org_id or share_level"
---

## When to Use This

A PR adds or changes code that writes documents to Elasticsearch.

## How It Works

Request changes if a write bypasses MemoryRecord validation or index_for(), hard-codes an index name, or omits org_id or share_level. Point to the exact lines and the relevant section of docs/SPEC.md or AGENTS.md.

## Why This Matters

Index routing is the security boundary: a record in the wrong index can leak to another company's delegate.
