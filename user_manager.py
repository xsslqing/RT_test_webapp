"""Supabase-backed user management and persistent user data."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone
from typing import Any

import streamlit as st
from supabase import Client, create_client


def _get_secret(name: str) -> str:
    """Read from Streamlit Secrets, falling back to environment variables."""
    value = st.secrets.get(name) or os.environ.get(name)
    if not value:
        raise RuntimeError(f"缺少配置项：{name}")
    return str(value)



@st.cache_resource
def _get_db() -> Client:
    url = _get_secret("SUPABASE_URL").strip().rstrip("/")
    key = _get_secret("SUPABASE_SERVICE_KEY").strip()

    # ── 绕过代理 ──────────────────────────────────────────
    # 错误栈出现 http_proxy → 系统代理拦截了 Supabase 的 HTTPS，
    # 将 Supabase 域名加入 NO_PROXY 让 httpx 直连。
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    no_proxy = os.environ.get("NO_PROXY", "")
    if host and host not in no_proxy:
        os.environ["NO_PROXY"] = f"{no_proxy},{host}".lstrip(",")

    return create_client(url, key)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Session-state cache ────────────────────────────────────
# Streamlit 每次交互都重跑整个脚本，直接读 Supabase 延迟高。
# 用 session_state 缓存 user_data，写入时同步更新缓存。

_CACHE_KEY = "_user_data_cache"


def _invalidate_cache() -> None:
    st.session_state.pop(_CACHE_KEY, None)


def _get_cached_data(username: str) -> dict | None:
    cache = st.session_state.get(_CACHE_KEY)
    if cache and cache.get("_username") == username:
        return cache
    return None


def _set_cached_data(username: str, data: dict) -> None:
    data = dict(data)
    data["_username"] = username
    st.session_state[_CACHE_KEY] = data


def _hash_pw(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    """
    Hash password with PBKDF2-HMAC-SHA256.

    Returns:
        (password_hash, salt_hex)
    """
    if salt_hex is None:
        salt = secrets.token_bytes(16)
        salt_hex = salt.hex()
    else:
        salt = bytes.fromhex(salt_hex)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        600_000,
    ).hex()

    return password_hash, salt_hex


def ensure_admin() -> None:
    """Create the configured administrator account if absent."""
    username = st.secrets.get("ADMIN_USERNAME", "admin")
    password = st.secrets.get("ADMIN_PASSWORD")

    if not password:
        raise RuntimeError("请在 Streamlit Secrets 中配置 ADMIN_PASSWORD")

    if login_user_record(username) is None:
        register(username, password, role="admin")


def login_user_record(username: str) -> dict[str, Any] | None:
    result = (
        _get_db()
        .table("app_users")
        .select("username,password_hash,password_salt,role,created_at")
        .eq("username", username.strip())
        .limit(1)
        .execute()
    )

    return result.data[0] if result.data else None


def list_users() -> list[str]:
    result = (
        _get_db()
        .table("app_users")
        .select("username")
        .order("username")
        .execute()
    )
    return [row["username"] for row in result.data]


def list_users_with_role() -> list[dict]:
    """返回所有用户信息（用户名、角色、创建时间），用于管理员界面。"""
    result = (
        _get_db()
        .table("app_users")
        .select("username,role,created_at")
        .order("created_at")
        .execute()
    )
    return result.data


def delete_user(username: str) -> None:
    """删除用户及其所有数据（app_users + user_data）。"""
    db = _get_db()
    db.table("user_data").delete().eq("username", username).execute()
    db.table("app_users").delete().eq("username", username).execute()
    _invalidate_cache()


def register(
    username: str,
    password: str,
    role: str = "user",
) -> dict[str, Any]:
    username = username.strip()

    if not username:
        raise ValueError("用户名不能为空")

    if len(username) > 50:
        raise ValueError("用户名不能超过50个字符")

    if len(password) < 8:
        raise ValueError("密码至少8个字符")

    if login_user_record(username) is not None:
        raise ValueError(f"用户 '{username}' 已存在")

    password_hash, password_salt = _hash_pw(password)

    user = {
        "username": username,
        "password_hash": password_hash,
        "password_salt": password_salt,
        "role": role,
        "created_at": _now(),
    }

    try:
        _get_db().table("app_users").insert(user).execute()

        _get_db().table("user_data").insert(
            {
                "username": username,
                "practice": {"answered": {}, "stats": {}},
                "exams": [],
                "wrong": {},
                "updated_at": _now(),
            }
        ).execute()
    except Exception as exc:
        raise ValueError(f"注册失败：{exc}") from exc

    return {
        "username": username,
        "role": role,
        "created_at": user["created_at"],
    }


def login(username: str, password: str) -> dict[str, Any] | None:
    user = login_user_record(username)

    if user is None:
        return None

    supplied_hash, _ = _hash_pw(password, user["password_salt"])

    if not hmac.compare_digest(supplied_hash, user["password_hash"]):
        return None

    return {
        "username": user["username"],
        "role": user["role"],
        "created_at": user["created_at"],
    }


def _load_user_data(username: str) -> dict[str, Any]:
    result = (
        _get_db()
        .table("user_data")
        .select("practice,exams,wrong")
        .eq("username", username)
        .limit(1)
        .execute()
    )

    if not result.data:
        initial = {
            "username": username,
            "practice": {"answered": {}, "stats": {}},
            "exams": [],
            "wrong": {},
            "updated_at": _now(),
        }

        _get_db().table("user_data").insert(initial).execute()
        return initial

    return result.data[0]


def _save_field(username: str, field: str, value: Any) -> None:
    if field not in {"practice", "exams", "wrong"}:
        raise ValueError("不允许写入该字段")

    (
        _get_db()
        .table("user_data")
        .update(
            {
                field: value,
                "updated_at": _now(),
            }
        )
        .eq("username", username)
        .execute()
    )

    # 同步更新 session_state 缓存，保证同一次 rerun 内读取一致
    cache = _get_cached_data(username)
    if cache is not None:
        cache[field] = value
        _set_cached_data(username, cache)


# ── Practice ───────────────────────────────────────────────

def load_practice(username: str) -> dict:
    return _load_user_data(username).get(
        "practice",
        {"answered": {}, "stats": {}},
    )


def save_practice(username: str, data: dict) -> None:
    _save_field(username, "practice", data)


def load_practice_cached(username: str) -> dict:
    """从 session_state 缓存读取 practice，缓存未命中才查数据库。"""
    cache = _get_cached_data(username)
    if cache is not None:
        return cache.get("practice", {"answered": {}, "stats": {}})
    data = _load_user_data(username)
    _set_cached_data(username, data)
    return data.get("practice", {"answered": {}, "stats": {}})


def _pos_key(bank: str, part: str, qtype: str) -> str:
    return f"{bank}:{part}:{qtype}"


def save_practice_position(
    username: str,
    bank: str,
    part: str,
    qtype: str,
    index: int,
) -> None:
    data = load_practice_cached(username)

    positions = data.get("positions", {})
    positions[_pos_key(bank, part, qtype)] = {"index": index}
    data["positions"] = positions

    # 同时保存最后活跃位置（用于登录恢复）
    data["last_position"] = {
        "bank": bank,
        "part": part,
        "qtype": qtype,
        "index": index,
    }

    save_practice(username, data)


def load_practice_position(username: str):
    """返回最后一次活跃的位置（兼容旧数据）。"""
    data = load_practice_cached(username)
    return data.get("last_position") or data.get("position")


def load_position_for_filter(username: str, bank: str, part: str, qtype: str):
    """返回指定筛选组合的保存位置，无则返回 None。"""
    data = load_practice_cached(username)
    positions = data.get("positions", {})
    entry = positions.get(_pos_key(bank, part, qtype))
    if entry:
        return entry.get("index")
    return None


def record_practice_answer(
    username: str,
    q_key: str,
    bank: str,
    q_id: int,
    q_num: int,
    q_type: str,
    part: str,
    user_ans: str,
    correct_ans: str,
    is_correct: bool,
):
    data = load_practice_cached(username)

    data.setdefault("answered", {})
    data["answered"][q_key] = {
        "bank": bank,
        "q_id": q_id,
        "q_num": q_num,
        "type": q_type,
        "part": part,
        "user_ans": user_ans,
        "correct_ans": correct_ans,
        "is_correct": is_correct,
        "timestamp": _now(),
    }

    total = len(data["answered"])
    correct = sum(
        1
        for value in data["answered"].values()
        if value.get("is_correct")
    )

    data["stats"] = {
        "total_answered": total,
        "correct_count": correct,
        "accuracy": round(correct / total * 100, 1) if total else 0,
        "last_practice": _now(),
    }

    save_practice(username, data)
    return data


# ── Exams ──────────────────────────────────────────────────

def load_exams(username: str) -> list:
    return _load_user_data(username).get("exams", [])


def save_exam_record(username: str, record: dict) -> None:
    exams = load_exams_cached(username)
    exams.append(record)
    # 裁剪旧记录，仅保留最新 N 条
    retention = get_exam_retention_count()
    if len(exams) > retention:
        exams = exams[-retention:]
    _save_field(username, "exams", exams)


def load_exams_cached(username: str) -> list:
    """从 session_state 缓存读取 exams，缓存未命中才查数据库。"""
    cache = _get_cached_data(username)
    if cache is not None:
        return cache.get("exams", [])
    data = _load_user_data(username)
    _set_cached_data(username, data)
    return data.get("exams", [])


# ── Wrong answers ──────────────────────────────────────────

def load_wrong(username: str) -> dict:
    return _load_user_data(username).get("wrong", {})


def save_wrong(username: str, data: dict) -> None:
    _save_field(username, "wrong", data)


def load_wrong_cached(username: str) -> dict:
    """从 session_state 缓存读取 wrong，缓存未命中才查数据库。"""
    cache = _get_cached_data(username)
    if cache is not None:
        return cache.get("wrong", {})
    data = _load_user_data(username)
    _set_cached_data(username, data)
    return data.get("wrong", {})


def add_wrong(
    username: str,
    q_key: str,
    bank: str,
    q_data: dict,
    user_ans: str,
    correct_ans: str,
) -> None:
    wrong = load_wrong_cached(username)
    entry = wrong.get(q_key, {"attempts": 0})

    entry.update(
        {
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
            "last_wrong": _now(),
        }
    )

    wrong[q_key] = entry
    save_wrong(username, wrong)


def remove_wrong(username: str, q_key: str) -> None:
    wrong = load_wrong_cached(username)
    wrong.pop(q_key, None)
    save_wrong(username, wrong)


def clear_wrong(username: str) -> None:
    save_wrong(username, {})


# ── Leaderboard ─────────────────────────────────────────────

def load_leaderboard() -> list[dict]:
    """查询所有用户的考试记录，返回排行榜数据（按最高分降序）。"""
    result = (
        _get_db()
        .table("user_data")
        .select("username,exams")
        .execute()
    )

    rows = []
    for row in result.data:
        exams = row.get("exams") or []
        if not exams:
            continue

        scores = [e["total_score"] for e in exams if "total_score" in e]
        durations = [e["duration_seconds"] for e in exams if "duration_seconds" in e]

        if not scores:
            continue

        best_score = max(scores)
        rows.append({
            "username": row["username"],
            "best_score": best_score,
            "exam_count": len(scores),
            "avg_score": round(sum(scores) / len(scores), 1),
            "best_duration": min(durations) if durations else 0,
        })

    rows.sort(key=lambda r: (-r["best_score"], r["best_duration"]))
    return rows


def load_practice_leaderboard() -> list[dict]:
    """查询所有用户的练习记录，返回练习排行榜数据（按刷题数量降序）。"""
    result = (
        _get_db()
        .table("user_data")
        .select("username,practice")
        .execute()
    )

    rows = []
    for row in result.data:
        username = row.get("username")
        if username == "_system":
            continue
        practice = row.get("practice") or {}
        stats = practice.get("stats", {})
        answered = practice.get("answered", {})

        total_answered = stats.get("total_answered", 0) or len(answered)
        if total_answered == 0:
            continue

        correct_count = stats.get("correct_count", 0)
        accuracy = stats.get("accuracy", 0)
        if accuracy == 0 and correct_count > 0:
            accuracy = round(correct_count / total_answered * 100, 1)

        # 按题库统计
        bank_stats = {}
        for q_key, ans_info in answered.items():
            bank = ans_info.get("bank", "未知")
            if bank not in bank_stats:
                bank_stats[bank] = {"total": 0, "correct": 0}
            bank_stats[bank]["total"] += 1
            if ans_info.get("is_correct"):
                bank_stats[bank]["correct"] += 1

        last_practice = stats.get("last_practice", "")

        rows.append({
            "username": username,
            "total_answered": total_answered,
            "correct_count": correct_count,
            "accuracy": accuracy,
            "bank_stats": bank_stats,
            "last_practice": last_practice,
        })

    rows.sort(key=lambda r: -r["total_answered"])
    return rows


# ── Global Config ───────────────────────────────────────────

_SYSTEM_USER = "_system"
_DEFAULT_EXAM_RETENTION = 5


def _ensure_system_config() -> dict:
    """确保 _system 配置行存在，返回 config 字典。"""
    db = _get_db()
    result = db.table("user_data").select("practice").eq("username", _SYSTEM_USER).limit(1).execute()
    if result.data:
        return result.data[0].get("practice", {})
    # 先在 app_users 创建 _system 用户（满足外键约束）
    try:
        db.table("app_users").insert({
            "username": _SYSTEM_USER,
            "password_hash": "",
            "password_salt": "",
            "role": "system",
            "created_at": _now(),
        }).execute()
    except Exception:
        pass  # 已存在则忽略
    initial = {
        "username": _SYSTEM_USER,
        "practice": {"exam_retention": _DEFAULT_EXAM_RETENTION},
        "exams": [],
        "wrong": {},
        "updated_at": _now(),
    }
    db.table("user_data").insert(initial).execute()
    return {"exam_retention": _DEFAULT_EXAM_RETENTION}


def get_exam_retention_count() -> int:
    """获取考试记录保留条数（默认 5）。"""
    config = _ensure_system_config()
    return config.get("exam_retention", _DEFAULT_EXAM_RETENTION)


def set_exam_retention_count(count: int) -> None:
    """设置考试记录保留条数。"""
    db = _get_db()
    config = _ensure_system_config()
    config["exam_retention"] = count
    db.table("user_data").update({"practice": config, "updated_at": _now()}).eq("username", _SYSTEM_USER).execute()


# ── Question Corrections (纠错) ─────────────────────────────

def load_corrections() -> dict:
    """加载所有题目纠错（全局共享）。返回 {q_key: [{user, text, time}, ...]}。"""
    db = _get_db()
    result = db.table("user_data").select("wrong").eq("username", _SYSTEM_USER).limit(1).execute()
    if result.data:
        return result.data[0].get("wrong", {})
    return {}


def add_correction(q_key: str, username: str, text: str) -> None:
    """为指定题目添加纠错备注。"""
    db = _get_db()
    corrections = load_corrections()
    entries = corrections.get(q_key, [])
    entries.append({
        "user": username,
        "text": text.strip(),
        "time": _now(),
    })
    corrections[q_key] = entries
    db.table("user_data").update({"wrong": corrections, "updated_at": _now()}).eq("username", _SYSTEM_USER).execute()
