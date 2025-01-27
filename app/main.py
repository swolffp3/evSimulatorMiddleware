from os import environ
from random import randint
from logging import getLogger
from typing import Dict, List, Any, Optional

from pydantic import BaseModel
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi import FastAPI, Request, Response, status, WebSocket, WebSocketDisconnect, Depends, HTTPException, APIRouter, Body

topics: Dict[str, str] = dict(charging="off")
subscribers: Dict[str, List[WebSocket]] = dict()
app = FastAPI(root_path="/api/v1")
log = getLogger("uvicorn.error")

users = dict(test=dict(username="test", password="test", userId=1),
             subscriber=dict(username="subscriber", password="subscribe", userId=2)
)
sessions = dict()

class Topic(BaseModel):
    name: Optional[str] = None
    value: Optional[str] = None


def validJsonBody(request: Request) -> Dict[str, Any]:
    try:
        return request.json()
    except Exception as e:
        return e

def validateJsonBody(REQUIRED_KEYS: List[str], body: Dict[str, str]) -> List[str]:
    missingKeys = list()
    for key in REQUIRED_KEYS:
        if key not in body:
            missingKeys.append(key)
    return missingKeys


# def authenticateUser(credentials: HTTPBasicCredentials=Depends(security)):
#     user = users.get(credentials.username)
#     if user is None or user.get("password") != credentials.password:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid credentials",
#             headers={"WWW-Authenticate": "Basic"},
#         )
#     return user

# def createSession(userId: int):
#     sessionId = len(sessions) + randint(0, 1000000)
#     sessions[sessionId] = userId
#     return sessionId

# @router.post("login")
# def login(user: dict=Depends(authenticateUser)):
#     sessionId = createSession(user.get("userId"))
#     return {"message": "Logged in successfully", "sessionId": sessionId}

# Read all or a specific topic value
@app.get("/topics", status_code=status.HTTP_200_OK,
    name="Get all topics",
    description="Returns a list of all existing topics which their values."
)
def getAllTopics():
    log.info("All topics were requested")
    return {"topics": dict(topics.items())}

@app.get("/topics/{topic}", status_code=status.HTTP_200_OK,
    name="Get a topic",
    description="Returns the requested topic with its value."
)
def getIndividualTopic(topic: str, response: Response):
    if topic not in topics:
        response.status_code = status.HTTP_404_NOT_FOUND
        return dict()
    log.info(f"The '{topic}' topic was requested")
    return {"value": topics.get(topic)}


# Create a topic if it not already exists
@app.post("/topics", status_code=status.HTTP_201_CREATED,
    name="Create a topic",
    description="Creates a new topic."
)
async def createTopic(request: Request, response: Response, body: Topic=Body(...)):
    REQUIRED_KEYS = ["name", "value"]
    requestBody = await validJsonBody(request)
    missingKeys = validateJsonBody(REQUIRED_KEYS, requestBody)
    if len(missingKeys) > 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            f"The following keys are missing: '{missingKeys}'")

    topic = requestBody.get("name")
    value = requestBody.get("value")
    if topic in topics:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            f"A topic with the name '{topic}' already exists")

    topics[topic] = value
    log.info(f"The '{topic}' topic with '{value}' as intial value was created")
    return {topic: topics.get(topic)}


# Update the value of a existing topic
@app.patch("/topics/{topic}", status_code=status.HTTP_200_OK,
    name="Update value of a topic",
    description="Update a value of an existing topic. Triggers an event at the subscribers of the topic."
)
async def updateTopic(topic: str, request: Request, response: Response, body: Topic=Body(..., example={"value": "string"})):
    REQUIRED_KEYS = ["value"]
    requestBody = await validJsonBody(request)
    missingKeys = validateJsonBody(REQUIRED_KEYS, requestBody)
    if len(missingKeys) > 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            f"The following keys are missing: '{missingKeys}'")

    newValue = requestBody.get("value")
    if topic == "charging" and newValue != "A" and newValue != "B" and newValue != "C" and newValue != "D" and newValue != "off":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Only 'A', 'B', 'C', 'D', and 'off' are allowed values for topic 'charging'")

    if topic not in topics:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
            f"The topic {topic} doesn't exists")

    oldValue = topics.get(topic)
    topics[topic] = newValue
    if topic in subscribers:
        for subscriber in subscribers[topic]:
            try:
                await subscriber.send_text(topics.get(topic))
            except Exception as e:
                print(f"Failed to notify subscriber: {e}")
    log.info(f"The value from '{topic}' was changed from '{oldValue}' to '{newValue}'")
    return {"message": f"Topic '{topic}' updated successfully","value": newValue}


# Delete an existing topic
@app.delete("/topics/{topic}", status_code=status.HTTP_204_NO_CONTENT,
    name="Delete a topic",
    description="Deletes a topic and closes all connections to the clients which subscribes this topic."
)
async def deleteTopic(topic: str, response: Response):
    if topic == "charging":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            "The topic 'charging' can't be deleted")

    if topic not in topics:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
            f"No topic named: '{topic}'")

    topics.pop(topic)

    # Close all opened websocket connections from the topic which will removed
    if topic in subscribers:
        for subscriber in subscribers.get(topic):
            await subscriber.close()
        subscribers.pop(topic)
    log.info(f"The '{topic}' topic was removed and all connections to the subscribors were closed")
    return {}


# Websocket connection endpoint to subscribe a topic
@app.websocket("/topics/{topic}/subscribe")
async def subscribeTopic(topic: str, websocket: WebSocket):
    if topic not in topics:
        log.warning("Subscriber refused because the '{topic}' topic doesn't exists")
        await websocket.close()
    else:
        log.info("A new subscriber appeared")
        await websocket.accept()
        if topic not in subscribers:
            subscribers[topic] = list()
        subscribers[topic].append(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            if subscribers.get(topic):
                subscribers[topic].remove(websocket)


# Entry point of program
if __name__ == "__main__":
    port = int(environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)