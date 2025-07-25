# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import boto3
import json
import os
import time
import traceback

import urllib.request
import urllib.parse

from typing import Optional
from botocore.config import Config
from bs4 import BeautifulSoup
from botocore.exceptions import ClientError
import re

MODEL_ID = os.environ["MODEL_ID"]
MODEL_REGION = os.environ["MODEL_REGION"]
NOTIFIERS = json.loads(os.environ["NOTIFIERS"])
SUMMARIZERS = json.loads(os.environ["SUMMARIZERS"])

ssm = boto3.client("ssm")


def sanitize_text(text):
    """Remove unwanted XML tags from text
    
    Args:
        text (str): The text to sanitize
        
    Returns:
        str: The sanitized text
    """
    if not text:
        return ""
    
    # プロンプト由来の不要なタグを除去
    unwanted_tags = [
        r'<outputFormat>.*?</outputFormat>',
        r'<summaryRule>.*?</summaryRule>',
        r'<outputLanguage>.*?</outputLanguage>',
        r'<instruction>.*?</instruction>',
        r'<persona>.*?</persona>',
        r'<input>.*?</input>'
    ]
    
    cleaned_text = text
    for pattern in unwanted_tags:
        cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.DOTALL)
    
    # 連続する改行を2つまでに制限
    cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
    
    return cleaned_text.strip()


def get_blog_content(url):
    """Retrieve the content of a blog post

    Args:
        url (str): The URL of the blog post

    Returns:
        str: The content of the blog post, or None if it cannot be retrieved.
    """

    try:
        if url.lower().startswith(("http://", "https://")):
            # Use the `with` statement to ensure the response is properly closed
            with urllib.request.urlopen(url) as response:
                html = response.read()
                if response.getcode() == 200:
                    soup = BeautifulSoup(html, "html.parser")
                    main = soup.find("main")

                    if main:
                        return main.text
                    else:
                        return None

        else:
            print(f"Error accessing {url}, status code {response.getcode()}")
            return None

    except urllib.error.URLError as e:
        print(f"Error accessing {url}: {e.reason}")
        return None


def get_bedrock_client(
    assumed_role: Optional[str] = None,
    region: Optional[str] = None,
    runtime: Optional[bool] = True,
):
    """Create a boto3 client for Amazon Bedrock, with optional configuration overrides

    Args:
        assumed_role (Optional[str]): Optional ARN of an AWS IAM role to assume for calling the Bedrock service. If not
            specified, the current active credentials will be used.
        region (Optional[str]): Optional name of the AWS Region in which the service should be called (e.g. "us-east-1").
            If not specified, AWS_REGION or AWS_DEFAULT_REGION environment variable will be used.
        runtime (Optional[bool]): Optional choice of getting different client to perform operations with the Amazon Bedrock service.
    """

    if region is None:
        target_region = os.environ.get(
            "AWS_REGION", os.environ.get("AWS_DEFAULT_REGION")
        )
    else:
        target_region = region

    print(f"Create new client\n  Using region: {target_region}")
    session_kwargs = {"region_name": target_region}
    client_kwargs = {**session_kwargs}

    profile_name = os.environ.get("AWS_PROFILE")
    if profile_name:
        print(f"  Using profile: {profile_name}")
        session_kwargs["profile_name"] = profile_name

    retry_config = Config(
        region_name=target_region,
        retries={
            "max_attempts": 10,
            "mode": "standard",
        },
    )
    session = boto3.Session(**session_kwargs)

    if assumed_role:
        print(f"  Using role: {assumed_role}", end="")
        sts = session.client("sts")
        response = sts.assume_role(
            RoleArn=str(assumed_role), RoleSessionName="langchain-llm-1"
        )
        print(" ... successful!")
        client_kwargs["aws_access_key_id"] = response["Credentials"]["AccessKeyId"]
        client_kwargs["aws_secret_access_key"] = response["Credentials"][
            "SecretAccessKey"
        ]
        client_kwargs["aws_session_token"] = response["Credentials"]["SessionToken"]

    if runtime:
        service_name = "bedrock-runtime"
    else:
        service_name = "bedrock"

    bedrock_client = session.client(
        service_name=service_name, config=retry_config, **client_kwargs
    )

    return bedrock_client


