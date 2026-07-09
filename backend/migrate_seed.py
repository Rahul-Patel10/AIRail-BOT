"""
migrate_seed.py — Idempotent migration to add new ADI-origin trains to live DB.
Run while backend is running; uses upsert logic so it is safe to run multiple times.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import Session, Train, Station, TrainSchedule

NEW_TRAINS = [
    ("19031", "Haridwar Express",       "ADI", "HWH",  "Tue,Fri"),
    ("22955", "Gujarat SF Express",      "ADI", "BCT",  "Daily"),
    ("16531", "Garib Nawaz Express",     "ADI", "SBC",  "Mon,Wed"),
    ("19032", "ADI Haridwar Express",    "HWH", "ADI",  "Wed,Sat"),
    ("19033", "Gujarat Queen Express",   "ADI", "NDLS", "Daily"),
]

NEW_SCHEDULES = [
    # 19031: ADI → BPL → NGP → HWH
    ("19031", 1, "ADI", "--:--", "11:30", 0),
    ("19031", 2, "BPL", "05:10", "05:20", 702),
    ("19031", 3, "NGP", "11:05", "11:15", 1110),
    ("19031", 4, "HWH", "12:30", "--:--", 2130),
    # 22955: ADI → BCT
    ("22955", 1, "ADI", "--:--", "07:10", 0),
    ("22955", 2, "BCT", "16:00", "--:--", 493),
    # 16531: ADI → SC → SBC
    ("16531", 1, "ADI", "--:--", "14:05", 0),
    ("16531", 2, "SC",  "17:00", "17:10", 1100),
    ("16531", 3, "SBC", "02:30", "--:--", 1724),
    # 19032: HWH → BPL → ADI
    ("19032", 1, "HWH", "--:--", "23:55", 0),
    ("19032", 2, "NGP", "01:15", "01:25", 1020),
    ("19032", 3, "BPL", "07:10", "07:20", 1428),
    ("19032", 4, "ADI", "01:00", "--:--", 2130),
    # 19033: ADI → JP → NDLS
    ("19033", 1, "ADI",  "--:--", "05:20", 0),
    ("19033", 2, "JP",   "16:05", "16:10", 671),
    ("19033", 3, "NDLS", "22:05", "--:--", 934),
]

with Session() as db:
    for train_no, name, src, dest, days in NEW_TRAINS:
        existing = db.query(Train).filter(Train.train_no == train_no).first()
        if not existing:
            db.add(Train(train_no=train_no, train_name=name, source_code=src, dest_code=dest, run_days=days))
            print(f"  [+] Train {train_no} {name}")
        else:
            print(f"  [=] Train {train_no} already exists — skipping")

    db.flush()

    for train_no, stop_no, station, arr, dep, dist in NEW_SCHEDULES:
        exists = db.query(TrainSchedule).filter(
            TrainSchedule.train_no == train_no,
            TrainSchedule.stop_number == stop_no,
        ).first()
        if not exists:
            db.add(TrainSchedule(
                train_no=train_no, stop_number=stop_no,
                station_code=station, arrival=arr,
                departure=dep, distance_km=dist,
            ))

    db.commit()
    print("Migration complete.")
