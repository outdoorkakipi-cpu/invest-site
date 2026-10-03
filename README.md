# 投資シグナル帳

日本株・米国株・暗号資産について、「出てから1週間以内に動けば、数か月〜1年で効いてくる」指標を毎朝まとめる自分専用サイトです。

- 更新: 毎朝 6:30（日本時間）に GitHub Actions が自動実行
- 公開: GitHub Pages
- データ: すべて無料・APIキー不要（FRED、Yahoo Finance、Coin Metrics、alternative.me、DefiLlama、OKX、各種RSS）

## 状態の見方

| 状態 | 意味 |
|---|---|
| 点灯 | 数か月〜1年の上昇を期待しやすい局面 |
| 注目 | 売られすぎ・転換の手前 |
| 警戒 | 景気・需給の悪化や過熱 |
| 平常 | 特になし |

判定ルールは各カードの「判定ルール・出典」に書いてあり、`invest_site/signals.py` で変更できます。閾値は経験則の初期値で、将来の値動きを保証するものではありません。

## 構成

- `invest_site/sources.py` データ取得
- `invest_site/signals.py` 判定ルール
- `invest_site/render.py` ページ生成
- `data/signal_log.csv` 状態が変わった日の記録（毎日自動でコミット）
- `data/latest.json` 最新の判定結果

## 手元で確認する

```
pip install -r requirements.txt
python -m invest_site.main --sample   # ネットに出ず合成データで画面だけ確認
python -m invest_site.main            # 実データで更新
```

`site/index.html` をブラウザで開くと確認できます。