def summarize_blog(
    blog_body,
    language,
    persona,
):
    """Summarize the content of a blog post
    Args:
        blog_body (str): The content of the blog post to be summarized
        language (str): The language for the summary
        persona (str): The persona to use for the summary

    Returns:
        str: The summarized text
    """

    boto3_bedrock = get_bedrock_client(
        assumed_role=os.environ.get("BEDROCK_ASSUME_ROLE", None),
        region=MODEL_REGION,
    )
    # Converse API向けに最適化されたプロンプト
    prompt_data = f"""You are a professional {persona} who analyzes technology updates.

Your task is to analyze the provided content and create:
1. A detailed bullet-point analysis
2. A concise 1-2 sentence summary

Output Requirements:
- Language: {language}
- Format your response EXACTLY as follows:
<thinking>
- [Bullet point about what the new feature is]
- [Bullet point about who this update is good for]
- [Additional relevant bullet points as needed]
</thinking>
<summary>
[1-2 sentence summary of the update]
</summary>

Important: Use ONLY the information provided in the input. Do not add external knowledge."""

    max_tokens = 4096
    system_prompts = [
        {
            "text": prompt_data
        }
    ]

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "text": f"Please analyze the following content and provide the output in the specified format:\n\n{blog_body}"
                }
            ]
        }
    ]

    inference_config = {
        "maxTokens": max_tokens,
        "temperature": 0.5,
        "topP": 1,
    }

    additional_model_request_fields = {
        "inferenceConfig": {
            "topK": 125
        }
    }

    try:
        response = boto3_bedrock.converse(
            system=system_prompts,
            messages=messages,
            modelId=MODEL_ID,
            inferenceConfig=inference_config,
            additionalModelRequestFields=additional_model_request_fields
        )
        outputText = response["output"]["message"]["content"][0]["text"]
        print(f"=== Bedrock Response ===\n{outputText}\n=== End Response ===")
        
        # Log if the response contains unexpected XML tags
        if "<outputFormat>" in outputText or "<summaryRule>" in outputText:
            print(f"WARNING: Response contains prompt-related XML tags")
        
        # extract content inside <summary> tag with error handling
        summary_match = re.findall(r"<summary>([\s\S]*?)</summary>", outputText)
        if summary_match:
            summary = summary_match[0].strip()
            print(f"Summary extracted successfully: {len(summary)} chars")
        else:
            # If no summary tag found, use sanitized output
            print("Warning: No <summary> tag found in output")
            # Sanitize the output to remove unwanted XML tags
            sanitized = sanitize_text(outputText)
            summary = sanitized[:200] + "..." if len(sanitized) > 200 else sanitized
            print(f"Using sanitized output as summary: {len(summary)} chars")
        
        # extract content inside <thinking> tag with error handling
        detail_match = re.findall(r"<thinking>([\s\S]*?)</thinking>", outputText)
        if detail_match:
            detail = detail_match[0].strip()
            print(f"Detail extracted successfully: {len(detail)} chars")
        else:
            # If no thinking tag found, don't use the full outputText to avoid XML tags
            print("Warning: No <thinking> tag found in output")
            # Use sanitized summary as fallback or empty string
            detail = ""
            print("Using empty string for detail to avoid XML tags")
    except ClientError as error:
        if error.response["Error"]["Code"] == "AccessDeniedException":
            print(
                f"\x1b[41m{error.response['Error']['Message']}\
            \nTo troubeshoot this issue please refer to the following resources.\ \nhttps://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot_access-denied.html\
            \nhttps://docs.aws.amazon.com/bedrock/latest/userguide/security-iam.html\x1b[0m\n"
            )
        else:
            raise error

    return summary, detail


