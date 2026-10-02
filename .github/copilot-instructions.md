# GitHub Copilot 向けの指示

このフォルダの指示書は `AGENTS.md` です（`CLAUDE.md`・`GEMINI.md` と同じ内容）。作業を始める前に `AGENTS.md` を読み、そこに書かれた順序（`RULES.md` → `knowledge/project.md` → `knowledge/CURRENT.md`）で読み進めてください。

作業ごとの手順は `.claude/skills/<名前>/SKILL.md`（`.agents/skills/` に同じ写しがあります）にあります。該当する手順を開いてそのとおりに実行してください。

費用のかかる生成（AI 映像・読み上げ）と動画ファイルの書き出しの前には、必ず何を・何本・どのサービスで作るかを伝え、はっきりした承諾を得てから実行してください。承諾の記録が無いと `scripts/approve.py` の門で止まります。
依頼主から聞き取った答え（商材・届ける相手・台本前の3つ）は、その場で `knowledge/project.md` に書いてください。チャットに残すだけでは次の会話に引き継がれず、空欄のままだとリサーチ・生成・検査・書き出しのスクリプトが止まります（`python3 scripts/check_project.py --for script`）。
