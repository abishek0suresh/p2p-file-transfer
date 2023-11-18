from fastapi import FastAPI, File, UploadFile, Request, WebSocket, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from starlette.responses import FileResponse
from fastapi.templating import Jinja2Templates
import os
import shutil
import uvicorn
import asyncio
import websockets
import jwt

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Hardcoded secret key for JWT (replace with a strong, secret key in production)
SECRET_KEY = "mysecretkey"

# Keep track of connected peers and known peers
connected_peers = set()
known_peers = set()


async def discover_peers():
    while True:
        await asyncio.sleep(10)  # Adjust the interval as needed
        for peer in known_peers.copy():
            try:
                async with websockets.connect(f"ws://{peer}/ws") as ws:
                    await ws.send("DISCOVER")
            except websockets.exceptions.ConnectionClosed:
                known_peers.discard(peer)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(discover_peers())


async def get_current_peer(request: Request):
    return request.client.host


def create_jwt(data: dict):
    return jwt.encode(data, SECRET_KEY, algorithm="HS256")


def decode_jwt(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@app.get("/")
async def home(request: Request, current_peer: str = Depends(get_current_peer)):
    files = os.listdir("uploads/")
    return templates.TemplateResponse("index.html", {"request": request, "files": files, "current_peer": current_peer})


@app.post("/uploadfile/")
async def create_upload_file(file: UploadFile = File(...)):
    file_path = f"uploads/{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"filename": file.filename}


@app.get("/downloadfile/{filename}")
async def download_file(filename: str):
    file_path = f"uploads/{filename}"
    return FileResponse(file_path)


@app.get("/listfiles/")
async def list_files():
    files = os.listdir("uploads/")
    return {"files": files}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, current_peer: str = Depends(get_current_peer)):
    connected_peers.add(current_peer)

    await websocket.accept()

    try:
        while True:
            message = await websocket.receive_text()
            if message == "DISCOVER":
                # Respond with a list of connected peers
                await websocket.send_text("\n".join(connected_peers))
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_peers.discard(current_peer)


@app.get("/sharefile/{filename}/{target_ip}")
async def share_file(filename: str, target_ip: str, current_peer: str = Depends(get_current_peer)):
    file_path = f"uploads/{filename}"

    try:
        async with websockets.connect(f"ws://{target_ip}/ws") as ws:
            token = create_jwt({"filename": filename, "peer": current_peer})
            await ws.send(f"SHARE {token}")
            # Code to send the file content to the target peer
    except websockets.exceptions.ConnectionClosed:
        return {"message": f"Could not connect to {target_ip}"}

    return {"message": f"File {filename} has been shared with {target_ip}"}


def create_app():
    os.makedirs("uploads", exist_ok=True)
    return app


if __name__ == '__main__':
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
