"""app.py - 第6章:Streamlit 使用者介面(風格 A:儀表板)

啟動:streamlit run app.py
(本機需要先啟動 FastAPI:python -m uvicorn main:app --reload;
 沒有另外啟動時,會自動改用「內建 API 模式」,見 start_embedded_api)
"""
import os
import re
import sys

import pandas as pd
import requests
import streamlit as st

API = os.environ.get("API_URL", "http://127.0.0.1:8000")  # 雲端部署時可由環境變數指定
FEATURE_LABELS = {"danceability": "舞動性", "energy": "能量", "valence": "情緒", "acousticness": "原聲度"}
METHODS = {"hybrid": "混合", "cf": "協同過濾", "content": "音樂特徵"}

GLOSSARY = """
**推薦方法**
- **混合**:綜合「聽的人重疊」與「聲音相近」兩種線索(協同過濾佔 60%、音樂特徵佔 40%)
- **協同過濾**:常被同一批人聽的歌,視為互相相似
- **音樂特徵**:聲音特徵(下方四項)接近的歌,視為互相相似

**音樂特徵**(數值都在 0 到 1 之間,來自 Spotify)
- **舞動性**:適合跳舞的程度,依節奏穩定度、拍子強度等判斷
- **能量**:強烈、熱鬧的程度,越高越快、越大聲、越吵
- **情緒**:音樂傳達的正向程度,越高越開心明亮,越低越憂傷
- **原聲度**:越高,越有把握是原聲(非電子)風格的歌

**相似度**:分數越高越相似,只用來比較排序,數字本身不是百分比。
"""

st.set_page_config(page_title="音樂搜尋與推薦", page_icon="🎵", layout="wide")


def esc(s):
    """跳脫 Markdown 特殊符號,避免歌名中的 * _ $ 等被誤判成格式。"""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!$~|<>])", r"\\\1", str(s))


@st.cache_resource(show_spinner="第一次啟動,正在載入資料並啟動內建 API ...")
def start_embedded_api():
    """沒有另外啟動 FastAPI 時(例如部署在 Streamlit Community Cloud),
    就在同一個程式裡用背景執行緒啟動它。本機照 README 開兩個終端機時不會用到這段。"""
    import threading
    import time
    import urllib.request

    import uvicorn

    try:
        import main  # 載入資料庫並計算相似度
    except BaseException as e:  # main.py 找不到資料庫時會 SystemExit
        return f"無法載入 main.py:{e}"
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=8000, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(120):
        try:
            urllib.request.urlopen(f"{API}/popular?limit=1", timeout=2)
            return None
        except Exception:
            time.sleep(0.5)
    return "內建 API 啟動逾時"


