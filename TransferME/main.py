from fastapi import FastAPI, Request, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

# Mount static + templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/transfer/spotify-to-soundcloud")
async def spotify_to_soundcloud(
    request: Request,
    spotify_url: str = Form(...)
):
    # Call your script logic here
    from spotify import transfer_to_spotify
    from soundcloud import transfer_to_soundcloud

    txt_file, name = transfer_to_spotify(spotify_url)
    result = transfer_to_soundcloud(txt_file, name)

    return templates.TemplateResponse("result.html", {
        "request": request,
        "message": result
    })


@app.post("/transfer/soundcloud-to-spotify")
async def soundcloud_to_spotify(
    request: Request,
    soundcloud_url: str = Form(...)
):
    from soundcloud import transfer_to_spotify
    from transfer import transfer_to_spotify

    txt_file, name = transfer_to_spotify(soundcloud_url)
    result = transfer_to_spotify(txt_file, name)

    return templates.TemplateResponse("result.html", {
        "request": request,
        "message": result
    })
