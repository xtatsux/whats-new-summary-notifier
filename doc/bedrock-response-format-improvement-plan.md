# Bedrock応答フォーマット改善プラン

## 問題の概要

Slack通知にBedrock Converse APIのプロンプトで使用しているXMLタグ（`<thinking>`, `<outputFormat>`など）がそのまま表示される問題が発生しています。

### 現象
- Slack通知メッセージに以下のような不要なタグが表示される：
  - `<outputFormat>`
  - `<thinking>(bullet points of the input)</thinking>`
  - `<summary>(final summary)</summary>`

### 根本原因
1. Bedrock APIが期待通りのフォーマットで応答を返さない場合がある
2. `<thinking>`タグが見つからない場合のエラーハンドリングで、`outputText`全体を`detail`に代入している
3. プロンプト内のXMLタグがエスケープされずにSlackメッセージに含まれる

## 改善プラン

### Phase 1: 即時対応 - XMLタグの適切な処理

#### 1.1 エラーハンドリングの改善
- **対象ファイル**: `lambda/notify-to-app/index.py`
- **修正箇所**: `summarize_blog`関数（204-210行目）
- **対応内容**:
  - `<thinking>`タグが見つからない場合、`outputText`全体ではなく適切なデフォルト値を設定
  - 予期しないXMLタグを除去する処理を追加

#### 1.2 XMLタグのサニタイズ処理
- **対象ファイル**: `lambda/notify-to-app/index.py`
- **修正箇所**: `create_slack_message`関数の前
- **対応内容**:
  - Slackメッセージ作成前に、不要なXMLタグを除去する関数を追加
  - プロンプト由来のタグ（`<outputFormat>`, `<summaryRule>`など）を確実に除去

### Phase 2: 根本対応 - 応答フォーマットの安定化

#### 2.1 プロンプトエンジニアリングの改善
- **対象ファイル**: `lambda/notify-to-app/index.py`
- **修正箇所**: `summarize_blog`関数のプロンプト部分（144-151行目）
- **対応内容**:
  - Converse API向けに最適化されたプロンプト構造に変更
  - システムプロンプトとユーザープロンプトの役割を明確化
  - 出力フォーマットの指示をより明確に

#### 2.2 応答検証ロジックの追加
- **対象ファイル**: `lambda/notify-to-app/index.py`
- **修正箇所**: `summarize_blog`関数の応答処理部分
- **対応内容**:
  - 期待されるXMLタグの存在を確認
  - フォーマットが不正な場合の再試行ロジック（オプション）

### Phase 3: 監視とデバッグの強化

#### 3.1 デバッグログの追加
- **対象ファイル**: `lambda/notify-to-app/index.py`
- **修正箇所**: 各処理ステップ
- **対応内容**:
  - Bedrockからの生の応答をログ出力
  - タグ抽出の成功/失敗をログで確認
  - 最終的なメッセージフォーマットをログ出力

#### 3.2 CloudWatch Logsでの監視
- **監視項目**:
  - XMLタグ抽出の失敗率
  - 予期しないフォーマットの応答頻度
  - エラーパターンの分析

## 実装の詳細

### 1. サニタイズ関数の実装例

```python
def sanitize_text(text):
    """Remove unwanted XML tags from text"""
    # プロンプト由来のタグを除去
    unwanted_tags = [
        r'<outputFormat>.*?</outputFormat>',
        r'<summaryRule>.*?</summaryRule>',
        r'<outputLanguage>.*?</outputLanguage>',
        r'<instruction>.*?</instruction>',
        r'<persona>.*?</persona>'
    ]
    
    import re
    cleaned_text = text
    for pattern in unwanted_tags:
        cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.DOTALL)
    
    return cleaned_text.strip()
```

### 2. エラーハンドリングの改善例

```python
# extract content inside <thinking> tag with error handling
detail_match = re.findall(r"<thinking>([\s\S]*?)</thinking>", outputText)
if detail_match:
    detail = detail_match[0].strip()
else:
    # outputText全体を使用せず、サマリーのみを使用
    print("Warning: No <thinking> tag found in output")
    detail = ""  # または summary を使用
```

### 3. プロンプト改善の方向性

- XMLタグを使わない明確な出力フォーマット指定
- JSON形式での出力を検討
- より簡潔で曖昧さのない指示

## テスト計画

1. **単体テスト**
   - サニタイズ関数のテスト
   - 各種エラーパターンでの動作確認

2. **統合テスト**
   - 実際のBedrock APIレスポンスでのテスト
   - 様々な入力に対する出力確認

3. **本番環境でのモニタリング**
   - CloudWatch Logsでの継続的な監視
   - 問題発生時のアラート設定

## リスクと対策

1. **後方互換性**
   - 既存の正常な動作に影響を与えないよう注意
   - 段階的なロールアウト

2. **パフォーマンス**
   - サニタイズ処理による遅延は最小限
   - 必要に応じて処理を最適化

## スケジュール

1. **Phase 1**: 即時対応（1-2時間）
2. **Phase 2**: 1-2日以内
3. **Phase 3**: 継続的な改善

## 成功基準

- Slack通知にXMLタグが表示されない
- 正常なサマリーと詳細情報が表示される
- エラー発生時も適切なフォールバック処理が動作する