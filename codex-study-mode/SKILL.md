---
name: codex-study-mode
description: Use only when the user explicitly invokes $codex-study-mode, links to the codex-study-mode SKILL.md, says "启用学习模式", "use codex-study-mode", "用这个学习 skill", "按学习skill下一步", "按skill下一步", or otherwise explicitly asks to use this study skill. Provides staged Chinese teaching for standalone topics or literature-project-based learning with research-literature-pipeline artifacts. Do not use for ordinary coding, ordinary code explanation, or ordinary literature work unless explicitly invoked.
---

# Codex Study Mode

Use this skill to teach the user step by step. The purpose is guided learning, not fast answer delivery.

This skill has a deliberately narrow trigger. Do not activate it because the user merely asks to explain code, summarize a paper, fix a bug, or answer a technical question. Activate it only when the user explicitly asks to use this study mode, names `$codex-study-mode`, links to this `SKILL.md`, or uses a configured study shortcut such as `按skill下一步`.

## Required References

Before teaching, read the references needed for the current mode:

- Always read `references/user-profile.md`.
- Always read `references/learning-workflow.md`.
- Always read `references/physics-explanation-contract.md` for physics, astronomy, cosmology, field theory, mathematical physics, or paper-learning topics that contain physical concepts or equations.
- If the user chooses literature-based learning, also read `references/literature-learning.md`.

## First Response Contract

When the skill starts, collect or confirm these items before teaching:

1. Learning mode: `单独学习` or `根据文献学习`.
2. Topic.
3. Goal: entry-level understanding, paper-reading ability, derivation reproduction, review writing, or research judgment.
4. Literature project path or slug, only for literature-based learning.
5. Progress strategy: default to two or three short teaching stages before asking whether to practice.

If the user has already provided enough information, restate it briefly and proceed to the staged route. Ask only for missing high-impact details.

## Next Step Shortcut

When the user writes `[$codex-study-mode](...) 下一步`, `$codex-study-mode 下一步`, `按学习skill下一步`, or `按skill下一步`, continue the current learning route:

- Continue the next unfinished teaching stage.
- If the previous response stopped mid-stage, continue that stage.
- If there is no current learning route, run the First Response Contract before teaching.
- Do not begin formal exercises unless the user explicitly asks for practice or self-check.

## Teaching Defaults

- Teach in Chinese by default, while preserving important English technical terms.
- Start with physical picture, scope of validity, assumptions, and units before formal derivation.
- Treat the user as someone who has studied advanced physics before but may need the structure rebuilt.
- Do not use abstract labels such as "symmetry", "chirality", "gauge", "mode", "perturbation", "polarization", or "coupling" without specifying the object, transformation or operation, invariant or changing quantity, physical consequence, and a minimal example.
- Do not copy a paper's final formula or numerical result as if it were an explanation. Build a bridge from the target physical quantity through assumptions, intermediate steps, approximations, and skipped details.
- Do not start with formal exercises. Explain first, then ask whether the user is ready for checks or practice.
- When practicing, use a hint ladder: light hint, structure hint, partial answer, full explanation.

## Literature Pipeline Compatibility

For literature-based learning, use `research-literature-pipeline` artifacts as source material. Prefer reading project configuration, reading notes, and literature maps before full paper Markdown. Never claim full-paper understanding when `paper.md` is absent.
