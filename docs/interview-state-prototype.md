# InterviewState / 業務操作ツール試作メモ

## 結論

今回の最小契約は、公開発言だけから次を同じ更新経路で保持できることを確認した。

- 発言本文をハーネスが不変に保存し、引用を `utterance_id + [start, end)` で検証できる。
- 業務上の主張を根拠、暫定/確認済み/棄却状態、訂正元とともに残せる。
- 処理、担当者、入出力、フロー、分岐、システム、データ種別、CRUD を現在の業務モデルとして読める。
- `unknown` CRUD、システム `dont_know`、手作業システムを、推測した `create`/`update` と混同しない。
- 終了、関係者の確認、内容の完全性を別々に保持できる。

既存3ケースと追記・訂正の適合caseはすべて `InterviewHarness` → `InterviewToolExecutor` → Pydantic検証の同じ経路を通る。これはモデルの自動抽出精度やベンチマーク合格率を測るものではなく、手動で構成したツール呼び出し列による契約適合確認である。

## 既存実験から採用した知見

| 区分 | 確認できた事実 | 参照元 | 今回の扱い |
| --- | --- | --- | --- |
| 事実 | Phase 20 は WHAT の7試行を6件のcanonical mode mismatch、1件の有効試行として再分類している。利用可能ログは2件で、もう1件は保存前タイムアウト。 | `experiments/phase20/README.md`、`real-calibration-summary.json` | モード/意味論の自動抽出を今回の入力にせず、公開発言と手動のツール列だけを扱う。 |
| 事実 | Phase 21 は Candidate の生成を question/tool/empty/output exhaustion/provider error 等に分け、利用可能な校正は1件、他2件は終端前タイムアウトとしている。 | `experiments/phase21/README.md`、`real-calibration-summary.json` | 生成失敗を新しい品質スコアや質問戦略で解決しない。途中状態を保存できるかだけを見る。 |
| 事実 | 現行の Candidate 側は `get_agent_graph`、`get_observations` とグラフ編集ツール19個を `build_interview_tools()` で公開し、回答取り込みは `LiveInterviewStore.ingest_stakeholder_response()` が private sidecar と公開本文を別に保存する。 | `src/business_interview_bench/inspect_adapter/tools.py`、`src/business_interview/runtime.py` | 既存 Phase 13 の契約を大規模改修せず、新しい7操作を独立した最小境界として試作する。 |
| 事実 | `src/business_interview/replay_data/seed9004/evaluation_context.json` には公開 stakeholder observation 14件と `protocol_completed: true` があるが、`provenance.json` は full conversation/evidence ledger を意図的に省略したと記録している。 | `src/business_interview/replay_data/seed9004/evaluation_context.json`、`provenance.json` | Aは保存済み公開 observation の再生と呼ぶ。assistant の欠落発言を復元・捏造しない。 |
| 仮説 | Phase 20/21 の少数ログから、ツール粒度や回答取り込みが品質の主因だと断定することはできない。 | 上記実験資料 | 今回は原因帰属をしない。操作の不自然さは既存3ケースの手動再生で定性的に記録し、追記経路は別の合成適合caseで確認する。 |

## 状態の正本と不確実性

`src/business_interview/interview_state.py` の `InterviewState` は Pydantic の frozen model で、操作は新しい状態を構築する。`InterviewHarness` だけが utterance の登録と evidence ID (`ev_0001` 形式) の発行を行い、agent-facing tool catalog にはその操作を含めない。

- `utterances` は `id`、`speaker`、原文 `text` の不変タプル。話者は業務担当者ではなく、`ProcessStep.actor` は別のローカルIDである。
- `EvidenceRef` は `evidence_id`、utterance ID、Unicode code-point の `[start, end)`（終端はexclusive）、引用本文、`semantic_support` を持つ。ハーネスは範囲と文字列一致だけを検証し、引用が主張の意味を支持することは自動判定しない。`semantic_support` は別の明示入力であり、confirmed の根拠要件と文字列検証を混同しない。
- `InformationValue` / `EntityLink` / `EntityList` の `unset`、`value`、`absent`、`dont_know` は別状態である。`CrudOperation` の `unknown` は業務操作種別としての値であり、DONT_KNOW への変換ではない。
- `Claim.status` の `provisional`、`confirmed`、`rejected` は情報状態とは別軸。`confirmed` は evidence があり、少なくとも一つが明示的に `supports` とされた場合だけ受理する。これは意味的支持を自動証明するものではない。
- `claims` は根拠付きの履歴の正本、`business_model` は同じ操作が同時に更新する現在の読み取り用projectionとした。訂正は旧claimを削除せず `rejected` にし、新claimの `supersedes` で結ぶ。現在の成果物は `business_model` の一意な値だけを読むため、失効した内容を現行フロー/CRUDに残さない。active claimは対象フィールドごとに高々1件で、保存/読込時にもprojectionとの一致を検証する。
- `SOURCE` と `SINK` は `source_boundary` / `sink_boundary` の Flow としてだけ使う。normal/branch/exception flow の endpoint に混ぜない。
- `Completion` の `status=ended`、`stakeholder_confirmed`、`content_completeness` は別フィールドである。`complete_interview` しただけでは承認済みにならない。

