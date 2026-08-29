# CLIリファレンス

推奨commandは`formulatracer`です。historicalな`cpp-audit`は互換entry pointとして残ります。
source-derived defaultは`--help`で確認します。

Python互換CLIはsource audit、formula parse/compare、CFG、certificate、dtype/parallel、
provider-contract、project commandを含みます。Python不要のnative CLIは
`canonicalize FILE`、`tex FILE`、`kernel FILE`、`compare THEORY IMPLEMENTATION`を提供します。
exit code 0はcommand完了、nonzeroはinvalid input、unsupported operation、execution failureです。

JSONは構造化出力です。command成功は全semantic claimのverifiedを意味しません。
result statusとevidenceを確認してください。

