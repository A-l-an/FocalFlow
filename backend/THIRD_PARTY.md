# Third-party provenance and redistribution inventory

**Current source release (2026-10-13):** original FocalFlow source and documentation
now use the root [Apache-2.0 license](../LICENSE). See the current
[licensing scope](../docs/licensing-status.md) for third-party and distribution
boundaries. The dated inventory below is preserved unchanged: its earlier absence
of a project license and open publication questions describe that historical
snapshot, not the current license selection. Dependencies and models keep their
own terms; no blanket Apache grant is assigned to them.

This is an offline, static inventory as of 2026-09-26, inspected at commit
`b31058f974721761f8c15f35c98b699e46194ab1`. It records local evidence and open
questions; it does not grant a project license, determine ownership, or approve
publication. File/line references describe that snapshot.

## Source and project ownership

The inspected tracked tree has 20 files and no tracked `LICENSE`, `COPYING`,
`NOTICE`, or other complete license text. A text scan of the tracked Python files
did not find explicit copyright/license headers. This does **not** establish that
those files are original work or available for redistribution.

The provenance of the project-specific implementation, including
[run.py](run.py), [MobileAgent](MobileAgent), and
[evaluation](evaluation), needs confirmation from its contributors and any
applicable institutional rights holder. In particular, directory names such as
`MobileAgent` are not evidence of an upstream project or license. No upstream
source revision or source-code license is assigned here. Retain any established
attribution when that provenance is recovered.

## Declared external dependencies

[requirements.txt](requirements.txt) retains the legacy full-environment declaration: 165
entries, comprising 163 `==` pins and two Git references. Step 09 replaced the
seven personal local-file references with versions from installed distribution
metadata; the original Step 02 baseline was 156 pins, two Git references and
seven local paths. This is not a portable installation lock or a bundled-license
inventory. The narrower supported offline dependencies and measured scope are
in [SUPPORT.md](SUPPORT.md) and [requirements-offline.txt](requirements-offline.txt).
No packages were downloaded or installed; package license metadata was not verified.

| Material | Local evidence | Confirmed declaration and remaining scope |
| --- | --- | --- |
| OpenAI CLIP dependency | [requirements.txt:24](requirements.txt#L24) | Declares `https://github.com/openai/CLIP.git` at `dcba3cb2e2827b402d2701e7e1c7d9fed8a20ef1`. The source and its license are not vendored in this tracked tree; upstream identity, license text, and any weight terms remain to be checked before bundling. |
| OpenAI Whisper dependency | [requirements.txt:80](requirements.txt#L80) | Declares `https://github.com/openai/whisper.git` at `517a43ecd132a2089d85f4ebc044728a71d49f6e`. This pin does not identify the downloaded model-weight revision. Source and weight redistribution terms have not been checked here. |
| Principal SDK/runtime declarations | [requirements.txt:30](requirements.txt#L30), [70](requirements.txt#L70), [79](requirements.txt#L79), [143](requirements.txt#L143), [147](requirements.txt#L147), [148](requirements.txt#L148) | Respectively declare DashScope `1.20.10`, ModelScope `1.18.1`, OpenAI `1.52.2`, Torch `2.4.1`, Transformers `4.45.2`, and transitions `0.9.2`. Their own notices/terms and those of other manifest entries remain separate from project ownership. |
| Former local-file dependency references | [requirements.txt:18](requirements.txt#L18), [21](requirements.txt#L21), [49](requirements.txt#L49), [51](requirements.txt#L51), [77](requirements.txt#L77), [100](requirements.txt#L100), [123](requirements.txt#L123) | These now pin cached-property `1.5.2`, cffi `1.17.0`, grpcio `1.46.3`, h5py `3.6.0`, numpy `1.24.4`, pycparser `2.22`, and six `1.16.0`, respectively. Installed metadata supports these versions only; clean installation, artifact reproducibility and local license availability are not established. |

Before distributing an environment, wheel collection, container, or executable,
record the actual included dependency versions and retain their applicable
license/attribution material. This inventory does not infer those terms from
package names.

## Models, fonts, media, and research material

| Material | Local evidence | Scope of this check |
| --- | --- | --- |
| Whisper model | [run.py:393](run.py#L393) | Code calls `whisper.load_model("base")`. The tracked tree contains no model weights; the code reference alone does not establish weight provenance or redistribution permission. No load/download was executed. |
| Other model references | [run.py:56](run.py#L56), [339](run.py#L339), [341](run.py#L341), [342](run.py#L342) | Active `qwen-vl-plus` service model name; commented GroundingDINO `v1.0.0` and two ModelScope OCR identifiers. These are references, not evidence that model artifacts are included or licensed for redistribution. |
| System fonts | [statisticAnalysis.py:24](statisticAnalysis.py#L24), [26](statisticAnalysis.py#L26), [evaluation/androidcontrol_eval.py:1763](evaluation/androidcontrol_eval.py#L1763) | Code requests installed fonts, including Arial Unicode MS, PingFang, and Microsoft YaHei. No font files are tracked. System availability does not grant permission to bundle them. |
| Media, binary artifacts, research data, and paper files | Tracked-tree enumeration at the commit above | No tracked audio, screenshots/images, model weights, fonts, executables, archives, datasets, or PDF/TeX paper artifacts remain in this 20-file candidate. This does not cover excluded local files or Git history, and does not grant permission to publish participant material or paper content. |

## Publication prerequisites still open

- Have contributors and applicable rights holders establish source provenance,
  authorship/ownership, and the intended project license. Do not infer these from
  a dependency's license or from the accompanying Android repository.
- Verify exact upstream/dependency/model artifacts and applicable notices before
  adding them to a distributed package. Resolve the local-file manifest entries
  through the separate reproducibility work.
- Keep research data, excluded local files, and historical sensitive content
  outside any release until their independent privacy and permission checks are
  satisfied. This document does not clear the separate publication blockers.

These open items block the related publication decisions, not authorized local
engineering. No existing attribution or license has been replaced by this file.