def push_notification(item_list):
    """Notify the arrival of articles

    Args:
        item_list (list): List of articles to be notified
    """

    for item in item_list:
        
        notifier = NOTIFIERS[item["rss_notifier_name"]]
        webhook_url_parameter_name = notifier["webhookUrlParameterName"]
        destination = notifier["destination"]
        ssm_response = ssm.get_parameter(Name=webhook_url_parameter_name, WithDecryption=True)
        app_webhook_url = ssm_response["Parameter"]["Value"]
        
        item_url = item["rss_link"]

        # Get the blog context
        content = get_blog_content(item_url)

        # Summarize the blog
        summarizer = SUMMARIZERS[notifier["summarizerName"]]
        summary, detail = summarize_blog(content, language=summarizer["outputLanguage"], persona=summarizer["persona"])

        # Add the summary text to notified message
        item["summary"] = summary
        item["detail"] = detail
        if destination == "teams":
            item["detail"] = item["detail"].replace("。\n", "。\r")
            msg = create_teams_message(item)
        else:  # Slack
            msg = create_slack_message(item)

        encoded_msg = json.dumps(msg).encode("utf-8")
        print("push_msg:{}".format(item))
        headers = {
            "Content-Type": "application/json",
        }
        req = urllib.request.Request(app_webhook_url, encoded_msg, headers)
        with urllib.request.urlopen(req) as res:
            print(res.read())
        time.sleep(0.5)

def parse_bullet_points(text):
    """Parse bullet points from text and group them by topic
    
    Args:
        text (str): Text containing bullet points starting with '-'
        
    Returns:
        list: List of parsed bullet point groups
    """
    if not text:
        return []
    
    lines = text.strip().split('\n')
    groups = []
    current_group = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('- '):
            # Extract the bullet point content
            content = line[2:].strip()
            
            # Check if this is a topic header (contains keywords)
            topic_keywords = ['新機能', '利用可能', '対象', '詳細', '特徴', 'メリット', '更新', '変更', '追加']
            is_topic = any(keyword in content for keyword in topic_keywords)
            
            if is_topic and ':' in content:
                # This is a new topic group
                topic, details = content.split(':', 1)
                current_group = {
                    'topic': topic.strip(),
                    'items': [details.strip()] if details.strip() else []
                }
                groups.append(current_group)
            elif current_group:
                # Add to current group
                current_group['items'].append(content)
            else:
                # No group yet, create a default one
                if not groups or groups[-1].get('topic'):
                    groups.append({'topic': None, 'items': []})
                groups[-1]['items'].append(content)
    
    return groups


def create_slack_message(item):
    """Create a rich Slack message using Block Kit
    
    Args:
        item (dict): Dictionary containing RSS item information
        
    Returns:
        dict: Slack message in Block Kit format
    """
    # Sanitize summary and detail to ensure no XML tags remain
    safe_summary = sanitize_text(item['summary'])
    safe_detail = sanitize_text(item['detail'])
    
    # Parse bullet points from detail
    bullet_groups = parse_bullet_points(safe_detail)
    
    # Build blocks
    blocks = []
    
    # Header block
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": item['rss_title'][:150],  # Slack header limit
            "emoji": True
        }
    })
    
    # Context block for date/time
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"📅 *公開日時:* {item['rss_time']}"
            }
        ]
    })
    
    # Summary section
    if safe_summary:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📝 要約*\n{safe_summary}"
            }
        })
    
    # Divider
    blocks.append({"type": "divider"})
    
    # Detail sections
    if bullet_groups:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🔍 詳細分析*"
            }
        })
        
        # Add bullet point groups
        for group in bullet_groups:
            if group['topic']:
                # Topic header with emoji
                emoji = "📌"
                if "利用可能" in group['topic'] or "対象" in group['topic']:
                    emoji = "✅"
                elif "新機能" in group['topic'] or "追加" in group['topic']:
                    emoji = "🚀"
                elif "変更" in group['topic'] or "更新" in group['topic']:
                    emoji = "🔄"
                
                # Create formatted bullet list
                bullet_text = f"{emoji} *{group['topic']}*"
                if group['items']:
                    bullet_text += "\n" + "\n".join([f"• {item}" for item in group['items']])
                
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": bullet_text[:3000]  # Slack text limit
                    }
                })
            else:
                # Items without topic
                if group['items']:
                    bullet_text = "\n".join([f"• {item}" for item in group['items']])
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": bullet_text[:3000]
                        }
                    })
    
    # Another divider before action
    blocks.append({"type": "divider"})
    
    # Action block
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "📖 記事を読む",
                    "emoji": True
                },
                "url": item['rss_link'],
                "style": "primary"
            }
        ]
    })
    
    # Create message with blocks
    message = {
        "blocks": blocks,
        # Fallback text for notifications
        "text": f"{item['rss_title']} - {safe_summary[:100]}..."
    }
    
    return message

