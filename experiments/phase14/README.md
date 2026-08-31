# Phase 14 calibration set

`calibration.json` is a deliberately small experiment manifest with one
reproducible run for each initial calibration scenario:

- `lab_sample_flow` — profile `phase14-lab-technician`, seed `1401`
- `quotation_workflow_1` — profile `phase14-sales-owner`, seed `1402`
- `quotation_workflow_1_ja` — profile `phase14-sales-owner-ja`, seed `1403`

Each entry fixes the scenario, profile, projection seed, interview/generation
limits, candidate generation parameters, epoch, and run index. Model names are
environment placeholders; no API key or credential is stored here:

```bash
export PHASE14_CANDIDATE_MODEL='your-provider/your-candidate-model'
export PHASE14_STAKEHOLDER_MODEL='your-provider/your-stakeholder-model'
```

The manifest is not a provider credential file. Render the task arguments for
one run, then supply the model names and generation parameters through the
normal Inspect CLI/provider configuration:

```bash
python -m business_interview_bench.phase14 task-config \
  experiments/phase14/calibration.json --run-index 0 \
  --output /tmp/phase14-task.json

inspect eval business_interview_bench/phase13_interview \
  --task-config /tmp/phase14-task.json \
  --model "$PHASE14_CANDIDATE_MODEL" \
  --model-role "stakeholder={model: $PHASE14_STAKEHOLDER_MODEL, temperature: 0}" \
  --temperature 0
```

Set Inspect's `--epochs` to the `epoch` value in the selected manifest entry.
The `candidate_generation` and `stakeholder_generation` objects are explicit
launch settings; apply them through the corresponding Inspect generation/model
role options. The initial set uses temperature `0.0` and one epoch, but the
harness does not claim statistical significance.

After an eval, extract a safe per-run summary and aggregate one or more logs:

```bash
python -m business_interview_bench.phase14 summarize logs/run.eval
python -m business_interview_bench.phase14 summarize logs/*.eval \
  --output phase14-summary.json
```

The JSON contains model/runtime usage where Inspect recorded it, all 41
primary-evaluation fields, deterministic failure/quality diagnostics, and
scenario/model groups. It does not dump Truth, exact stakeholder knowledge,
or the full stakeholder profile.
