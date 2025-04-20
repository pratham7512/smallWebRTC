from datetime import datetime
from typing import List, Dict
from pymongo import MongoClient
import os

class MongoDBHandler:
    def __init__(self):
        # Get MongoDB connection string from environment variable
        self.connection_string = os.getenv("MONGODB_URI", "mongodb+srv://admin:desai1969@cluster0.mqucw.mongodb.net/db1?retryWrites=true&w=majority")
        self.client = MongoClient(self.connection_string)
        self.db = self.client.db1
        self.chats = self.db.chats

    def save_chat(self, user_id: str, chat_id: str, messages: List[Dict]):
        """
        Save chat messages to MongoDB
        
        Args:
            user_id (str): User identifier
            chat_id (str): Chat session identifier
            messages (List[Dict]): List of message objects
        """
        chat_data = {
            "user_id": user_id,
            "chat_id": chat_id,
            "messages": messages,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }
        
        self.chats.insert_one(chat_data)
        return chat_data

    def close(self):
        """Close MongoDB connection"""
        self.client.close()

# Create a global instance
mongodb_handler = MongoDBHandler() 