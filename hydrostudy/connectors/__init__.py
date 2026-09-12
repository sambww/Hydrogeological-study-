"""Phase 2 connectors: populate a project's data/ folder from public sources on a machine with internet access.

None of these run during `hydrostudy run`; the pipeline reads local files only. They were written against the
documented public endpoints but could not be exercised in the sandbox where this package was built (external hosts
blocked), so treat the first run on a networked machine as a validation step and report failures as issues."""
