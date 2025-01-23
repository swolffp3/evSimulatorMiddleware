from os import environ
from logging import getLogger

from typing import Dict, List, Any
from fastapi import FastAPI, Request, Response, status, WebSocket, WebSocketDisconnect


topics: Dict[str, str] = dict(charging="disabled")
subscribers: Dict[str, List[WebSocket]] = dict()
app = FastAPI()
log = getLogger("uvicorn.error")

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

# Read all or a specific topic value
@app.get("/topics", status_code=status.HTTP_200_OK)
def getAllTopicsWithValue():
    log.info("All topics were requested")
    return {"topics": dict(topics.items())}

@app.get("/topics/{topic}", status_code=status.HTTP_200_OK)
def getTopicWithValue(topic: str, response: Response):
    if topic not in topics:
        response.status_code = status.HTTP_404_NOT_FOUND
        return dict()
    log.info(f"The '{topic}' topic was requested")
    return {"value": topics.get(topic)}


# Create a topic if it not already exists
@app.post("/topics", status_code=status.HTTP_201_CREATED)
async def createTopic(request: Request, response: Response):
    REQUIRED_KEYS = ["name", "value"]
    requestBody = await validJsonBody(request)
    missingKeys = validateJsonBody(REQUIRED_KEYS, requestBody)
    if len(missingKeys) > 0:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"message": f"The following keys are missing: '{missingKeys}'"}

    topic = requestBody.get("name")
    value = requestBody.get("value")
    if topic in topics:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"message": f"A topic with the name '{topic}' already exists"}

    topics[topic] = value
    log.info(f"The '{topic}' topic with '{value}' as intial value was created")
    return {topic: topics.get(topic)}


# Update the value of a existing topic
@app.patch("/topics/{topic}")
async def updateTopic(topic: str, request: Request, response: Response):
    REQUIRED_KEYS = ["value"]
    requestBody = await validJsonBody(request)
    missingKeys = validateJsonBody(REQUIRED_KEYS, requestBody)
    if len(missingKeys) > 0:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"message": f"The following keys are missing: '{missingKeys}'"}

    newValue = requestBody.get("value")
    if topic not in topics:
        response.status_code = status.HTTP_404_NOT_FOUND
        return dict()

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
@app.delete("/topics/{topic}", status_code=status.HTTP_204_NO_CONTENT)
async def deleteTopic(topic: str, response: Response):
    if topic not in topics:
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"message": f"No topic named: '{topic}'"}
    topics.pop(topic)

    # Close all opened websocket connections from the topic which will removed
    if topic in subscribers:
        for subscriber in subscribers.get(topic):
            await subscriber.close()
        subscribers.pop(topic)
    log.info(f"The '{topic}' topic was removed and all connections to the subscribors were closed")
    return {"message": f"Removed topic '{topic}' successfully"}


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