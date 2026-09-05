---
description: 보유한 스톡옵션의 세후가치와 현재가치를 계산한다 — 질문 7개
argument-hint: "[회사 이름]"
allowed-tools: Bash, Read, Write, AskUserQuestion, Skill
---

`Skill` 도구로 `ipo-eval:ipo-eval`을 부르고, 그 SKILL.md의 **옵션 모드** 절차를 그대로 따른다.

- 모드는 이미 정해졌다. "회사 / 옵션" 중 무엇을 할지 다시 묻지 않는다.
- 먼저 `profiles`를 확인한다. 저장된 회사가 없거나 그 회사의 `result.company`가 없으면
  **회사 모드부터 해야 한다**고 알리고 그쪽을 먼저 진행한다.
- 아래에 회사 이름이 적혀 있으면 질문 1번의 답으로 쓴다.

회사 이름: $ARGUMENTS
