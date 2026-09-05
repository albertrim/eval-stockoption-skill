---
description: 우리 회사가 코스닥에 상장하면 예상 시총·주당 가격이 얼마인지 계산한다 — 질문 8개
argument-hint: "[회사 이름]"
allowed-tools: Bash, Read, Write, AskUserQuestion, Skill
---

`Skill` 도구로 `ipo-eval:ipo-eval`을 부르고, 그 SKILL.md의 **회사 모드** 절차를 그대로 따른다.

- 모드는 이미 정해졌다. "회사 / 옵션" 중 무엇을 할지 다시 묻지 않는다.
- 아래에 회사 이름이 적혀 있으면 질문 1번의 답으로 쓰고, 바로 DART 조회(1-a)로 넘어간다.
  비어 있으면 질문 1번부터 시작한다.

회사 이름: $ARGUMENTS
