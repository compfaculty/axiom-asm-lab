# Target benchmark and promotion protocol

The existing runner is a bootstrap and does not yet meet this protocol. Implement M003 before using automated performance promotion.

## Fair comparison
Use identical typed contracts, input bytes, output requirements, allocation scope, toolchain, and supported CPU target features. Compile reference code in a separate translation unit without LTO initially, so calls remain comparable. Capture flags and disassembly. Keep baseline and candidate under the same harness. Never time a Python loop around individual native calls.

For unsigned sum, input generation and allocation occur outside the timed interval. A checksum consumes results. Count bytes read as n*8 per call; this is logical traffic, not measured DRAM traffic. Report ns/call and logical GiB/s where n>0. Empty/small inputs are dominated by fixed overhead. Do not subtract noisy overhead samples to manufacture a gain.

## Sampling
Calibrate iterations to at least 20 ms per sample with an upper bound. Warm up before measurement. Use at least 30 paired candidate/baseline samples per size in a session, randomize order with a recorded seed, and keep raw samples. Run at least two independent sessions for a promotion claim. Record power mode/background-load notes. Exclude a sample only under a rule declared before collection; retain exclusions and reasons. Include cache-resident and larger-than-last-level-cache inputs when feasible, based on recorded machine data, with memory caps.

## Analysis and default gate
Predeclare objective sizes and equal weights. For each pair compute baseline_time/candidate_time; aggregate using the geometric mean across size medians. Use a seeded paired bootstrap with 10,000 resamples to estimate a 95% interval for this aggregate. Test analysis with known synthetic data including ties, regressions, outliers and missing measurements. Default promotion requires aggregate speedup >=1.05, its interval lower bound >1.0, and no required size median slowdown >3%, in both sessions. These are project defaults, not universal statistical guarantees. If the hardware is too noisy, label inconclusive and improve the experiment.

Record thresholds before the search. Tuning uses training sizes; final candidates must also pass held-out sizes/distributions to reduce benchmark overfitting. Selection among many candidates can inflate apparent gains; report search count and validate the winner with fresh measurements. A candidate can be correct and useful for learning without passing promotion.

## Stop rules
Default search: 20 proposals, 30 minutes of local evaluation, 5 consecutive correct candidates without an objective improvement, whichever arrives first. Record which bound stopped it. API budget is zero until configured. Partial/time-out runs never imply success.
