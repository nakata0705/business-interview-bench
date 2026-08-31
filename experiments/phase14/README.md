# Phase 14 calibration set

`calibration.json` is a deliberately small experiment manifest with one
reproducible run for each initial calibration scenario:

- `lab_sample_flow` — profile `phase14-lab-technician`, seed `1401`
- `quotation_workflow_1` — profile `phase14-sales-owner`, seed `1402`
- `quotation_workflow_1_ja` — profile `phase14-sales-owner-ja`, seed `1403`

Each entry fixes the scenario, profile, projection seed, runtime limits,
generation settings, epoch, and run index. Model names are environment
placeholders; no API key or credential is stored here:

```bash
export PHASE14_CANDIDATE_MODEL='your-provider/your-candidate-model'
export PHASE14_STAKEHOLDER_MODEL='your-provider/your-stakeholder-model'
```

The authoritative Phase 14 launch artifact is one complete Inspect run config.
Rendering resolves both model placeholders and fails clearly if either variable
is unavailable:

```bash
python -m business_interview_bench.phase14 run-config \
  experiments/phase14/calibration.json --run-index 0 \
  --output /tmp/phase14-run-0.yaml
inspect eval --run-config /tmp/phase14-run-0.yaml
```

The generated config contains the registered task and all task args, the
candidate model, the `stakeholder` model role and generation config, the
candidate `generate_config`, and `eval_config.epochs`. The runtime hard bound
`candidate_max_tokens` remains a task argument; if candidate GenerateConfig
also specifies `max_tokens`, it must match that bound. Provider credentials
remain in the provider's normal environment configuration.

`task-config` remains available as a task-argument helper, but it is not the
reproduction artifact for Phase 14.

After an eval, extract a safe per-run summary and aggregate one or more logs:

```bash
python -m business_interview_bench.phase14 summarize logs/run.eval
python -m business_interview_bench.phase14 summarize logs/*.eval \
  --output phase14-summary.json
```

The schema-versioned JSON contains all 41 primary-evaluation fields,
authoritative terminal completion/failure classification, separate recoverable
error and semantic attempt diagnostics, model/runtime usage where Inspect
recorded it, and scenario/model groups. It does not dump Truth, exact
`StakeholderKnowledge`, or the full stakeholder profile.