## 7操作の最終形

JSON Schema は `interview_tools.py` の入力Pydanticモデルから `get_tool_definitions()` / `tool_schemas()` で生成する。再生コマンドは同じ生成結果を `examples/interview_state/replays/tool-schemas.json` に保存する。失敗は `ToolOutput(ok=false, errors=[code, message])` で返し、candidateに修正に必要な理由を返す。失敗した操作は状態を差し替えない。

| 操作 | 主な入力 | 事前条件 / 更新 | 戻り値 |
| --- | --- | --- | --- |
| `inspect_interview_state` | 対象レコードID、evidence有無 | なし。active claim、現在モデル、関連根拠、未解決質問、矛盾を読む。 | `snapshot` |
| `record_process_step` | step ID、activity、actor、inputs、outputs、evidence、claim status | step IDは新規。actor/data IDは既存なら再参照、未知IDならlabel付きで作成。speakerをactorに自動変換しない。 | 更新step、claim IDs |
| `connect_process_steps` | flow ID、既存stepまたは `SOURCE`/`SINK`、kind、条件、evidence | endpoint参照を検証。境界は専用kind。 | 更新flow、claim IDs |
| `record_resource_usage` | usage ID、既存step、system、data type、CRUD、evidence | system/data type はIDで再参照、label付きで作成。systemは named/manual または `dont_know`。CRUDは `create/read/update/delete/unknown` のいずれかで、writesから推測しない。 | 更新data operation、claim IDs |
| `record_issue` | issue kind、対象、説明、必要ならclaim IDs/question、矛盾の解決claim、evidence | unknown は open question、contradiction は既存claim 2件以上を参照し、必要なら resolved と解決claimを明示。 | issue、質問/矛盾 IDs |
| `revise_record` | 対象レコードID、`field`、fieldに対応したPydantic値、replacement ID、更新理由、evidence | `activity` / `actor` / `inputs` / `outputs` / `condition` / `crud` / `system` / `data_type` の1フィールドだけを扱う。現在claimがなければ初回追記、あれば旧claimを`rejected`にして新claimの`supersedes`で訂正する。actor/system/data typeはID再利用または同じ操作内でlabel付き作成、inputs/outputsは型付きリスト全体置換。任意JSON Patchではない。 | 対象レコード、新claim、`revised_from`、作成/再利用entity IDs |
| `complete_interview` | 終了理由、未解決質問、確認有無/根拠、内容完全性 | unresolved省略時はopen questionを保持。confirmation=trueには支持根拠が必要。終了後は編集不可。 | completion receipt |

operation ID の生成は仕様上の暗黙の重複回避にしない。呼び出し側が安定IDを渡し、同じIDにlabelを添えれば再参照、別labelならエラーとする。発言保存やevidence発行のtoolは公開しない。

## 追記・訂正の回帰適合例

レビューで再現した問題は、担当者・入出力を未指定のまま`record_process_step`で登録した後、同じstep IDを再送して重複エラーになり、未作成の`claim:review:actor`を旧形式の`revise_record`で指定して失敗することだった。`revise_record`はレコードIDとフィールドを指定する契約に変更し、この経路を解消した。

`incremental_synthetic` は合成・手動ツール呼び出しによる適合例であり、モデルによる自動抽出や人間評価の成功を示さない。再生器はこのcaseだけ、未来の発言を先に登録せず、次の順で発言登録と操作を交互に実行する。

1. 「まず申請内容を確認します」→ `review` をactivityだけで作成（actor/inputs/outputsは`unset`）。
2. 「担当は経理で、申請書を確認します」→ 同じ`review`の`actor`と`inputs`を別々の型付き`revise_record`で初回追記。経理と申請書はこの時点で作成する。
3. 「確認後は確認結果を残します」→ 同じ`review`の`outputs`を初回追記。actorとinputsは維持する。
4. 「すみません、担当は経理ではなく営業です」→ actorだけを訂正。経理の旧claim/evidenceは`rejected`履歴に残し、現行actorは営業になる。

