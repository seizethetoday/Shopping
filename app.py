import json
import os
import re
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="쇼핑리스트", page_icon="🛒")

DATA_FILE = Path(__file__).parent / "shopping_list.json"
MAX_NAME_LEN = 50


# ===== 데이터 =====
def load_items() -> list[dict]:
    """JSON 파일에서 아이템을 읽는다. 파일이 없거나 손상되었으면 빈 리스트를 반환한다."""
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    items, seen_ids, repaired = [], set(), False
    for raw in data:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            continue
        item_id = str(raw.get("id") or "")
        if not item_id or item_id in seen_ids:  # id 누락·중복은 새 id로 교체 (위젯 key 충돌 방지)
            item_id, repaired = str(uuid.uuid4()), True
        seen_ids.add(item_id)
        items.append(
            {
                "id": item_id,
                "name": raw["name"],
                "checked": bool(raw.get("checked", False)),
                "created_at": raw.get("created_at") or datetime.now().isoformat(timespec="seconds"),
            }
        )
    if repaired:  # 새 id를 파일에도 반영해야 다음 읽기에서 id가 바뀌지 않음
        save_items(items)
    return items


def save_items(items: list[dict]) -> bool:
    """아이템 목록을 JSON 파일에 저장한다. 임시 파일에 먼저 쓴 뒤 교체하므로 쓰는 도중 끊겨도 기존 파일이 손상되지 않는다.
    실패하면 오류 안내 메시지를 남기고 False를 반환한다."""
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=DATA_FILE.parent, prefix=".shopping_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(3):  # Windows에서 다른 프로세스가 잠깐 파일을 열고 있을 때를 대비한 재시도
            try:
                os.replace(tmp_path, DATA_FILE)
                return True
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05)
    except OSError:
        _flash("error", "저장하지 못했어요. 파일 권한이나 디스크 상태를 확인해 주세요.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return False


# ===== 로직 =====
def _normalize(name: str) -> str:
    return " ".join(name.split()).casefold()


def _validate(name: str, exclude_id: str | None = None) -> str | None:
    """이름이 유효하면 None, 아니면 오류 메시지를 반환한다."""
    if not name:
        return "아이템 이름을 입력해 주세요."
    if len(name) > MAX_NAME_LEN:
        return f"이름은 {MAX_NAME_LEN}자 이하로 입력해 주세요."
    if is_duplicate(name, exclude_id):
        return f"이미 목록에 있습니다: {name}"
    return None


def _flash(kind: str, text: str) -> None:
    st.session_state.flash = (kind, text)


def _sync() -> None:
    """다른 탭·세션이 먼저 저장한 내용을 잃지 않도록, 변경 직전에 파일에서 목록을 다시 읽는다."""
    st.session_state.shopping_items = load_items()


def is_duplicate(name: str, exclude_id: str | None = None) -> bool:
    """공백·대소문자를 무시하고 같은 이름이 이미 있는지 검사한다. exclude_id는 검사에서 제외할 아이템."""
    key = _normalize(name)
    return any(
        _normalize(item["name"]) == key and item["id"] != exclude_id
        for item in st.session_state.shopping_items
    )


def add_item(name: str) -> bool:
    """검증(빈 값, 중복) 후 새 아이템을 목록 끝에 추가하고 저장한다. 성공 여부를 반환한다."""
    _sync()
    name = name.strip()
    error = _validate(name)
    if error:
        _flash("warning", error)
        return False
    st.session_state.shopping_items.append(
        {
            "id": str(uuid.uuid4()),
            "name": name,
            "checked": False,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    save_items(st.session_state.shopping_items)
    return True


def update_item(item_id: str, new_name: str) -> bool:
    """검증(빈 값, 중복) 후 아이템 이름을 변경하고 저장한다. 성공 여부를 반환한다."""
    _sync()
    new_name = new_name.strip()
    error = _validate(new_name, exclude_id=item_id)
    if error:
        _flash("warning", error)
        return False
    for item in st.session_state.shopping_items:
        if item["id"] == item_id:
            item["name"] = new_name
            break
    save_items(st.session_state.shopping_items)
    return True


def delete_item(item_id: str) -> None:
    """아이템을 삭제하고 저장한다."""
    _sync()
    st.session_state.shopping_items = [
        item for item in st.session_state.shopping_items if item["id"] != item_id
    ]
    if st.session_state.editing_id == item_id:
        st.session_state.editing_id = None
    save_items(st.session_state.shopping_items)


def toggle_item(item_id: str, checked: bool | None = None) -> None:
    """아이템의 체크 상태를 반전(또는 checked 값으로 지정)하고 저장한다."""
    _sync()
    for item in st.session_state.shopping_items:
        if item["id"] == item_id:
            item["checked"] = (not item["checked"]) if checked is None else checked
            break
    save_items(st.session_state.shopping_items)


def clear_checked() -> None:
    """체크된 아이템을 모두 삭제하고 저장한다."""
    _sync()
    st.session_state.shopping_items = [
        item for item in st.session_state.shopping_items if not item["checked"]
    ]
    remaining = {item["id"] for item in st.session_state.shopping_items}
    if st.session_state.editing_id not in remaining:
        st.session_state.editing_id = None
    save_items(st.session_state.shopping_items)


# ===== UI =====
WEEKDAYS = "월화수목금토일"

CSS = """
<style>
/* 화면 폭 / 여백 */
div.block-container { max-width: 640px; padding-top: 2.5rem; padding-bottom: 4rem; }

/* 헤더 */
.app-date { color: #8A948C; font-size: 0.9rem; margin: -0.6rem 0 1.2rem 0; }

/* 추가 폼 */
[data-testid="stForm"] { padding: 0; border: none; }
[data-testid="InputInstructions"] { display: none; }  /* "Press Enter to submit form" 힌트가 placeholder와 겹침 */

/* 요약 카드 */
[class*="st-key-summary"] {
    background: #EDF3EC; border-radius: 14px; padding: 0.9rem 1.1rem 0.6rem 1.1rem; margin: 0.4rem 0 1rem 0;
}
[class*="st-key-summary"] p { margin-bottom: 0.4rem; font-weight: 600; }
.bar-text { font-weight: 600; font-size: 0.85rem; margin-bottom: 0.35rem; }
.bar { height: 8px; background: #CFE0CE; border-radius: 999px; overflow: hidden; margin-bottom: 0.5rem; }
.bar-fill { height: 100%; background: #2E7D32; border-radius: 999px; transition: width 0.3s; }
.done-msg { text-align: center; font-weight: 700; color: #2E7D32; margin: 0.2rem 0 0.4rem 0; }

/* 아이템 행 (카드) */
[class*="st-key-row_"] { border-radius: 12px; background: #FFFFFF; padding: 0.15rem 0.3rem; }
[class*="st-key-row_done_"] { opacity: 0.55; background: #F3F4F2; }

/* 모바일에서도 한 줄 유지 (입력 폼 + 아이템 행) */
[class*="st-key-row_"] [data-testid="stHorizontalBlock"],
[data-testid="stForm"] [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 0.4rem; align-items: center; }
[class*="st-key-row_"] [data-testid="stColumn"],
[data-testid="stForm"] [data-testid="stColumn"] { min-width: 0 !important; }
[class*="st-key-row_"] [data-testid="stVerticalBlock"] { gap: 0; }
[class*="st-key-row_"] [data-testid="stMarkdown"],
[class*="st-key-row_"] [data-testid="stMarkdownContainer"] { margin: 0 !important; }
[class*="st-key-row_"] p { margin: 0; word-break: break-word; line-height: 1.4; }
[class*="st-key-row_"] [data-testid="stCheckbox"] { justify-content: center; }

/* 아이콘 버튼: 칸 전체 폭 사용 */
[class*="st-key-row_"] [data-testid="stButton"] { width: 100%; }
[class*="st-key-row_"] button { padding: 0.25rem 0; min-height: 2.2rem; width: 100%; }

/* 빈 목록 */
.empty-state { text-align: center; padding: 2.5rem 0 2rem 0; color: #6B756D; }
.empty-state .emoji { font-size: 3.5rem; line-height: 1.2; }
</style>
"""


def _escape_md(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+\-.!~|<>$:])", r"\\\1", text)


# ----- 콜백 (위젯 이벤트 → 로직 함수) -----
def _item_name(item_id: str) -> str:
    return next((i["name"] for i in st.session_state.shopping_items if i["id"] == item_id), "")


def on_add() -> None:
    name = st.session_state.get("new_item", "").strip()
    if add_item(name):
        st.toast(f"추가했어요: {name}", icon="🛒")


def on_check(item_id: str) -> None:
    toggle_item(item_id, st.session_state[f"check_{item_id}"])


def on_delete(item_id: str) -> None:
    name = _item_name(item_id)
    delete_item(item_id)
    st.toast(f"삭제했어요: {name}", icon="🗑️")


def on_clear_checked() -> None:
    count = sum(1 for i in st.session_state.shopping_items if i["checked"])
    clear_checked()
    st.toast(f"완료한 {count}개를 삭제했어요", icon="🧹")


def on_start_edit(item_id: str) -> None:
    st.session_state.editing_id = item_id


def on_cancel_edit() -> None:
    st.session_state.editing_id = None


def on_save_edit(item_id: str) -> None:
    new_name = st.session_state[f"editinput_{item_id}"].strip()
    if update_item(item_id, new_name):
        st.session_state.editing_id = None
        st.toast(f"수정했어요: {new_name}", icon="✏️")


# ----- 화면 -----
st.session_state.shopping_items = load_items()  # 매 실행마다 파일 기준으로 갱신 (다른 탭의 변경 반영)
if "editing_id" not in st.session_state:
    st.session_state.editing_id = None

st.markdown(CSS, unsafe_allow_html=True)

# 헤더
now = datetime.now()
st.title("🛒 쇼핑리스트")
st.markdown(
    f'<div class="app-date">{now.year}년 {now.month}월 {now.day}일 ({WEEKDAYS[now.weekday()]})</div>',
    unsafe_allow_html=True,
)

# 입력 영역 (Enter 로도 제출)
with st.form("add_form", clear_on_submit=True, border=False):
    col_input, col_add = st.columns([0.78, 0.22], vertical_alignment="bottom")
    col_input.text_input(
        "아이템 이름",
        key="new_item",
        placeholder="예: 우유, 계란, 식빵",
        label_visibility="collapsed",
    )
    col_add.form_submit_button("추가", type="primary", on_click=on_add, use_container_width=True)

# 콜백에서 저장한 검증 메시지
flash = st.session_state.pop("flash", None)
if flash:
    getattr(st, flash[0])(flash[1])

items = st.session_state.shopping_items
total = len(items)
done = sum(1 for item in items if item["checked"])
ratio = done / total if total else 0.0

# 요약 카드
with st.container(key="summary"):
    st.markdown(f"전체 {total}개 · 완료 {done}개")
    pct = round(ratio * 100)
    st.markdown(
        f'<div class="bar-text">{pct}%</div>'
        f'<div class="bar" role="progressbar" aria-valuenow="{pct}" aria-valuemin="0" aria-valuemax="100">'
        f'<div class="bar-fill" style="width:{pct}%"></div></div>',
        unsafe_allow_html=True,
    )
    if total and done == total:
        st.markdown('<div class="done-msg">🎉 장보기 완료!</div>', unsafe_allow_html=True)

# 빈 목록
if not items:
    st.markdown(
        '<div class="empty-state"><div class="emoji">🧺</div>'
        "<div>쇼핑리스트가 비어 있습니다.<br>아이템을 추가해 보세요.</div></div>",
        unsafe_allow_html=True,
    )

# 목록: 미완료가 위, 완료가 아래 (표시 순서만 바꾸고 저장 순서는 그대로)
for item in sorted(items, key=lambda i: i["checked"]):
    item_id = item["id"]
    prefix = "row_done" if item["checked"] else "row"
    with st.container(border=True, key=f"{prefix}_{item_id}"):
        col_check, col_name, col_a, col_b = st.columns(
            [0.08, 0.62, 0.15, 0.15], vertical_alignment="center"
        )
        col_check.checkbox(
            "완료",
            value=item["checked"],
            key=f"check_{item_id}",
            label_visibility="collapsed",
            on_change=on_check,
            args=(item_id,),
        )
        if st.session_state.editing_id == item_id:
            col_name.text_input(
                "이름 수정",
                value=item["name"],
                key=f"editinput_{item_id}",
                label_visibility="collapsed",
            )
            col_a.button("✅", key=f"save_{item_id}", help="저장", on_click=on_save_edit, args=(item_id,), width="stretch")
            col_b.button("↩️", key=f"cancel_{item_id}", help="취소", on_click=on_cancel_edit, width="stretch")
        else:
            label = _escape_md(item["name"])
            col_name.markdown(f":gray[~~{label}~~]" if item["checked"] else label)
            col_a.button("✏️", key=f"edit_{item_id}", help="수정", on_click=on_start_edit, args=(item_id,), width="stretch")
            col_b.button("🗑️", key=f"del_{item_id}", help="삭제", on_click=on_delete, args=(item_id,), width="stretch")

# 체크된 항목 일괄 삭제
st.button("체크된 항목 모두 삭제", on_click=on_clear_checked, disabled=done == 0, use_container_width=True)
