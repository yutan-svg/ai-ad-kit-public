#!/usr/bin/env python3
"""採用した1カット目を、一時的な公開URLにする（同じ人物を保つための参照づくり）。

なぜ要るか: AI 映像制作ツールは、参照する動画をファイルの中身のままでは受け取りません。
**公開URLでしか渡せません。** そして同じ人物を2カット目以降も保つには、採用した1カット目の
**無加工の原本**を参照として渡す必要があります（音を消す・作り直す等の加工をした原本は拒否されます）。

使い方（案件フォルダのルートで。引数は渡したいファイルのパスだけ）:

  python3 scripts/rehost.py assets/videos/takes/s1-t1.mp4     # URL を作って表示し、配り続ける
  python3 scripts/rehost.py --status                          # いま配っている URL を表示
  python3 scripts/rehost.py --stop                            # 配るのをやめる（URL は消える）
  python3 scripts/rehost.py <ファイル> --local-only           # 公開せず、手元だけで配って動作を確かめる

やっていること:
  1. 渡されたファイルを `out/rehost-serve/` に**そのままの中身で**置き、そのフォルダだけを
     `python3 -m http.server <ポート>` で配る（案件フォルダ全体は配りません。`.env` を晒さないため）
  2. `cloudflared tunnel --url http://localhost:<ポート>`（無ければ `npx localtunnel --port <ポート>`）
     で一時的な公開URLを作る
  3. `curl -sI <URL>` に相当する確認をして、**200 が返ってから**URLを表示する

URL を知っている人は誰でもそのファイルを取得できます。置くのは渡した1ファイルだけにしてあります。
**用が済んだら必ず `--stop` してください。**
URL は数時間〜1日で失効します。失効したらもう一度このコマンドを実行すれば作り直せます。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _config import load_config, rel, resolve  # noqa: E402

STATE = "out/rehost.json"
SERVE_DIR = "out/rehost-serve"
HTTP_LOG = "out/rehost-http.log"
TUNNEL_LOG = "out/rehost-tunnel.log"
URL_RE = re.compile(r"https://[0-9a-z][0-9a-z.-]*\.(?:trycloudflare\.com|loca\.lt)")


def say(msg: str) -> None:
    print(msg, flush=True)


def free_port(start: int = 8765, tries: int = 30) -> int:
    for port in range(start, start + tries):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("空いているポートが見つかりません")


def state_path(cfg) -> Path:
    return resolve(cfg, STATE)


def read_state(cfg) -> dict:
    p = state_path(cfg)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def stop(cfg) -> int:
    st = read_state(cfg)
    stopped = []
    for key in ("http_pid", "tunnel_pid"):
        pid = st.get(key)
        if alive(pid):
            try:
                os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
            except OSError:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except OSError:
                    pass
            stopped.append(f"{key}={pid}")
    state_path(cfg).unlink(missing_ok=True)
    say("公開を止めました" + (f"（{', '.join(stopped)}）" if stopped else "（動いているものはありませんでした）"))
    return 0


def status(cfg) -> int:
    st = read_state(cfg)
    if not st or not alive(st.get("http_pid")):
        say("いま配っているものはありません")
        return 1
    say(f"配布中: {st.get('url')}")
    say(f"  ファイル: {st.get('file')}  開始: {st.get('at')}")
    return 0


def head_ok(url: str, timeout: float = 10.0) -> tuple[int, str]:
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, res.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:  # noqa: BLE001 名前解決前・起動直後は届かない
        return 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", help="公開したいファイル（例 assets/videos/takes/s1-t1.mp4）")
    ap.add_argument("--stop", action="store_true", help="公開を止める")
    ap.add_argument("--status", action="store_true", help="いま配っている URL を表示する")
    ap.add_argument("--port", type=int, default=None, help="ポート番号（既定は空いているものを自動で選ぶ）")
    ap.add_argument("--local-only", dest="local_only", action="store_true",
                    help="外に公開せず、手元（127.0.0.1）だけで配る。動作確認用")
    ap.add_argument("--timeout", type=float, default=60.0, help="URL ができるまで待つ秒数（既定60）")
    a = ap.parse_args()

    cfg = load_config()
    root = cfg["_cwd"]
    if a.stop:
        return stop(cfg)
    if a.status:
        return status(cfg)
    if not a.file:
        ap.error("公開したいファイルのパスを指定してください（例: assets/videos/takes/s1-t1.mp4）")

    target = resolve(cfg, a.file)
    if not target.exists():
        raise SystemExit(f"ファイルがありません: {target}")

    old = read_state(cfg)
    if alive(old.get("http_pid")):
        say(f"NOTE 既に配っているものがあります（{old.get('file')}）。止めてから作り直します")
        stop(cfg)

    port = a.port or free_port()
    (root / "out").mkdir(parents=True, exist_ok=True)
    # 配るのは渡された1ファイルだけ。中身は変えずにそのまま置く（加工した原本は参照として拒否されるため）
    serve_dir = resolve(cfg, SERVE_DIR)
    if serve_dir.exists():
        shutil.rmtree(serve_dir)
    serve_dir.mkdir(parents=True, exist_ok=True)
    served = serve_dir / target.name
    shutil.copyfile(target, served)
    http_log = open(resolve(cfg, HTTP_LOG), "w", encoding="utf-8")
    tunnel_log_path = resolve(cfg, TUNNEL_LOG)
    tunnel_log = open(tunnel_log_path, "w", encoding="utf-8")

    http = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                            cwd=str(serve_dir), stdout=http_log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    say(f"配布サーバー: http://127.0.0.1:{port}/{target.name}（配るのはこの1ファイルだけ）pid={http.pid}")

    if a.local_only:
        url = f"http://127.0.0.1:{port}/{target.name}"
        code = 0
        for _ in range(10):
            code, _info = head_ok(url, timeout=3.0)
            if code == 200:
                break
            time.sleep(0.5)
        state_path(cfg).write_text(json.dumps(
            {"url": url, "base": f"http://127.0.0.1:{port}", "file": rel(cfg, target), "port": port,
             "tool": "local-only", "http_pid": http.pid, "tunnel_pid": None,
             "at": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        say(f"{'✓ 200 を確認しました' if code == 200 else f'⚠ 200 が返りません（HTTP {code}）'}（--local-only なので外からは見えません）")
        say("")
        say(url)
        say("")
        say("止めるとき: python3 scripts/rehost.py --stop")
        return 0 if code == 200 else 1

    if shutil.which("cloudflared"):
        tunnel_cmd = ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"]
        tool = "cloudflared"
    else:
        tunnel_cmd = ["npx", "--yes", "localtunnel", "--port", str(port)]
        tool = "localtunnel"
    tunnel = subprocess.Popen(tunnel_cmd, cwd=str(root), stdout=tunnel_log,
                              stderr=subprocess.STDOUT, start_new_session=True)
    say(f"一時公開: {tool}（pid={tunnel.pid}）。URL ができるまで待ちます…")

    base = ""
    deadline = time.time() + a.timeout
    while time.time() < deadline:
        time.sleep(1.0)
        text = tunnel_log_path.read_text(encoding="utf-8", errors="replace")
        m = URL_RE.search(text)
        if m:
            base = m.group(0)
            break
        if tunnel.poll() is not None:
            break
    if not base:
        tail = tunnel_log_path.read_text(encoding="utf-8", errors="replace")[-800:]
        os.killpg(os.getpgid(http.pid), signal.SIGTERM)
        if tunnel.poll() is None:
            os.killpg(os.getpgid(tunnel.pid), signal.SIGTERM)
        raise SystemExit(
            f"✗ 公開URLを作れませんでした（{tool}）。ログの末尾:\n{tail}\n"
            "  cloudflared を入れると安定します: brew install cloudflared")

    url = f"{base}/{target.name}"
    code = 0
    for _ in range(20):
        code, _info = head_ok(url)
        if code == 200:
            break
        time.sleep(1.5)
    state = {"url": url, "base": base, "file": rel(cfg, target), "port": port, "tool": tool,
             "http_pid": http.pid, "tunnel_pid": tunnel.pid, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    state_path(cfg).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if code != 200:
        say(f"⚠ URL はできましたが、まだ 200 が返りません（HTTP {code}）。数十秒おいて確かめてください:")
        say(f"    curl -sI '{url}' | head -3")
    else:
        say("✓ 200 を確認しました（このURLをそのまま参照に使えます）")
    say("")
    say(url)
    say("")
    say("使い終わったら必ず止めてください: python3 scripts/rehost.py --stop")
    return 0 if code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
