# Contributing

Add or change registry entries separately from generated entity inventories.
Every result-affecting entity needs an explicit classification and effect.
Breaking IR/registry changes require a schema-version change. Run Python, CMake,
and Lean tests; do not commit `sorry` or silently refresh golden artifacts.

## Reporting and discussion

Use the repository's structured GitHub Issue Forms for reproducible bugs,
feature proposals, and unsupported semantics or provider requests. Usage
questions and general technical discussion belong in
[GitHub Discussions](https://github.com/3e456/FormulaTracer/discussions).
Security vulnerabilities must follow [SECURITY.md](SECURITY.md) and must not be
reported in a public issue.

Issues may be submitted in Japanese or English. Depending on the topic and the
need for detailed technical discussion, reports with Japanese descriptions,
follow-up information, or reproduction steps may sometimes be reviewed or
handled first. Filing an issue does not guarantee implementation, a fix, or a
response date. FormulaTracer does not promote unsupported semantics based on
guesswork when adequate evidence is unavailable.

## Pull Request policy

FormulaTracer does not currently accept external pull requests.

If you find a bug, unsupported semantic case, provider gap, documentation
issue, or have an idea for an improvement, please open a GitHub Issue or start
a GitHub Discussion instead. External code contributions submitted as pull
requests may be closed without review or merge.

This policy keeps semantic ownership, verification responsibility, release
provenance, and the single-source-of-truth architecture under maintainer
control. Issue and Discussion submissions are welcome, but they do not
guarantee implementation, adoption, response time, or future support.

## Pull Requestについて

FormulaTracerでは、現在、外部からのPull Requestは受け付けていません。

バグ、未対応semantic、providerの不足、ドキュメント上の問題、改善案などがある場合は、
GitHub IssueまたはGitHub Discussionsを利用してください。外部から提出されたPull Requestは、
内容の確認やmergeを行わずcloseする場合があります。

この方針は、semantic ownership、検証責任、release provenance、および
single-source-of-truth architectureをmaintainer側で一貫して管理するためのものです。
IssueやDiscussionでの報告・提案は歓迎しますが、実装、採用、返信時期、将来の対応を
保証するものではありません。

