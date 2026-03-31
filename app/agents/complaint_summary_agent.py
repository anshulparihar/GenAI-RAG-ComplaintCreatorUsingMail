import os
import json
import re
from ollama import Client, chat
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "98036d790377434c84f79ac038fd965f.U0vHYw41mQaeqFMt_d-lHbss")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral-large-3:675b-cloud")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "https://ollama.com")


def get_ollama_client():
    client = Client(
        host=OLLAMA_HOST,
        headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"}
    )
    return client


def complaint_extracter(system_prompt: str, user_prompt: str) -> str:
    """Send a prompt to Ollama with system and user messages, return the response."""
    logger.info(f"---- Inside complaint_extracter ----")
    client = get_ollama_client()
    response = client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    logger.info(f"---- Response: {response.message.content[:100]} ----")
    return response.message.content


def _extract_json(text: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    # Try to find JSON in markdown code blocks
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        # Try finding raw JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON: {text[:200]}")
        return None


def classify_email(email_id: str, sender: str, subject: str, body: str, email_date: str = "") -> dict:
    """
    Classify an email as complaint or non-complaint and extract fields.

    Args:
        email_id: Gmail message ID
        sender: Email sender
        subject: Email subject
        body: Email body
        email_date: Email date (optional)

    Returns:
        dict with classification fields (including email_id)
    """
    # Read classification prompt from file
    file_path = "app/agents/classification_prompt.txt"
    logger.info(f"---- Reading prompt from: {file_path} ----")
    with open(file_path, "r", encoding="utf-8") as file:
        system_prompt = file.read()

    # Build email content to classify
    email_content = f"""From: {sender}
        Date: {email_date}
        Subject: {subject}

        Body:
        {body}

    ## Output Format
    Return ONLY a valid JSON object with no additional text."""

    # Call Ollama with system prompt (instructions) + user prompt (email data)
    response_text = complaint_extracter(system_prompt, email_content)

    # Parse JSON response
    result = _extract_json(response_text)
    if result is None:
        return {"is_complaint": "0", "email_id": email_id, "error": "Failed to parse LLM response"}

    # Add email_id to result
    result["email_id"] = email_id
    return result

def suggest_filed(subject, body):
    file_path = "app/agents/suggestion_prompt.txt"
    logger.info(f"---- Reading prompt from: {file_path} ----")
    with open(file_path, "r", encoding="utf-8") as file:
        system_prompt = file.read()

    user_prompt = f"""Subject: {subject}
        Body:
        {body}

    ## Output Format
    Return ONLY a valid JSON object with no additional text."""
    # Call Ollama with system prompt (instructions) + user prompt (email data)
    response_text = complaint_extracter(system_prompt, user_prompt)


def chat_with_context(system_prompt: str, user_message: str) -> str:
    """Send a chat message to Ollama and return the response."""
    client = get_ollama_client()
    response = client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    return response.message.content