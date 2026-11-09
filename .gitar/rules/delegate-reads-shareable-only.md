---
title: "Delegates read shareable memory only"
description: "Code in src/rapport_delegate may only query shareable_index(SELF_ORG) and the conference index, and may only send record summaries."
when: "A PR changes files under src/rapport_delegate/"
actions: "Request changes if delegate code references internal_index, the briefer, es-briefer credentials, an index taken from input, or sends a record's text field"
---

## When to Use This

A PR changes files under src/rapport_delegate/.

## How It Works

Request changes if delegate code references internal_index, the briefer, es-briefer credentials, an index taken from input, or sends a record's text field. Point to the exact lines and the relevant section of docs/SPEC.md or AGENTS.md.

## Why This Matters

The delegate talks to another company. It must not be able to leak what it never saw.
