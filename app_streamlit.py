"""辐射安全考试练习系统 v2 - with user system, mock exam, persistent records."""
import streamlit as st
import json
import random
import os
import re
import time
from datetime import datetime
from PIL import Image

import user_manager as um

# ══════════════════════════════════════════════════════════
# 页面配置
# ══════════════════════════════════════════════════════════
st.set_page_config(page_title="辐射安全考试练习", page_icon="📝", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "images")
IMG_PIC_DIR = os.path.join(BASE_DIR, "images_pic")

# ══════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════
@st.cache_data
def load_questions():
    with open(os.path.join(BASE_DIR, "questions.json"), encoding="utf-8") as f:
        return json.load(f)

@st.cache_data
def load_pic_questions():
    with open(os.path.join(BASE_DIR, "questions_pic.json"), encoding="utf-8") as f:
        return json.load(f)

ALL_BANKS = {"综合题库": load_questions(), "图片题库": load_pic_questions()}

PARTS_MAP = {
    "综合题库": ["全部", "电离辐射安全与防护基础", "核技术利用辐射安全法律法规", "专业实务"],
    "图片题库": ["全部", "图片题-电离辐射安全与防护基础"],
}
PART_SHORT = {
    "电离辐射安全与防护基础": "基础",
    "核技术利用辐射安全法律法规": "法规",
    "专业实务": "实务",
    "图片题-电离辐射安全与防护基础": "图片基础",
}

# 模拟考试配置
EXAM_SINGLE_COUNT = 40
EXAM_SINGLE_SCORE = 2
EXAM_MULTI_COUNT = 10
EXAM_MULTI_SCORE = 4
EXAM_TOTAL_SCORE = EXAM_SINGLE_COUNT * EXAM_SINGLE_SCORE + EXAM_MULTI_COUNT * EXAM_MULTI_SCORE  # 120
EXAM_DEFAULT_MINUTES = 120

# ══════════════════════════════════════════════════════════
# 图片 / 题目渲染辅助
# ══════════════════════════════════════════════════════════
def get_img_dir(bank_name):
    return IMG_PIC_DIR if bank_name == "图片题库" else IMG_DIR

def show_image(img_name, width=300, bank_name="综合题库"):
    img_path = os.path.join(get_img_dir(bank_name), img_name)
    if os.path.exists(img_path):
        try:
            st.image(Image.open(img_path), width=width)
        except Exception:
            st.warning(f"图片加载失败: {img_name}")
    else:
        st.warning(f"图片不存在: {img_name}")

def render_stem_images(stem_text, bank_name):
    parts = re.split(r'\[IMG:([^\]]+)\]', stem_text)
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part.strip():
                st.markdown(part.strip())
        else:
            show_image(part, width=400, bank_name=bank_name)

def render_options(q, key_prefix, disabled=False, user_answer=None, bank_name="综合题库"):
    """渲染选项（含图片），返回用户选择列表。"""
    opts = q["options"]
    opt_imgs = q.get("option_images", {})
    if not opts and not opt_imgs:
        st.info("本题无文字选项，请根据图片作答。")
        return None

    opt_keys = sorted(set(list(opts.keys()) + list(opt_imgs.keys())))
    is_multi = q["type"] == "multiple"

    if is_multi:
        selections = []
        for k in opt_keys:
            checked = user_answer and k in user_answer
            label = f"{k}、{opts.get(k, '')}"
            val = st.checkbox(label, value=checked, key=f"{key_prefix}_{k}", disabled=disabled)
            if val:
                selections.append(k)
            if k in opt_imgs:
                for img_name in opt_imgs[k]:
                    show_image(img_name, width=200, bank_name=bank_name)
        return selections if selections else None
    else:
        labels = [f"{k}、{opts.get(k, '')}" for k in opt_keys]
        default_idx = None
        if user_answer and len(user_answer) == 1:
            try:
                default_idx = opt_keys.index(user_answer[0])
            except (ValueError, IndexError):
                pass
        choice = st.radio("请选择答案", labels, index=default_idx,
                          key=f"{key_prefix}_radio", disabled=disabled,
                          label_visibility="collapsed")
        if opt_imgs:
            img_cols = st.columns(len(opt_keys))
            for idx, k in enumerate(opt_keys):
                with img_cols[idx]:
                    if k in opt_imgs:
                        for img_name in opt_imgs[k]:
                            show_image(img_name, width=150, bank_name=bank_name)
        if choice:
            return [choice[0]]
        return None

