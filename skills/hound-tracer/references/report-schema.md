# Hound Report Use

Start from the bounded `failure`, `root_cause`, and `triage` summary returned by `hound_analyze`. Use `report_path` and `available_sections` to request only needed report content. Typical sections include `meta`, `failure`, `root_cause`, `triage`, `context`, timeline/investigation data, and ticket output depending on evidence.

Confirm cited source locations before editing. Low-confidence hypotheses and missing stores are insufficient evidence, not successful outcomes.
