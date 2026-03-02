# Warnings 定義（Phase 1: 請求項）

## 共通ルール
- warnings は「致命傷になり得るもの」を優先して出す
- evidence は可能なら quote + location を付ける（短文でOK）

## TERM_INCONSISTENCY（用語ゆれ）
発生条件：
- 同一の構成要素を指していそうな語が複数混在（例：センサ/検出器）
期待挙動：
- severity: medium（致命ではないが要修正）
- message: 統一候補を提示

## DEPENDENCY_BROKEN（従属破綻）
発生条件：
- depends_on が存在しない / 循環参照の疑い
- 従属項が参照元にない要素を前提に限定している
期待挙動：
- severity: high（出力ブロック候補）

## UNIT_OR_RANGE_CONFLICT（単位/範囲矛盾）
発生条件：
- invention_text 内で同一パラメータに矛盾する範囲や単位がある
- 請求項に入れた範囲が invention_text と矛盾
期待挙動：
- severity: high（そのまま出すと危険）
- message: 矛盾箇所を明示

## SUPPORT_LACKING（根拠不足）※最重要
根拠不足は次の3種のどれかに分類して message に明記する（A/B/C）。

(A) 要素根拠不足（Element missing）
- 請求項に登場する主要構成要素が、invention_text に明示されていない（同義語含む）
例：
- 請求項「暗号化部」を追加したが、発明文に暗号化の記載がない

(B) 条件・数値根拠不足（Parameter/Condition missing）
- 請求項に数値範囲・閾値・条件（温度/時間/割合/回数など）を入れたが、invention_text に根拠がない

(C) 関係・作用根拠不足（Relationship/Mechanism missing）
- AがBに〇〇する、のような関係を請求項に書いたが、発明文にその関係が示されていない

期待挙動：
- A/B は severity: high（そのまま出すと危険）
- C は severity: medium（要確認）
- message 例：
  - 「SUPPORT_LACKING(A): 請求項1の要素『暗号化部』が invention_text に見当たりません。追記してください。」
  - 「SUPPORT_LACKING(B): 請求項2の範囲『1〜10mm』の根拠が invention_text にありません。」
  - 「SUPPORT_LACKING(C): 『AがBを識別する』関係の説明が invention_text にありません。」
