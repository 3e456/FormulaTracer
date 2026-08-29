# Python API

完全なsignature、引数表、戻り値、例外、所有権、実行可能な例は
[クラス・関数の使い方](api-usage-guide.ja.md)（[English](api-usage-guide.md)）を
参照してください。

正式package名は`formulatracer`です。`cpp_audit`と`cpp-audit`は互換名であり、
新しいdocumentでは使いません。

`FormulaTracer`はproject/source/TeXから監査を作ります。`analyze()`はproject audit
object、`from_tex()`はmathematical formula facadeを返します。`plan_generation()`は
候補を取得し、`generate()`は厳密に採用できた候補からsourceを生成します。
生成sourceは未検証から始まり、独立に再解析します。

`NativeResult`はstatus、theory、implementation、relation、assumptions、error/range、
evidence、provenance、debugger情報を持ちます。TeX/JSON/説明文は構造化resultから派生します。
`reconstruct(request)`はRust native kernelへ委譲し、relationを崩さず返します。

native libraryがない場合は`NativeUnavailableError`、不正または未対応requestは
`NativeCallError`でfail-closedします。全public symbolは
`output/public_docs/public-api-inventory.json`に自動出力します。
