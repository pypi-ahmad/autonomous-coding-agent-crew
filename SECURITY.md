# Security Policy

Autonomous Coding Agent Crew is a local-first tool: it runs on your own machine, with your own API keys, against your own files. There is no hosted service and no server component operated by the maintainer.

## Scope

In scope: vulnerabilities in this repository's code (e.g. path-jail bypass, command-injection in the shell/terminal tools, unsafe deserialization, secret leakage into logs/exports).

Out of scope: the security of your own machine, your own API keys, your own `.env`, or third-party provider APIs (Ollama, OpenAI, Agnes AI, Google) — those are your responsibility per [DISCLAIMER.md](DISCLAIMER.md).

## Reporting a vulnerability

Please do **not** open a public issue for security reports. Instead use GitHub's private [Security Advisory](https://github.com/pypi-ahmad/autonomous-coding-agent-crew/security/advisories/new) form, or email the maintainer via the address on their GitHub profile.

Include: affected file/module, reproduction steps, and impact. Expect an acknowledgment within a few days — this is a volunteer-maintained project, not a funded security team.

## Disclosure

No bug bounty is offered. Credit is given in the fix's release notes unless you ask otherwise.
