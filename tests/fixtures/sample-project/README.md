# Hound sample project

This fixture is a dependency-free Python project with a `package.json` command manifest. It exercises Hound's workspace, project runs, artifact discovery, RCA, batch analysis, incident deduplication, test history, coverage, SARIF, and quality-gate surfaces.

Run from this directory:

```sh
python scripts/run_checks.py test
```

Available scenarios:

```sh
python scripts/run_checks.py test       # deterministic failure, exit 1
python scripts/run_checks.py pass       # passing JUnit evidence, exit 0
python scripts/run_checks.py flaky      # intermittent-style evidence, exit 1
python scripts/run_checks.py artifacts  # generate every fixture artifact, exit 0
python scripts/run_checks.py build      # successful build output
python scripts/run_checks.py lint       # successful lint output
```

The failure scenario produces:

- command output suitable for capture as `.log`;
- JUnit XML;
- structured test-result JSON;
- SARIF security findings;
- Cobertura coverage XML;
- an application failure log.

Suggested manual Hound workflow from this directory:

```sh
hound init
hound log --analyze --offline -- python scripts/run_checks.py test
hound analyze . --offline
hound batch . --offline
hound insights import test-results --run-id sample-failure
hound insights tests
hound gate test-results --baseline-ref HEAD --candidate-ref HEAD --repo-dir . --coverage reports/coverage.xml --sarif reports/security.sarif --policy quality.yml --report-only
hound incidents list
hound console
```

`deploy` and `clean` scripts intentionally exist only to verify that command discovery does not suggest destructive operations. The script refuses to perform either action.
