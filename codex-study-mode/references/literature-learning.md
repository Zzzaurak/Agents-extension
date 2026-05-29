# Literature-Based Learning

Use this reference when the user chooses `根据文献学习` or asks to learn from a `research-literature-pipeline` project.

## Source Project

The expected project root is usually one of:

- `research-literature-pipeline/projects/<slug>/` inside the current workspace.
- A user-provided absolute or relative project path.

If the user provides a slug, first look for `research-literature-pipeline/projects/<slug>/` from the current workspace and nearby project roots. If the user provides an absolute or relative path, use that path after verifying it exists.

## Preferred Reading Order

Read artifacts in this order:

1. `project.toml`: project topic, Zotero tags, selected statuses, and pipeline settings.
2. `maps/literature-map.md`: field-level structure, claims, timeline, methods, controversies, and open questions.
3. `notes/*.md`: structured Chinese reading notes for individual papers.
4. `papers/<paper-id>/metadata.json`: paper metadata when needed.
5. `papers/<paper-id>/paper.md`: full MinerU Markdown only when notes or map are insufficient.

Do not begin with all full paper Markdown. Use progressive disclosure to keep context focused.

## Missing Artifact Rules

- If `project.toml` is missing, the directory is not a valid literature project.
- If `notes/*.md` is missing, say that literature-level teaching can only use project metadata or the literature map.
- If `paper.md` is missing for a paper, do not claim the full paper has been read.
- If full-paper learning is needed but `paper.md` is missing, recommend running the existing `research-literature-pipeline` read step before continuing.

When using `paper.md`, state that it is MinerU Markdown extracted from the PDF and may not preserve all visual layout.

## Learning Route From Literature

Build the stage route from the project and papers:

1. Field orientation: what the project is trying to understand.
2. Background concepts: prerequisites needed to read the selected papers.
3. Paper problem statements: what each major paper asks.
4. Method families: observational, theoretical, simulation, statistical, or instrumental methods.
5. Key models and equations: only those needed for understanding the claims.
6. Evidence chain: how claims are supported by data, figures, or derivations.
7. Limitations and controversies.
8. Open questions and how the user could judge new papers.

Tie explanations to specific paper notes or literature-map claims when possible. Distinguish paper claims from the assistant's synthesis.

## First Response In Literature Mode

If the user gives a project slug or path, inspect the available artifacts and then respond with:

- Resolved project path.
- Available learning sources: project config, map, note count, paper Markdown count.
- A staged learning route tied to those sources.
- The first short teaching stage, unless key artifacts are missing.

If the user only says they want literature-based learning without a project, ask for the slug or path.

## Relationship To Research Pipeline Skill

This study skill does not replace `research-literature-pipeline`.

Use `research-literature-pipeline` for collecting papers, converting PDFs through MinerU, generating reading notes, updating literature maps, and exporting BibTeX. Use this study skill after those artifacts exist, or when the user wants a conceptual learning path from them.
