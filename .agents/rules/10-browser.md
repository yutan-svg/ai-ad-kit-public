---
trigger: always_on
description: Web の実物（広告ライブラリ・透明性センター・LP）を見るときは、Antigravity の Browser subagent を使う
---

# Web の実物は Browser subagent で開く

`ad-research` や出典の確認で **Web ページの実物を見る必要があるとき**は、Antigravity に備わっている
**Browser subagent（チャットで `/browser` から始める、または browser のツール）** を使ってください。
Meta 広告ライブラリ・Google 広告の透明性センター・各社の LP は JavaScript で描画されるため、
`curl` や検索エンジンの要約では中身が取れません。

- 「GUI の道具が無い」「Chrome を再起動する必要がある」と答えないでください。Browser subagent は最初から使えます（Google Chrome が入っていれば足ります）
- 開いた画面は `out/research/img/` に保存し、出典表で `opened: direct` にします。開けなかったものは `summary` か「開けない」と正直に書きます
- Browser subagent が使えない環境（Chrome 未導入など）では、その旨を人に伝えて、要約で代用したことを資料に明記します
