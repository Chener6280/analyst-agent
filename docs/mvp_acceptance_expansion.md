# MVP Acceptance Expansion

Current acceptance proof run:

- scan_id: `manual-2026-06-01-2026-06-07-v1`
- eligible manual samples: 10
- global acceptance target: 10 covered teams and 5 extracted stance samples
- latest MVP acceptance: passed
- acceptance report: `~/macro-strategy/diagnostics/mvp_acceptance.md`

Current eligible samples:

| analyst_id | status |
|---|---|
| 广发证券:macro | partial |
| 华创证券:macro | partial |
| 国金证券:strategy | covered |
| 兴业证券:macro | partial |
| 中信建投:macro | partial |
| 中金公司:macro | partial |
| 国泰海通:macro | partial |
| 申万宏源:macro | partial |
| 招商证券:macro | partial |
| 中国银河:macro | partial |

Latest acceptance metrics:

| metric | actual |
|---|---:|
| coverage teams | 10 |
| covered + partial rate | 100% |
| full/partial text rate | 100% |
| high/med attribution rate | 100% |
| extracted samples | 10 |
| sqlite stance rows | 50 |

Generate or refresh templates:

```bash
python3 scripts/scaffold_manual_wechat_templates.py \
  --analyst-list data/analyst-list-acceptance-candidates.md \
  --max-teams 10 \
  --output-dir ~/macro-strategy/manual_wechat_articles/2026-W23
```

Audit the real sample gap:

```bash
python3 scripts/audit_manual_wechat_gap.py \
  --analyst-list data/analyst-list-acceptance-candidates.md \
  --max-teams 10
```

Run the full gated pipeline:

```bash
python3 scripts/run_mvp_pipeline.py \
  --analyst-list data/analyst-list-acceptance-candidates.md \
  --max-teams 10
```

Do not rename `.md.template` files to `.md` until they contain real article metadata and article text or a short, source-verifiable excerpt. Templates are ignored by coverage.
