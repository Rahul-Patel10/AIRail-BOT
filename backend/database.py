"""
database.py — SQLite Database Setup & Seed Data
================================================
Defines all ORM models and seeds the database with realistic Indian
Railway mock data (trains, stations, schedules, PNRs, seat availability).

Tables:
  - Train            : Master list of trains with source/destination
  - Station          : All major Indian stations (code + name + city)
  - TrainSchedule    : Per-train ordered list of stops with timings
  - SeatAvailability : Available seats per class per date per train
  - PNRRecord        : Mock passenger booking records
  - PNRWatchlist     : PNRs that the user asked the bot to "watch"
  - ChatSession      : Stores conversation messages per session ID
"""

import os
from datetime import datetime, date, timedelta
from sqlalchemy import (
    create_engine, Column, String, Integer,
    DateTime, Date, Boolean, Text, Float, ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# ── Database file lives next to this script ───────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "railway.db")
ENGINE   = create_engine(f"sqlite:///{DB_PATH}", echo=False)
Session  = sessionmaker(bind=ENGINE)
Base     = declarative_base()


# ══════════════════════════════════════════════════════════════════════════════
#  ORM MODELS
# ══════════════════════════════════════════════════════════════════════════════

class Train(Base):
    """Master train info — number, name, and terminal stations."""
    __tablename__ = "trains"

    train_no    = Column(String(10), primary_key=True)
    train_name  = Column(String(100), nullable=False)
    source_code = Column(String(10), ForeignKey("stations.code"), nullable=False)
    dest_code   = Column(String(10), ForeignKey("stations.code"), nullable=False)
    # Days of operation (e.g. "Mon,Wed,Fri,Sun")
    run_days    = Column(String(50), default="Daily")

    schedule    = relationship("TrainSchedule",
                               back_populates="train",
                               order_by="TrainSchedule.stop_number",
                               cascade="all, delete")
    availability= relationship("SeatAvailability",
                               back_populates="train",
                               cascade="all, delete")


class Station(Base):
    """Indian railway station master."""
    __tablename__ = "stations"

    code        = Column(String(10), primary_key=True)   # e.g. "NDLS"
    name        = Column(String(100), nullable=False)     # e.g. "New Delhi"
    city        = Column(String(100), nullable=False)
    state       = Column(String(100), nullable=False)
    zone        = Column(String(20),  nullable=False)     # e.g. "NR"


class TrainSchedule(Base):
    """Ordered list of stops for each train."""
    __tablename__ = "train_schedule"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    train_no     = Column(String(10), ForeignKey("trains.train_no"), nullable=False)
    stop_number  = Column(Integer, nullable=False)        # 1 = origin, N = destination
    station_code = Column(String(10), ForeignKey("stations.code"), nullable=False)
    arrival      = Column(String(10), default="--:--")    # "HH:MM" or "--:--" for origin
    departure    = Column(String(10), default="--:--")    # "HH:MM" or "--:--" for dest
    distance_km  = Column(Integer, default=0)             # from origin

    train        = relationship("Train", back_populates="schedule")


class SeatAvailability(Base):
    """Available seats for a train on a given date and class."""
    __tablename__ = "seat_availability"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    train_no      = Column(String(10), ForeignKey("trains.train_no"), nullable=False)
    travel_date   = Column(Date, nullable=False)
    travel_class  = Column(String(5),  nullable=False)    # SL, 3A, 2A, 1A, CC
    total_seats   = Column(Integer, nullable=False)
    available     = Column(Integer, nullable=False)
    waitlist      = Column(Integer, default=0)
    fare          = Column(Float,   nullable=False)        # base fare in INR

    train         = relationship("Train", back_populates="availability")


class PNRRecord(Base):
    """Mock passenger booking record."""
    __tablename__ = "pnr_records"

    pnr            = Column(String(15), primary_key=True)
    passenger_name = Column(String(100), nullable=False)
    passenger_age  = Column(Integer, nullable=False)
    train_no       = Column(String(10), ForeignKey("trains.train_no"), nullable=False)
    travel_date    = Column(Date, nullable=False)
    travel_class   = Column(String(5),  nullable=False)
    from_station   = Column(String(10), nullable=False)
    to_station     = Column(String(10), nullable=False)
    # Status: CNF / RAC / WL
    booking_status = Column(String(20), nullable=False)
    coach          = Column(String(10), default="--")
    seat_no        = Column(String(10), default="--")
    fare_paid      = Column(Float, nullable=False)
    booked_on      = Column(DateTime, default=datetime.utcnow)


class PNRWatchlist(Base):
    """PNRs that the user asked to watch for status changes."""
    __tablename__ = "pnr_watchlist"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    pnr            = Column(String(15), nullable=False)
    session_id     = Column(String(64), nullable=False)
    last_status    = Column(String(20), nullable=False)
    is_active      = Column(Boolean, default=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatSession(Base):
    """Stores individual messages in each conversation session."""
    __tablename__ = "chat_sessions"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    session_id  = Column(String(64), nullable=False, index=True)
    role        = Column(String(20), nullable=False)    # "user" or "assistant"
    content     = Column(Text, nullable=False)
    intent      = Column(String(30), default=None)      # Supervisor's classified intent
    agent_trace = Column(Text, default=None)            # JSON string of tool call logs
    timestamp   = Column(DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════════════════════
#  SEED DATA
# ══════════════════════════════════════════════════════════════════════════════

STATIONS = [
    # code    name                        city            state           zone
    ("NDLS",  "New Delhi",               "New Delhi",    "Delhi",        "NR"),
    ("CSTM",  "Mumbai Chhatrapati Shiv", "Mumbai",       "Maharashtra",  "CR"),
    ("BCT",   "Mumbai Central",          "Mumbai",       "Maharashtra",  "WR"),
    ("MAS",   "Chennai Central",         "Chennai",      "Tamil Nadu",   "SR"),
    ("SBC",   "Bengaluru City",          "Bengaluru",    "Karnataka",    "SWR"),
    ("HWH",   "Howrah Junction",         "Kolkata",      "West Bengal",  "ER"),
    ("PUNE",  "Pune Junction",           "Pune",         "Maharashtra",  "CR"),
    ("ADI",   "Ahmedabad Junction",      "Ahmedabad",    "Gujarat",      "WR"),
    ("JP",    "Jaipur Junction",         "Jaipur",       "Rajasthan",    "NWR"),
    ("LKO",   "Lucknow Charbagh",        "Lucknow",      "Uttar Pradesh","NR"),
    ("PNBE",  "Patna Junction",          "Patna",        "Bihar",        "ECR"),
    ("BPL",   "Bhopal Junction",         "Bhopal",       "Madhya Pradesh","WCR"),
    ("NGP",   "Nagpur Junction",         "Nagpur",       "Maharashtra",  "CR"),
    ("HYB",   "Hyderabad Deccan",        "Hyderabad",    "Telangana",    "SCR"),
    ("SC",    "Secunderabad Junction",   "Hyderabad",    "Telangana",    "SCR"),
    ("VSKP",  "Visakhapatnam",           "Visakhapatnam","Andhra Pradesh","ECoR"),
    ("GHY",   "Guwahati",               "Guwahati",     "Assam",        "NFR"),
    ("UDZ",   "Udaipur City",            "Udaipur",      "Rajasthan",    "NWR"),
    ("AGC",   "Agra Cantt",              "Agra",         "Uttar Pradesh","NCR"),
    ("CDG",   "Chandigarh",              "Chandigarh",   "Chandigarh",   "NR"),
    ("KOTA",  "Kota Junction",           "Kota",         "Rajasthan",    "WCR"),
    ("ET",    "Itarsi Junction",         "Itarsi",       "Madhya Pradesh","WCR"),
    ("BSP",   "Bilaspur Junction",       "Bilaspur",     "Chhattisgarh", "SECR"),
    ("R",     "Raipur Junction",         "Raipur",       "Chhattisgarh", "SECR"),
    ("GWL",   "Gwalior Junction",        "Gwalior",      "Madhya Pradesh","NCR"),
    ("MTJ",   "Mathura Junction",        "Mathura",      "Uttar Pradesh","NCR"),
    ("CNB",   "Kanpur Central",          "Kanpur",       "Uttar Pradesh","NCR"),
    ("ALD",   "Prayagraj Junction",      "Prayagraj",    "Uttar Pradesh","NCR"),
    ("MGS",   "Mughal Sarai Jn",         "Varanasi",     "Uttar Pradesh","ECR"),
    ("DBRG",  "Dibrugarh",               "Dibrugarh",    "Assam",        "NFR"),
    # Additional stations for expanded connecting-route network
    ("BRC",   "Vadodara Junction",       "Vadodara",     "Gujarat",      "WR"),
    ("ST",    "Surat",                   "Surat",        "Gujarat",      "WR"),
    ("MMCT",  "Mumbai Central",          "Mumbai",       "Maharashtra",  "WR"),  # alias for journey planner
    ("BSB",   "Varanasi Junction",       "Varanasi",     "Uttar Pradesh","NR"),
    ("GKP",   "Gorakhpur Junction",      "Gorakhpur",    "Uttar Pradesh","NER"),
    ("BHUJ",  "Bhuj",                    "Bhuj",         "Gujarat",      "WR"),
    ("RJT",   "Rajkot Junction",         "Rajkot",       "Gujarat",      "WR"),
    ("VRL",   "Veraval",                 "Veraval",      "Gujarat",      "WR"),
    ("UHL",   "Ambala Cantonment",       "Ambala",       "Haryana",      "NR"),
    ("SVDK",  "Shri Mata Vaishno Devi Katra", "Katra", "Jammu",        "NR"),
]

TRAINS = [
    # train_no  train_name                                    src    dest   run_days
    ("12301",  "Howrah Rajdhani Express",                    "NDLS","HWH", "Daily"),
    ("12951",  "Mumbai Rajdhani Express",                    "NDLS","BCT", "Daily"),
    ("12259",  "Sealdah Duronto Express",                    "NDLS","HWH", "Mon,Thu,Sat"),
    ("12002",  "New Delhi Shatabdi Express",                 "NDLS","CDG", "Daily"),
    ("12627",  "Karnataka Express",                          "NDLS","SBC", "Daily"),
    ("22691",  "Rajdhani Express (Bangalore)",               "NDLS","SBC", "Daily"),
    ("12621",  "Tamil Nadu Express",                         "NDLS","MAS", "Daily"),
    ("12309",  "Rajendra Nagar Patna Rajdhani",              "NDLS","PNBE","Daily"),
    ("12903",  "Golden Temple Mail",                         "BCT", "AGC", "Daily"),
    ("12723",  "Telangana Express",                          "NDLS","HYB", "Daily"),
    # ── ADI-origin trains for connecting route coverage ────────────────────────
    ("19031",  "Haridwar Express",                           "ADI", "HWH", "Tue,Fri"),
    ("22955",  "Gujarat SF Express",                         "ADI", "BCT", "Daily"),
    ("16531",  "Garib Nawaz Express",                        "ADI", "SBC", "Mon,Wed"),
    ("19032",  "ADI Haridwar Express",                       "HWH", "ADI", "Wed,Sat"),
    ("19033",  "Gujarat Queen Express",                      "ADI", "NDLS","Daily"),
    # ── Expanded network — strategic trains for realistic BFS connecting routes ─
    # ADI ↔ BRC ↔ ST ↔ BCT corridor (Western Railway trunk line)
    ("12932",  "Ahmedabad Double Decker Express",            "ADI", "BCT", "Daily"),
    ("12921",  "Flying Ranee Express",                       "ADI", "BCT", "Daily"),
    # BCT → NGP → HWH (Central/Southeast corridor — enables ADI→BCT→HWH)
    ("12859",  "Gitanjali Express",                          "BCT", "HWH", "Daily"),
    # BCT → PUNE → SBC (Deccan/Southern corridor)
    ("11027",  "Mumbai-Chennai Mail",                        "BCT", "MAS", "Daily"),
    # ADI → BPL leg (enables ADI→BPL→NDLS, ADI→BPL→HWH connections)
    ("19489",  "Gorakhpur Express",                          "ADI", "GKP", "Daily"),
    # NDLS → HWH via PNBE (alternative Howrah corridor)
    ("12381",  "Poorva Express",                             "NDLS","HWH", "Mon,Wed,Fri,Sun"),
    # SC → MAS (Hyderabad–Chennai corridor, enable SBC↔HYB connections)
    ("12163",  "Chennai Egmore Superfast Express",           "SC",  "MAS", "Daily"),
    # PUNE → HWH (Azad Hind Express — connects west/east)
    ("12129",  "Azad Hind Express",                         "PUNE","HWH", "Daily"),
]

# Schedule: (train_no, stop_no, station_code, arrival, departure, distance_km)
SCHEDULES = [
    # 12301 Howrah Rajdhani: NDLS → GWL → CNB → ALD → MGS → HWH
    ("12301", 1, "NDLS", "--:--", "16:55", 0),
    ("12301", 2, "GWL",  "22:08", "22:15", 309),
    ("12301", 3, "CNB",  "01:45", "01:50", 440),
    ("12301", 4, "ALD",  "04:05", "04:10", 634),
    ("12301", 5, "MGS",  "06:00", "06:15", 789),
    ("12301", 6, "HWH",  "09:45", "--:--", 1446),

    # 12951 Mumbai Rajdhani: NDLS → KOTA → BPL → ET → BCT
    ("12951", 1, "NDLS", "--:--", "16:25", 0),
    ("12951", 2, "KOTA", "22:50", "22:55", 576),
    ("12951", 3, "BPL",  "01:10", "01:15", 702),
    ("12951", 4, "ET",   "03:35", "03:40", 862),
    ("12951", 5, "BCT",  "08:35", "--:--", 1384),

    # 12627 Karnataka Express: NDLS → AGC → GWL → BPL → NGP → SC → SBC
    ("12627", 1, "NDLS", "--:--", "22:30", 0),
    ("12627", 2, "AGC",  "01:28", "01:33", 200),
    ("12627", 3, "GWL",  "03:15", "03:20", 309),
    ("12627", 4, "BPL",  "08:00", "08:10", 702),
    ("12627", 5, "NGP",  "14:10", "14:20", 1092),
    ("12627", 6, "SC",   "22:55", "23:00", 1622),
    ("12627", 7, "SBC",  "06:15", "--:--", 2444),

    # 12621 Tamil Nadu Express: NDLS → AGC → BPL → NGP → MAS
    ("12621", 1, "NDLS", "--:--", "22:30", 0),
    ("12621", 2, "AGC",  "01:00", "01:05", 200),
    ("12621", 3, "BPL",  "08:00", "08:10", 702),
    ("12621", 4, "NGP",  "14:15", "14:25", 1092),
    ("12621", 5, "MAS",  "07:25", "--:--", 2184),

    # 12309 Patna Rajdhani: NDLS → CNB → ALD → PNBE
    ("12309", 1, "NDLS", "--:--", "18:00", 0),
    ("12309", 2, "CNB",  "23:30", "23:35", 440),
    ("12309", 3, "ALD",  "01:50", "01:55", 634),
    ("12309", 4, "PNBE", "06:40", "--:--", 1000),

    # 12723 Telangana Express: NDLS → KOTA → BPL → NGP → HYB
    ("12723", 1, "NDLS", "--:--", "06:15", 0),
    ("12723", 2, "KOTA", "12:40", "12:45", 576),
    ("12723", 3, "BPL",  "16:30", "16:40", 702),
    ("12723", 4, "NGP",  "22:00", "22:10", 1092),
    ("12723", 5, "HYB",  "10:00", "--:--", 1632),

    # 12002 Shatabdi: NDLS → CDG
    ("12002", 1, "NDLS", "--:--", "07:20", 0),
    ("12002", 2, "CDG",  "11:00", "--:--", 265),

    # 22691 Bangalore Rajdhani: NDLS → KOTA → BPL → SC → SBC
    ("22691", 1, "NDLS", "--:--", "20:15", 0),
    ("22691", 2, "KOTA", "02:35", "02:40", 576),
    ("22691", 3, "BPL",  "06:40", "06:50", 702),
    ("22691", 4, "SC",   "18:55", "19:00", 1622),
    ("22691", 5, "SBC",  "23:00", "--:--", 2444),

    # 12259 Duronto: NDLS → HWH (few stops)
    ("12259", 1, "NDLS", "--:--", "06:00", 0),
    ("12259", 2, "MGS",  "16:30", "16:35", 789),
    ("12259", 3, "HWH",  "21:30", "--:--", 1446),

    # 12903 Golden Temple Mail: BCT → AGC
    ("12903", 1, "BCT",  "--:--", "21:30", 0),
    ("12903", 2, "KOTA", "06:15", "06:20", 500),
    ("12903", 3, "AGC",  "13:00", "--:--", 920),

    # 19031 Haridwar Express: ADI → BPL → NGP → HWH
    ("19031", 1, "ADI",  "--:--", "11:30", 0),
    ("19031", 2, "BPL",  "05:10", "05:20", 702),
    ("19031", 3, "NGP",  "11:05", "11:15", 1110),
    ("19031", 4, "HWH",  "12:30", "--:--", 2130),

    # 22955 Gujarat SF Express: ADI → BCT (direct)
    ("22955", 1, "ADI",  "--:--", "07:10", 0),
    ("22955", 2, "BCT",  "16:00", "--:--", 493),

    # 16531 Garib Nawaz Express: ADI → SC → SBC
    ("16531", 1, "ADI",  "--:--", "14:05", 0),
    ("16531", 2, "SC",   "17:00", "17:10", 1100),
    ("16531", 3, "SBC",  "02:30", "--:--", 1724),

    # 19032 Haridwar Express return: HWH → BPL → ADI
    ("19032", 1, "HWH",  "--:--", "23:55", 0),
    ("19032", 2, "NGP",  "01:15", "01:25", 1020),
    ("19032", 3, "BPL",  "07:10", "07:20", 1428),
    ("19032", 4, "ADI",  "01:00", "--:--", 2130),

    # 19033 Gujarat Queen: ADI → JP → NDLS
    ("19033", 1, "ADI",  "--:--", "05:20", 0),
    ("19033", 2, "JP",   "16:05", "16:10", 671),
    ("19033", 3, "NDLS", "22:05", "--:--", 934),

    # ── EXPANDED SCHEDULES for connecting-route coverage ──────────────────────

    # 12932 Ahmedabad Double Decker: ADI → BRC → ST → BCT
    # Departs ADI early morning — passengers can connect at BCT to HWH/MAS trains
    ("12932", 1, "ADI",  "--:--", "06:05", 0),
    ("12932", 2, "BRC",  "08:20", "08:25", 109),
    ("12932", 3, "ST",   "10:05", "10:10", 263),
    ("12932", 4, "BCT",  "13:55", "--:--", 493),

    # 12921 Flying Ranee Express: ADI → BRC → ST → BCT
    # Evening departure — provides a second daily ADI→BCT leg
    ("12921", 1, "ADI",  "--:--", "17:05", 0),
    ("12921", 2, "BRC",  "19:25", "19:30", 109),
    ("12921", 3, "ST",   "21:15", "21:20", 263),
    ("12921", 4, "BCT",  "00:55", "--:--", 493),

    # 12859 Gitanjali Express: BCT → NGP → R → BSP → HWH
    # Departs BCT at 06:00 — connects well with ADI morning trains arriving ~14:00
    # Provides BCT→HWH leg for ADI→BCT→HWH journeys
    ("12859", 1, "BCT",  "--:--", "06:05", 0),
    ("12859", 2, "ET",   "14:40", "14:45", 750),
    ("12859", 3, "NGP",  "19:30", "19:40", 1091),
    ("12859", 4, "R",    "00:10", "00:15", 1472),
    ("12859", 5, "BSP",  "02:45", "02:50", 1637),
    ("12859", 6, "HWH",  "12:45", "--:--", 2050),

    # 11027 Mumbai-Chennai Mail: BCT → PUNE → SC → MAS
    # Departs BCT at 23:45 — connects with ADI afternoon arrivals at BCT ~14:00-17:00
    ("11027", 1, "BCT",  "--:--", "23:45", 0),
    ("11027", 2, "PUNE", "02:50", "03:00", 192),
    ("11027", 3, "SC",   "13:30", "13:40", 1148),
    ("11027", 4, "MAS",  "18:30", "--:--", 1543),

    # 19489 Gorakhpur Express: ADI → BPL → LKO → GKP
    # Departs ADI afternoon — BPL arrival ~04:00, enabling BPL→NDLS morning connections
    ("19489", 1, "ADI",  "--:--", "16:10", 0),
    ("19489", 2, "BPL",  "04:15", "04:20", 702),
    ("19489", 3, "CNB",  "10:05", "10:10", 1000),
    ("19489", 4, "LKO",  "12:35", "12:40", 1102),
    ("19489", 5, "GKP",  "18:00", "--:--", 1381),

    # 12381 Poorva Express: NDLS → ALD → MGS → PNBE → HWH
    # Alternate NDLS→HWH route — avoids GWL corridor used by 12301
    ("12381", 1, "NDLS", "--:--", "10:05", 0),
    ("12381", 2, "CNB",  "15:30", "15:35", 440),
    ("12381", 3, "ALD",  "17:50", "17:55", 634),
    ("12381", 4, "MGS",  "19:40", "19:50", 789),
    ("12381", 5, "PNBE", "23:50", "00:00", 1000),
    ("12381", 6, "HWH",  "07:30", "--:--", 1446),

    # 12163 SC→MAS Superfast: SC → MAS
    # Departs Secunderabad morning — MAS arrival afternoon
    ("12163", 1, "SC",   "--:--", "06:30", 0),
    ("12163", 2, "MAS",  "14:30", "--:--", 794),

    # 12129 Azad Hind Express: PUNE → NGP → BSP → HWH
    # Departs PUNE afternoon — connects PUNE→HWH corridor
    ("12129", 1, "PUNE", "--:--", "15:40", 0),
    ("12129", 2, "NGP",  "23:30", "23:40", 588),
    ("12129", 3, "BSP",  "04:15", "04:20", 924),
    ("12129", 4, "HWH",  "15:15", "--:--", 1516),
]

# PNR seed records
PNRS = [
    # pnr        name              age  train   date       class from    to      status  coach seat   fare
    ("2145678901","Ravi Kumar",     34, "12301","2026-06-20","3A","NDLS","HWH","CNF",   "B2", "45",  1275.0),
    ("2145678902","Priya Sharma",   28, "12951","2026-06-18","2A","NDLS","BCT","CNF",   "A1", "12",  2040.0),
    ("2145678903","Amit Singh",     45, "12627","2026-06-22","SL","NDLS","SBC","WL/12", "--", "--",  650.0),
    ("2145678904","Sunita Devi",    55, "12621","2026-06-25","3A","NDLS","MAS","RAC/3", "B4", "RAC 3",1560.0),
    ("2145678905","Rohit Gupta",    30, "12309","2026-06-19","3A","NDLS","PNBE","CNF",  "C1", "32",  895.0),
    ("2145678906","Deepa Nair",     38, "22691","2026-06-21","1A","NDLS","SBC","CNF",   "H1", "5",   4250.0),
    ("2145678907","Suresh Reddy",   42, "12723","2026-06-23","SL","NDLS","HYB","WL/3",  "--", "--",  520.0),
    ("2145678908","Meena Patel",    25, "12002","2026-06-17","CC","NDLS","CDG","CNF",   "C3", "78",  410.0),
]


def seed_availability(session):
    """Generate seat availability for the next 30 days for all trains."""
    import random
    classes = {
        "SL":  {"total": 600, "fare_per_km": 0.40},
        "3A":  {"total": 240, "fare_per_km": 1.05},
        "2A":  {"total": 120, "fare_per_km": 1.55},
        "1A":  {"total":  48, "fare_per_km": 2.85},
    }
    today = date.today()

    for train_no, _, _, _, run_days in TRAINS:
        # Get distance from last schedule stop
        stops = [(t, d) for t, sn, st, a, dep, d in SCHEDULES if t == train_no]
        total_km = max([d for _, d in stops]) if stops else 1000

        for days_ahead in range(1, 31):
            travel_date = today + timedelta(days=days_ahead)
            for cls, info in classes.items():
                # Skip CC class for non-Shatabdi
                if cls == "CC" and train_no != "12002":
                    continue
                avail  = random.randint(0, info["total"])
                wl     = random.randint(0, 30) if avail == 0 else 0
                fare   = round(total_km * info["fare_per_km"] / 10) * 10
                session.add(SeatAvailability(
                    train_no=train_no, travel_date=travel_date,
                    travel_class=cls, total_seats=info["total"],
                    available=avail, waitlist=wl, fare=fare
                ))


def init_db():
    """Create all tables and seed data while keeping the process idempotent."""
    Base.metadata.create_all(ENGINE)

    with Session() as session:
        has_trains = session.query(Train).first() is not None

        if not has_trains:
            print("[DB] Seeding database with mock Indian railway data...")

            # Stations
            for code, name, city, state, zone in STATIONS:
                session.add(Station(code=code, name=name, city=city,
                                    state=state, zone=zone))

            # Trains
            for train_no, name, src, dest, days in TRAINS:
                session.add(Train(train_no=train_no, train_name=name,
                                  source_code=src, dest_code=dest, run_days=days))

            session.flush()  # Ensure FKs resolve before adding schedules

            # Schedules
            for train_no, stop_no, station, arr, dep, dist in SCHEDULES:
                session.add(TrainSchedule(
                    train_no=train_no, stop_number=stop_no,
                    station_code=station, arrival=arr,
                    departure=dep, distance_km=dist
                ))

        if session.query(PNRRecord).first() is None:
            print("[DB] Seeding PNR records...")
            for (pnr, name, age, train_no, d, cls,
                 frm, to, status, coach, seat, fare) in PNRS:
                session.add(PNRRecord(
                    pnr=pnr, passenger_name=name, passenger_age=age,
                    train_no=train_no, travel_date=date.fromisoformat(d),
                    travel_class=cls, from_station=frm, to_station=to,
                    booking_status=status, coach=coach, seat_no=seat,
                    fare_paid=fare
                ))

        if session.query(SeatAvailability).first() is None:
            print("[DB] Seeding seat availability...")
            seed_availability(session)

        session.commit()
        print("[DB] Database ready.")
        print(f"[DB] File location: {DB_PATH}")


if __name__ == "__main__":
    init_db()