def show_result_feedback(q, user_ans, correct_ans, key_prefix, bank_name):
    """显示答题结果反馈，返回是否正确。"""
    correct_set = set(correct_ans.split(","))
    user_set = set(user_ans) if user_ans else set()
    is_correct = user_set == correct_set

    if is_correct:
        st.success("✅ 回答正确！")
    else:
        st.error(f"❌ 回答错误！正确答案是：**{correct_ans}**")

    opts = q["options"]
    if opts:
        cols = st.columns(len(opts))
        for idx, (k, v) in enumerate(sorted(opts.items())):
            with cols[idx]:
                bg = ""
                if k in correct_set:
                    bg = "background-color: #d4edda; padding: 8px; border-radius: 4px;"
                if k in user_set and k not in correct_set:
                    bg = "background-color: #f8d7da; padding: 8px; border-radius: 4px;"
                if bg:
                    st.markdown(f"<div style='{bg}'><b>{k}</b>、{v}</div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"**{k}**、{v}")
    return is_correct


def _get_wrong_questions(username):
    """从用户错题本重建题目列表，每题附带 _orig_bank 用于图片渲染。"""
    wrong = um.load_wrong(username)
    result = []
    for q_key, info in wrong.items():
        bank = info.get("bank", "")
        q_id = info.get("q_id")
        orig_q = None
        if bank in ALL_BANKS and q_id is not None:
            orig_q = next((q for q in ALL_BANKS[bank] if q["id"] == q_id), None)
        if orig_q:
            q_copy = dict(orig_q)
            q_copy["_orig_bank"] = bank
            result.append(q_copy)
    return result


# ══════════════════════════════════════════════════════════
# 登录 / 注册页面
# ══════════════════════════════════════════════════════════
def page_login():
    st.title("📝 辐射安全考试练习系统")
    st.markdown("请登录或注册以开始练习")

    tab_login, tab_register = st.tabs(["登录", "注册"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            if st.form_submit_button("登录", use_container_width=True):
                user = um.login(username, password)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.current_user = user
                    st.session_state.page = "顺序刷题"
                    st.rerun()
                else:
                    st.error("用户名或密码错误")

    with tab_register:
        with st.form("register_form"):
            new_username = st.text_input("用户名", key="reg_user")
            new_password = st.text_input("密码", type="password", key="reg_pass")
            confirm_password = st.text_input("确认密码", type="password", key="reg_confirm")
            if st.form_submit_button("注册", use_container_width=True):
                if not new_username.strip():
                    st.error("用户名不能为空")
                elif new_password != confirm_password:
                    st.error("两次密码不一致")
                elif len(new_password) < 3:
                    st.error("密码至少3个字符")
                else:
                    try:
                        user = um.register(new_username.strip(), new_password)
                        st.success(f"注册成功！欢迎 {user['username']}")
                        st.session_state.logged_in = True
                        st.session_state.current_user = user
                        st.session_state.page = "顺序刷题"
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))


# ══════════════════════════════════════════════════════════
# 顺序刷题
# ══════════════════════════════════════════════════════════
def page_practice(username, bank_name, filtered):
    st.header("📖 顺序刷题")

    def _save_pos():
        """保存当前刷题位置，以便下次登录恢复。"""
        part_val = st.session_state.get("sel_part", "全部")
        qtype_val = st.session_state.get("sel_qtype", "全部")
        um.save_practice_position(username, bank_name, part_val, qtype_val,
                                  st.session_state.seq_idx)

    wrong = um.load_wrong(username)
    is_wrong_bank = (bank_name == "错题库")
    show_wrong_first = st.checkbox("优先显示错题", value=False, disabled=is_wrong_bank)

    if not is_wrong_bank and show_wrong_first:
        bank_prefix = f"{bank_name}:"
        wrong_in_bank = [k for k in wrong if k.startswith(bank_prefix)]
        wrong_ids = {int(k.split(":")[1]) for k in wrong_in_bank}
        pool = [q for q in filtered if q["id"] in wrong_ids]
        if not pool:
            pool = filtered
            st.info("当前筛选条件下没有错题，显示全部题目。")
    else:
        pool = filtered

    if not pool:
        st.warning("当前筛选条件下没有题目。")
        return

    if "seq_idx" not in st.session_state:
        st.session_state.seq_idx = 0
    if st.session_state.seq_idx >= len(pool):
        st.session_state.seq_idx = 0

    q = pool[st.session_state.seq_idx]
    q_key = f"{bank_name}:{q['id']}"
    pfx = f"prac_{q['id']}"
    render_bank = q.get("_orig_bank", bank_name)

    type_label = "单选题" if q["type"] == "single" else "多选题"
    part_label = PART_SHORT.get(q["part"], q["part"])
    st.markdown(f"**第 {st.session_state.seq_idx + 1} / {len(pool)} 题** | {part_label} | {type_label}")

    render_stem_images(q["stem"], bank_name=render_bank)

    answered_key = f"{pfx}_answered"
    if answered_key not in st.session_state:
        st.session_state[answered_key] = False

    user_ans = render_options(q, pfx, disabled=st.session_state[answered_key],
                              user_answer=st.session_state.get(f"{pfx}_user_ans"),
                              bank_name=render_bank)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ 确认答案", key=f"{pfx}_confirm", disabled=st.session_state[answered_key]):
            if user_ans:
                st.session_state[answered_key] = True
                st.session_state[f"{pfx}_user_ans"] = user_ans
                # 持久化记录
                user_ans_str = ",".join(sorted(user_ans))
                is_correct = user_ans_str == q["answer"]
                um.record_practice_answer(
                    username, q_key, bank_name, q["id"], q.get("num", q["id"]),
                    q["type"], q["part"], user_ans_str, q["answer"], is_correct
                )
                if not is_correct:
                    um.add_wrong(username, q_key, bank_name, q, user_ans_str, q["answer"])
                else:
                    um.remove_wrong(username, q_key)
                st.rerun()
            else:
                st.warning("请先选择答案！")
    with col2:
        if st.button("⏭️ 下一题", key=f"{pfx}_next"):
            _save_pos()
            st.session_state.seq_idx += 1
            st.rerun()

    if st.session_state[answered_key]:
        show_result_feedback(q, st.session_state[f"{pfx}_user_ans"], q["answer"], pfx, render_bank)

    # 导航
    st.markdown("---")
    nav_cols = st.columns(4)
    with nav_cols[0]:
        if st.button("⬅️ 上一题", key="prac_prev"):
            _save_pos()
            st.session_state.seq_idx = max(0, st.session_state.seq_idx - 1)
            st.rerun()
    with nav_cols[1]:
        if st.button("下一题 ➡️", key="prac_next"):
            _save_pos()
            st.session_state.seq_idx = min(len(pool) - 1, st.session_state.seq_idx + 1)
            st.rerun()
    with nav_cols[2]:
        target = st.number_input("跳转到", min_value=1, max_value=len(pool),
                                  value=st.session_state.seq_idx + 1, key="prac_jump_input")
        if st.button("跳转", key="prac_jump"):
            _save_pos()
            st.session_state.seq_idx = target - 1
            st.rerun()
    with nav_cols[3]:
        st.caption(f"进度：{st.session_state.seq_idx + 1} / {len(pool)}")


# ══════════════════════════════════════════════════════════
# 模拟考试
# ══════════════════════════════════════════════════════════
def _build_exam_pool(bank_choice):
    """构建模拟考试题目池。返回 (single_pool, multi_pool)。"""
    if bank_choice == "综合题库":
        banks = ["综合题库"]
    elif bank_choice == "图片题库":
        banks = ["图片题库"]
    else:
        banks = ["综合题库", "图片题库"]

    single_pool, multi_pool = [], []
    for b in banks:
        for q in ALL_BANKS[b]:
            if q["type"] == "single":
                single_pool.append((b, q))
            else:
                multi_pool.append((b, q))
    return single_pool, multi_pool


def page_mock_exam(username):
    st.header("🎯 模拟考试")

    # 如果正在考试中
    if st.session_state.get("exam_active"):
        _run_exam(username)
        return

    # 考试配置界面
    st.markdown(f"""
    **考试规则：**
    - 单选题 **{EXAM_SINGLE_COUNT}** 题，每题 **{EXAM_SINGLE_SCORE}** 分
    - 多选题 **{EXAM_MULTI_COUNT}** 题，每题 **{EXAM_MULTI_SCORE}** 分
    - 总分 **{EXAM_TOTAL_SCORE}** 分
    """)

    col1, col2 = st.columns(2)
    with col1:
        bank_choice = st.selectbox("题目范围", ["全部题库（综合+图片）", "综合题库", "图片题库"])
    with col2:
        exam_time = st.slider("考试时长（分钟）", min_value=30, max_value=180,
                              value=EXAM_DEFAULT_MINUTES, step=10)

    # 检查题目数量是否足够
    single_pool, multi_pool = _build_exam_pool(bank_choice)
    s_ok = len(single_pool) >= EXAM_SINGLE_COUNT
    m_ok = len(multi_pool) >= EXAM_MULTI_COUNT

    if not s_ok or not m_ok:
        if not s_ok:
            st.warning(f"单选题数量不足：需要 {EXAM_SINGLE_COUNT} 题，仅有 {len(single_pool)} 题")
        if not m_ok:
            st.warning(f"多选题数量不足：需要 {EXAM_MULTI_COUNT} 题，仅有 {len(multi_pool)} 题")
        return

    if st.button("🚀 开始考试", key="start_exam", use_container_width=True):
        sampled_s = random.sample(single_pool, EXAM_SINGLE_COUNT)
        sampled_m = random.sample(multi_pool, EXAM_MULTI_COUNT)
        exam_qs = [(b, q) for b, q in sampled_s] + [(b, q) for b, q in sampled_m]
        random.shuffle(exam_qs)

        st.session_state.exam_active = True
        st.session_state.exam_questions = exam_qs
        st.session_state.exam_answers = {}
        st.session_state.exam_submitted = False
        st.session_state.exam_start_time = time.time()
        st.session_state.exam_duration = exam_time * 60
        st.session_state.exam_current = 0
        st.rerun()


def _run_exam(username):
    """考试进行中界面。"""
    exam_qs = st.session_state.exam_questions
    elapsed = time.time() - st.session_state.exam_start_time
    remaining = max(0, st.session_state.exam_duration - elapsed)
    submitted = st.session_state.exam_submitted

    # 倒计时
    if not submitted:
        mins, secs = divmod(int(remaining), 60)
        st.markdown(f"### ⏰ 剩余时间：{mins:02d}:{secs:02d}")
        if remaining <= 0:
            _submit_exam(username)
            st.rerun()
            return

    # 显示题目
    current_idx = st.session_state.exam_current
    bank_name, q = exam_qs[current_idx]
    q_key = f"exam_{q['id']}"

    type_label = "单选题" if q["type"] == "single" else "多选题"
    part_label = PART_SHORT.get(q["part"], q["part"])
    score_info = f"{EXAM_SINGLE_SCORE}分" if q["type"] == "single" else f"{EXAM_MULTI_SCORE}分"
    st.markdown(f"**第 {current_idx + 1} / {len(exam_qs)} 题** | {part_label} | {type_label} | {score_info}")

    render_stem_images(q["stem"], bank_name=bank_name)

    if submitted:
        user_ans = st.session_state.exam_answers.get(q["id"], [])
        render_options(q, q_key, disabled=True, user_answer=user_ans, bank_name=bank_name)
        show_result_feedback(q, user_ans, q["answer"], q_key, bank_name)
    else:
        prev_ans = st.session_state.exam_answers.get(q["id"])
        user_ans = render_options(q, q_key, disabled=False, user_answer=prev_ans, bank_name=bank_name)
        if user_ans:
            st.session_state.exam_answers[q["id"]] = user_ans

        nav_cols = st.columns(4)
        with nav_cols[0]:
            if st.button("⬅️ 上一题", key="exam_prev"):
                st.session_state.exam_current = max(0, current_idx - 1)
                st.rerun()
        with nav_cols[1]:
            if st.button("下一题 ➡️", key="exam_next"):
                st.session_state.exam_current = min(len(exam_qs) - 1, current_idx + 1)
                st.rerun()
        with nav_cols[2]:
            if st.button("📤 交卷", key="exam_submit"):
                _submit_exam(username)
                st.rerun()
        with nav_cols[3]:
            st.caption(f"进度：{current_idx + 1} / {len(exam_qs)}")

    # 交卷后显示成绩（在第一题下方）
    if submitted and current_idx == 0:
        _display_exam_result(username)


def _submit_exam(username):
    """交卷：计算成绩、保存记录、更新错题。"""
    exam_qs = st.session_state.exam_questions
    answers = st.session_state.exam_answers
    st.session_state.exam_submitted = True

    total_score = 0
    correct_count = 0
    details = []

    for bank_name, q in exam_qs:
        user_ans = answers.get(q["id"], [])
        user_ans_str = ",".join(sorted(user_ans)) if user_ans else ""
        correct_ans = q["answer"]
        correct_set = set(correct_ans.split(","))
        user_set = set(user_ans) if user_ans else set()
        is_correct = user_set == correct_set

        pts = EXAM_SINGLE_SCORE if q["type"] == "single" else EXAM_MULTI_SCORE
        if is_correct:
            total_score += pts
            correct_count += 1

        q_key = f"{bank_name}:{q['id']}"
        details.append({
            "bank": bank_name,
            "q_id": q["id"],
            "num": q.get("num", q["id"]),
            "type": q["type"],
            "user_ans": user_ans_str,
            "correct_ans": correct_ans,
            "is_correct": is_correct,
            "score": pts if is_correct else 0,
        })

        if not is_correct:
            um.add_wrong(username, q_key, bank_name, q, user_ans_str, correct_ans)
        else:
            um.remove_wrong(username, q_key)

    duration = time.time() - st.session_state.exam_start_time
    record = {
        "exam_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "date": datetime.now().isoformat(timespec="seconds"),
        "total_score": total_score,
        "max_score": EXAM_TOTAL_SCORE,
        "correct_count": correct_count,
        "total_count": len(exam_qs),
        "single_correct": sum(1 for d in details if d["type"] == "single" and d["is_correct"]),
        "multi_correct": sum(1 for d in details if d["type"] == "multiple" and d["is_correct"]),
        "duration_seconds": round(duration),
        "details": details,
    }
    um.save_exam_record(username, record)
    st.session_state.exam_result = record


def _display_exam_result(username):
    """显示考试成绩和错题列表。"""
    result = st.session_state.get("exam_result")
    if not result:
        return

    st.markdown("---")
    st.header("📊 考试成绩")

    pct = round(result["total_score"] / result["max_score"] * 100, 1)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("总分", f"{result['total_score']} / {result['max_score']}")
    with col2:
        st.metric("正确题数", f"{result['correct_count']} / {result['total_count']}")
    with col3:
        dur_min = result["duration_seconds"] // 60
        dur_sec = result["duration_seconds"] % 60
        st.metric("用时", f"{dur_min}分{dur_sec}秒")

    st.markdown(f"**单选题正确：** {result['single_correct']}/{EXAM_SINGLE_COUNT}  "
                f"**多选题正确：** {result['multi_correct']}/{EXAM_MULTI_COUNT}")

    # 错题列表
    wrong_details = [d for d in result["details"] if not d["is_correct"]]
    if wrong_details:
        st.markdown(f"### ❌ 错题列表（{len(wrong_details)} 题）")
        for d in wrong_details:
            type_label = "单选" if d["type"] == "single" else "多选"
            bank = d["bank"]
            orig_q = next((q for q in ALL_BANKS[bank] if q["id"] == d["q_id"]), None)
            stem_preview = orig_q["stem"][:60] if orig_q else f"题目{d['num']}"
            with st.expander(f"[{type_label}] [{bank}] {stem_preview}..."):
                if orig_q:
                    render_stem_images(orig_q["stem"], bank_name=bank)
                    if orig_q["options"]:
                        for k, v in sorted(orig_q["options"].items()):
                            marker = ""
                            correct_set = set(d["correct_ans"].split(","))
                            user_set = set(d["user_ans"].split(",")) if d["user_ans"] else set()
                            if k in correct_set:
                                marker = " ✅"
                            if k in user_set and k not in correct_set:
                                marker = " ❌"
                            st.write(f"{k}、{v}{marker}")
                st.write(f"**你的答案：** {d['user_ans'] or '未作答'}")
                st.write(f"**正确答案：** {d['correct_ans']}")

    # 结束考试按钮
    if st.button("🏁 结束考试", key="end_exam", use_container_width=True):
        for key in ["exam_active", "exam_questions", "exam_answers", "exam_submitted",
                     "exam_start_time", "exam_duration", "exam_current", "exam_result"]:
            st.session_state.pop(key, None)
        st.rerun()


# ══════════════════════════════════════════════════════════
# 错题本
# ══════════════════════════════════════════════════════════
def page_wrong_book(username):
    st.header("📕 错题本")

    wrong = um.load_wrong(username)
    if not wrong:
        st.info("错题本为空，继续加油！")
        return

    # 按题库筛选
    banks_in_wrong = sorted(set(v["bank"] for v in wrong.values()))
    filter_bank = st.selectbox("筛选题库", ["全部"] + banks_in_wrong)

    items = [(k, v) for k, v in wrong.items() if filter_bank == "全部" or v["bank"] == filter_bank]
    items.sort(key=lambda x: x[1].get("last_wrong", ""), reverse=True)

    st.caption(f"共 **{len(items)}** 道错题")

    for idx, (q_key, info) in enumerate(items):
        bank = info["bank"]
        type_label = "单选题" if info["type"] == "single" else "多选题"
        part_label = PART_SHORT.get(info.get("part", ""), info.get("part", ""))
        attempts = info.get("attempts", 1)

        with st.expander(f"{idx+1}. [{type_label}] [{bank}] {info['stem'][:50]}... (错{attempts}次)"):
            render_stem_images(info["stem"], bank_name=bank)
            if info.get("options"):
                for k, v in sorted(info["options"].items()):
                    st.write(f"{k}、{v}")
                if info.get("option_images"):
                    for k, imgs in info["option_images"].items():
                        for img_name in imgs:
                            show_image(img_name, width=150, bank_name=bank)
            st.write(f"**你的答案：** {info.get('user_ans', '未知')}")
            st.write(f"**正确答案：** {info['answer']}")
            if st.button("✅ 标记为已掌握", key=f"master_{q_key}"):
                um.remove_wrong(username, q_key)
                st.rerun()

    st.markdown("---")
    if st.button("🗑️ 清空错题本", key="clear_all_wrong"):
        um.clear_wrong(username)
        st.rerun()


# ══════════════════════════════════════════════════════════
# 考试记录
# ══════════════════════════════════════════════════════════
def page_exam_history(username):
    st.header("📋 考试记录")

    exams = um.load_exams(username)
    if not exams:
        st.info("暂无考试记录。")
        return

    exams_sorted = sorted(exams, key=lambda e: e.get("date", ""), reverse=True)
    st.markdown(f"共 **{len(exams_sorted)}** 次考试")

    for i, exam in enumerate(exams_sorted):
        pct = round(exam["total_score"] / exam["max_score"] * 100, 1)
        dur_min = exam.get("duration_seconds", 0) // 60
        date_str = exam.get("date", "未知")[:16].replace("T", " ")

        header = (f"**{date_str}** | "
                  f"得分 {exam['total_score']}/{exam['max_score']} ({pct}%) | "
                  f"正确 {exam['correct_count']}/{exam['total_count']} | "
                  f"用时 {dur_min}分钟")

        with st.expander(header):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("总分", f"{exam['total_score']}/{exam['max_score']}")
            with col2:
                st.metric("单选正确", f"{exam.get('single_correct', '?')}/{EXAM_SINGLE_COUNT}")
            with col3:
                st.metric("多选正确", f"{exam.get('multi_correct', '?')}/{EXAM_MULTI_COUNT}")

            details = exam.get("details", [])
            wrong_details = [d for d in details if not d["is_correct"]]
            if wrong_details:
                st.markdown(f"**错题（{len(wrong_details)} 题）：**")
                for d in wrong_details:
                    type_label = "单选" if d["type"] == "single" else "多选"
                    bank = d.get("bank", "")
                    orig_q = next((q for q in ALL_BANKS.get(bank, []) if q["id"] == d["q_id"]), None)
                    stem_preview = orig_q["stem"][:50] if orig_q else f"题目{d.get('num', '?')}"
                    st.write(f"- [{type_label}] [{bank}] {stem_preview}... "
                             f"| 你的: {d['user_ans'] or '未答'} | 正确: {d['correct_ans']}")


# ══════════════════════════════════════════════════════════
# 练习统计
# ══════════════════════════════════════════════════════════
def page_stats(username):
    st.header("📊 练习统计")

    practice = um.load_practice(username)
    stats = practice.get("stats", {})
    wrong = um.load_wrong(username)
    exams = um.load_exams(username)

    st.subheader("刷题统计")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总答题数", stats.get("total_answered", 0))
    with col2:
        st.metric("正确数", stats.get("correct_count", 0))
    with col3:
        st.metric("正确率", f"{stats.get('accuracy', 0)}%")
    with col4:
        st.metric("错题数", len(wrong))

    last = stats.get("last_practice")
    if last:
        st.caption(f"最近练习：{last[:16].replace('T', ' ')}")

    st.subheader("考试统计")
    col5, col6, col7 = st.columns(3)
    with col5:
        st.metric("考试次数", len(exams))
    if exams:
        avg_score = sum(e["total_score"] for e in exams) / len(exams)
        best_score = max(e["total_score"] for e in exams)
        with col6:
            st.metric("平均分", f"{avg_score:.1f}/{EXAM_TOTAL_SCORE}")
        with col7:
            st.metric("最高分", f"{best_score}/{EXAM_TOTAL_SCORE}")
    else:
        with col6:
            st.metric("平均分", "-")
        with col7:
            st.metric("最高分", "-")


# ══════════════════════════════════════════════════════════
# 主应用
# ══════════════════════════════════════════════════════════
def main():
    um.ensure_admin()

    for k, v in [("logged_in", False), ("current_user", None), ("page", "顺序刷题")]:
        if k not in st.session_state:
            st.session_state[k] = v

    # ── 未登录 → 登录页 ──
    if not st.session_state.logged_in:
        page_login()
        return

    user = st.session_state.current_user
    username = user["username"]
    is_admin = user.get("role") == "admin"

    # ── 恢复上次刷题位置（仅登录后首次） ──
    if not st.session_state.get("_position_restored"):
        pos = um.load_practice_position(username)
        if pos:
            restored_bank = pos.get("bank", "综合题库")
            valid_banks = set(ALL_BANKS.keys()) | {"错题库"}
            if restored_bank not in valid_banks:
                restored_bank = "综合题库"
            restored_part = pos.get("part", "全部")
            if restored_part not in PARTS_MAP.get(restored_bank, ["全部"]):
                restored_part = "全部"
            restored_qtype = pos.get("qtype", "全部")
            if restored_qtype not in ("全部", "单选题", "多选题"):
                restored_qtype = "全部"
            st.session_state["bank_name"] = restored_bank
            st.session_state["bank_selector"] = restored_bank
            st.session_state.page = "顺序刷题"
            st.session_state.seq_idx = pos.get("index", 0)
            st.session_state.sel_part = restored_part
            st.session_state.sel_qtype = restored_qtype
        st.session_state._position_restored = True
        if pos:
            st.rerun()

    # ── 侧边栏 ──
    with st.sidebar:
        st.title("📝 辐射安全考试练习")
        role_tag = "👑 管理员" if is_admin else "👤 用户"
        st.markdown(f"**{username}** ({role_tag})")
        if st.button("🚪 退出登录", use_container_width=True):
            for key in list(st.session_state.keys()):
                if key not in ("logged_in", "current_user"):
                    del st.session_state[key]
            st.session_state.logged_in = False
            st.session_state.current_user = None
            st.rerun()

        st.markdown("---")

        # 考试中 → 答题卡
        if st.session_state.get("exam_active") and not st.session_state.get("exam_submitted"):
            exam_qs = st.session_state.exam_questions
            st.markdown("### 答题卡")
            answered_count = sum(1 for _, eq in exam_qs if eq["id"] in st.session_state.exam_answers)
            st.progress(answered_count / len(exam_qs), text=f"已答 {answered_count}/{len(exam_qs)}")

            st.markdown("""
            <style>
            div[data-testid="stSidebar"] div.stColumns button[kind="secondary"] {
                font-size: 0.7rem !important;
                padding: 4px 0 !important;
                min-height: 28px !important;
                background-color: #e8e8e8 !important;
                color: #666 !important;
            }
            div[data-testid="stSidebar"] div.stColumns button[kind="primary"] {
                font-size: 0.7rem !important;
                padding: 4px 0 !important;
                min-height: 28px !important;
                background-color: #4CAF50 !important;
                border-color: #4CAF50 !important;
                color: white !important;
            }
            </style>
            """, unsafe_allow_html=True)

            current_num = st.session_state.get("exam_current", 0) + 1
            st.caption(f"📍 当前第 **{current_num}** 题")

            def _exam_nav(idx):
                st.session_state.exam_current = idx

            for row_start in range(0, len(exam_qs), 10):
                cols = st.columns(min(10, len(exam_qs) - row_start))
                for i, col in enumerate(cols):
                    idx = row_start + i
                    if idx >= len(exam_qs):
                        break
                    _, eq = exam_qs[idx]
                    is_current = idx == st.session_state.get("exam_current", 0)
                    is_answered = eq["id"] in st.session_state.exam_answers
                    label = f"•{idx + 1}" if is_current else str(idx + 1)
                    btn_key = f"nav_exam_{idx}"
                    btn_type = "primary" if (is_answered or is_current) else "secondary"
                    col.button(label, key=btn_key, type=btn_type,
                              help=f"第{idx+1}题（{'当前' if is_current else '已答' if is_answered else '未答'}）",
                              on_click=_exam_nav, args=(idx,))
            st.markdown("---")
        else:
            # 正常导航
            pages = ["顺序刷题", "模拟考试", "错题本", "考试记录", "练习统计"]
            page = st.radio("导航", pages,
                           index=pages.index(st.session_state.page) if st.session_state.page in pages else 0,
                           label_visibility="collapsed")
            st.session_state.page = page

            st.markdown("---")

            # 题库选择（非考试/记录/统计模式）
            if page in ("顺序刷题", "错题本"):
                st.markdown("### 题库选择")
                bank_options = ["综合题库", "图片题库", "错题库"] if page == "顺序刷题" else ["综合题库", "图片题库"]
                selected_bank = st.radio("题库", bank_options, horizontal=True,
                                        key="bank_selector")
                st.session_state["bank_name"] = selected_bank

                if page == "顺序刷题":
                    st.markdown("### 题库筛选")
                    if selected_bank == "错题库":
                        wrong_qs = _get_wrong_questions(username)
                        # 按题型筛选
                        q_type_filter = st.radio("题型", ["全部", "单选题", "多选题"], horizontal=True, key="sel_qtype")
                        filtered = wrong_qs
                        if q_type_filter == "单选题":
                            filtered = [q for q in filtered if q["type"] == "single"]
                        elif q_type_filter == "多选题":
                            filtered = [q for q in filtered if q["type"] == "multiple"]
                        st.caption(f"错题库：**{len(filtered)}** 题")
                    else:
                        questions = ALL_BANKS[selected_bank]
                        PARTS = PARTS_MAP[selected_bank]
                        selected_part = st.selectbox("选择部分", PARTS, key="sel_part")
                        q_type_filter = st.radio("题型", ["全部", "单选题", "多选题"], horizontal=True, key="sel_qtype")

                        filtered = questions
                        if selected_part != "全部":
                            filtered = [q for q in filtered if q["part"] == selected_part]
                        if q_type_filter == "单选题":
                            filtered = [q for q in filtered if q["type"] == "single"]
                        elif q_type_filter == "多选题":
                            filtered = [q for q in filtered if q["type"] == "multiple"]

                        st.caption(f"当前题库：**{len(filtered)}** 题")

            # 错题概览
            wrong = um.load_wrong(username)
            st.markdown("---")
            st.caption(f"错题本：**{len(wrong)}** 题")

    # ── 主内容区 ──
    if st.session_state.get("exam_active"):
        _run_exam(username)
    else:
        page = st.session_state.page
        bank_name = st.session_state.get("bank_name", "综合题库")

        if page == "顺序刷题":
            page_practice(username, bank_name, filtered)
        elif page == "模拟考试":
            page_mock_exam(username)
        elif page == "错题本":
            page_wrong_book(username)
        elif page == "考试记录":
            page_exam_history(username)
        elif page == "练习统计":
            page_stats(username)


if __name__ == "__main__":
    main()
