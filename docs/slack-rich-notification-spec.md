# Slack Rich Notification Specification

## 背景と目的

現在のSlack通知は単純なテキストフォーマットで送信されており、箇条書きが `-` で表現されている。これをSlackのBlock Kitを使用してよりリッチで視覚的に分かりやすいフォーマットに改善する。

## 現状の課題

1. **視認性の低さ**: プレーンテキストのため、情報の階層構造が分かりにくい
2. **モバイル対応**: 長い文章が画面幅で折り返され、読みにくい
3. **ブランドイメージ**: シンプルすぎる表示で、プロフェッショナルさに欠ける
4. **アクションの不便さ**: リンクがインラインで埋め込まれており、クリックしにくい

## 改善後のフォーマット仕様

### Block Kit構造

#### 1. ヘッダーセクション
- **タイプ**: `header`
- **内容**: 記事タイトル
- **スタイル**: プレーンテキスト、絵文字対応

#### 2. コンテキストセクション
- **タイプ**: `context`
- **内容**: 公開日時
- **スタイル**: マークダウン形式、グレー表示

#### 3. サマリーセクション
- **タイプ**: `section`
- **内容**: Bedrockが生成した要約（`<summary>`タグ内容）
- **スタイル**: マークダウン形式、太字

#### 4. 詳細セクション
- **タイプ**: `section`
- **内容**: Bedrockが生成した詳細分析（`<thinking>`タグ内容）
- **処理**: 箇条書きを解析して構造化
- **スタイル**: 
  - 各箇条書き項目を個別のテキストブロックとして表示
  - インデント表現をサポート
  - 絵文字（📌、✅、🔸など）を使用して視覚的に強調

#### 5. ディバイダー
- **タイプ**: `divider`
- **目的**: セクション間の視覚的な区切り

#### 6. アクションセクション
- **タイプ**: `actions`
- **内容**: 「記事を読む」ボタン
- **スタイル**: プライマリボタン、URLリンク

### サンプルJSON構造

```json
{
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "Amazon RDS Custom for SQL Server is now available in the AWS Africa (Cape Town) Region",
        "emoji": true
      }
    },
    {
      "type": "context",
      "elements": [
        {
          "type": "mrkdwn",
          "text": "📅 *公開日時:* 2025-07-18T18:02:00"
        }
      ]
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*📝 要約*\nAmazon RDS Custom for SQL ServerがAWS Africa (Cape Town) リージョンで利用可能になりました。"
      }
    },
    {
      "type": "divider"
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*🔍 詳細分析*"
      }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "📌 *新機能の概要*\n• SQL Server環境をカスタマイズできるサービス\n• 高可用性と自動バックアップ機能を維持"
      }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "✅ *利用可能なケース*\n• 特定の設定が必要な企業\n• カスタムエージェントを使用する場合"
      }
    },
    {
      "type": "divider"
    },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": {
            "type": "plain_text",
            "text": "📖 記事を読む",
            "emoji": true
          },
          "url": "https://aws.amazon.com/about-aws/whats-new/...",
          "style": "primary"
        }
      ]
    }
  ]
}
```

## 実装上の注意点

### 1. 箇条書きの解析
- Bedrockの出力から`<thinking>`タグ内の内容を抽出
- `-` で始まる行を箇条書きとして認識
- 必要に応じてグループ化（関連する項目をまとめる）

### 2. 文字数制限
- Slackのテキストフィールドは3000文字まで
- 長い詳細は必要に応じて省略し、「...続きは記事で」と表示

### 3. エスケープ処理
- マークダウン特殊文字（`*`, `_`, `~`など）を適切にエスケープ
- URLエンコーディングの処理

### 4. 絵文字の使用
- 情報の種類に応じて適切な絵文字を選択
- 過度な使用は避け、プロフェッショナルさを保つ

### 5. エラーハンドリング
- Block Kit形式が正しくない場合のフォールバック処理
- 既存のプレーンテキスト形式へのフォールバック

## 移行計画

1. 既存の`create_slack_message`関数を保持（`create_slack_message_legacy`として）
2. 新しい実装を段階的にテスト
3. 問題がなければ完全に移行

## 参考資料

- [Slack Block Kit Builder](https://app.slack.com/block-kit-builder)
- [Slack API Documentation - Block Kit](https://api.slack.com/block-kit)
- [Slack Message Formatting](https://api.slack.com/reference/surfaces/formatting)