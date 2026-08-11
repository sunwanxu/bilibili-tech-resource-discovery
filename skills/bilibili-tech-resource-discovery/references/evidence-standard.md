# Evidence and reporting standard

## Contents

- Open-source labels
- Completeness language
- Evidence hierarchy
- Required report shape

## Open-source labels

Use exactly one primary label per resource:

1. `明确许可证且已验证` — A repository or project page exposes a verifiable license/SPDX value.
2. `平台声称许可证，条款待复核` — A hosting platform displays a license claim, but platform terms
   or retrieved evidence need review.
3. `作者提及许可证，未独立验证` — Description, comment, or README mentions a license without a
   verified repository license record.
4. `公开源码，无许可证证据` — Source files are publicly accessible but no license was verified.
5. `共享文件，授权不明确` — Cloud files, group files, documents, or designs are shared without a
   clear reuse license.
6. `承诺开源，未找到链接` — The author promises a future release but no usable link was found.
7. `声称开源，未找到链接` — The content calls itself open source but no usable source location was
   found.
8. `无开源证据` — No source or license evidence was found.

Do not equate downloadable, visible, cloneable, free-of-charge, or described as “资料” with open
source.

Apply labels to their actual scope. When one component has a verified license but other key project
resources are unverified, use project-level `授权范围不完整` and retain the verified license only on
that component. Never propagate a component license to an entire competition solution.

## Completeness language

For schematic, PCB, BOM, Gerber, firmware/source code, documentation, hardware validation, and
license, use:

- `已发现` when direct evidence exists;
- `未发现证据` when inspection did not reveal it;
- `需登录或人工确认` when access prevented inspection.

Never rewrite `未发现证据` as `不存在`.

## Evidence hierarchy

Prefer evidence in this order for the claim it supports:

1. license file, repository tree, release artifact, or directly inspected project page;
2. author-controlled README or linked documentation;
3. Bilibili description or pinned author comment;
4. ordinary viewer comment;
5. title, tag, or search snippet;
6. inference.

Label inference explicitly. Viewer comments are useful leads, not proof of licensing or technical
correctness.

## Required report shape

1. Restate the interpreted need and assumptions.
2. Summarize search scope and expanded keywords.
3. Present five to ten prioritized usable project resources before videos.
4. For each resource, give its direct link, value, usability, open-source label, license scope,
   artifact completeness, evidence origins, supporting Bilibili links, and limitations.
5. Present useful explanatory videos after the resource list; separate videos with no usable project
   evidence.
6. Compare distinct technical approaches when applicable.
7. Separate login-restricted, inaccessible, and unverified leads at the end.
8. State subtitle/comment/video-viewing limitations, blind spots, and why the search stopped.
