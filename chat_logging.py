#####################################################################################################################
# Description:
# The chat_logging.py module is responsible for handling all logging-related functionality for user login and chat history 
# in the Ivy Chatbot application. It provides functions to log user login events, store chat interactions, 
# update chat reactions, fetch flagged messages, and generate CSV files of flagged chats. 
#####################################################################################################################

import time
from datetime import datetime, timezone
import boto3
import csv
import tempfile
import os


# Initialize DynamoDB
dynamodb = boto3.resource("dynamodb")
login_table = dynamodb.Table("UserLogin")
chat_history_table = dynamodb.Table("ChatHistory")

def log_user_login(user_id, session_id):
        timestamp = time.time()
        dt = datetime.fromtimestamp(timestamp)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")
        login_data = {
            "Username": user_id,
            "SessionId": session_id,
            "Timestamp": timestamp,
        }
        login_table.put_item(Item=login_data)

def log_chat_history(user_id, session_id, question, response, reaction):
    timestamp = time.time()
    dt = datetime.fromtimestamp(timestamp)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")

    chat_data = {
        "Username": user_id,
        "SessionId": session_id,
        "Timestamp": timestamp,
        "Question": question,
        "Response": response,
        "Reaction": reaction,
    }

    # Check if item exists and update or put item
    existing_item = chat_history_table.get_item(
        Key={
            "Username": user_id,
            "Timestamp": timestamp,
        }
    )

    if "Item" in existing_item:
        update_chat_history(user_id, session_id, question, response, reaction)
        print("Chat data updated successfully")
    else:
        chat_history_table.put_item(Item=chat_data)
        print("Chat data logged successfully")

def update_chat_history(user_id, session_id, question, response, reaction):
    timestamp = time.time()
    dt = datetime.fromtimestamp(timestamp)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")

    # Update item in DynamoDB
    response = chat_history_table.update_item(
        Key={
            "Username": user_id,
            "Timestamp": timestamp,
        },
        UpdateExpression="SET Reaction = :reaction",
        ExpressionAttributeValues={":reaction": reaction},
        ReturnValues="UPDATED_NEW",
    )

####################################################################################
# Handling Flagged Responses
####################################################################################

def fetch_flagged_messages(user_id, session_id):
        response = chat_history_table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr("Username").eq(user_id)
            & boto3.dynamodb.conditions.Attr("SessionId").eq(session_id)
            & boto3.dynamodb.conditions.Attr("Reaction").eq("flagged")
        )
        return response.get("Items", [])

def generate_csv(user_id, session_id):
    items = fetch_flagged_messages(user_id, session_id)
    if not items:
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")
    temp_dir = tempfile.gettempdir()
    filepath = os.path.join(temp_dir, f"{user_id}_{timestamp}_flagged.csv")

    with open(filepath, mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "Username",
                "Timestamp",
                "Question",
                "Response",
                "Reaction",
            ]
        )
        for item in items:
            writer.writerow(
                [
                    item["Username"],
                    item["Timestamp"],
                    item["Question"],
                    item["Response"],
                    item["Reaction"],
                ]
            )

    return filepath
