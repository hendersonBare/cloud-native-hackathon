---
title: "Flag security-sensitive changes for a human"
description: "Changes to policy, RBAC, NetworkPolicy, Secrets, uploads and redaction, or the handling of counterparty messages need human review."
when: "A PR touches policy/, deploy/base/, any RBAC or NetworkPolicy manifest, secret handling, src/rapport_briefer upload or redaction code, or src/rapport_delegate message handling"
actions: "Comment that human security review is required and check the PR description has a 'Security review needed' section listing the files"
---

## When to Use This

A PR touches policy/, deploy/base/, any RBAC or NetworkPolicy manifest, secret handling, src/rapport_briefer upload or redaction code, or src/rapport_delegate message handling.

## How It Works

Comment that human security review is required and check the PR description has a 'Security review needed' section listing the files. Point to the exact lines and the relevant section of docs/SPEC.md or AGENTS.md.

## Why This Matters

Organization policy requires human review of security-sensitive code before merging.