def get_new_entries(blog_entries):
    """Determine if there are new blog entries to notify on Slack by checking the eventName

    Args:
        blog_entries (list): List of blog entries registered in DynamoDB
    """

    res_list = []
    for entry in blog_entries:
        print(entry)
        if entry["eventName"] == "INSERT":
            new_data = {
                "rss_category": entry["dynamodb"]["NewImage"]["category"]["S"],
                "rss_time": entry["dynamodb"]["NewImage"]["pubtime"]["S"],
                "rss_title": entry["dynamodb"]["NewImage"]["title"]["S"],
                "rss_link": entry["dynamodb"]["NewImage"]["url"]["S"],
                "rss_notifier_name": entry["dynamodb"]["NewImage"]["notifier_name"]["S"],
            }
            print(new_data)
            res_list.append(new_data)
        else:  # Do not notify for REMOVE or UPDATE events
            print("skip REMOVE or UPDATE event")
    return res_list


def create_teams_message(item):
    message = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.3",
                    "body": [
                        {
                            "type": "ColumnSet",
                            "columns": [
                                {
                                    "type": "Column",
                                    "width": "auto",
                                    "items": [
                                        {
                                            "type": "Container",
                                            "id": "collapsedItems",
                                            "items": [
                                                {
                                                    "type": "TextBlock",
                                                    "text": f'**{item["rss_title"]}**',
                                                },
                                                {
                                                    "type": "TextBlock",
                                                    "wrap": True,
                                                    "text": f'{item["summary"]}',
                                                },
                                            ],
                                        },
                                        {
                                            "type": "Container",
                                            "id": "expandedItems",
                                            "isVisible": False,
                                            "items": [
                                                {
                                                    "type": "TextBlock",
                                                    "wrap": True,
                                                    "text": f'{item["detail"]}',
                                                }
                                            ],
                                        },
                                    ],
                                }
                            ],
                        },
                        {
                            "type": "Container",
                            "items": [
                                {
                                    "type": "ColumnSet",
                                    "columns": [
                                        {
                                            "type": "Column",
                                            "width": "stretch",
                                            "items": [
                                                {
                                                    "type": "TextBlock",
                                                    "text": "see less",
                                                    "id": "collapse",
                                                    "isVisible": False,
                                                    "wrap": True,
                                                    "color": "Accent",
                                                },
                                                {
                                                    "type": "TextBlock",
                                                    "text": "see more",
                                                    "id": "expand",
                                                    "wrap": True,
                                                    "color": "Accent",
                                                },
                                            ],
                                        }
                                    ],
                                    "selectAction": {
                                        "type": "Action.ToggleVisibility",
                                        "targetElements": [
                                            "collapse",
                                            "expand",
                                            "expandedItems",
                                        ],
                                    },
                                }
                            ],
                        },
                    ],
                    "actions": [
                        {
                            "type": "Action.OpenUrl",
                            "title": "Open Link",
                            "wrap": True,
                            "url": f'{item["rss_link"]}',
                        }
                    ],
                    "msteams": {"width": "Full"},
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                },
            }
        ],
    }

    return message


def handler(event, context):
    """Notify about blog entries registered in DynamoDB

    Args:
        event (dict): Information about the updated items notified from DynamoDB
    """

    try:
        new_data = get_new_entries(event["Records"])
        if 0 < len(new_data):
            push_notification(new_data)
    except Exception as e:
        print(traceback.print_exc())
