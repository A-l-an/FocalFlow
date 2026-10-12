# Third-party license texts

These verbatim terms support separately licensed vendored Android/native source.
They do **not** select a license for FocalFlow's original code or the Python backend.
File-level notices and the corresponding component/table terms remain authoritative.
The original Apache-2.0 text remains at [android/LICENSE](../android/LICENSE).

| Text | Scope of referenced declarations |
| --- | --- |
| [LGPL-2.1.txt](LGPL-2.1.txt) | BRLTTY/liblouis files and key/translation tables declaring LGPL-2.1-or-later |
| [GPL-2.0.txt](GPL-2.0.txt) | BRLTTY-related makefile and VisioBraille sources declaring GPL-2.0-or-later |
| [LGPL-3.0.txt](LGPL-3.0.txt) | Translation tables with LGPL-3.0-or-later notices; incorporates GPL3 terms |
| [GPL-3.0.txt](GPL-3.0.txt) | Complete GPL3 terms accompanying LGPL3; does not relabel all liblouis code |

Mixed table notices, source/relinking obligations, binary notice delivery and
project contribution rights require their own review. Read the dated
[Android inventory](../android/THIRD_PARTY.md) and current
[licensing status](../docs/licensing-status.md).

## Sources and exact copied-file hashes

The three LGPL/GPL3 files are copied without edits. GPL2 is copied as the exact
bytes after `License-Text:` and its newline in the Linux license source; the Linux
SPDX/usage metadata before that marker is omitted. Leading whitespace and license
headers are preserved. These hashes identify the files shipped here:

- [LGPL-2.1.txt](LGPL-2.1.txt): [source](https://raw.githubusercontent.com/brltty/brltty/BRLTTY-6.6/LICENSE-LGPL); SHA-256 `d80c9d084ebfb50ea1ed91bfbc2410d6ce542097a32c43b00781b83adcb8c77f`.
- [GPL-3.0.txt](GPL-3.0.txt): [source](https://raw.githubusercontent.com/liblouis/liblouis/v3.26.0/COPYING); SHA-256 `8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903`.
- [LGPL-3.0.txt](LGPL-3.0.txt): [source](https://raw.githubusercontent.com/coreutils/gnulib/master/doc/COPYING.LESSERv3); SHA-256 `e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118`.
- [GPL-2.0.txt](GPL-2.0.txt): [source](https://raw.githubusercontent.com/torvalds/linux/master/LICENSES/preferred/GPL-2.0); SHA-256 `0babccc806836e61267516151fae4d433cf90048b5e182b55ff889317a275afb`.

The complete downloaded Linux source (including its omitted metadata) had SHA-256
`8780e78a1a737e127f25a65f6d95269bffd36158dc261114de7859b490bfc5aa`; it is not the file distributed here.
