from os import environ
from logging import getLogger
from secrets import compare_digest
from argparse import ArgumentParser, Namespace
from typing import Dict, List, Any, Optional, Union

from uvicorn import run
from pydantic import BaseModel
from bcrypt import hashpw, checkpw, gensalt
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi import FastAPI, Request, Response, status, WebSocket, WebSocketDisconnect, HTTPException, Body, Depends


topics: Dict[str, str] = dict(cp="off")
subscribers: Dict[str, List[WebSocket]] = dict()

app = FastAPI(root_path="/api/v1")
log = getLogger("uvicorn.error")

security = HTTPBasic()

def authenticateUser(credentials: HTTPBasicCredentials=Depends(security)):
    """
    authenticateUser Checks whether the credentials are valid.

    Keyword Arguments:
        credentials -- The basic authentication credentials. (default: {Depends(security)})

    Raises:
        HTTPException: HTTP - 401 if the credentials are not valid.

    Returns:
        The username.
    """
    receivedPassword = credentials.password = credentials.password.encode("UTF-8")
    usernameCorrect = compare_digest(credentials.username, VALID_USERNAME)
    passwordCorrect = checkpw(receivedPassword, VALID_PASSWORD)

    if not (usernameCorrect and passwordCorrect):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid credentials",
            {"WWW-Authenticate": "Basic"}
        )
    return credentials.username

class Topic(BaseModel):
    name: Optional[str] = None
    value: Optional[str] = None


def validJsonBody(request: Request) -> Union[Dict[str, Any], str]:
    """
    validJsonBody Checks whether a request body is a valid JSON object.

    Arguments:
        request -- The request body.

    Returns:
        The parsed JSON body or the error.
    """
    try:
        return request.json()
    except Exception as e:
        return e

def validateJsonBody(REQUIRED_KEYS: List[str], body: Dict[str, str]) -> List[str]:
    """
    validateJsonBody Validates a JSON body. I details it checks whether all required keys are given.

    Arguments:
        REQUIRED_KEYS -- A list of required keys.
        body -- The request body.

    Returns:
        The list with the missing fields.
    """
    missingKeys = list()
    for key in REQUIRED_KEYS:
        if key not in body:
            missingKeys.append(key)
    return missingKeys


# Read all or a specific topic value
@app.get("/topics", status_code=status.HTTP_200_OK,
    name="Get all topics",
    description="Returns a list of all existing topics with their values.")
def getAllTopics(username: str = Depends(authenticateUser)):
    """
    getAllTopics Returns a list of key value pairs of all topics.

    Keyword Arguments:
        username -- The basic authentication credentials. (default: {Depends(authenticateUser)})

    Returns:
        HTTP - 200 if a list of all items is returned.
    """
    log.info("All topics were requested")
    return {"topics": dict(topics.items())}


@app.get("/topics/{topic}", status_code=status.HTTP_200_OK,
    name="Get a topic",
    description="Returns the requested topic with its value.")
def getIndividualTopic(topic: str, response: Response, credentials: str = Depends(authenticateUser)):
    """
    getIndividualTopic Returns the value of a specific topic.

    Arguments:
        topic -- The topic.
        response -- The response object.

    Keyword Arguments:
        credentials -- The basic authentication credentials. (default: {Depends(authenticateUser)})

    Raises:
        HTTPException: HTTP - 404 if the topic doesn't exists.
    Returns:
        HTTP - 200 if the value of the topic is returned.
    """
    if topic not in topics:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
        f"The topic {topic} doesn't exists")
    log.info(f"The '{topic}' topic was requested")
    return {"value": topics.get(topic)}


# Creates a topic if it not already exists
@app.post("/topics", status_code=status.HTTP_201_CREATED,
    name="Create a topic",
    description="Creates a new topic.")
async def createTopic(request: Request, response: Response, body: Topic=Body(...), credentials: str = Depends(authenticateUser)):
    """
    createTopic Creates a new topic.

    Arguments:
        request -- The request object.
        response -- The response object.

    Keyword Arguments:
        body -- Creates the wassger ui body example. (default: {Body(...)})
        credentials -- The basic authentication credentials. (default: {Depends(authenticateUser)})

    Raises:
        HTTPException: HTTP - 400 if a required field in body is missing.
        HTTPException: HTTP - 404 if the topic doesn't exists.

    Returns:
        HTTP 201 if the topic is created successfully.
    """
    REQUIRED_KEYS = ["name", "value"]
    requestBody = await validJsonBody(request)
    missingKeys = validateJsonBody(REQUIRED_KEYS, requestBody)
    if len(missingKeys) > 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            f"The following keys are missing: '{missingKeys}'")

    topic = requestBody.get("name")
    value = requestBody.get("value")
    if topic in topics:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
            f"A topic with the name '{topic}' already exists")

    topics[topic] = value
    log.info(f"The '{topic}' topic with '{value}' as intial value was created")
    return {topic: topics.get(topic)}


