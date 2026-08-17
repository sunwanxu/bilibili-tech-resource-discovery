# Adaptive clarification before discovery

Use this reference when a natural-language request names a goal but leaves an important technical
route unresolved. The purpose is not to collect every preference. It is to prevent one early,
unstated assumption from sending the entire search down the wrong branch.

## Decision-axis gate

1. Extract facts already supplied: goal, experience, fixed parts, environment, budget, expected
   result, and any rejected route.
2. List unresolved choices that could change at least one of: system architecture, primary parts,
   software/toolchain, learning prerequisites, useful search terms, or the artifacts the user can
   reuse.
3. Remove choices that merely change ranking or can be decided after seeing results.
4. Ask only the remaining choice with the largest downstream effect. Use plain consequences instead
   of unexplained jargon.
5. Validate the answer against fixed facts. Record it as a constraint, or record comparison mode.
6. Repeat only while another unresolved choice would still send discovery down a materially different
   branch. Then search.

This is dynamic slot filling: required information depends on previous answers. Do not use a fixed
question count or a domain-specific keyword table.

## How to phrase the question

Use one short question with two to four realistic routes. Each choice should contain:

- the route name;
- one consequence the user can understand;
- no assumption that the user already knows which route is correct.

Always allow one of these exits when relevant:

- “不确定，先比较这些路线” — branch the search and explain tradeoffs;
- “我有其他方案” — accept the user's own route;
- “直接搜索” — stop asking and use stable defaults.

Do not recommend a route before learning the constraint that distinguishes it. If the available
routes are not reliable knowledge, first consult official documentation or maintained open-source
implementations, then ask. That check discovers the choice set; it does not replace user consent.

## Cross-domain examples

| Request | High-impact question | Skip when |
|---|---|---|
| 搭建云台 | servo / stepper / brushless / compare; these lead to different drivers and control code | actuator and use case are explicit |
| 做远距离传感器 | battery life, range, and available network decide LoRa / cellular / Wi-Fi-class routes | radio and network are fixed |
| 部署本地 AI | device class and latency/privacy decide CPU / GPU / edge accelerator routes | target device is named |
| 画电源 PCB | input/output, power, isolation, and topology determine entirely different references | topology and electrical limits are fixed |
| 学某个 fixed-version framework | usually no architecture question; ask level or desired endpoint only | alternatives would retrieve nearly the same tutorial set |

The examples demonstrate the rule; they are not a runtime allowlist.

## Propagate the answer

For one selected route:

```text
--constraint "<selected route>" --query "<topic + selected route + requested artifact>"
```

For comparison mode, preserve a shared base topic and build separate queries, for example one query
per route plus at most one comparison query. Keep results grouped by route so a popular route does
not hide viable alternatives. State when a route has weak evidence instead of filling the gap with
assumptions.

Before executing, silently verify:

- the selected route appears in the intent constraints;
- every precise query contains either that route or an explicit comparison purpose;
- the report can explain which user answer caused the branch;
- no answered question is asked again.
