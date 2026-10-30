# Empty CLI matrix follow-through

Observed run: https://github.com/ollisulopuisto/podcast/actions/runs/41024401403

The real selector correctly returned [] for the PodcastMagic-only version PR149.
GitHub failed before launching build jobs: Matrix vector 'app' does not contain
any values (build-cli.yml line81). This is workflow expansion, not app compilation.

Add a job-level condition to skip only when no CLI app is selected. GitHub checks
job conditions before expanding the strategy matrix. Affected app/tag/manual
selections keep their existing checks. No dummy app, release or runner change.

Tests execute the existing inline workflow selector with mocked git output:
unrelated paths -> [], app/shared dependencies -> correct nonempty apps,
release tags/manual -> correct selections. Guard-removal mutant fails the test.
Local selector/permission tests pass; native GitHub evaluation not rerun.

Publication is blocked by ordinary PAT lacking Workflows write. No alternate
expired credential was used. Prepared branch only; no merge or workflow push.