@st.cache_data(ttl=60)
def call(path, **params):
    """呼叫 FastAPI,結果快取 60 秒。"""
    r = requests.get(f"{API}{path}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def show_songs(rows, with_score=False, plays_key="total_plays", plays_label="總播放數"):
    """把歌曲清單畫成表格;推薦結果的相似度以長條顯示。"""
    df = pd.DataFrame(rows)
    out = pd.DataFrame({"排名": range(1, len(df) + 1), "歌名": df["title"], "歌手": df["artist"]})
    if plays_key in df:
        out[plays_label] = df[plays_key]
    config = {}
    if with_score and "score" in df:
        out["相似度"] = df["score"]
        config["相似度"] = st.column_config.ProgressColumn(
            "相似度", help="分數越高越相似,只用來比較排序", min_value=0.0,
            max_value=float(df["score"].max()) or 1.0, format="%.3f")
    st.dataframe(out, column_config=config, width="stretch", hide_index=True)


def pick_method(key):
    """推薦方法選擇(新版 Streamlit 用並排按鈕,舊版退回單選鈕)。"""
    seg = getattr(st, "segmented_control", None)
    if seg:
        return seg("推薦方法", list(METHODS), default="hybrid", format_func=METHODS.get,
                   key=key, label_visibility="collapsed") or "hybrid"
    return st.radio("推薦方法", list(METHODS), format_func=METHODS.get, horizontal=True, key=key)


st.title("🎵 音樂搜尋與推薦系統")
st.caption("輸入歌名或歌手,找出相似的歌;也可以選一位使用者,看系統會推薦他什麼歌。")

try:
    call("/popular", limit=1)
except requests.exceptions.ConnectionError:
    err = start_embedded_api() if API.startswith("http://127.0.0.1") else "API_URL 指定的 FastAPI 連不上"
    if err:
        st.error(f"連不上 FastAPI。{err}\n\n本機請先在另一個終端機執行:python -m uvicorn main:app --reload")
        st.stop()
    call("/popular", limit=1)

if "main" in sys.modules:
    st.caption("ℹ️ 目前使用「內建 API 模式」:FastAPI 與網頁在同一個程式中執行。")

# ---------- 頂端:資料概況卡片 ----------
try:
    stats = call("/stats")
except requests.exceptions.RequestException:
    stats = None  # 舊版 API 沒有 /stats,就不顯示卡片
if stats:
    for col, (label, key) in zip(st.columns(4), [("歌曲", "songs"), ("歌手", "artists"),
                                                  ("使用者", "users"), ("聆聽紀錄", "plays")]):
        with col.container(border=True):
            st.metric(label, f"{stats[key]:,}")

with st.expander("名詞說明(點開查看)"):
    st.markdown(GLOSSARY)

tab1, tab2, tab3 = st.tabs(["🔍 搜尋與相似歌曲", "👤 使用者推薦", "🔥 熱門歌曲"])

# ---------- 分頁1:搜尋 -> 選一首 -> 歌曲卡片與相似歌曲 ----------
with tab1:
    q = st.text_input("搜尋歌名或歌手", placeholder="輸入歌名或歌手,例如:Neon、Coldplay")
    if q:
        results = call("/search", q=q, limit=30)
        if not results:
            st.warning("找不到符合的歌曲")
        else:
            st.caption(f"找到 {len(results)} 首(最多顯示 30 首)")
            label = {f"{s['title']} - {s['artist']}": s for s in results}
            song = label[st.selectbox("選一首歌,查看詳細資料與相似歌曲", list(label))]
            left, right = st.columns([5, 7])
            with left, st.container(border=True):
                st.subheader(esc(song["title"]))
                st.caption(f"{esc(song['artist'])} · 總播放 {song['total_plays']:,} 次 · {song['tempo']:.0f} BPM")
                for key, name in FEATURE_LABELS.items():
                    v = min(max(float(song[key]), 0.0), 1.0)
                    st.progress(v, text=f"{name} {v:.2f}")
            with right, st.container(border=True):
                st.markdown("**相似歌曲**")
                method = pick_method("song_method")
                show_songs(call(f"/recommend/song/{song['song_id']}", k=10, method=method), with_score=True)
    else:
        st.info("在上方輸入歌名或歌手開始搜尋,例如 Coldplay、Neon。")

# ---------- 分頁2:選使用者 -> 聆聽紀錄與推薦 ----------
with tab2:
    uid = st.selectbox("選擇使用者", call("/users"))
    k = st.slider("推薦幾首", 5, 20, 10)
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.markdown("**聽最多的歌**")
        show_songs(call(f"/users/{uid}/history", limit=10), plays_key="play_count", plays_label="播放次數")
    with right, st.container(border=True):
        st.markdown("**為你推薦(還沒聽過的歌)**")
        method = pick_method("user_method")
        show_songs(call(f"/recommend/user/{uid}", k=k, method=method), with_score=True)

# ---------- 分頁3:熱門排行 ----------
with tab3:
    n = st.slider("顯示前幾名", 5, 30, 10, key="pop")
    pop = pd.DataFrame(call("/popular", limit=n))
    st.bar_chart(pop.set_index("title")["total_plays"])
    show_songs(pop.to_dict("records"))
