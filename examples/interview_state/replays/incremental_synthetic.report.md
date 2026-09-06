# incremental_synthetic: 段階的な処理情報の追記と訂正

- source: `synthetic_human`
- source reference: `手動で構成した日本語4発言の適合例`
- human evaluation: `not_performed`
- note: 合成・手動ツール呼び出しによる適合例。発言登録とツール実行を会話順に交互に行い、モデルによる自動抽出や人間評価の成功を示すものではない。

## Current business flow

- (no flow recorded)

## Process steps

- `review` 申請内容を確認; actor=営業 [sales]; inputs=申請書 [application]; outputs=確認結果 [review_result]

## Systems

- (no named or manual system recorded)

## Process × system × data × CRUD

| process | system | data type | CRUD |
| --- | --- | --- | --- |
| (none) | | | |

## Evidence and claims

- `claim:review:activity` [provisional] process_step/review/activity: 申請内容を確認; evidence=ev_0001=i1[0:12]
- `claim:review:actor` [rejected] process_step/review/actor: accounting; evidence=ev_0002=i2[0:16]
- `claim:review:inputs` [confirmed] process_step/review/inputs: ["application"]; evidence=ev_0003=i2[0:16]
- `claim:review:outputs` [confirmed] process_step/review/outputs: ["review_result"]; evidence=ev_0004=i3[0:13]
- `claim:review:actor:revision1` [confirmed] process_step/review/actor: sales; evidence=ev_0005=i4[0:19]; supersedes `claim:review:actor`

## Open questions

- (none)

## Contradictions

- (none)

## Corrections

- `claim:review:actor` → `claim:review:actor:revision1`; old claim is rejected, new value is sales

## Completion

- status: `active`
- termination reason: `None`
- unresolved: (none)
- stakeholder confirmed: `False`
- content completeness: `unknown`
