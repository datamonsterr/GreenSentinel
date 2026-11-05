# PR #258 body (refresh — paste as PR description; `gh` unauthenticated locally)

## feat(benchmark): 30k-trip fraud benchmark dataset, EDA suite, generator fixes

Closes #248–#257, #266, #270, #271, #275, #276. Refs epic #247.
Follow-ups left open (detector behavior, need safety review): #260–#265.

### What is in (branch `build-benchmark-dataset`, squash-merge on VALIDATED)

- 3 × 10k batches, exact class mix each (7000/800/600/500/500/300/300):
  v1 seed 20261011 (sha `b6aed4a2…`, acc 0.7043) / v2 seed 20261012
  (sha `8675f823…`, acc 0.6778, silent/empty dialogues, customer actions,
  ratings) / v3 seed 20261013 (sha `8ba37647…`, acc 0.6583, G1 slow-crawl
  233 + G2 loop 138). 30k union 21000/2400/1800/1500/500… (full: see
  `docs/data/BENCHMARK.md` §9). Combined acc **0.6801**,
  macro-F1 **0.4904**, 0 cross-batch duplicates (ref/id/assignment/geometry).
- 6 EDA reports replacing assumptions with measured priors (Porto 50k,
  NYC TLC 2.87M, MultiWOZ 1,872, PaySim 530k, Nayfeh 7k, MiPo 2.7k).
- Generator fixes (#248): gridlock CHECK violation, stall GPS drift +
  sampled accuracy, SSD 240 s measured, nullable coverage/gap migration,
  ERR-01/03/04 label CHECKs.
- Scale-up command: `/benchmark-grow` — one canonical file
  `.agents/commands/benchmark-grow.md`, thin pointers for
  opencode/claude/agy/codex-skill.
- Reviewer guide: `docs/data/README.md` (15-min path, exact
  pass criteria). Validation: #259.

### What is NOT in

No `src/` detector behavior change. No production DB migration apply
(sync migration ships with rollback; apply at ops time). Bulk trips
(~450 MB) git-ignored; `sample_100` + manifests + `combined_labels.csv`
tracked.

### Known gaps (do not re-report)

v2 ships no `seed_data.sql`; ERR-03/ERR-04 recall 0 by construction
(#262–#264); legit-cancel deferral is correct behavior scored as error
(#265); E2E Playwright CI failure is infra (fails on `main`, zero
frontend/API files in diff).