# Updates a value of an existing topic
@app.patch("/topics/{topic}", status_code=status.HTTP_200_OK,
    name="Update value of a topic",
    description="Update a value of an existing topic. Triggers an event at the subscribers of the topic.")
async def updateTopic(topic: str, request: Request, response: Response, body: Topic=Body(..., example={"value": "string"}), credentials: str = Depends(authenticateUser)):
    """
    updateTopic Updates a value of a topic. Renaming a topic is denied. If a topic is updated all subscriber of it are informed.

    Arguments:
        topic -- The topic.
        request -- The request object.
        response -- The response object.

    Keyword Arguments:
        body -- Creates the Swagger ui body example. (default: {Body(..., example={"value": "string"})})
        credentials -- The basic authentication credentials. (default: {Depends(authenticateUser)})

    Raises:
        HTTPException: HTTP - 400 if not all required fields are received.
        HTTPException: HTTP - 422 if an unallowed value is sent.
        HTTPException: HTTP - 404 if the topic doesn't exists.

    Returns:
        HTTP - 200 if the value was updated.
    """
    REQUIRED_KEYS = ["value"]
    requestBody = await validJsonBody(request)
    missingKeys = validateJsonBody(REQUIRED_KEYS, requestBody)
    if len(missingKeys) > 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            f"The following keys are missing: '{missingKeys}'")

    newValue = requestBody.get("value")
    if topic == "cp" and newValue != "A" and newValue != "B" and newValue != "C" and newValue != "D" and newValue != "off":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Only 'A', 'B', 'C', 'D', and 'off' are allowed values for topic 'cp'")

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
    description="Deletes a topic and closes all connections to the clients which subscribes this topic.")
async def deleteTopic(topic: str, response: Response, credentials: str = Depends(authenticateUser)):
    """
    deleteTopic Deletes an existing topic specified by path variable 'topic'

    Arguments:
        topic -- The topic which will be deleted.
        response -- The response object.

    Keyword Arguments:
        credentials -- The basic authentication credentials. (default: {Depends(authenticateUser)})

    Raises:
        HTTPException: HTTP - 400 because you can't remove the the topic cp.
        HTTPException: HTTP - 404 if the topic doesn't exists.

    Returns:
        HTTP 204 if the topic is deleted.
    """
    if topic == "cp":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            "The topic 'cp' can't be deleted")

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
    """
    subscribeTopic A websocket api where incoming messages are ignored.
    Subscribers just are informed when a subscribed topic is updated.

    Arguments:
        topic -- The subscribed topic.
        websocket -- The websocket object.
    """
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


def hashPassword(password: str) -> bytes:
    """
    hashPassword Hashes the passed password with the bcrypt library.

    Arguments:
        password -- The plaintext password.

    Returns:
        The hashed password.
    """
    return hashpw(password.encode("utf-8"), gensalt())

def parseCommandLineArgs() -> Namespace:
    """
    parseCommandLineArgs Parses passed arguments. Username and password are required.

    Returns:
        The parsed arguments as namespace.
    """
    parser = ArgumentParser(add_help=True)
    parser.add_argument("-u", "--username", type=str, dest="username", required=True, help="The required username for basic authentication")
    parser.add_argument("-p", "--password", type=hashPassword, dest="password", required=True, help="The required password for basic authentication")
    return parser.parse_args()

def main(credentials: Namespace) -> None:
    """
    main The main function of the service.

    Arguments:
        credentials -- The credentials which are passed to the service.
    """
    global VALID_USERNAME
    global VALID_PASSWORD
    VALID_USERNAME = credentials.username
    VALID_PASSWORD = credentials.password
    port = int(environ.get("PORT", 8000))
    run(app, host="0.0.0.0", port=port)


# Entry point of program
if __name__ == "__main__":
    main(parseCommandLineArgs())