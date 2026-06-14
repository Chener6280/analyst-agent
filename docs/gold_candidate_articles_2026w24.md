# Gold Candidate Articles - 2026-W24

These five articles were manually confirmed by the user as the latest articles
from the target WeChat accounts on 2026-06-14. They are candidates for the
human-labeled extraction gold set, not active gate rows yet.

Because this repository is public, this file records public article metadata
only. Do not commit phone screenshot paths, images, or long article bodies here.
When promoting a candidate into the active gold set, add a human-labeled row to
`tests/gold/extraction_gold.jsonl` or use a private local gold file with
`scripts/check_extract_accuracy.py --gold`.

| id | date | institution | role | account | title | label status |
|---|---|---|---|---|---|---|
| gold_2026w24_hczq_macro_zhangyu_finance_data | 2026-06-13 23:54 | 华创证券 | macro | 一瑜中的 | 贷款分析范式的两个变化——2026年5月金融数据点评 | needs human ordinal labels |
| gold_2026w24_gjzq_strategy_old_world | 2026-06-14 15:50 | 国金证券 | strategy | 一凌策略研究 | 推开旧世界的门｜国金策略 | needs human ordinal labels |
| gold_2026w24_zxjt_strategy_weekly | 2026-06-14 11:37 | 中信建投 | strategy | CSC研究 策略团队 | 【中信建投策略】震荡寻机，预期校准——中信建投策略周思考 | needs human ordinal labels |
| gold_2026w24_gfzq_macro_cycle_overlap | 2026-06-14 17:00 | 广发证券 | macro | 郭磊宏观茶座 | 【广发宏观团队】目前处于周期叠加的什么阶段？ | needs human ordinal labels |
| gold_2026w24_xyzq_strategy_global_tech_calls | 2026-06-14 07:53 | 兴业证券 | strategy | XYSTRATEGY | 【兴证策略】200+全球科技龙头：Earnings Call有何指引？ | needs human ordinal labels |

## Promotion Checklist

1. Save the full article body into a private/local source or a copyright-safe
   short excerpt suitable for testing.
2. Fill the role-specific ordinal `expected` map by human judgment. Current
   macro ordinal keys are `growth`, `inflation`, `monetary`, `fiscal`, and
   `overseas`; current strategy ordinal keys are `market_view` and `liquidity`.
3. Run:

```bash
python3 scripts/check_extract_accuracy.py \
  --gold tests/gold/extraction_gold.jsonl \
  --diagnostics-dir outputs/diagnostics
```

4. Only treat the row as a true gold sample after the human labeler confirms
   every non-null value and every intentional `null`.
