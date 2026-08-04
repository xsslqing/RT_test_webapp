"""User management module - handles registration, login, and data persistence."""
import json
import os
import hashlib
from datetime import datetime

# Default project root = directory containing this file
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.path.join(_PROJECT_ROOT, "users")
os.makedirs(USERS_DIR, exist_ok=True)

ADMIN_USER = "admin"
ADMIN_PASS = "xssl"


# ── helpers ──────────────────────────────────────────────

def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _user_file(username: str) -> str:
    return os.path.join(USERS_DIR, f"{username}.json")


def _user_data_dir(username: str) -> str:
    d = os.path.join(USERS_DIR, username)
    os.makedirs(d, exist_ok=True)
    return d


def _load_json(path: str, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── bootstrap admin ──────────────────────────────────────

def ensure_admin():
    """Create admin account if it does not exist."""
    if not os.path.exists(_user_file(ADMIN_USER)):
        register(ADMIN_USER, ADMIN_PASS, role="admin")


# ── auth ─────────────────────────────────────────────────

def list_users():
    """Return list of usernames."""
    return [f[:-5] for f in os.listdir(USERS_DIR) if f.endswith(".json")]


def register(username: str, password: str, role: str = "user") -> dict:
    """Register a new user. Raises ValueError on conflict."""
    username = username.strip()
    if not username:
        raise ValueError("用户名不能为空")
    if os.path.exists(_user_file(username)):
        raise ValueError(f"用户 '{username}' 已存在")

    user = {
        "username": username,
        "password_hash": _hash_pw(password),
        "role": role,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_json(_user_file(username), user)
    _user_data_dir(username)          # create data directory
    return user


def login(username: str, password: str):
    """Return user dict on success, None on failure."""
    uf = _user_file(username)
    if not os.path.exists(uf):
        return None
    user = _load_json(uf, None)
    if user and user["password_hash"] == _hash_pw(password):
        return user
    return None


# ── per-user data I/O ────────────────────────────────────

def _prac_path(u):
    return os.path.join(_user_data_dir(u), "practice.json")


def _exam_path(u):
    return os.path.join(_user_data_dir(u), "exams.json")


def _wrong_path(u):
    return os.path.join(_user_data_dir(u), "wrong.json")


# -- practice --

def load_practice(username: str) -> dict:
    return _load_json(_prac_path(username), {"answered": {}, "stats": {}})


def save_practice(username: str, data: dict):
    _save_json(_prac_path(username), data)


def save_practice_position(username: str, bank: str, part: str,
                           qtype: str, index: int):
    """Save current practice navigation position."""
    data = load_practice(username)
    data["position"] = {
        "bank": bank,
        "part": part,
        "qtype": qtype,
        "index": index,
    }
    save_practice(username, data)


def load_practice_position(username: str):
    """Return saved position dict or None."""
    data = load_practice(username)
    return data.get("position")


def record_practice_answer(username: str, q_key: str, bank: str,
                          q_id: int, q_num: int, q_type: str, part: str,
                          user_ans: str, correct_ans: str, is_correct: bool):
    """Record a single practice answer and update stats."""
    data = load_practice(username)
    data["answered"][q_key] = {
        "bank": bank,
        "q_id": q_id,
        "q_num": q_num,
        "type": q_type,
        "part": part,
        "user_ans": user_ans,
        "correct_ans": correct_ans,
        "is_correct": is_correct,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    # update stats
    total = len(data["answered"])
    correct = sum(1 for v in data["answered"].values() if v["is_correct"])
    data["stats"] = {
        "total_answered": total,
        "correct_count": correct,
        "accuracy": round(correct / total * 100, 1) if total else 0,
        "last_practice": datetime.now().isoformat(timespec="seconds"),
    }
    save_practice(username, data)
    return data


# -- exams --

def load_exams(username: str) -> list:
    return _load_json(_exam_path(username), [])


def save_exam_record(username: str, record: dict):
    exams = load_exams(username)
    exams.append(record)
    _save_json(_exam_path(username), exams)


# -- wrong answers --

def load_wrong(username: str) -> dict:
    return _load_json(_wrong_path(username), {})


def save_wrong(username: str, data: dict):
    _save_json(_wrong_path(username), data)


def add_wrong(username: str, q_key: str, bank: str, q_data: dict,
              user_ans: str, correct_ans: str):
    wrong = load_wrong(username)
    entry = wrong.get(q_key, {"attempts": 0})
    entry.update({
        "bank": bank,
        "q_id": q_data.get("id"),
        "num": q_data.get("num"),
        "type": q_data.get("type"),
        "part": q_data.get("part"),
        "stem": q_data.get("stem", ""),
        "options": q_data.get("options", {}),
        "option_images": q_data.get("option_images", {}),
        "answer": correct_ans,
        "user_ans": user_ans,
        "attempts": entry["attempts"] + 1,
        "last_wrong": datetime.now().isoformat(timespec="seconds"),
    })
    wrong[q_key] = entry
    save_wrong(username, wrong)


def remove_wrong(username: str, q_key: str):
    wrong = load_wrong(username)
    wrong.pop(q_key, None)
    save_wrong(username, wrong)


def clear_wrong(username: str):
    save_wrong(username, {})