このcaseの最終状態はprocess stepが1件のままで、actor=`sales`、inputs=`application`、outputs=`review_result`となる。初回追記は`supersedes`なし、訂正は`supersedes`ありとして履歴上区別され、保存/読込後にも同じ操作を続けられる。

`claim_status="rejected"`の候補はclaim履歴だけに残り、projectionや新規entityを変更しない。不正引用、対象参照、entity label衝突はcandidate stateの検証前に失敗し、状態を差し替えない。

## 既存3ケースの再生結果

### A: 既存の正常終了した公開 observation fixture

`normal_existing` は seed 9004 の保存済み `evaluation_context.json` の公開発言14件を入力にした。full transcript はリポジトリにないため、元の完全な会話を再生したとは言わない。protocol flag は終了を示すだけで品質合格ではない。

- 6 process steps、amount/month-end の分岐、SOURCE/SINK境界を表現できた。
- CRM/read、quoting system/create、email/unknown、システム不明/unknown CRUD を表現できた。
- month-end path の「追加か置換か」を open question として残し、終了しても stakeholder confirmation は false。

### B: 既存ログがない失敗/途中ケースの代替

Phase 20/21 の raw provider transcript は公開リポジトリに保存されていない。要約から発言を復元しないため、`partial_synthetic` は明示的な合成ケースであり、既存ログの再生ではない。

- receive → review だけを記録し、review actor は `dont_know`。
- email と intake sheet のCRUDは `unknown` のまま。
- review の create/update を open question として保持し、time limit で `ended` にしても content completeness は `incomplete`、confirmation は false。

### C: 5〜10分の人間ヒアリング用の暫定ケース

利用許可された実会話は今回なかったため、`human_synthetic` は合成で、人間評価は未実施である。手動ツール列は次を含む。

- urgent / normal の分岐。
- shared inbox、tracker、manual work。
- review の `update` を stakeholder の訂正で `read` に変更。旧claimと旧evidenceは残し、現行CRUDは read とした。
- その訂正前後の2 claimを resolved contradiction として追跡。
- approval status の `dont_know` と未解決質問。
- 話者の「I」を業務担当者に自動同一視せず、review/call/schedule の actor は DONT_KNOW。

後で人間に実施する手順は、機密会話をコミットせず、ローカル一時ディレクトリに同じ形式のcase JSONを置き、公開可能な発言だけを `utterances` に登録して次を実行することである。

```bash
uv run python -m business_interview.prototype \
  --case-dir /tmp/authorized-interview-case \
  --output-dir /tmp/interview-state-replay
```

実会話では、ツール呼び出し列を手動で評価し、`human_evaluation` を `performed` に変えるだけではなく、確認者、確認範囲、未解決点を別のレビュー記録に残す。機密原文や私有意味注釈は公開リポジトリに追加しない。

## 適合性と無理があった点

- 7操作は、会話例で必要になった記録・分岐・CRUD・不明点・訂正・終了を表せた。万能 `record_fact` を必要としなかった。
- actor/system/data の作成と再参照は、step/resource操作の `id + label` で一貫した。ID不一致labelは重複エンティティを作らず失敗する。
- exact range は機械検証できるが、agentが文字列オフセットを数えるのは不自然である。次の縦断では、ハーネスが公開発言に安定した引用候補を添える。ただしEvidence発行/発言登録自体をagent操作にはしない。
- current projection と履歴を二重に自由編集できる契約ではない。訂正可能なclaim predicateは試作で限定し、任意JSON Patchを避けた。複雑なレコード分割・統合、複数人承認、意味的な証拠判定は未実装である。
- Aは保存済み公開 observation 断片、B/Cは合成、Cの人間確認は未実施、という区別をstateとは別のcase metadata/reportに残した。

## 次の最小縦断

適合確認は成功したため、次に進める価値はある。ただし今回の範囲を広げず、次の一段だけを実装候補とする。

1. 現行Inspect adapterとは別に、Pydantic入力Schemaをそのまま受ける薄いagent adapterを追加する。
2. ハーネスの公開utterance登録と引用候補供給を既存の回答取り込み境界に接続する。
3. 1会話を中断→JSON保存→再開する最小テストを追加する。

本格的な質問戦略、音声/Zoom/Teams、改善提案、スコア、Phase 21診断、旧19グラフツールの大規模置換は、この試作の結果だけで自動開始しない。
