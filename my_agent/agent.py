import os
from dotenv import load_dotenv

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from pymongo.mongo_client import MongoClient, UpdateOne
from pymongo.server_api import ServerApi

from my_agent.tools import QueryValidatorTools, MongoExecutorTools
from my_agent.instructions import WORKLOG_EXEC_AGENT_INSTRUCTION


# Load environment variable
load_dotenv()

# Connection Creds
GPT_KEY = os.getenv("OPENAI_API_KEY")
MONGO_DB_USER = os.getenv("db_user")
MONGO_DB_PASSWORD = os.getenv("db_password")

# MONGO DB connection uri
mongo_uri = f"mongodb+srv://{MONGO_DB_USER}:{MONGO_DB_PASSWORD}@cluster0.tjivksu.mongodb.net/?appName=Cluster0"

# Create a new client and connect to the server
mongo_client = MongoClient(mongo_uri, server_api=ServerApi('1'))

# Tools to be used
validator = QueryValidatorTools()

# Mongo executor tool
executor = MongoExecutorTools(mongo_client, "worklog_agent", max_limit=500)

# Send a ping to confirm a successful connection
try:
    mongo_client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)


root_agent = LlmAgent(
    name="worklog_agent",
    instruction=WORKLOG_EXEC_AGENT_INSTRUCTION,
    tools=[
        validator.validate_query_spec,
        executor.run_query,
    ],
    model=LiteLlm(model="openai/responses/gpt-5.2-pro"),
)
