"""FastAPI app.

    uvicorn app.main:app --reload --port 8000

Flow the UI follows:
    POST /api/history/upload   last month's sheet, on the last day of the month
    POST /api/roster/generate  build the new month
    GET  /api/roster/{id}/export.xlsx
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .config import MIN_PER_CLIENT_SHIFT, OFF_DAYS_PER_WEEK, SHIFTS, WEEKDAYS
from .parsing import RosterParseError
from .service import RosterService
from .solver import InfeasibleRoster

app = FastAPI(title="Roster builder", version="1.0.0",
              description="Learns from last month's roster and builds the next one.")

#: Only needed while the UI runs on its own dev server. Served from this app
#: (the production path) it is same-origin and CORS never comes into it.
#: Override with ROSTER_CORS_ORIGINS="http://localhost:4300,http://192.168.1.5:4200".
CORS_ORIGINS = [origin.strip() for origin
                in os.environ.get("ROSTER_CORS_ORIGINS",
                                  "http://localhost:4200,http://127.0.0.1:4200").split(",")
                if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = RosterService()


class GenerateRequest(BaseModel):
    month: Optional[str] = Field(None, description='Target month, "2025-07". '
                                                   "Defaults to the month after the uploaded one.")
    source_month: Optional[str] = Field(None, description="Which stored month to build from.")
    employees: Optional[list[dict]] = Field(None, description="Override the team (e.g. new joiners).")
    seed: int = 42
    time_limit_seconds: float = Field(20.0, ge=1.0, le=300.0)
    min_per_client_shift: int = Field(MIN_PER_CLIENT_SHIFT, ge=1, le=20)
    balance_slack: int = Field(1, ge=0, le=50)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "history_months": len(service.store.months())}


@app.get("/api/rules")
def rules() -> dict:
    """The constraints the UI displays, straight from the backend config."""
    return {
        "shifts": SHIFTS,
        "off_days_per_week": OFF_DAYS_PER_WEEK,
        "weekdays": WEEKDAYS,
        "min_per_client_shift": MIN_PER_CLIENT_SHIFT,
    }


@app.post("/api/history/upload")
async def upload_history(file: UploadFile = File(...), month: Optional[str] = Form(None),
                         persist: bool = Form(True)) -> dict:
    """Upload last month's roster (xlsx / csv / json) and retrain on it."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    try:
        return service.upload(content, file.filename or "roster.xlsx", month, persist)
    except RosterParseError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/api/history")
def history() -> dict:
    return {"months": service.history(), "model": service.model_report()}


@app.delete("/api/history/{month}")
def delete_month(month: str) -> dict:
    if not service.delete_month(month):
        raise HTTPException(status_code=404, detail=f"No stored roster for {month}.")
    return {"deleted": month, "model": service.model_report()}


@app.post("/api/train")
def train() -> dict:
    service.train()
    return service.model_report()


@app.get("/api/model")
def model() -> dict:
    return service.model_report()


@app.post("/api/roster/generate")
def generate(request: GenerateRequest) -> dict:
    try:
        roster = service.generate(**request.model_dump())
    except InfeasibleRoster as error:
        raise HTTPException(status_code=422, detail={"reasons": error.reasons})
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return roster.to_dict()


@app.get("/api/roster/{roster_id}")
def get_roster(roster_id: str) -> dict:
    roster = service.get(roster_id)
    if roster is None:
        raise HTTPException(status_code=404, detail="Unknown roster id.")
    return roster.to_dict()


@app.get("/api/roster/{roster_id}/export.xlsx")
def export_xlsx(roster_id: str) -> Response:
    payload = service.export_xlsx(roster_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Unknown roster id.")
    roster = service.get(roster_id)
    filename = f"roster-{roster.month.key}.xlsx"
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/roster/{roster_id}/export.csv")
def export_csv(roster_id: str) -> Response:
    payload = service.export_csv(roster_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Unknown roster id.")
    roster = service.get(roster_id)
    return Response(content=payload, media_type="text/csv",
                    headers={"Content-Disposition":
                             f'attachment; filename="roster-{roster.month.key}.csv"'})


# Serve the built Angular app when it is there, so one process runs everything.
# Angular puts the browser bundle in dist/<project>/browser; older builds wrote
# straight into dist/<project>, so accept either.
_DIST_ROOT = Path(__file__).resolve().parent.parent.parent / "dist" / "button-app"
_DIST = next((path for path in (_DIST_ROOT / "browser", _DIST_ROOT)
              if (path / "index.html").exists()), None)
if _DIST is not None:
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="ui")
