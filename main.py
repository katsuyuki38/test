from fastapi import FastAPI, BackgroundTasks
import time

app = FastAPI()

def run_timer(background_task: BackgroundTasks, seconds: int):
    time.sleep(seconds)
    print(f"Timer done! Waited for {seconds} seconds.")

@app.post("/start_timer/")
async def start_timer(background_task: BackgroundTasks, seconds: int):
    background_task.add_task(run_timer, background_task, seconds)
    return {"message": "Timer started"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
