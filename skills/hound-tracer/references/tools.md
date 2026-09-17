# Hound Engine Tool Map

Use discovered names and schemas because clients may namespace tools.

- Diagnose artifacts: `hound_analyze`; retrieve large report sections through `hound://report{?path,section}` or `hound_read_report` fallback.
- Capture commands: `hound_log_command` (execute capability plus explicit command opt-in).
- Gate: `hound_check_gate`.
- History/incident reads: `hound_get_insights`, `hound_list_incidents`.
- History writes: `hound_history_import`, `hound_history_export`.
- Feedback: `hound_feedback_list`, `hound_feedback_record`.
- Audit/eval: `hound_validate_report`, `hound_evaluate`.
- Readiness: `hound_doctor`.

Compatibility adapters `hound_history_transfer` and `hound_feedback` are deprecated. Prefer operation-specific tools.

Every response envelope has `status`, `summary`, `data`, `artifacts`, and `next_actions`. Protocol success does not imply test/gate success; inspect `data`.
